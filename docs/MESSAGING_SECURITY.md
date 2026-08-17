# Messaging security contract

Desktop messaging is allowlisted to WhatsApp, Telegram, Signal, and Discord. Exact
platform aliases are accepted; arbitrary application names and browser messaging
flows are disabled. Recipient names are bounded and reject control characters;
message content is bounded to 4,000 characters.

`preview` is read-only and shows platform, exact recipient, and a bounded content
preview. `send` always requires the runtime's explicit external-action approval,
whose prompt includes the target and message. On macOS, Misha opens the allowlisted
application, performs its known search shortcut, then reads local Accessibility
state. The active application and an exact AX title equal to the requested recipient
must match before content is typed and must still match immediately before Enter.
Any missing permission, ambiguous result, wrong window, or changed recipient blocks
submission.

A private local database keeps only a SHA-256 fingerprint and status, never message
or recipient plaintext. It blocks the same platform/recipient/content combination
for five minutes unless the user explicitly approves a duplicate. Automatic retries
remain disabled.

The tool can verify the local recipient-selection boundary, but desktop UI automation
cannot independently prove server receipt or end-device delivery. A successful local
submission is therefore reported as `sent_unverified`, not as delivered. Provider
API/read-receipt connectors would be required to close that final acceptance item.
