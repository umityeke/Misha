# Local database tool security

The database tool is limited to a selected developer workspace and regular
`.db`, `.sqlite`, or `.sqlite3` files. Paths cannot be absolute, escape the
workspace, or cross a symlink.

Read operations use SQLite `mode=ro`, `query_only=ON`, one statement, a 32,000
character input limit, a three-second lock timeout, and a 100-row result limit.
Mutations require explicit owner approval plus a read-only verification query and
an exact expected JSON row set. The write runs under `BEGIN IMMEDIATE`; a mismatch
rolls the transaction back. The agent verifier then opens the database separately
and repeats the read-back before it may report success.
