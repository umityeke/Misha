import json
import re
import sys
from pathlib import Path

from core.ai.runtime import generate_json
from core.action_policy import approval_reason
from agent.tool_registry import TOOL_REGISTRY, planner_catalog, validate_tool_parameters


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


PLANNER_PROMPT = """You are the planning module of MISHA, a private local AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- NEVER reference previous step results in parameters. Every step is independent.
- Use web_search only for public internet research or current external data.
- NEVER use web_search to inspect a local project, local file, installed software, or IDE context.
- Use developer_tools for local codebase inspection, testing, debugging, Git reads, and transactional code changes.
- Never use the legacy dev_agent; it is retained only for backward compatibility.
- Never invent a filename, workspace path, package manager, framework, or command.
- When the local workspace or required path is unknown, ask one concise question with respond.
- Use file_controller to save content to disk.
- Use respond for conversation, explanations, or questions that need no external action.
- When the user explicitly teaches a lasting preference or says "from now on", use remember_rule.
- Never store passwords, tokens, API keys, secrets, or one-time sensitive values as rules.
- If a material detail is missing, use respond to ask one concise clarifying question.
- Prefer safe, reversible and read-only actions.
- Max 5 steps. Use the minimum steps needed.
- Add depends_on as a list of step numbers only when a step needs another step.
- Never create circular, self, missing, or duplicate dependencies.

AVAILABLE TOOLS AND THEIR PARAMETERS:

respond
  message: string (required)

remember_rule
  rule: string (required) — durable instruction stated by the user
  scope: string (optional, default: global)

open_app
  app_name: string (required)

web_search
  query: string (required) — write a clear, focused search query
  mode: "search" or "compare" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)

game_updater
  action: "update" | "install" | "list" | "download_status" | "schedule" (required)
  platform: "steam" | "epic" | "both" (optional, default: both)
  game_name: string (optional)
  app_id: string (optional)
  shutdown_when_done: boolean (optional)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "get_text" | "press" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  text: string (for click/type)
  direction: "up" | "down" (for scroll)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (required)
  path: string — use "desktop" for Desktop folder
  name: string — filename
  content: string — file content (for write/create_file)

computer_settings
  action: string (required)
  description: string — natural language description
  value: string (optional)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (required)
  text: string (for type)
  x, y: int (for click)
  keys: string (for hotkey, e.g. "ctrl+c")
  key: string (for press)
  direction: "up" | "down" (for scroll)
  description: string (for screen_find/screen_click)

screen_process
  text: string (required) — what to analyze or ask about the screen
  angle: "screen" | "camera" (optional)

send_message
  receiver: string (required)
  message_text: string (required)
  platform: string (required)
  action: "preview" | "send" (optional, default: send)
  allow_duplicate: boolean (optional; only when user explicitly requests a duplicate)

reminder
  action: "create" | "list" | "status" | "edit" | "delete" (required)
  date: string YYYY-MM-DD (for create/edit)
  time: string HH:MM (for create/edit)
  message: string (for create/edit)
  timezone: IANA timezone such as "Europe/Istanbul" (optional)
  repeat: "none" | "daily" | "weekly" (optional)
  fold: 0 | 1 for an ambiguous daylight-saving time (optional)
  reminder_id: string (for status/edit/delete)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "trending" (required)
  query: string (for play)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

developer_tools
  action: "select_workspace" | "search" | "context" | "diff_preview" | "edit" | "rollback" | "test" | "lint" | "typecheck" | "git_status" | "git_diff" | "git_log" | "commit_suggest" | "git_push" (required)
  workspace: absolute path inside Desktop, Documents, or Downloads (required for selection; optional after selection)
  file_path: workspace-relative path (for context/diff_preview/edit)
  content: complete UTF-8 file content (for diff_preview/edit)
  query: literal code search text (for search)
  transaction_id: single-use undo ID (for rollback)

db_manager
  action: "schema" | "query" | "execute" (required)
  workspace: selected absolute developer workspace (required)
  db_path: workspace-relative .db/.sqlite/.sqlite3 path (required)
  query: one allowlisted SQL statement (for query/execute)
  verify_query: read-only SELECT proving the exact mutation result (for execute)
  expected_json: exact JSON row array expected from verify_query (for execute)
EXAMPLES:

Goal: "research mechanical engineering and save it to a notepad file"
Steps:

web_search | query: "mechanical engineering overview definition history"
web_search | query: "mechanical engineering applications and future trends"
file_controller | action: write, path: desktop, name: mechanical_engineering.txt, content: "MECHANICAL ENGINEERING RESEARCH\n\nThis file will be filled with web research results."

Goal: "What is the price of Bitcoin"
Steps:

web_search | query: "Bitcoin price today USD"

Goal: "List the files on the desktop and find the largest 5 files"
Steps:

file_controller | action: list, path: desktop
file_controller | action: largest, path: desktop, count: 5

Goal: "Install PUBG from Steam"
Steps:

game_updater | action: install, platform: steam, game_name: "PUBG"

Goal: "Update all my Steam games"
Steps:

game_updater | action: update, platform: steam

Goal: "Explain how to run this project's tests"
Steps:

developer_tools | action: test, workspace: "/absolute/user-provided/workspace"

Goal: "Send John a message on WhatsApp saying there is a meeting tomorrow"
Steps:

send_message | receiver: John, message_text: "There is a meeting tomorrow", platform: WhatsApp

Goal: "Open the clock and set a reminder for 30 minutes later"
Steps:

reminder | action: create, date: [today], time: [now+30min], message: "Reminder", timezone: [user timezone]

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true,
      "depends_on": []
    }
  ]
}
"""


