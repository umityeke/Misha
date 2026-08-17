# Voice stability acceptance — 2026-08-17

The actual-duration local stability harness completed successfully on macOS arm64.

- Duration: 1800.002 seconds
- Completed cycles and interruptions: 144,975
- Errors: 0
- Threads: 1 before, 1 after
- RSS: 34.8 MiB before, 48.8 MiB after, 48.8 MiB peak
- RSS growth: 14.0 MiB against a 96.0 MiB maximum
- State history: bounded at 2,048 entries
- Input/output queues: bounded at four entries with expected oldest-item drops

The machine-readable report is stored outside the source repository at
`outputs/MISHA_VOICE_STABILITY_30M_2026-08-17.json`. It reports
`acoustic_hardware_measured: false`: this acceptance exercises the local voice state
machine, synthetic VAD, bounded realtime queues and interruption coordinator. It does
not close the separate 30-minute acoustic conversation or four-to-eight-hour soak
acceptance gates.
