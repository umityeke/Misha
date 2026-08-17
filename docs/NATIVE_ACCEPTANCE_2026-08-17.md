# Native macOS Acceptance — 2026-08-17

Environment: owner macOS session, native `dist/Misha.app`, bundle identifier
`com.umityeke.misha`.

## Observed acceptance

- Misha launched to its protected PIN dialog without crashing.
- The PIN dialog exposed a named secure text field, ten named digit buttons, Clear,
  Submit and explanatory text through the macOS accessibility tree.
- macOS System Settings → Privacy & Security → Microphone listed **Misha: on**.
- macOS System Settings → Privacy & Security → Accessibility listed **Misha: on**.

No permission was changed during this check. No PIN or other credential was entered,
read or recorded.

## Still separate

This observation confirms the permission grants and native PIN surface. It does not
claim Developer ID signing, notarization, Gatekeeper, clean-Mac installation, live
acoustic wake metrics or the owner-completed setup flow.