ALLOWED_TOOLS = frozenset(TOOL_REGISTRY)


def _planner_system_prompt() -> str:
    catalog = json.dumps(planner_catalog(), ensure_ascii=False, separators=(",", ":"))
    return (
        PLANNER_PROMPT
        + "\n\nAUTHORITATIVE RUNTIME TOOL SCHEMAS — these override any older examples above:\n"
        + catalog
    )


_STEP_FIELDS = frozenset({
    "step", "tool", "description", "parameters", "critical", "depends_on",
})
_LOCAL_CONTEXT_RE = re.compile(
    r"(?i)(?:\blocal\b|\bworkspace\b|\bcodebase\b|\brepository\b|\brepo\b|"
    r"\bproject\b|\bfile\b|\bfolder\b|\bide\b|\bterminal\b|yerel|proje|"
    r"dosya|klasör|kod tabanı)"
)


def _goal_tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[^\W_]{3,}", str(value).casefold(), re.UNICODE)
        if token not in {"the", "and", "for", "ile", "bir", "bunu", "şunu"}
    }


def _validate_declared_goal(plan: dict, goal: str) -> None:
    declared = str(plan.get("goal", "")).strip()
    expected_tokens = _goal_tokens(goal)
    declared_tokens = _goal_tokens(declared)
    if declared and len(expected_tokens) >= 2 and len(declared_tokens) >= 2 and not (
        expected_tokens & declared_tokens
    ):
        raise ValueError("Plan goal does not align with the user's request")
    plan["goal"] = str(goal).strip()[:2_000]


def _topological_steps(steps: list[dict]) -> list[dict]:
    raw_ids: list[int] = []
    by_id: dict[int, dict] = {}
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError("Every plan step must be an object")
        raw_id = step.get("step", index)
        if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id <= 0:
            raise ValueError("Plan step IDs must be positive integers")
        if raw_id in by_id:
            raise ValueError("Plan step IDs must be unique")
        raw_ids.append(raw_id)
        by_id[raw_id] = step

    dependencies: dict[int, list[int]] = {}
    for raw_id, step in zip(raw_ids, steps):
        deps = step.get("depends_on", [])
        if not isinstance(deps, list) or any(
            not isinstance(dep, int) or isinstance(dep, bool) for dep in deps
        ):
            raise ValueError("depends_on must contain only step numbers")
        if len(deps) != len(set(deps)):
            raise ValueError("Duplicate step dependencies are not allowed")
        if raw_id in deps:
            raise ValueError("A plan step cannot depend on itself")
        missing = sorted(set(deps) - set(raw_ids))
        if missing:
            raise ValueError(f"Unknown dependency step(s): {missing}")
        dependencies[raw_id] = list(deps)

    ordered: list[int] = []
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(step_id: int) -> None:
        if step_id in visiting:
            raise ValueError("Circular plan dependency detected")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)
        ordered.append(step_id)

    for raw_id in raw_ids:
        visit(raw_id)
    canonical = {raw_id: index for index, raw_id in enumerate(ordered, start=1)}
    result = []
    for raw_id in ordered:
        step = by_id[raw_id]
        step["step"] = canonical[raw_id]
        step["depends_on"] = [canonical[dep] for dep in dependencies[raw_id]]
        result.append(step)
    return result


