from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import platform
import re
import subprocess
from typing import Any


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    message: str

    @property
    def verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED


_FAILURE_PREFIXES = (
    "access denied", "could not", "error", "failed", "file not found",
    "i couldn't", "i need", "invalid", "no application", "no destination",
    "not found", "permission denied", "please specify", "protected directory",
    "source not found", "that time has already passed", "timed out",
    "transaction is already", "rollback blocked", "rollback target",
    "developer tool error", "developer command failed", "code execution blocked",
    "git push failed", "no allowlisted",
    "navigation blocked", "credential entry blocked", "upload blocked", "download blocked",
    "reminder not found", "reminder error", "could not remove the reminder",
    "message blocked", "duplicate message blocked",
    "unknown action", "unknown browser action", "unsupported",
    "database error", "database mutation blocked",
)


def _reported_failure(output: str) -> VerificationResult | None:
    normalized = output.strip().casefold()
    if not normalized:
        return VerificationResult(VerificationStatus.FAILED, "Tool returned no evidence.")
    if normalized.startswith(_FAILURE_PREFIXES):
        return VerificationResult(
            VerificationStatus.FAILED,
            "Tool output explicitly reported failure.",
        )
    return None


def _target(parameters: dict[str, Any]) -> Path:
    from actions.file_controller import _resolve_path

    base = _resolve_path(str(parameters.get("path", "desktop")))
    name = str(parameters.get("name", ""))
    return (base / name) if name else base


def _verify_file(parameters: dict[str, Any]) -> VerificationResult:
    action = str(parameters.get("action", "")).casefold()
    target = _target(parameters)
    if action in {"create_file", "write"}:
        if not target.is_file():
            return VerificationResult(VerificationStatus.FAILED, "Expected file is missing.")
        content = str(parameters.get("content", ""))
        actual = target.read_text(encoding="utf-8", errors="replace")
        matches = actual.endswith(content) if parameters.get("append") else actual == content
        return VerificationResult(
            VerificationStatus.VERIFIED if matches else VerificationStatus.FAILED,
            "File content matches the requested write." if matches else "File content mismatch.",
        )
    if action == "create_folder":
        ok = target.is_dir()
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Folder exists." if ok else "Expected folder is missing.",
        )
    if action == "delete":
        ok = not target.exists()
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Original path no longer exists." if ok else "Original path still exists.",
        )
    if action == "rename":
        renamed = target.parent / str(parameters.get("new_name", ""))
        ok = bool(parameters.get("new_name")) and renamed.exists() and not target.exists()
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Renamed path exists." if ok else "Rename could not be confirmed.",
        )
    if action in {"move", "copy"}:
        from actions.file_controller import _resolve_path

        destination = _resolve_path(str(parameters.get("destination", "")))
        candidates = (destination, destination / target.name)
        found = next((path for path in candidates if path.exists()), None)
        source_ok = action == "copy" or not target.exists()
        ok = found is not None and source_ok
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Destination state confirmed." if ok else "Destination state was not confirmed.",
        )
    if action == "undo":
        from core.file_transactions import transaction_status

        ok = transaction_status(str(parameters.get("transaction_id", ""))) == "rolled_back"
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Encrypted rollback transaction confirmed." if ok else "Rollback was not confirmed.",
        )
    return VerificationResult(
        VerificationStatus.VERIFIED,
        "Read-only file operation returned a valid result contract.",
    )


def _verify_developer(parameters: dict[str, Any], output: str) -> VerificationResult:
    action = str(parameters.get("action", "")).casefold()
    if action == "git_push":
        from actions.developer_tools import selected_workspace

        try:
            workspace = selected_workspace(str(parameters.get("workspace", "")))
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, capture_output=True,
                text=True, timeout=5, check=True,
            ).stdout.strip()
            upstream = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                cwd=workspace, capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            remote, branch = upstream.split("/", 1)
            if not remote or not branch or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
                raise ValueError("Invalid upstream ref.")
            remote_result = subprocess.run(
                ["git", "ls-remote", "--exit-code", remote, f"refs/heads/{branch}"],
                cwd=workspace, capture_output=True, text=True, timeout=30, check=True,
            )
            remote_head = remote_result.stdout.split(maxsplit=1)[0]
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return VerificationResult(
                VerificationStatus.UNVERIFIED,
                f"Remote Git ref could not be independently queried: {type(exc).__name__}.",
            )
        matches = bool(head) and head == remote_head
        return VerificationResult(
            VerificationStatus.VERIFIED if matches else VerificationStatus.FAILED,
            "Remote branch matches local HEAD." if matches else "Remote branch differs from local HEAD.",
        )
    if action == "edit":
        from actions.developer_tools import selected_workspace, _workspace_path

        try:
            workspace = selected_workspace(str(parameters.get("workspace", "")))
            target = _workspace_path(workspace, str(parameters.get("file_path", "")), must_exist=True)
            matches = target.read_text(encoding="utf-8") == str(parameters.get("content", ""))
        except (OSError, UnicodeError, ValueError):
            matches = False
        return VerificationResult(
            VerificationStatus.VERIFIED if matches else VerificationStatus.FAILED,
            "Transactional edit content confirmed." if matches else "Edited content was not confirmed.",
        )
    if action == "rollback":
        from core.file_transactions import transaction_status

        ok = transaction_status(str(parameters.get("transaction_id", ""))) == "rolled_back"
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Developer rollback confirmed." if ok else "Developer rollback was not confirmed.",
        )
    if action in {"git_status", "git_diff", "git_log", "commit_suggest"}:
        from actions.developer_tools import selected_workspace

        try:
            workspace = selected_workspace(str(parameters.get("workspace", "")))
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"], cwd=workspace,
                capture_output=True, text=True, timeout=5, check=True,
            )
            is_repository = result.stdout.strip() == "true"
        except (OSError, subprocess.SubprocessError, ValueError):
            is_repository = False
        return VerificationResult(
            VerificationStatus.VERIFIED if is_repository else VerificationStatus.FAILED,
            "Git repository state independently confirmed."
            if is_repository else "Selected workspace is not a confirmed Git repository.",
        )
    return VerificationResult(VerificationStatus.VERIFIED, "Developer tool output contract accepted.")


