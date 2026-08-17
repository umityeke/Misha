# Task recovery

Misha writes a local encrypted checkpoint when an executor request begins. The
journal records the current phase, verified-step count, total planned steps and
whether an effectful step was attempted. Task text is authenticated and
encrypted with a separate key held by macOS Keychain.

If the app or computer stops before a terminal result, the next launch changes
the orphaned phase to `interrupted` and presents a protected review dialog.
Partial results are presented through the same review path.

Recovery is deliberately review-only:

- no interrupted task is automatically resumed;
- no tool is automatically dispatched from the recovery dialog;
- an attempted write or external effect is clearly identified;
- the user may dismiss a checkpoint or issue a fresh command;
- terminal records are retained for a bounded period and then purged;
- corrupt, plaintext or wrongly keyed task content fails closed.

The recovery dialog is excluded from proactive screen observation before its
contents can be collected.
