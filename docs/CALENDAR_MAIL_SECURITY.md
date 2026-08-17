# Calendar and mail integration contract

Calendar and mail are provider-neutral services. OAuth tokens must use the OS
credential store; no provider adapter may persist them in config, logs, or a repo.
Google/Microsoft live adapters remain disabled until an owner-created OAuth app,
minimal scopes, and real-account acceptance are available.

The shared OAuth layer uses Authorization Code + S256 PKCE, a one-shot 10-minute
state, exact provider endpoint allowlists, and a fixed loopback callback. Token
responses cannot escalate beyond requested scopes. Access/refresh tokens are
stored only in the OS credential store; refresh preserves the old refresh token
when a provider rotates only the access token.

Calendar datetimes are timezone-aware and DST gaps/ambiguities fail closed.
Create/update/delete require mutation approval, new attendee invitations require a
separate approval, and overlaps are blocked unless the owner explicitly accepts the
conflict.

Mail validates recipients, size, attachment roots, symlinks and executable/script
extensions. The final recipients/subject/body are SHA-256 bound to approval.
Sensitive-content matches require an additional approval. A provider response is
not called sent/verified unless it contains a non-empty receipt ID.
