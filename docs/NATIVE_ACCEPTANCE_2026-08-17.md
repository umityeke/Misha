# Native macOS Acceptance — 2026-08-17

Environment: owner macOS session, native `dist/Misha.app`, bundle identifier
`com.umityeke.misha`.

## Observed acceptance

- Misha launched to its protected PIN dialog without crashing.
- The PIN dialog exposed a named secure text field, ten named digit buttons, Clear,
  Submit and explanatory text through the macOS accessibility tree.
- macOS System Settings → Privacy & Security → Microphone listed **Misha: on**.
- macOS System Settings → Privacy & Security → Accessibility listed **Misha: on**.
- The current 263 MB arm64 bundle was rebuilt after the voice stability and Whisper
  fallback changes, ad-hoc hardened-runtime signed, deep-verified and launched through
  an isolated writable data directory to its PIN surface.
- The locked PIN surface exposes **Quit Misha without unlocking**; its accessibility
  contract and reject action are covered by the local UI gate.
- Finder created a 1 KB `Misha` alias on the Desktop. **Show Original** resolved it to
  the current project `dist/Misha.app`, so replacing the bundle does not leave a second
  275 MB Desktop copy.

No permission was changed during this check. No PIN or other credential was entered,
read or recorded.

## Still separate

This observation confirms the permission grants and native PIN surface. It does not
claim Developer ID signing, notarization, Gatekeeper, clean-Mac installation, live
acoustic wake metrics or the owner-completed setup flow.
