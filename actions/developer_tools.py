from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from core.file_transactions import apply_text_edit, rollback_text_edit
from memory.config_manager import get_config, set_config


MAX_CONTEXT_BYTES = 256 * 1024
MAX_SEARCH_FILES = 10_000
MAX_RESULTS = 100
MAX_OUTPUT_CHARS = 32_000
SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build"}
WORKSPACE_KEY = "developer_workspace"
_TX_ID = re.compile(r"tx_[0-9a-f]{16}")


def _allowed_roots() -> list[Path]:
    return [Path.home() / name for name in ("Desktop", "Documents", "Downloads")]


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    base = root.resolve()
    return resolved == base or resolved.is_relative_to(base)


def _has_symlink(path: Path, root: Path) -> bool:
    try:
        relative = Path(os.path.abspath(path)).relative_to(root.resolve())
    except ValueError:
        return True
    current = root.resolve()
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def validate_workspace(value: str) -> Path:
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute() or not candidate.is_dir():
        raise ValueError("Workspace must be an existing absolute directory.")
    for root in _allowed_roots():
        if _inside(candidate, root) and not _has_symlink(candidate, root):
            return candidate.resolve()
    raise ValueError("Workspace must stay inside Desktop, Documents, or Downloads.")


def selected_workspace(explicit: str = "") -> Path:
    value = str(explicit).strip() or str(get_config(WORKSPACE_KEY) or "").strip()
    if not value:
        raise ValueError("No developer workspace selected.")
    return validate_workspace(value)


def select_workspace(path: str) -> str:
    workspace = validate_workspace(path)
    set_config(WORKSPACE_KEY, str(workspace))
    return f"Developer workspace selected: {workspace}"


def _workspace_path(workspace: Path, relative: str, *, must_exist: bool = False) -> Path:
    rel = Path(str(relative))
    if not str(relative).strip() or rel.is_absolute():
        raise ValueError("File path must be a non-empty workspace-relative path.")
    target = workspace / rel
    if not _inside(target, workspace) or _has_symlink(target, workspace):
        raise ValueError("File path escapes the selected workspace or crosses a symlink.")
    if must_exist and not target.is_file():
        raise ValueError("Workspace file was not found.")
    return target


def _iter_files(workspace: Path) -> Iterable[Path]:
    seen = 0
    for root, dirs, names in os.walk(workspace, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs
            if name not in SKIP_DIRS and not (Path(root) / name).is_symlink()
        )
        for name in sorted(names):
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            seen += 1
            if seen > MAX_SEARCH_FILES:
                return
            yield path


def search_code(workspace: Path, query: str, limit: int = 50) -> str:
    needle = str(query).strip().casefold()
    if not needle:
        return "Invalid search query."
    matches: list[str] = []
    for path in _iter_files(workspace):
        try:
            if path.stat().st_size > MAX_CONTEXT_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(workspace)
        for number, line in enumerate(text.splitlines(), 1):
            if needle in line.casefold():
                safe_line = line.strip()[:300]
                matches.append(f"{relative}:{number}: {safe_line}")
                if len(matches) >= max(1, min(int(limit), MAX_RESULTS)):
                    return "Search results:\n" + "\n".join(matches)
    return "Search results:\n" + "\n".join(matches) if matches else "No matching code found."


def read_context(workspace: Path, relative: str) -> str:
    target = _workspace_path(workspace, relative, must_exist=True)
    if target.stat().st_size > MAX_CONTEXT_BYTES:
        return "Could not read context: file exceeds the 256 KiB limit."
    try:
        return target.read_text(encoding="utf-8", errors="strict")
    except UnicodeError:
        return "Could not read context: file is not valid UTF-8 text."


def diff_preview(workspace: Path, relative: str, content: str) -> str:
    target = _workspace_path(workspace, relative)
    if target.exists() and target.stat().st_size > MAX_CONTEXT_BYTES:
        return "Could not preview diff: existing file exceeds the 256 KiB limit."
    before = target.read_text(encoding="utf-8", errors="strict") if target.exists() else ""
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), str(content).splitlines(keepends=True),
        fromfile=f"a/{relative}", tofile=f"b/{relative}",
    ))
    return diff[:MAX_OUTPUT_CHARS] if diff else "No changes to preview."


def edit_file(workspace: Path, relative: str, content: str) -> str:
    target = _workspace_path(workspace, relative)
    preview = diff_preview(workspace, relative, content)
    if preview == "No changes to preview.":
        return preview
    if len(str(content).encode("utf-8")) > MAX_CONTEXT_BYTES:
        return "Could not edit: content exceeds the 256 KiB limit."
    tx_id = apply_text_edit(target, str(content))
    return f"Transactional edit applied: {relative}. Undo ID: {tx_id}\n{preview}"


