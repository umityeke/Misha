# macOS Entitlement and Hardened Runtime Decision

Misha is distributed as a direct-download, non-sandboxed macOS application.
The application needs microphone access, Accessibility only after an explicit
user grant, and outbound client connections to local Ollama plus user-requested
public web services.

## Decision

- App Sandbox is not enabled. Enabling it would require a separate architecture
  for broad user-selected file access and Accessibility automation.
- A non-sandboxed direct-download app does not need the App Sandbox
  `com.apple.security.network.client` entitlement for outbound client traffic.
- No broad file, camera, microphone, JIT, unsigned-executable-memory, or disabled
  library-validation entitlement is declared.
- `packaging/macos/entitlements.plist` is intentionally an empty allowlist.
- Release signing uses `scripts/sign_macos_bundle.sh` to sign every embedded
  Mach-O from the inside out with one identity and `--options runtime`, then
  signs the outer bundle. This prevents mixed-Team-ID library validation errors.

Ad-hoc signatures do not carry a Team ID, so hardened-runtime CI smoke builds
cannot satisfy same-team library validation for embedded CPython. Only those
non-distributable ad-hoc builds use
`packaging/macos/entitlements-development.plist`, which disables library
validation. A Developer ID release must use the empty production entitlement
file; the signing script never chooses the development file implicitly.

The CI and local release checks inspect the bundle plist, verify the deep
signature, and check for the runtime flag. Developer ID signing and Apple
notarization remain external release credentials and are never simulated.
