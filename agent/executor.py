import threading
import time
from queue import Empty, Queue
from typing import Any, Callable

from agent.planner       import create_plan, replan, summarize_plan
from agent.error_handler import analyze_error, ErrorDecision
from core.action_policy import approval_reason
from core.ai.runtime import generate_text
from core.approval import ApprovalManager
from core.retry_policy import classify_retry, exponential_backoff
from agent.runtime_result import ExecutionResult, ResultStatus, ToolResult
from agent.tool_registry import get_tool_spec, validate_tool_parameters
from agent.verifier import VerificationStatus, verify_tool_result
from core.user_preferences import personalize_address


def _build_agent_context(extra_context: str = "") -> str:
    sections = []
    if extra_context.strip():
        sections.append(extra_context.strip())
    try:
        from memory.memory_manager import format_memory_for_prompt, load_memory
        memory_context = format_memory_for_prompt(load_memory()).strip()
        if memory_context:
            sections.append(memory_context)
    except Exception as exc:
        print(f"[Executor] ⚠️ Memory context unavailable: {exc}")
    try:
        from memory.learning_store import format_rules_for_prompt
        learned_rules = format_rules_for_prompt().strip()
        if learned_rules:
            sections.append(learned_rules)
    except Exception as exc:
        print(f"[Executor] ⚠️ Learned rules unavailable: {exc}")
    try:
        from core.ide_context import current_ide_context
        ide_context = current_ide_context.get_context_string().strip()
        if ide_context:
            sections.append("[CURRENT IDE CONTEXT]\n" + ide_context)
    except Exception as exc:
        print(f"[Executor] ⚠️ IDE context unavailable: {exc}")
    return "\n\n".join(sections)[:8000]

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                print(f"[Executor] 💉 Injected + translated content")

    return params
def _detect_language(text: str) -> str:
    try:
        response = generate_text(
            f"What language is this text written in? "
            f"Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}",
            temperature=0.0,
        )
        return response.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        target_lang = _detect_language(goal)
        print(f"[Executor] 🌐 Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        translated = generate_text(prompt, temperature=0.1).strip()
        print(f"[Executor] ✅ Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Executor] ⚠️ Translation failed: {e}")
        return content

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> Any:

    if tool == "respond":
        message = str(parameters.get("message", "")).strip()
        if not message:
            raise ValueError("respond.message is required")
        return message

    if tool == "remember_rule":
        from memory.learning_store import add_rule
        return add_rule(
            rule=str(parameters.get("rule", "")),
            scope=str(parameters.get("scope", "global")),
        )

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None)

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None)
    elif tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak)
    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None)

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None)

    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak)

    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak)

    elif tool == "developer_tools":
        from actions.developer_tools import developer_tools
        return developer_tools(parameters=parameters, player=None, speak=speak)

    elif tool == "db_manager":
        from actions.db_manager import db_manager
        return db_manager(parameters=parameters, player=None)

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        return screen_process(parameters=parameters, player=None)

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None)

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None)

    elif tool == "personal_apps":
        from actions.personal_apps import personal_apps
        return personal_apps(parameters=parameters, player=None)

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None)

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None)

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None)

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None)

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None)

    elif tool == "generated_code":
        raise PermissionError(
            "Generated-code execution is disabled. Use a registered, validated tool."
        )

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak)

    else:
        raise ValueError(f"Unknown or disabled tool: {tool}")


def _authorize_tool(
    manager: ApprovalManager,
    tool: str,
    parameters: dict,
    approve: Callable[[str], bool] | None,
) -> str | None:
    reason = approval_reason(tool, parameters)
    if not reason:
        return None
    if approve is None:
        return f"Approval required before {tool}: {reason}"
    grant = manager.request(tool, parameters, reason, approve)
    if grant is None:
        return f"User rejected the {tool} action."
    try:
        manager.consume(grant.token, tool, parameters)
    except PermissionError as exc:
        return f"Approval failed for {tool}: {exc}"
    return None


def _normalize_tool_output(tool: str, raw: Any) -> str:
    if raw is False or raw is None:
        raise RuntimeError(f"{tool} did not report a successful result.")
    if raw is True:
        return "Done."
    output = personalize_address(str(raw).strip())
    if not output:
        raise RuntimeError(f"{tool} returned an empty result.")
    return output