def _run(workspace: Path, args: list[str], timeout: int = 120) -> str:
    command = list(args)
    sandbox = shutil.which("sandbox-exec")
    if sandbox:
        escaped = str(workspace).replace('"', '\\"')
        profile = (
            '(version 1)(deny default)(import "system.sb")'
            '(allow process*)(allow file-read*)'
            f'(allow file-write* (subpath "{escaped}"))'
            '(allow file-write* (subpath "/private/tmp"))(deny network*)'
        )
        command = [sandbox, "-p", profile, *command]
    else:
        return "Code execution blocked: an operating-system sandbox is unavailable."
    try:
        result = subprocess.run(
            command, cwd=workspace, capture_output=True, text=True,
            timeout=max(1, min(int(timeout), 300)), env={
                "PATH": os.environ.get("PATH", ""), "HOME": str(workspace),
                "TMPDIR": "/private/tmp", "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    except subprocess.TimeoutExpired:
        return "Developer command timed out."
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    output = output[:MAX_OUTPUT_CHARS] or "(no output)"
    status = "passed" if result.returncode == 0 else f"failed with exit code {result.returncode}"
    return f"Developer command {status}: {' '.join(args)}\n{output}"


def _package_scripts(workspace: Path) -> dict[str, str]:
    path = workspace / "package.json"
    if not path.is_file() or path.stat().st_size > MAX_CONTEXT_BYTES:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        return scripts if isinstance(scripts, dict) else {}
    except (OSError, ValueError):
        return {}


def run_quality(workspace: Path, action: str) -> str:
    scripts = _package_scripts(workspace)
    if action in scripts:
        return _run(workspace, ["npm", "run", action])
    if action == "test":
        if (workspace / "tests").is_dir():
            return _run(workspace, [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"])
    elif action == "lint" and shutil.which("ruff"):
        return _run(workspace, [shutil.which("ruff") or "ruff", "check", "."])
    elif action == "typecheck":
        checker = shutil.which("pyright") or shutil.which("mypy")
        if checker:
            return _run(workspace, [checker, "."])
    return f"No allowlisted {action} command was detected in the selected workspace."


def git_read(workspace: Path, action: str) -> str:
    args = {
        "git_status": ["git", "status", "--short", "--branch"],
        "git_diff": ["git", "diff", "--", "."],
        "git_log": ["git", "log", "-10", "--oneline", "--decorate"],
    }[action]
    try:
        result = subprocess.run(args, cwd=workspace, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "Git command timed out."
    output = (result.stdout or result.stderr).strip()[:MAX_OUTPUT_CHARS]
    return output or "Git command completed with no output."


def suggest_commit(workspace: Path) -> str:
    status = git_read(workspace, "git_status")
    names = []
    for line in status.splitlines():
        if len(line) > 3 and not line.startswith("##"):
            names.append(Path(line[3:].split(" -> ")[-1]).name)
    if not names:
        return "No changed files found for a commit suggestion."
    preview = ", ".join(names[:3])
    return f"Suggested commit message: update {preview}"[:500]


def git_push(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "push"], cwd=workspace, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return "Git push timed out; remote state must be checked before retrying."
    output = (result.stdout or result.stderr).strip()[:MAX_OUTPUT_CHARS]
    status = "completed" if result.returncode == 0 else f"failed ({result.returncode})"
    return f"Git push {status}: {output}"


def developer_tools(parameters: dict | None = None, **_: object) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).strip().casefold()
    try:
        if action == "select_workspace":
            return select_workspace(str(params.get("workspace", "")))
        workspace = selected_workspace(str(params.get("workspace", "")))
        if action == "search":
            return search_code(workspace, str(params.get("query", "")), int(params.get("limit", 50)))
        if action == "context":
            return read_context(workspace, str(params.get("file_path", "")))
        if action == "diff_preview":
            return diff_preview(workspace, str(params.get("file_path", "")), str(params.get("content", "")))
        if action == "edit":
            return edit_file(workspace, str(params.get("file_path", "")), str(params.get("content", "")))
        if action == "rollback":
            tx_id = str(params.get("transaction_id", ""))
            if not _TX_ID.fullmatch(tx_id):
                return "Invalid transaction ID."
            return rollback_text_edit(tx_id, allowed_roots=[workspace])
        if action in {"test", "lint", "typecheck"}:
            return run_quality(workspace, action)
        if action in {"git_status", "git_diff", "git_log"}:
            return git_read(workspace, action)
        if action == "commit_suggest":
            return suggest_commit(workspace)
        if action == "git_push":
            return git_push(workspace)
        return f"Unknown developer action: '{action}'"
    except (OSError, UnicodeError, ValueError) as exc:
        return f"Developer tool error: {exc}"
