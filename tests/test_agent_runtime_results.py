from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

from agent.error_handler import ErrorDecision
from agent.executor import AgentExecutor
from agent.runtime_result import ExecutionResult, ResultStatus
from agent.task_queue import Task, TaskPriority, TaskQueue, TaskStatus


def _plan(tool="respond", parameters=None):
    return {
        "goal": "test",
        "steps": [{
            "step": 1,
            "tool": tool,
            "description": "test step",
            "parameters": parameters or {"message": "hello"},
        }],
    }


class AgentRuntimeResultTests(unittest.TestCase):
    def test_executor_writes_start_checkpoint_and_terminal_phase(self):
        journal = Mock()
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=_plan()),
            patch("agent.executor._call_tool", return_value="hello"),
        ):
            result = AgentExecutor(journal=journal).execute_result(
                "journalled", request_id="journal-1"
            )
        self.assertTrue(result.succeeded)
        journal.start.assert_called_once_with("journal-1", "journalled")
        terminal = [
            call for call in journal.set_phase.call_args_list
            if len(call.args) > 1 and call.args[1] == "succeeded"
        ]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0].kwargs["completed_steps"], 1)
        self.assertEqual(terminal[0].kwargs["total_steps"], 1)

    def test_validated_plan_is_visible_before_tool_execution(self):
        events = []
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=_plan()),
            patch("agent.executor._call_tool", side_effect=lambda *_: events.append("tool") or "hello"),
        ):
            result = AgentExecutor().execute_result(
                "visible plan", plan_callback=lambda summary: events.append(("plan", summary))
            )
        self.assertTrue(result.succeeded)
        self.assertEqual(events[0][0], "plan")
        self.assertEqual(events[1], "tool")
        self.assertNotIn("parameters", events[0][1])

    def test_transient_idempotent_failure_uses_bounded_retry(self):
        call = Mock(side_effect=[ConnectionError("temporarily unavailable"), "hello"])
        states = []
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=_plan()),
            patch("agent.executor._call_tool", call),
            patch("agent.executor.time.sleep") as sleep,
        ):
            result = AgentExecutor().execute_result("retry", state_callback=states.append)
        self.assertEqual(result.status, ResultStatus.SUCCEEDED)
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(0.25)
        self.assertTrue(result.step_results[0].retryable)
        self.assertIn("RECOVERING", states)
        self.assertIn("VERIFYING", states)

    def test_non_transient_failure_is_not_retried_even_if_model_requests_it(self):
        recovery = {"decision": ErrorDecision.RETRY, "reason": "try"}
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=_plan()),
            patch("agent.executor._call_tool", side_effect=ValueError("invalid input")) as call,
            patch("agent.executor.analyze_error", return_value=recovery),
        ):
            result = AgentExecutor().execute_result("no retry")
        self.assertEqual(result.status, ResultStatus.FAILED)
        self.assertEqual(call.call_count, 1)

    def test_later_failure_returns_partial_after_verified_success(self):
        plan = _plan()
        plan["steps"].append({
            "step": 2,
            "tool": "respond",
            "description": "fails",
            "parameters": {"message": "second"},
        })
        recovery = {"decision": ErrorDecision.ABORT, "reason": "stopped"}
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=plan),
            patch("agent.executor._call_tool", side_effect=["hello", False]),
            patch("agent.executor.analyze_error", return_value=recovery),
        ):
            result = AgentExecutor().execute_result("partial")
        self.assertEqual(result.status, ResultStatus.PARTIAL)
        self.assertIn("Partially completed", result.message)

    def test_success_is_typed_and_duplicate_request_is_cached(self):
        executor = AgentExecutor()
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=_plan()),
            patch("agent.executor._call_tool", return_value="hello") as call_tool,
        ):
            first = executor.execute_result("hello", request_id="request-1")
            second = executor.execute_result("hello", request_id="request-1")
        self.assertEqual(first.status, ResultStatus.SUCCEEDED)
        self.assertIs(first, second)
        self.assertEqual(first.step_results[0].output, "hello")
        call_tool.assert_called_once()

    def test_false_tool_result_is_never_reported_as_success(self):
        recovery = {
            "decision": ErrorDecision.ABORT,
            "reason": "tool reported failure",
        }
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=_plan()),
            patch("agent.executor._call_tool", return_value=False),
            patch("agent.executor.analyze_error", return_value=recovery),
        ):
            result = AgentExecutor().execute_result("failure")
        self.assertEqual(result.status, ResultStatus.FAILED)
        self.assertFalse(result.step_results[0].succeeded)

    def test_timeout_is_typed_and_stops_later_steps(self):
        plan = _plan()
        plan["steps"].append({
            "step": 2,
            "tool": "respond",
            "description": "must not run",
            "parameters": {"message": "second"},
        })
        call_tool = Mock(side_effect=lambda *args: time.sleep(0.15) or "late")
        spec = SimpleNamespace(timeout_seconds=0.03, external_impact=False)
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=plan),
            patch("agent.executor._call_tool", call_tool),
            patch("agent.executor.get_tool_spec", return_value=spec),
        ):
            result = AgentExecutor().execute_result("timeout")
        self.assertEqual(result.status, ResultStatus.TIMED_OUT)
        self.assertEqual(call_tool.call_count, 1)

    def test_cancellation_stops_dispatching_later_steps(self):
        cancel = threading.Event()
        plan = _plan()
        plan["steps"].append({
            "step": 2,
            "tool": "respond",
            "description": "must not run",
            "parameters": {"message": "second"},
        })

        def slow_tool(*args):
            time.sleep(0.15)
            return "late"

        call_tool = Mock(side_effect=slow_tool)
        timer = threading.Timer(0.02, cancel.set)
        timer.start()
        try:
            with (
                patch("agent.executor._build_agent_context", return_value=""),
                patch("agent.executor.create_plan", return_value=plan),
                patch("agent.executor._call_tool", call_tool),
            ):
                result = AgentExecutor().execute_result("cancel", cancel_flag=cancel)
        finally:
            timer.cancel()
        self.assertEqual(result.status, ResultStatus.CANCELLED)
        self.assertEqual(call_tool.call_count, 1)

    def test_external_impact_failure_is_not_automatically_retried(self):
        recovery = {"decision": ErrorDecision.RETRY, "reason": "temporary"}
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch(
                "agent.executor.create_plan",
                return_value=_plan(
                    "send_message",
                    {
                        "receiver": "Ada",
                        "message_text": "Hello",
                        "platform": "WhatsApp",
                    },
                ),
            ),
            patch("agent.executor._call_tool", side_effect=RuntimeError("uncertain")) as call,
            patch("agent.executor.analyze_error", return_value=recovery),
        ):
            result = AgentExecutor().execute_result(
                "send", approve=lambda _: True
            )
        self.assertEqual(result.status, ResultStatus.FAILED)
        self.assertIn("prevent duplication", result.message)
        call.assert_called_once()


class TaskQueueResultTests(unittest.TestCase):
    def test_submit_idempotency_key_returns_same_task(self):
        queue = TaskQueue()
        first = queue.submit("same", idempotency_key="event-1")
        second = queue.submit("same", idempotency_key="event-1")
        self.assertEqual(first, second)
        self.assertEqual(queue.pending_count(), 1)

    def test_failed_execution_result_marks_task_failed(self):
        queue = TaskQueue()
        queue._active_count = 1
        callback = Mock()
        queue._executor = Mock()
        queue._executor.execute_result.return_value = ExecutionResult(
            ResultStatus.FAILED, "failed"
        )
        task = Task(
            priority=TaskPriority.NORMAL.value,
            created_at=time.time(),
            task_id="task-1",
            goal="fail",
            on_complete=callback,
        )
        queue._run_task(task)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.error, "failed")
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