def _run_tool_bounded(
    tool: str,
    parameters: dict,
    speak: Callable | None,
    cancel_flag: threading.Event | None,
    attempt: int,
    state_callback: Callable[[str], None] | None = None,
) -> ToolResult:
    """Run one tool with a registry deadline and cooperative cancellation boundary."""
    started = time.monotonic()
    result_queue: Queue[tuple[bool, Any]] = Queue(maxsize=1)

    def invoke() -> None:
        try:
            result_queue.put((True, _call_tool(tool, parameters, speak)))
        except BaseException as exc:
            result_queue.put((False, exc))

    worker = threading.Thread(
        target=invoke,
        name=f"misha-tool-{tool}",
        daemon=True,
    )
    worker.start()
    deadline = started + get_tool_spec(tool).timeout_seconds
    while worker.is_alive():
        if cancel_flag is not None and cancel_flag.is_set():
            return ToolResult(
                tool=tool,
                status=ResultStatus.CANCELLED,
                error="Task cancelled; no later step was started.",
                duration_seconds=time.monotonic() - started,
                attempt=attempt,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return ToolResult(
                tool=tool,
                status=ResultStatus.TIMED_OUT,
                error=f"{tool} exceeded its {get_tool_spec(tool).timeout_seconds}s deadline.",
                duration_seconds=time.monotonic() - started,
                attempt=attempt,
            )
        worker.join(timeout=min(0.05, remaining))

    try:
        ok, value = result_queue.get_nowait()
    except Empty:
        ok, value = False, RuntimeError(f"{tool} ended without a result.")
    duration = time.monotonic() - started
    if not ok:
        retry = classify_retry(value)
        return ToolResult(
            tool=tool,
            status=ResultStatus.FAILED,
            error=str(value) or value.__class__.__name__,
            duration_seconds=duration,
            attempt=attempt,
            retryable=retry.retryable,
            retry_category=retry.category,
        )
    try:
        output = _normalize_tool_output(tool, value)
    except Exception as exc:
        retry = classify_retry(exc)
        return ToolResult(
            tool=tool,
            status=ResultStatus.FAILED,
            error=str(exc),
            duration_seconds=duration,
            attempt=attempt,
            retryable=retry.retryable,
            retry_category=retry.category,
        )
    if state_callback is not None:
        try:
            state_callback("VERIFYING")
        except Exception:
            pass
    verification = verify_tool_result(tool, parameters, output)
    if verification.status is VerificationStatus.FAILED:
        return ToolResult(
            tool=tool,
            status=ResultStatus.FAILED,
            output=output,
            error=verification.message,
            duration_seconds=duration,
            attempt=attempt,
            verification=verification,
            retryable=False,
            retry_category="verification_failed",
        )
    if verification.status is VerificationStatus.UNVERIFIED:
        return ToolResult(
            tool=tool,
            status=ResultStatus.UNVERIFIED,
            output=output,
            error=verification.message,
            duration_seconds=duration,
            attempt=attempt,
            verification=verification,
            retryable=False,
            retry_category="unverified_effect",
        )
    return ToolResult(
        tool=tool,
        status=ResultStatus.SUCCEEDED,
        output=output,
        duration_seconds=duration,
        attempt=attempt,
        verification=verification,
    )


def _audit_tool_result(
    tool: str,
    parameters: dict,
    result: ToolResult,
    request_id: str,
) -> None:
    try:
        from core.audit_logger import AuditEvent, log_event

        spec = get_tool_spec(tool)
        log_event(AuditEvent(
            category="tool_execution",
            action="execute",
            status=result.status.value,
            request_id=request_id,
            tool=tool,
            risk=spec.risk.value,
            duration_seconds=result.duration_seconds,
            details={
                "parameters": parameters,
                "attempt": result.attempt,
                "output": result.output,
                "error": result.error,
                "verification": (
                    result.verification.status.value
                    if result.verification is not None
                    else "none"
                ),
                "retryable": result.retryable,
                "retry_category": result.retry_category,
            },
        ))
    except Exception:
        pass

class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2

    def __init__(self, journal=None) -> None:
        self._request_lock = threading.Lock()
        self._request_results: dict[str, ExecutionResult | None] = {}
        self._journal = journal

    def _journal_call(self, method: str, *args, **kwargs) -> None:
        if self._journal is None:
            return
        try:
            getattr(self._journal, method)(*args, **kwargs)
        except Exception:
            # Recovery metadata must never make the active task unavailable.
            pass

    def execute(self, goal: str, **kwargs) -> str:
        """Compatibility facade; active callers should use the typed result API."""
        return self.execute_result(goal, **kwargs).message

    def _claim_request(self, request_id: str) -> ExecutionResult | None:
        if not request_id:
            return None
        with self._request_lock:
            if request_id in self._request_results:
                existing = self._request_results[request_id]
                if existing is not None:
                    return existing
                return ExecutionResult(
                    ResultStatus.REJECTED,
                    "Duplicate request is already running.",
                    request_id=request_id,
                )
            self._request_results[request_id] = None
            while len(self._request_results) > 256:
                oldest = next(iter(self._request_results))
                if self._request_results[oldest] is None:
                    break
                self._request_results.pop(oldest)
        return None

    def _finish(self, result: ExecutionResult) -> ExecutionResult:
        if result.request_id:
            with self._request_lock:
                self._request_results[result.request_id] = result
        return result

    def execute_result(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
        approve:     Callable[[str], bool] | None = None,
        context:     str = "",
        request_id:  str = "",
        state_callback: Callable[[str], None] | None = None,
        plan_callback: Callable[[str], None] | None = None,
    ) -> ExecutionResult:
        print(f"\n[Executor] 🎯 Goal: {goal}")

        if speak is not None:
            original_speak = speak
            speak = lambda text: original_speak(personalize_address(str(text)))

        duplicate = self._claim_request(request_id)
        if duplicate is not None:
            return duplicate

        if request_id:
            self._journal_call("start", request_id, goal)

        replan_attempts = 0
        approval_manager = ApprovalManager()
        completed_steps = []
        step_results    = {}
        typed_results: list[ToolResult] = []
        total_steps = 0
        external_effect_seen = False

        def emit(state: str) -> None:
            if state_callback is not None:
                try:
                    state_callback(state)
                except Exception:
                    pass
            if request_id:
                self._journal_call("set_phase", request_id, state.casefold())

        def finish(status: ResultStatus, message: str) -> ExecutionResult:
            effective = status
            if status in {
                ResultStatus.FAILED,
                ResultStatus.REJECTED,
                ResultStatus.TIMED_OUT,
                ResultStatus.UNVERIFIED,
            } and any(item.succeeded for item in typed_results):
                effective = ResultStatus.PARTIAL
                message = f"Partially completed; a later step stopped safely. {message}"
            if request_id:
                self._journal_call(
                    "set_phase",
                    request_id,
                    effective.value,
                    completed_steps=len(completed_steps),
                    total_steps=total_steps,
                    external_effect_seen=external_effect_seen,
                )
            return self._finish(ExecutionResult(
                effective, message, tuple(typed_results), request_id
            ))

        emit("PLANNING")
        try:
            plan = create_plan(goal, context=_build_agent_context(context))
            total_steps = len(plan.get("steps", []))
            if plan_callback is not None:
                try:
                    plan_callback(summarize_plan(plan))
                except Exception:
                    pass
            if request_id:
                self._journal_call(
                    "set_phase", request_id, "planning", total_steps=total_steps
                )
        except Exception as exc:
            return finish(ResultStatus.FAILED, f"Planning failed: {exc}")

        while True:
            steps = plan.get("steps", [])

            if not steps:
                msg = "I couldn't create a valid plan for this task, sir."
                if speak: speak(msg)
                return finish(ResultStatus.FAILED, msg)

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Task cancelled, sir.")
                    return finish(ResultStatus.CANCELLED, "Task cancelled.")

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)
                try:
                    params = validate_tool_parameters(tool, params)
                except ValueError as validation_error:
                    return finish(
                        ResultStatus.REJECTED,
                        f"Task rejected: {validation_error}",
                    )

                if approval_reason(tool, params):
                    emit("AWAITING_APPROVAL")
                approval_error = _authorize_tool(
                    approval_manager, tool, params, approve
                )
                if approval_error:
                    if speak: speak(approval_error)
                    return finish(ResultStatus.REJECTED, approval_error)

                print(f"\n[Executor] ▶️ Step {step_num}: [{tool}] {desc}")

                spec = get_tool_spec(tool)
                max_attempts = max(1, int(getattr(spec, "max_attempts", 1)))
                idempotent = bool(getattr(spec, "idempotent", False))
                attempt = 1
                step_ok = False

                while attempt <= max_attempts:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    risk_value = getattr(getattr(spec, "risk", None), "value", "read_only")
                    if spec.external_impact or risk_value != "read_only":
                        external_effect_seen = True
                        if request_id:
                            self._journal_call(
                                "set_phase",
                                request_id,
                                "executing",
                                completed_steps=len(completed_steps),
                                total_steps=total_steps,
                                external_effect_seen=True,
                            )
                    emit("EXECUTING")
                    tool_result = _run_tool_bounded(
                        tool, params, speak, cancel_flag, attempt, state_callback
                    )
                    typed_results.append(tool_result)
                    _audit_tool_result(tool, params, tool_result, request_id)
                    if tool_result.succeeded:
                        step_results[step_num] = tool_result.output
                        completed_steps.append(step)
                        if request_id:
                            self._journal_call(
                                "set_phase",
                                request_id,
                                "executing",
                                completed_steps=len(completed_steps),
                                total_steps=total_steps,
                                external_effect_seen=external_effect_seen,
                            )
                        print(
                            f"[Executor] ✅ Step {step_num} done: "
                            f"{tool_result.output[:100]}"
                        )
                        step_ok = True
                        break
                    if tool_result.status in {
                        ResultStatus.CANCELLED,
                        ResultStatus.TIMED_OUT,
                        ResultStatus.UNVERIFIED,
                    }:
                        msg = tool_result.error
                        if speak:
                            speak(msg)
                        return finish(tool_result.status, msg)
                    else:
                        error_msg = tool_result.error
                        print(f"[Executor] ❌ Step {step_num} attempt {attempt} failed: {error_msg}")

                        emit("RECOVERING")
                        if tool_result.retryable and idempotent and not spec.external_impact:
                            if attempt < max_attempts:
                                delay = exponential_backoff(attempt)
                                attempt += 1
                                if cancel_flag and cancel_flag.wait(timeout=delay):
                                    return finish(
                                        ResultStatus.CANCELLED, "Task cancelled."
                                    )
                                if cancel_flag is None:
                                    time.sleep(delay)
                                continue

                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")

                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            if (
                                spec.external_impact
                                or not idempotent
                                or not tool_result.retryable
                            ):
                                message = (
                                    "Automatic retry was blocked because the operation is "
                                    "not proven idempotent and transient; this helps prevent duplication."
                                )
                                return finish(ResultStatus.FAILED, message)
                            return finish(
                                ResultStatus.FAILED,
                                "Retry budget was exhausted safely.",
                            )

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Executor] ⏭️ Skipping step {step_num}")
                            typed_results.append(ToolResult(
                                tool=tool,
                                status=ResultStatus.SKIPPED,
                                error=error_msg,
                                attempt=attempt,
                            ))
                            failed_step = step
                            failed_error = error_msg
                            success = False
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Task aborted, sir. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            return finish(ResultStatus.FAILED, msg)

                        else:
                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if cancel_flag and cancel_flag.is_set():
                    return finish(ResultStatus.CANCELLED, "Task cancelled.")
                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False

                if not success:
                    break

            if success:
                emit("RESPONDING")
                summary = self._summarize(
                    goal, completed_steps, step_results, speak
                )
                return finish(ResultStatus.SUCCEEDED, summary)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Task failed after {replan_attempts} replan attempts, sir."
                if speak: speak(msg)
                return finish(ResultStatus.FAILED, msg)

            if speak: speak("Adjusting my approach, sir.")

            replan_attempts += 1
            emit("PLANNING")
            try:
                plan = replan(goal, completed_steps, failed_step, failed_error)
                total_steps = max(total_steps, len(completed_steps) + len(plan.get("steps", [])))
                if plan_callback is not None:
                    try:
                        plan_callback("SYS: Revised " + summarize_plan(plan)[5:])
                    except Exception:
                        pass
            except Exception as exc:
                return finish(ResultStatus.FAILED, f"Replanning failed: {exc}")

    def _summarize(
        self,
        goal: str,
        completed_steps: list,
        step_results: dict,
        speak: Callable | None,
    ) -> str:
        if completed_steps and completed_steps[-1].get("tool") == "respond":
            final_result = str(step_results.get(completed_steps[-1].get("step"), "")).strip()
            if final_result:
                if speak: speak(final_result)
                return final_result
        fallback = f"All done. Completed {len(completed_steps)} steps for: {goal[:60]}."
        try:
            steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)
            prompt    = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                "Write a single natural sentence summarizing what was accomplished. "
                "Use the user's configured form of address only when it is provided. "
                "Be direct and positive."
            )
            summary = personalize_address(generate_text(prompt, temperature=0.2).strip())
            if speak: speak(summary)
            return summary
        except Exception:
            if speak: speak(fallback)
            return fallback
