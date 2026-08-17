# Misha Rollback Procedure

## Source rollback without destructive Git commands

1. Stop Misha before changing runtime files.
2. Preserve the current `git status -sb` and `git diff --binary HEAD` output.
3. Use the task backups:
   - `MISHA_LOCAL_FOUNDATION_TRACKED.patch`
   - `MISHA_LOCAL_FOUNDATION_NEW_FILES.tar.gz`
4. Restore into a new directory or branch first; do not run `git reset --hard`
   or overwrite the dirty working tree.
5. Re-run all tests and the secret scanner before activation.

## Desktop application rollback

Previous generated app bundles are stored outside the Desktop with the suffix
`.app.disabled`. To roll back, stop the current Misha process, preserve the
current `Desktop/Misha.app`, restore exactly one known-good backup as
`Desktop/Misha.app`, verify it with `codesign --verify --deep --strict`, and
launch it through Finder. Keeping multiple active `.app` bundles with the same
bundle identifier can confuse LaunchServices.

## Local data rollback

Application data lives under `~/.misha/` and is intentionally not included in
source patches. Back it up before a migration. Never replace `config.db`, voice
identity, or memory from an untrusted archive. File permissions for private
databases and `voice/owner.json` must remain `0600`.

## Acceptance checks

```bash
venv/bin/python -m unittest discover -s tests -v
venv/bin/python scripts/scan_secrets.py
codesign --verify --deep --strict "$HOME/Desktop/Misha.app"
```

A rollback is accepted only when tests pass, secrets are not exposed, the app
launches, and risky actions still require explicit approval.