def _validate_plan(
    plan: dict,
    goal: str,
    completed_steps: list[dict] | None = None,
) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("Plan must be an object")
    _validate_declared_goal(plan, goal)
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Invalid plan structure")
    if len(steps) > 5:
        steps = steps[:5]
        plan["steps"] = steps
    steps = _topological_steps(steps)
    plan["steps"] = steps
    fingerprints = {
        (str(item.get("tool", "")), json.dumps(item.get("parameters", {}), sort_keys=True))
        for item in (completed_steps or [])
    }
    seen = set(fingerprints)
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError("Every plan step must be an object")
        unknown_fields = sorted(set(step) - _STEP_FIELDS)
        if unknown_fields:
            raise ValueError(f"Unknown plan step field(s): {', '.join(unknown_fields)}")
        tool = str(step.get("tool", ""))
        if tool not in ALLOWED_TOOLS:
            raise ValueError(f"Unknown or disabled tool in plan: {tool}")
        step["step"] = index
        description = " ".join(str(step.get("description", goal[:200])).split())[:300]
        step["description"] = description or goal[:200]
        step.setdefault("parameters", {})
        step.setdefault("critical", False)
        if not isinstance(step["critical"], bool):
            raise ValueError("Step critical must be a boolean")
        if not isinstance(step["parameters"], dict):
            raise ValueError("Step parameters must be an object")
        step["parameters"] = validate_tool_parameters(tool, step["parameters"])
        if tool == "web_search" and _LOCAL_CONTEXT_RE.search(goal):
            raise ValueError("Web search cannot be used as fallback for local context")
        fingerprint = (tool, json.dumps(step["parameters"], sort_keys=True))
        if fingerprint in seen:
            raise ValueError("Duplicate or already-completed tool step detected")
        seen.add(fingerprint)
    if (
        len(steps) > 1
        and any(step["tool"] == "respond" for step in steps)
        and any(step["tool"] != "respond" for step in steps)
    ):
        raise ValueError("A respond step cannot be mixed with executable tool steps")
    return plan


def summarize_plan(plan: dict) -> str:
    steps = tuple(plan.get("steps", ()))
    risky = sum(
        1 for step in steps
        if approval_reason(step["tool"], step["parameters"])
    )
    lines = [f"SYS: Plan ready — {len(steps)} step(s), {risky} approval-gated."]
    for step in steps:
        suffix = (
            " · approval required"
            if approval_reason(step["tool"], step["parameters"])
            else ""
        )
        lines.append(
            f"  {step['step']}. [{step['tool']}] {step['description'][:160]}{suffix}"
        )
    return "\n".join(lines)[:1_200]


def create_plan(goal: str, context: str = "") -> dict:
    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        plan = generate_json(user_input, system=_planner_system_prompt(), temperature=0.1)
        plan = _validate_plan(plan, goal)

        print(f"[Planner] ✅ Plan: {len(plan['steps'])} steps")
        for s in plan["steps"]:
            print(f"  Step {s['step']}: [{s['tool']}] {s['description']}")

        return plan

    except Exception as e:
        print(f"[Planner] ⚠️ Planning failed: {e}")
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    print("[Planner] 🔄 Fallback plan")
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "respond",
                "description": "Explain that the local planner is unavailable",
                "parameters": {
                    "message": "Yerel zekâ motoruna şu anda erişemiyorum. Ollama ve seçili modeli kontrol eder misin?"
                },
                "critical": False
            }
        ]
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    completed_summary = "\n".join(
        f"  - Step {s['step']} ({s['tool']}): DONE" for s in completed_steps
    )

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        plan = generate_json(prompt, system=_planner_system_prompt(), temperature=0.1)
        plan = _validate_plan(plan, goal, completed_steps=completed_steps)

        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan failed: {e}")
        return _fallback_plan(goal)
