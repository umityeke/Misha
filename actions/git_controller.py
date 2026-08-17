import subprocess
import os

def git_controller(parameters: dict, player=None):
    """
    Manages Git operations in a specified repository.
    """
    action = parameters.get("action", "status")
    cwd = parameters.get("cwd", os.path.expanduser("~"))
    message = parameters.get("message", "Auto-commit by MISHA")
    branch = parameters.get("branch", "main")
    remote = parameters.get("remote", "origin")

    if player:
        player.write_log(f"SYS: Git Action: {action}")

    try:
        def run_git(args):
            res = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
            if res.returncode == 0:
                out = res.stdout.strip()
                return out if out else "Success (no output)."
            return f"Error: {res.stderr.strip()}"

        if action == "status":
            return run_git(["status"])
        elif action == "diff":
            return run_git(["diff"])
        elif action == "commit":
            run_git(["add", "."])
            return run_git(["commit", "-m", message])
        elif action == "push":
            return run_git(["push", remote, branch])
        elif action == "pull":
            return run_git(["pull", remote, branch])
        elif action == "branch":
            return run_git(["checkout", "-b", branch])
        elif action == "log":
            return run_git(["log", "-n", "5", "--oneline"])
        else:
            return f"Unknown Git action: {action}"

    except Exception as e:
        return f"Exception in git operations: {str(e)}"