def _verify_browser(parameters: dict[str, Any], output: str) -> VerificationResult:
    action = str(parameters.get("action", "")).casefold()
    if action in {"go_to", "search", "get_url"}:
        from actions.browser_control import _validate_url, read_current_url

        candidate = output.split("Opened: ", 1)[-1].strip() if "Opened: " in output else output.strip()
        try:
            reported = _validate_url(candidate)
            observed = read_current_url(str(parameters.get("browser", "")) or None)
        except (OSError, RuntimeError, ValueError):
            return VerificationResult(VerificationStatus.FAILED, "Safe browser URL was not confirmed.")
        matches = reported == observed
        return VerificationResult(
            VerificationStatus.VERIFIED if matches else VerificationStatus.FAILED,
            "Live browser URL independently confirmed."
            if matches else "Reported browser URL differs from the live page.",
        )
    if action == "get_text":
        ok = output.startswith("[UNTRUSTED WEB CONTENT")
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Untrusted web content boundary confirmed." if ok else "Web content isolation label is missing.",
        )
    if action in {"download", "screenshot"}:
        marker = "Downloaded: " if action == "download" else "Screenshot saved: "
        try:
            path = Path(output.split(marker, 1)[1].strip())
            ok = path.is_file()
        except (IndexError, OSError):
            ok = False
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Browser artifact exists." if ok else "Browser artifact was not confirmed.",
        )
    if action in {"list_browsers"}:
        return VerificationResult(VerificationStatus.VERIFIED, "Browser session list returned.")
    if action in {"click", "smart_click", "type", "smart_type", "fill_form", "upload", "press"}:
        from actions.browser_control import read_dom_value

        selector = str(parameters.get("verify_selector", "")).strip()
        property_name = str(parameters.get("verify_property", "")).strip().casefold()
        expected = str(parameters.get("expected_value", ""))
        if action == "type" and not selector:
            selector = str(parameters.get("selector", "")).strip()
            property_name = property_name or "value"
            expected = expected or str(parameters.get("text", ""))
        if action == "upload" and not selector:
            selector = str(parameters.get("selector", "")).strip()
            property_name = property_name or "file_name"
            expected = expected or Path(str(parameters.get("path", ""))).name
        if not selector or not property_name or expected == "":
            return VerificationResult(
                VerificationStatus.UNVERIFIED,
                "Interactive browser action has no explicit DOM postcondition.",
            )
        try:
            observed = read_dom_value(
                str(parameters.get("browser", "")) or None,
                selector,
                property_name,
            )
        except (OSError, RuntimeError, ValueError):
            return VerificationResult(
                VerificationStatus.FAILED,
                "Browser DOM postcondition could not be independently read.",
            )
        matches = observed == expected
        return VerificationResult(
            VerificationStatus.VERIFIED if matches else VerificationStatus.FAILED,
            "Browser DOM postcondition confirmed."
            if matches else "Browser DOM state differs from the approved postcondition.",
        )
    return VerificationResult(
        VerificationStatus.UNVERIFIED,
        "Interactive browser state was not independently confirmed and will not be retried.",
    )


def _verify_rule(parameters: dict[str, Any]) -> VerificationResult:
    from memory.learning_store import list_rules

    expected_rule = " ".join(str(parameters.get("rule", "")).split())
    expected_scope = " ".join(str(parameters.get("scope", "global")).split()) or "global"
    found = any(
        item["rule"] == expected_rule and item["scope"] == expected_scope
        for item in list_rules(scope=expected_scope, limit=200)
    )
    return VerificationResult(
        VerificationStatus.VERIFIED if found else VerificationStatus.FAILED,
        "Learned rule is persisted." if found else "Learned rule was not found.",
    )


def _verify_open_app(parameters: dict[str, Any]) -> VerificationResult:
    name = str(parameters.get("app_name", "")).strip()
    if platform.system() == "Windows":
        return VerificationResult(VerificationStatus.UNVERIFIED, "Process verification unavailable.")
    try:
        result = subprocess.run(
            ["pgrep", "-if", name], capture_output=True, text=True, timeout=2
        )
        found = result.returncode == 0 and bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        found = False
    return VerificationResult(
        VerificationStatus.VERIFIED if found else VerificationStatus.UNVERIFIED,
        "Application process is running." if found else "Application process was not confirmed.",
    )


