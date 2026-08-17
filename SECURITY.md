# Misha Security Policy

## Supported code

Security fixes target the current `main` branch and the active development
branch. Historical prototypes are not supported and must not be used to store
credentials.

## Reporting a vulnerability

Do not open a public issue containing credentials, private logs, voice samples,
database URLs, or exploit details. Use a private GitHub security advisory:

<https://github.com/umityeke/Misha/security/advisories/new>

Include the affected component, reproduction steps, expected impact, and a
redacted log when available. Never include a live token or password.

## Security boundaries

- Active AI inference is local through Ollama on localhost.
- Risky tools must fail closed without explicit approval.
- Voice identity is a convenience gate, not a replacement for PIN or approval.
- Secrets must not be committed, logged, or stored as learned rules.
- Generated file operations must stay inside the selected workspace.
- A security control failing must not silently fall back to a less safe mode.

## Credential and memory storage

Misha uses the operating system's native owner-scoped secret store: macOS Keychain,
Windows Credential Manager, or Linux Secret Service through `secret-tool`. Linux
secret values are passed on stdin, never in process arguments. If the native store
or client is unavailable, credential operations fail closed; there is no plaintext
fallback.

- Desktop credentials use the macOS Keychain adapter. Secrets go directly to
  the Security framework and are never placed in shell arguments.
- Local configuration rejects credential-like keys and removes legacy secret
  rows from local SQLite and the optional remote configuration table.
- Memory values, keys, categories, and metadata use authenticated encryption.
  HMAC indexes permit exact lookup without storing the corresponding plaintext.
- Keychain or decryption failure has no plaintext fallback.
- JSON memory exports are plaintext owner-controlled backups with `0600` file
  permissions.

Run the local checks before proposing a security change:

```bash
venv/bin/python -m unittest discover -s tests -v
venv/bin/python scripts/scan_secrets.py
```
