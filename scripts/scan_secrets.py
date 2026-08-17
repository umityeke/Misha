from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    rule: str


RULES = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "github_token": re.compile(r"gh[pousr]_[0-9A-Za-z_]{20,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential_url": re.compile(
        r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s:/]+:[^\s/@]+@",
        re.IGNORECASE,
    ),
}

SKIPPED_SUFFIXES = {
    ".aiff", ".bin", ".bmp", ".gif", ".icns", ".ico", ".jpeg", ".jpg",
    ".mp3", ".mp4", ".pdf", ".png", ".pyc", ".sqlite", ".wav", ".zip",
}
SENSITIVE_HISTORY_NAMES = {
    ".env.tokens", "gh_code.txt", "gh_tokens.png", "railway_tab.png",
}


def scan_text(path: str, text: str) -> list[SecretFinding]:
    findings = []
    allow_next_line = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "pragma: allowlist secret" in line:
            allow_next_line = True
            continue
        if allow_next_line and not line.strip():
            continue
        if allow_next_line:
            allow_next_line = False
            continue
        for rule_name, pattern in RULES.items():
            if pattern.search(line):
                findings.append(SecretFinding(path, line_number, rule_name))
    return findings


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def scan_repository(root: Path) -> list[SecretFinding]:
    findings = []
    for path in tracked_files(root):
        if not path.is_file() or path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text(str(path.relative_to(root)), text))
    return findings


def scan_history(root: Path) -> list[SecretFinding]:
    commits = subprocess.run(
        ["git", "rev-list", "--all"], cwd=root, capture_output=True,
        text=True, check=True, timeout=30,
    ).stdout.splitlines()
    findings: list[SecretFinding] = []
    seen: set[tuple[str, int, str]] = set()
    for commit in commits:
        names = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit], cwd=root,
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.splitlines()
        for name in names:
            if Path(name).name in SENSITIVE_HISTORY_NAMES:
                key = (name, 0, "sensitive_artifact")
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        SecretFinding(f"history:{commit[:12]}:{name}", 0, "sensitive_artifact")
                    )
            if Path(name).suffix.casefold() in SKIPPED_SUFFIXES:
                continue
            result = subprocess.run(
                ["git", "show", f"{commit}:{name}"], cwd=root,
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or b"\0" in result.stdout[:8_192]:
                continue
            try:
                text = result.stdout.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for finding in scan_text(f"history:{commit[:12]}:{name}", text):
                key = (name, finding.line, finding.rule)
                if key not in seen:
                    seen.add(key)
                    findings.append(finding)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan current or historical Git text safely.")
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    findings = scan_history(root) if args.history else scan_repository(root)
    if not findings:
        scope = "Git history" if args.history else "tracked text files"
        print(f"Secret scan passed: no high-confidence findings in {scope}.")
        return 0
    scope = "history" if args.history else "current tree"
    print(f"Secret scan found {len(findings)} remediation item(s) in {scope}.")
    for finding in findings:
        print(f"{finding.path}:{finding.line} [{finding.rule}] value redacted")
    return 3 if args.history else 1


if __name__ == "__main__":
    sys.exit(main())
