# Misha 0.1.0 (Build 1) — Foundation Beta

Release channel: `stable` metadata, local beta distribution.

## Included

- Hands-free local wake, owner-voice convenience gate, VAD, barge-in and local TTS.
- Local Ollama planning with typed tool schemas, approvals, verification and recovery.
- Encrypted memory, reminders, task journal and transactional file/code rollback.
- Hardened file, developer, isolated-browser, system and messaging tool boundaries.
- Native macOS tray lifecycle, privacy/setup diagnostics and accessible keyboard controls.
- 50-task deterministic contract eval set and 390+ automated regression tests.

## Security and packaging

- Bundle identifier `com.umityeke.misha`, semantic version `0.1.0`, build `1`.
- Hardened-runtime ad-hoc development build with separate production entitlements.
- Native bundle reduced from 375 MB to 263 MB by excluding unused runtime modules.
- Developer ID signing, notarization, Gatekeeper and clean-Mac acceptance are not complete.

The precise implemented/partial/not-available boundary is published in
[`FEATURE_STATUS.md`](FEATURE_STATUS.md); automated tests do not imply completion of
the hardware, account or clean-machine acceptance gates listed there.

## Upgrade and rollback

This beta has no unattended updater. Signed Ed25519 manifest and SHA-256 package
verification primitives are present, but activation remains disabled until a production
release public key and hosting channel are configured. Follow `docs/ROLLBACK.md` to
restore a known-good bundle without destructive Git commands.
