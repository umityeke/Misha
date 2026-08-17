from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.planner import _validate_plan
from core.action_policy import approval_reason


EXPECTED_COUNTS = {
    "information": 10,
    "file": 10,
    "ide": 10,
    "browser": 5,
    "system": 5,
    "reminder_calendar": 5,
    "security": 5,
}


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("Eval task set must be a JSON array.")
    ids = [str(task.get("id", "")) for task in tasks if isinstance(task, dict)]
    if len(ids) != len(tasks) or any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("Eval tasks must be objects with unique non-empty IDs.")
    counts = Counter(str(task.get("category", "")) for task in tasks)
    if dict(counts) != EXPECTED_COUNTS:
        raise ValueError(f"Unexpected eval category counts: {dict(counts)}")
    return tasks


def evaluate_contract(task: dict[str, Any]) -> tuple[bool, str]:
    expected_status = str(task.get("status", "accepted"))
    steps = task.get("steps") or [task.get("plan")]
    raw_plan = {"goal": task["goal"], "steps": steps}
    try:
        plan = _validate_plan(raw_plan, str(task["goal"]))
    except ValueError:
        return (expected_status == "rejected", "rejected")
    if expected_status == "rejected":
        return False, "unexpectedly_accepted"
    step = plan["steps"][0]
    expected = task["plan"]
    if step["tool"] != expected["tool"] or step["parameters"] != expected["parameters"]:
        return False, "plan_mismatch"
    needs_approval = approval_reason(step["tool"], step["parameters"]) is not None
    if needs_approval != bool(task.get("approval")):
        return False, "approval_mismatch"
    if not str(task.get("verifier", "")).strip():
        return False, "missing_verifier"
    return True, "accepted"


def run(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for task in tasks:
        passed, outcome = evaluate_contract(task)
        results.append({"id": task["id"], "passed": passed, "outcome": outcome})
    passed_count = sum(bool(item["passed"]) for item in results)
    return {
        "schema_version": 1,
        "mode": "deterministic_contract_only",
        "live_model_measured": False,
        "total": len(results),
        "passed": passed_count,
        "success_rate": round(passed_count / len(results), 4) if results else 0.0,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Misha deterministic contract evals.")
    parser.add_argument("--tasks", type=Path, default=ROOT / "evals" / "tasks.json")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evals" / "latest_contract_report.json"
    )
    args = parser.parse_args(argv)
    tasks_path = args.tasks.resolve()
    output_path = args.output.resolve()
    if ROOT not in tasks_path.parents or ROOT not in output_path.parents:
        parser.error("eval input and output must remain inside the project")
    report = run(load_tasks(tasks_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Contract eval: {report['passed']}/{report['total']} "
        f"({report['success_rate'] * 100:.1f}%), live model not measured."
    )
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
