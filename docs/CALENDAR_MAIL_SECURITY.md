# Calendar and mail integration contract

The default Calendar and Mail path controls the accounts already configured in the
native macOS applications. User values are supplied as `osascript` arguments and are
never interpolated into script source or passed through a shell. Reads are bounded;
mutations require the central exact action approval. No account password, API key,
OAuth client, or paid provider is required.

Provider-neutral services and the OAuth layer remain isolated for a future explicit
opt-in. If enabled later, tokens must use the OS credential store; no provider adapter
may persist them in config, logs, or a repository.

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
Sensitive-content matches require an additional approval. A provider response is not
called sent/verified unless it contains a non-empty receipt ID. The local Mail adapter
reports acceptance by Mail with its local identifier and always describes remote
delivery as unverified.
