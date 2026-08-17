# Runtime resilience

Every registered tool declares whether it can require approval, whether an
identical call is idempotent, its maximum attempt count, verifier, deadline and
rollback capability. The planner receives the same metadata used by the
executor.

Automatic retry is intentionally narrow:

- the failure must be deterministically classified as transient;
- the tool must explicitly declare itself idempotent;
- the tool must have no external impact;
- the retry budget is at most three attempts;
- delays use bounded exponential backoff;
- cancellation interrupts the wait.

Permission, validation, unknown and unverified-effect failures fail closed.
Model-based error analysis cannot override the deterministic retry boundary.
If a verified step completed before a later terminal failure, the execution
returns `partial` instead of claiming complete success or hiding prior effects.

Runtime state changes are surfaced to the desktop UI, including planning,
approval, execution, verification, recovery and response preparation.
