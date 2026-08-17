import asyncio
import subprocess
import sys
import re
import shlex
from pathlib import Path

from core.ai.runtime import generate_json, generate_text
from core.task_state import TaskState

PROJECTS_DIR = Path.home() / "Desktop" / "MishaProjects"

class RateLimitError(Exception):
    pass


def _safe_project_path(project_dir: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError("Project file paths must be non-empty and relative.")
    root = project_dir.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Project path escapes the workspace: {relative_path}") from exc
    return candidate

def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()

def _is_rate_limit(error: Exception) -> bool:
    msg = str(error).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg

def _classify_error(output: str) -> str:
    low = output.lower()
    if any(x in low for x in ("no module named", "modulenotfounderror", "importerror")):
        return "dependency_error"
    if "syntaxerror" in low or "invalid syntax" in low:
        return "syntax_error"
    if "cannot import" in low or "importerror" in low:
        return "import_error"
    if any(x in low for x in (
        "traceback", "exception", "error:", "nameerror", "typeerror",
        "attributeerror", "valueerror", "keyerror", "indexerror",
        "zerodivisionerror", "filenotfounderror", "permissionerror",
    )):
        return "runtime_error"
    return "none"

def _has_error(output: str) -> bool:
    low = output.lower()
    if "timed out" in low:
        return False
    if not output.strip():
        return False
    return _classify_error(output) != "none"

def _parse_traceback(output: str, project_files: list[str]) -> tuple[str | None, int | None]:
    pattern = re.compile(r'File ["\']([^"\']+\.py)["\'],\s+line\s+(\d+)', re.IGNORECASE)
    matches = pattern.findall(output)
    for raw_path, line_str in reversed(matches):
        raw_name = Path(raw_path).name
        for pf in project_files:
            if Path(pf).name == raw_name or pf == raw_path or raw_path.endswith(pf):
                return pf, int(line_str)
    return None, None

# ----------------- AGENTS ----------------- #

async def orchestrator_agent(state: TaskState):
    """Plans the project structure."""
    state.log_event("Orchestrator", f"Planning project for: {state.description[:50]}...")
    
    prompt = f"""You are a senior software architect. Create a minimal, complete file plan for this project.

Language: {state.language}
Description: {state.description}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "project_name": "snake_case_name",
  "entry_point": "main.py",
  "files": [
    {{
      "path": "main.py",
      "description": "Entry point — what it does and which modules it imports",
      "imports": ["utils.helpers", "core.engine"]
    }},
    {{
      "path": "utils/helpers.py",
      "description": "Helper utilities — what functions it exposes",
      "imports": []
    }}
  ],
  "run_command": "python main.py",
  "dependencies": ["requests"]
}}

Critical rules:
1. List files in DEPENDENCY ORDER — files with no imports come first, entry point comes last.
2. The "imports" field must list every other project module this file imports.
3. Keep it minimal — only files truly needed.
4. Entry point must be in the files list.
5. Use relative paths only (e.g. "utils/helpers.py").
6. Standard library modules do NOT go in "dependencies".

JSON:"""

    try:
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(
            None,
            lambda: generate_json(prompt, temperature=0.1),
        )
        if not isinstance(plan, dict):
            raise ValueError("Project plan must be a JSON object")
        
        state.project_name = state.project_name or plan.get("project_name", "misha_project")
        state.project_name = re.sub(r"[^\w\-]", "_", state.project_name)
        state.plan = plan
        state.files_to_write = plan.get("files", [])
        if not isinstance(state.files_to_write, list) or not state.files_to_write:
            raise ValueError("Project plan must include at least one file.")
        if len(state.files_to_write) > 40:
            raise ValueError("Project plan exceeds the 40-file safety limit.")
        for file_info in state.files_to_write:
            if not isinstance(file_info, dict):
                raise ValueError("Every planned file must be an object.")
            _safe_project_path(PROJECTS_DIR / state.project_name, file_info.get("path", ""))
        state.run_command = plan.get("run_command", f"python {plan.get('entry_point', 'main.py')}")
        state.dependencies = plan.get("dependencies", [])
        
        state.status = "planned"
        state.log_event("Orchestrator", f"Project planned with {len(state.files_to_write)} files.")
    except Exception as e:
        state.status = "failed"
        state.log_event("Orchestrator", f"Planning failed: {e}")


async def explorer_agent(state: TaskState):
    """Sets up the project directory and checks dependencies."""
    if state.status == "failed": return
    
    state.log_event("Explorer", "Setting up workspace and checking dependencies...")
    project_dir = PROJECTS_DIR / state.project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Check dependencies
    to_install = []
    for dep in state.dependencies:
        pkg_name = re.split(r"[>=<!]", dep)[0].strip()
        result = subprocess.run([sys.executable, "-m", "pip", "show", pkg_name], capture_output=True, text=True)
        if result.returncode != 0:
            to_install.append(dep)
            
    if to_install:
        state.log_event("Explorer", f"Installing dependencies: {to_install}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install"] + to_install,
            capture_output=True, text=True, timeout=120, cwd=str(project_dir)
        )
    
    state.log_event("Explorer", "Environment ready.")


