import os
import json
import hashlib
import shutil
import difflib
import subprocess
import uuid
import re
from datetime import datetime

TRANSACTIONS_DIR = os.path.join(os.path.expanduser("~"), ".misha", "transactions")

def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def _git_head(workspace: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None

class PatchTransaction:
    def __init__(self, workspace: str):
        self.workspace = os.path.realpath(os.path.expanduser(workspace))
        if not os.path.isdir(self.workspace):
            raise ValueError(f"Workspace does not exist: {workspace}")
        self.tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        self.tx_dir = os.path.join(TRANSACTIONS_DIR, self.tx_id)
        self.originals_dir = os.path.join(self.tx_dir, "originals")
        os.makedirs(self.originals_dir, exist_ok=True)
        self.files = []
        self.diffs = []

    def _resolve_path(self, rel_path: str) -> tuple[str, str]:
        if not isinstance(rel_path, str) or not rel_path.strip():
            raise ValueError("Edit path must be a non-empty relative path.")
        if os.path.isabs(rel_path):
            raise ValueError("Absolute edit paths are not allowed.")
        normalized = os.path.normpath(rel_path)
        if normalized in (".", "..") or normalized.startswith(".." + os.sep):
            raise ValueError("Edit path must stay inside the workspace.")
        abs_path = os.path.realpath(os.path.join(self.workspace, normalized))
        if os.path.commonpath([self.workspace, abs_path]) != self.workspace:
            raise ValueError("Edit path must stay inside the workspace.")
        return abs_path, normalized

    def stage_edit(self, rel_path: str, new_content: str):
        """Stage a file edit. Saves original, computes diff."""
        abs_path, rel_path = self._resolve_path(rel_path)
        existed = os.path.exists(abs_path)
        old_content = ""
        before_hash = ""

        if existed:
            with open(abs_path, 'r', encoding='utf-8') as f:
                old_content = f.read()
            before_hash = _sha256(abs_path)
            # Save original
            orig_dest = os.path.join(self.originals_dir, rel_path)
            os.makedirs(os.path.dirname(orig_dest), exist_ok=True)
            shutil.copy2(abs_path, orig_dest)

        # Generate unified diff
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}"
        ))

        self.files.append({
            "path": rel_path,
            "before_sha256": before_hash,
            "existed_before": existed,
            "new_content": new_content,
        })
        self.diffs.append("".join(diff))

        return "".join(diff)

    def get_full_diff(self) -> str:
        """Returns the combined diff of all staged edits."""
        return "\n".join(self.diffs)

    def dry_run(self) -> tuple[bool, str]:
        """Write the patch to a temp file and run git apply --check."""
        full_diff = self.get_full_diff()
        if not full_diff.strip():
            return False, "No changes to apply."

        patch_path = os.path.join(self.tx_dir, "forward.patch")
        with open(patch_path, 'w', encoding='utf-8') as f:
            f.write(full_diff)

        try:
            result = subprocess.run(
                ["git", "apply", "--check", patch_path],
                cwd=self.workspace, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, "Patch is valid and can be applied."
            else:
                return False, f"Patch check failed: {result.stderr}"
        except FileNotFoundError:
            return True, "git not found, skipping --check. Patch will be applied directly."
        except Exception as e:
            return False, f"Dry run error: {e}"

    def apply(self) -> str:
        """Apply all staged edits and save manifest."""
        results = []
        for file_info in self.files:
            abs_path, _ = self._resolve_path(file_info["path"])
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(file_info["new_content"])
            file_info["after_sha256"] = _sha256(abs_path)
            results.append(f"✅ {file_info['path']}")

        # Save forward patch
        patch_path = os.path.join(self.tx_dir, "forward.patch")
        with open(patch_path, 'w', encoding='utf-8') as f:
            f.write(self.get_full_diff())

        # Generate and save reverse patch
        reverse_diffs = []
        for file_info in self.files:
            abs_path, _ = self._resolve_path(file_info["path"])
            with open(abs_path, 'r', encoding='utf-8') as f:
                new_content = f.read()
            
            if file_info["existed_before"]:
                orig_path = os.path.join(self.originals_dir, file_info["path"])
                with open(orig_path, 'r', encoding='utf-8') as f:
                    old_content = f.read()
            else:
                old_content = ""

            rdiff = list(difflib.unified_diff(
                new_content.splitlines(keepends=True),
                old_content.splitlines(keepends=True),
                fromfile=f"a/{file_info['path']}",
                tofile=f"b/{file_info['path']}"
            ))
            reverse_diffs.append("".join(rdiff))

        rev_path = os.path.join(self.tx_dir, "reverse.patch")
        with open(rev_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(reverse_diffs))

        # Save manifest
        manifest = {
            "transaction_id": self.tx_id,
            "workspace": self.workspace,
            "created_at": datetime.now().isoformat(),
            "git_head_before": _git_head(self.workspace),
            "files": [{
                "path": fi["path"],
                "before_sha256": fi["before_sha256"],
                "after_sha256": fi.get("after_sha256", ""),
                "existed_before": fi["existed_before"]
            } for fi in self.files],
            "status": "applied"
        }
        with open(os.path.join(self.tx_dir, "manifest.json"), 'w') as f:
            json.dump(manifest, f, indent=2)

        return f"Transaction {self.tx_id} applied.\n" + "\n".join(results)

    def rollback(self) -> str:
        """Rollback this transaction by restoring originals."""
        manifest_path = os.path.join(self.tx_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return f"Transaction {self.tx_id} not found."

        with open(manifest_path) as f:
            manifest = json.load(f)

        results = []
        for fi in manifest["files"]:
            abs_path, _ = self._resolve_path(fi["path"])
            
            if not os.path.exists(abs_path):
                results.append(f"⚠️ {fi['path']} — file missing, skipped")
                continue

            current_hash = _sha256(abs_path)
            if current_hash != fi["after_sha256"]:
                results.append(f"⚠️ {fi['path']} — modified after patch, manual review needed")
                continue

            if fi["existed_before"]:
                orig = os.path.join(self.originals_dir, fi["path"])
                if os.path.exists(orig):
                    shutil.copy2(orig, abs_path)
                    results.append(f"↩️ {fi['path']} — restored")
                else:
                    results.append(f"⚠️ {fi['path']} — original not found")
            else:
                os.remove(abs_path)
                results.append(f"🗑️ {fi['path']} — removed (was new file)")

        manifest["status"] = "rolled_back"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)

        return f"Transaction {self.tx_id} rolled back.\n" + "\n".join(results)


def list_transactions(workspace: str = None) -> list[dict]:
    """List all transactions, optionally filtered by workspace."""
    if not os.path.exists(TRANSACTIONS_DIR):
        return []
    txns = []
    for d in sorted(os.listdir(TRANSACTIONS_DIR), reverse=True):
        manifest_path = os.path.join(TRANSACTIONS_DIR, d, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                m = json.load(f)
            if workspace and m.get("workspace") != workspace:
                continue
            txns.append(m)
    return txns[:20]


def rollback_transaction(tx_id: str) -> str:
    """Rollback a specific transaction by ID."""
    if not re.fullmatch(r"tx_[0-9a-f]{12}", tx_id or ""):
        return "Invalid transaction ID."
    tx_dir = os.path.join(TRANSACTIONS_DIR, tx_id)
    if not os.path.exists(tx_dir):
        return f"Transaction {tx_id} not found."
    
    with open(os.path.join(tx_dir, "manifest.json")) as f:
        manifest = json.load(f)

    tx = PatchTransaction(manifest["workspace"])
    tx.tx_id = tx_id
    tx.tx_dir = tx_dir
    tx.originals_dir = os.path.join(tx_dir, "originals")
    return tx.rollback()
