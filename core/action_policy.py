from __future__ import annotations

import json
import re


_SYSTEM_POWER_ACTIONS = {
    "shutdown", "restart", "reboot", "sleep", "hibernate", "logout", "log_out",
}
_GIT_MUTATIONS = {"commit", "push", "pull", "branch"}
_FILE_MUTATIONS = {
    "append", "copy", "create_file", "delete", "move", "rename", "undo", "write",
}
_CODE_MUTATIONS = {"write", "edit", "run", "test"}


def approval_reason(tool_name: str, args: dict) -> str | None:
    """Return a user-facing reason when an action needs explicit approval."""
    action = str(args.get("action", "")).strip().lower()

    if tool_name == "send_message":
        if action == "preview":
            return None
        receiver = str(args.get("receiver", "unknown recipient"))
        return f"send a message to {receiver}"
    if tool_name == "reminder":
        if action in {"list", "status"}:
            return None
        return f"{action or 'create'} a system reminder"
    if tool_name == "personal_apps":
        if action in {"mail_inbox", "mail_search", "calendar_list", "calendar_events"}:
            return None
        if action == "mail_draft":
            return f"create a Mail draft for {args.get('receiver', 'the selected recipient')}"
        if action == "mail_reply_draft":
            return f"create a reply draft for local Mail message {args.get('original_message_id', '')}"
        if action == "mail_send":
            return f"send Mail to {args.get('receiver', 'the selected recipient')}"
        if action in {"calendar_create", "calendar_update", "calendar_delete"}:
            verb = action.removeprefix("calendar_")
            target = args.get("event_id") or args.get("calendar_name", "the selected calendar")
            return f"{verb} local calendar item {target}"
        return "run an unrecognized local personal-app operation"
    if tool_name == "file_controller":
        if action in _FILE_MUTATIONS:
            return f"{action} a file or folder"
        if action in {"read", "list", "find", "disk_usage"}:
            return None
        return "run an unrecognized file operation"
    if tool_name == "git_controller" and action in _GIT_MUTATIONS:
        return f"run the Git {action} operation"
    if tool_name == "db_manager":
        if action == "schema":
            return None
        if action == "query":
            query = str(args.get("query", "")).lstrip().upper()
            if query.startswith(("SELECT", "EXPLAIN", "WITH")):
                return None
            return "execute a database-changing query"
        return "execute a verified local database mutation"
    if tool_name == "computer_settings" and action in _SYSTEM_POWER_ACTIONS:
        return f"{action} the computer"
    if tool_name == "game_updater":
        if action in {"install", "update", "schedule"}:
            return f"{action} games or launchers"
        if bool(args.get("shutdown_when_done")):
            return "shut down the computer when the game operation finishes"
        if action in {"list", "download_status"}:
            return None
        return "run an unrecognized game or launcher operation"
    if tool_name == "code_helper":
        if action in _CODE_MUTATIONS:
            return f"{action} code"
        if action == "explain":
            return None
        return "run an unrecognized code operation"
    if tool_name == "dev_agent":
        return "let the development agent modify or run a project"
    if tool_name == "developer_tools":
        if action == "edit":
            return "apply a transactional code edit"
        if action == "rollback":
            return "roll back a previous code edit"
        if action in {"test", "lint", "typecheck"}:
            return f"run the project's sandboxed {action} command"
        if action == "git_push":
            return "push the selected workspace to its configured Git remote"
        return None
    if tool_name == "rollback_edit" and action == "rollback":
        return "roll back a previous code transaction"
    if tool_name == "desktop_control":
        if action in {"clean", "organize", "wallpaper", "wallpaper_url"}:
            return f"change the desktop using the {action} action"
        if action == "list":
            return None
        return "run an unrecognized desktop operation"
    try:
        from agent.tool_registry import RiskLevel, get_tool_spec

        spec = get_tool_spec(tool_name)
        if spec.external_impact:
            return f"run the external-impact {tool_name} action"
        if spec.risk is RiskLevel.EXTERNAL_IMPACT:
            return f"let {tool_name} affect another application"
        if spec.risk in {
            RiskLevel.WRITE,
            RiskLevel.DESTRUCTIVE,
        }:
            return f"let {tool_name} change local data"
    except (ImportError, ValueError):
        pass
    return None


def approval_prompt(tool_name: str, args: dict, reason: str) -> str:
    safe_args = {}
    for key, value in args.items():
        if re.search(r"token|password|secret|api[_-]?key|credential", str(key), re.I):
            safe_args[str(key)] = "[REDACTED]"
            continue
        rendered = str(value)
        safe_args[str(key)] = rendered[:160] + ("…" if len(rendered) > 160 else "")
    target = json.dumps(safe_args, ensure_ascii=False, sort_keys=True)
    return (
        "⚠️ Misha etkili bir işlem yapmak istiyor:\n\n"
        f"İşlem: {reason}\n"
        f"Araç: {tool_name}\n"
        f"Tam hedef: {target}\n\n"
        "Devam etmesine izin veriyor musunuz?"
    )