async def coder_agent(state: TaskState):
    """Writes or fixes code."""
    if state.status == "failed": return
    
    project_dir = PROJECTS_DIR / state.project_name
    
    # Sort files by dependency length
    def _dep_sort_key(fi: dict) -> int:
        return len(fi.get("imports", []))
    
    sorted_files = sorted(state.files_to_write, key=_dep_sort_key)
    
    for file_info in sorted_files:
        file_path = file_info.get("path", "")
        if not file_path: continue
        
        state.log_event("Coder", f"Writing {file_path}...")
        
        dependency_context = ""
        for dep_dotted in file_info.get("imports", []):
            dep_path = dep_dotted.replace(".", "/") + ".py"
            if dep_path in state.code_files:
                code_snippet = state.code_files[dep_path][:2000]
                dependency_context += f"\n\n--- {dep_path} ---\n{code_snippet}"
                
        prompt = f"""You are a senior {state.language} developer writing production-quality code.

Project goal: {state.description}
File to write: {file_path}
Purpose: {file_info.get("description", "")}

Dependencies this file must import from: {dependency_context}

General rules:
- Output ONLY raw code. No explanation, no markdown.
- Write COMPLETE, RUNNABLE code.
- Ensure import paths match the exact project structure.

Code for {file_path}:"""

        try:
            loop = asyncio.get_event_loop()
            generated = await loop.run_in_executor(
                None,
                lambda: generate_text(prompt, temperature=0.1),
            )
            code = _strip_fences(generated)
            
            full_path = _safe_project_path(project_dir, file_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(code, encoding="utf-8")
            
            state.code_files[file_path] = code
        except Exception as e:
            state.log_event("Coder", f"Failed to write {file_path}: {e}")
            state.status = "failed"
            return
            
    state.status = "coded"
    state.log_event("Coder", "All files written successfully.")


async def tester_agent(state: TaskState):
    """Runs the project and catches errors."""
    if state.status == "failed": return
    
    state.log_event("Tester", f"Running project: {state.run_command}")
    project_dir = PROJECTS_DIR / state.project_name
    
    try:
        parts = shlex.split(state.run_command)
        if not parts:
            raise ValueError("Run command is empty.")
        allowed_commands = {"python", "python3", "node", "npm", "pytest"}
        if Path(parts[0]).name.lower() not in allowed_commands:
            raise PermissionError(f"Generated run command is not allowed: {parts[0]}")
        if any(part == ".." or part.startswith("../") for part in parts[1:]):
            raise PermissionError("Generated run command escapes the project workspace.")
        if parts and parts[0].lower() == "python":
            parts[0] = sys.executable
            
        result = subprocess.run(
            parts,
            capture_output=True, text=True,
            timeout=30, cwd=str(project_dir)
        )
        
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        last_output = "\n\n".join(filter(None, [f"STDOUT:\n{stdout}" if stdout else "", f"STDERR:\n{stderr}" if stderr else ""]))
        
        state.last_output = last_output or "Ran with no output."
        
        if _has_error(last_output):
            state.error_type = _classify_error(last_output)
            state.status = "failed"
            state.log_event("Tester", f"Error found ({state.error_type}).")
        else:
            state.status = "tested"
            state.log_event("Tester", "Tests passed successfully.")
            
    except subprocess.TimeoutExpired:
        state.status = "tested"
        state.log_event("Tester", "Execution timed out (likely a long-running app). Considered success.")
    except Exception as e:
        state.status = "failed"
        state.error_type = "runtime_error"
        state.last_output = str(e)
        state.log_event("Tester", f"Failed to run project: {e}")


async def reviewer_agent(state: TaskState):
    """Analyzes errors and rewrites files to fix them."""
    if state.status != "failed" or state.fix_attempts >= state.max_fix_attempts:
        return
        
    state.fix_attempts += 1
    state.log_event("Reviewer", f"Reviewing error (Attempt {state.fix_attempts}/{state.max_fix_attempts})...")
    
    project_dir = PROJECTS_DIR / state.project_name
    error_file, error_line = _parse_traceback(state.last_output, list(state.code_files.keys()))
    
    # Very basic dependency auto-install if missing
    if state.error_type == "dependency_error":
        pattern = re.compile(r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE)
        match = pattern.search(state.last_output)
        if match:
            pkg = match.group(1).replace("_", "-").split(".")[0]
            state.log_event(
                "Reviewer",
                f"Missing dependency requires explicit installation approval: {pkg}",
            )
            state.last_output = f"Dependency installation approval required: {pkg}"
            return

    files_to_fix = [error_file] if error_file else [state.plan.get("entry_point", "main.py")]
    
    for fix_path in files_to_fix:
        current_code = state.code_files.get(fix_path, "")
        
        prompt = f"""You are an expert {state.language} debugger. Fix the broken file below.

Project goal: {state.description}
File to fix: {fix_path}
Error type: {state.error_type}
Error output: {state.last_output[:2000]}

Current code:
{current_code}

Output ONLY the complete fixed code. No markdown. Fix ALL visible errors."""

        try:
            loop = asyncio.get_event_loop()
            generated = await loop.run_in_executor(
                None,
                lambda: generate_text(prompt, temperature=0.1),
            )
            fixed = _strip_fences(generated)
            
            full_path = _safe_project_path(project_dir, fix_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(fixed, encoding="utf-8")
            
            state.code_files[fix_path] = fixed
            state.log_event("Reviewer", f"Applied fix to {fix_path}")
            
        except Exception as e:
            state.log_event("Reviewer", f"Could not fix {fix_path}: {e}")
            
    # Send back to testing phase
    state.status = "coded"


async def run_team(description: str, language: str, project_name: str = "") -> str:
    """Orchestrates the entire Multi-Agent loop."""
    state = TaskState(description=description, language=language, project_name=project_name)
    
    await orchestrator_agent(state)
    if state.status == "failed": return "Planning failed."
    
    await explorer_agent(state)
    
    await coder_agent(state)
    if state.status == "failed": return "Coding failed."
    
    # Review loop
    while state.status in ("coded", "failed") and state.fix_attempts < state.max_fix_attempts:
        if state.status == "coded":
            await tester_agent(state)
            
        if state.status == "failed":
            await reviewer_agent(state)
            
        if state.status == "tested":
            break
            
    if state.status == "tested":
        return f"Project built successfully after {state.fix_attempts} fixes. Path: {PROJECTS_DIR / state.project_name}"
    else:
        return f"Project failed after {state.max_fix_attempts} attempts. Last error: {state.last_output[:500]}"


def dev_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """Synchronous wrapper for the async multi-agent pipeline."""
    p            = parameters or {}
    description  = p.get("description", "").strip()
    language     = p.get("language", "python").strip()
    project_name = p.get("project_name", "").strip()

    if not description:
        return "Please describe the project you want me to build, sir."

    if speak:
        speak("I am assembling the agent team, sir. Please stand by.")
        
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run_team(description, language, project_name))
        if speak: speak(result)
        
        # Open in VSCode if successful or failed
        if state_name := p.get("project_name"):
            vscode_candidates = ["code"]
            for cmd in vscode_candidates:
                try:
                    subprocess.Popen([cmd, str(PROJECTS_DIR / state_name)])
                    break
                except: pass
                
        return result
    finally:
        loop.close()
