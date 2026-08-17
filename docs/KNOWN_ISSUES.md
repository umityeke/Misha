# Known Issues — 0.1.0

- Developer ID signing, notarization, stapling and clean-Mac Gatekeeper acceptance remain pending.
- Live acoustic wake accuracy, false-trigger rate, AEC and 30-minute/4–8-hour voice soak tests require real hardware sessions.
- Browser profiles are intentionally isolated and do not reuse personal logged-in sessions.
- Remote message delivery cannot be independently confirmed without provider receipts.
- Calendar/mail safety services and OAuth PKCE core are implemented; live Google and
  Microsoft adapters still require owner-created OAuth applications and consent.
- Formatter, dependency-audit and license reports require the first authenticated GitHub Actions run.
- The native bundle is 263 MB because it includes PyQt, Playwright and local media dependencies.
- Signed update verification exists, but automatic update activation is disabled until a production key/channel is configured.