def _verify_reminder(parameters: dict[str, Any], output: str) -> VerificationResult:
    from core.reminder_store import get_reminder
    from actions.reminder import scheduler_registered

    action = str(parameters.get("action", "create")).casefold()
    reminder_id = str(parameters.get("reminder_id", ""))
    if action in {"create", "edit"}:
        import re

        match = re.search(r"Reminder scheduled: (rem_[0-9a-f]{16})", output)
        item = get_reminder(match.group(1)) if match else None
        ok = (
            item is not None
            and item["status"] == "scheduled"
            and scheduler_registered(item)
        )
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Persistent scheduler registration confirmed." if ok else "Reminder registration was not confirmed.",
        )
    if action == "delete":
        item = get_reminder(reminder_id)
        ok = (
            item is not None
            and item["status"] == "deleted"
            and not scheduler_registered(item)
        )
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Reminder deletion confirmed." if ok else "Reminder deletion was not confirmed.",
        )
    if action in {"list", "status"}:
        return VerificationResult(VerificationStatus.VERIFIED, "Reminder store query completed.")
    return VerificationResult(VerificationStatus.FAILED, "Unknown reminder action.")


def _verify_computer_settings(parameters: dict[str, Any]) -> VerificationResult:
    action = str(parameters.get("action", "")).strip().casefold().replace("-", "_")
    if action not in {"volume_set", "mute", "unmute"}:
        return VerificationResult(
            VerificationStatus.UNVERIFIED,
            "This UI/system effect has no reliable independent state query.",
        )
    try:
        from actions.computer_settings import read_audio_state

        state = read_audio_state()
    except (ImportError, OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        return VerificationResult(
            VerificationStatus.UNVERIFIED,
            f"Audio state could not be independently queried: {type(exc).__name__}.",
        )
    if action == "volume_set":
        try:
            expected = max(0, min(100, int(parameters.get("value", 50))))
        except (TypeError, ValueError):
            return VerificationResult(VerificationStatus.FAILED, "Invalid target volume.")
        actual = int(state["volume"])
        ok = abs(actual - expected) <= 1
        message = "Target output volume confirmed." if ok else "Output volume differs from target."
    else:
        expected_muted = action == "mute"
        ok = bool(state["muted"]) is expected_muted
        message = "Target mute state confirmed." if ok else "Mute state differs from target."
    return VerificationResult(
        VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
        message,
    )


def _verify_database(parameters: dict[str, Any], output: str) -> VerificationResult:
    import json
    from actions.db_manager import _database, read_query

    action = str(parameters.get("action", "query")).strip().casefold()
    try:
        path = _database(parameters)
        if action == "schema":
            query = (
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE type IN ('table','index','view') ORDER BY type, name"
            )
            expected = json.loads(output.split("Database result: ", 1)[1])
        elif action == "query":
            query = str(parameters.get("query", ""))
            expected = json.loads(output.split("Database result: ", 1)[1])
        elif action == "execute":
            query = str(parameters.get("verify_query", ""))
            expected = json.loads(str(parameters.get("expected_json", "")))
        else:
            return VerificationResult(VerificationStatus.FAILED, "Unknown database action.")
        actual = read_query(path, query)
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError):
        return VerificationResult(
            VerificationStatus.FAILED,
            "Database result could not be independently read back.",
        )
    matches = actual == expected
    return VerificationResult(
        VerificationStatus.VERIFIED if matches else VerificationStatus.FAILED,
        "Database state independently confirmed." if matches else "Database state differs from the verified target.",
    )


def verify_tool_result(
    tool: str, parameters: dict[str, Any], output: str
) -> VerificationResult:
    failure = _reported_failure(output)
    if failure is not None:
        return failure
    if tool == "respond":
        expected = str(parameters.get("message", "")).strip()
        ok = output.strip() == expected
        return VerificationResult(
            VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            "Response matches the plan." if ok else "Response differs from the planned message.",
        )
    if tool == "remember_rule":
        return _verify_rule(parameters)
    if tool == "file_controller":
        return _verify_file(parameters)
    if tool == "developer_tools":
        return _verify_developer(parameters, output)
    if tool == "browser_control":
        return _verify_browser(parameters, output)
    if tool == "open_app":
        return _verify_open_app(parameters)
    if tool == "reminder":
        return _verify_reminder(parameters, output)
    if tool == "computer_settings":
        return _verify_computer_settings(parameters)
    if tool == "db_manager":
        return _verify_database(parameters, output)
    from agent.tool_registry import get_tool_spec

    if get_tool_spec(tool).external_impact:
        return VerificationResult(
            VerificationStatus.UNVERIFIED,
            "The external effect could not be independently confirmed; it will not be retried.",
        )
    return VerificationResult(
        VerificationStatus.VERIFIED,
        "Output contract passed for a non-external tool.",
    )
