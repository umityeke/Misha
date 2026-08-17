# Git history remediation plan

The current tree passes the high-confidence secret scan. Historical scanning is
separate and intentionally returns a non-zero remediation status without printing
secret values. It identifies removed sensitive artifact names and credential
patterns by commit/path/rule only.

The 2026-08-17 scan found three removed sensitive artifact names (`gh_code.txt`,
`gh_tokens.png`, and `railway_tab.png`) plus one PostgreSQL URL-shaped documentation
example in the old DB dialog. The scanner redacted all values. Artifact contents
must still be treated as exposed until the relevant credentials are rotated.

History rewriting is destructive and must not start until all of these are true:

1. Rotate/revoke every GitHub, Railway, database, and provider credential that may
   have appeared in any old artifact. Rotation comes first because rewriting does
   not invalidate a copied secret.
2. Confirm the canonical repository and every active clone/fork with the owner.
3. Create an offline mirror backup and record its SHA-256.
4. Use `git filter-repo` with an exact reviewed path/value replacement manifest;
   never a broad wildcard. Remove the known credential screenshots/code files and
   replace any confirmed text secret with a redaction marker.
5. Run current-tree and `--history` scans on the rewritten mirror, build/test it,
   and compare expected tags/branches before any remote change.
6. With explicit owner approval, coordinate the protected-branch force push,
   invalidate cached release/source archives, and require collaborators to fresh
   clone rather than merge old history back.

No rewrite or force push is authorized merely by this plan. The current GitHub CLI
tokens are invalid and the canonical account must be reauthenticated first.
