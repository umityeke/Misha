# Misha User Guide

After setup, Misha listens locally for “Misha” or “Mişa”; no talk button is required.
Say the wake name followed by a request, or type into **Ask Misha**. F4 toggles the
microphone and F11 toggles fullscreen. The menu-bar icon controls visibility, mute,
hands-free wake, always-on-top, start-at-login and explicit quit.

Risky actions show the exact target and default to **No**. Read the target before
approving. Voice identity does not replace the PIN or action approval. Message sends,
file mutations, code edits, browser/system effects and reminder changes use this gate.

Drop one local file into **Context file** only when you want it considered for the
current task. File tools remain inside the approved user folders; deletion goes to Trash.
Developer edits show a diff and create a single-use encrypted rollback transaction.

Privacy & Observation is off by default. When enabled, it remains locally processed,
shows a visible indicator and excludes protected/credential windows. Use the same panel
to inspect permissions, redacted audit events, memory and interrupted task checkpoints.

If voice is unavailable, open setup checks and test the selected microphone, speaker,
owner profile, Whisper model and wake pipeline. Misha fails closed instead of switching
to a paid cloud model.

The current beta does not provide live Google/Microsoft mail or calendar access,
production-signed/notarized distribution, or unattended updates. See
[`FEATURE_STATUS.md`](FEATURE_STATUS.md) before relying on a capability.
