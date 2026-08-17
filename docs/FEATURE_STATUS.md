# Feature Status — 0.1.0 Build 1

This table is the product-claim boundary for the current source tree. “Implemented”
means the behavior has automated coverage; it does not replace the external acceptance
listed in the final column.

| Capability | Status | Current boundary / remaining acceptance |
|---|---|---|
| Typed and local command execution | Implemented | Only registered tools run; mutation and external-impact policy is fail-closed. |
| Local Ollama planning | Implemented | Requires a running local Ollama service and an installed compatible model. No paid cloud fallback. |
| Local Whisper transcription | Implemented | CPU smoke passed with the installed model; real microphone and acoustic acceptance remain separate. |
| Hands-free wake and owner voice gate | Partial | Pipeline, UI test flow, VAD and fail-closed checks exist; target wake/false-trigger metrics need a labelled real-audio set. |
| Barge-in | Partial | State transition and interruption logic are covered; the <=300 ms acoustic target and echo cancellation need hardware measurement. |
| File and code changes | Implemented | Approved roots, diff/approval, encrypted transaction journal and rollback are covered; OS sandbox acceptance remains environment-dependent. |
| Isolated browser actions | Implemented | URL/DOM postconditions and security boundaries are covered; it intentionally does not reuse personal browser sessions. |
| Reminders and OS notifications | Implemented | Local scheduling and notification dispatch are covered; platform permission/display acceptance is still a native-session check. |
| Calendar and mail | Partial | Provider-neutral safety services and OAuth PKCE/token storage exist; live Google/Microsoft adapters and owner OAuth applications are not configured. |
| Screen observation | Implemented, opt-in | Local, visible and off by default; protected/credential windows are excluded. macOS permission acceptance is still required. |
| Encrypted memory | Implemented | Authenticated local storage and migration are covered; packaged-app Keychain acceptance remains open. |
| Automatic updates | Not enabled | Signed manifest/package verification primitives exist, but no production key or hosting channel is configured. |
| Native macOS distribution | Development build | Hardened-runtime ad-hoc bundle exists; Developer ID signing, notarization, stapling, Gatekeeper and clean-Mac acceptance are open. |
| Live Google/Microsoft integrations | Not available | Requires owner-created OAuth applications, approved scopes and provider adapters. |

Known external and hardware gaps are tracked in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).
The master development checklist remains the acceptance source of truth.
