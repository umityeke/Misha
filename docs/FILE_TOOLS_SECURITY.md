# File tools security contract

Misha's file tools are restricted to the current user's Desktop, Documents,
Downloads, Pictures, Music, and Videos directories. A path outside these roots,
including a path reached through a symlink, is rejected before an operation.

## Mutation rules

- File creation, copying, moving, and renaming never overwrite an existing target.
- Delete sends an item to the operating system Trash. Permanent deletion is not a
  fallback when Trash support is unavailable.
- Text writes are UTF-8, bounded to 2 MiB, and committed using a same-directory
  temporary file, `fsync`, and atomic replacement.
- Reads are bounded to 2 MiB. Copies are bounded to 100 MiB and 10,000 files.
- Direct and intermediate symlinks, including broken symlinks, are fail-closed.

## Encrypted undo

Each successful text create/write, copy, move, rename, or folder creation returns
a single-use `tx_…` undo identifier. Paths and prior text contents are encrypted
with an independent key stored by the operating-system credential store. The local
SQLite transaction database and its parent directory use private permissions.

Undo checks the allowed root again and requires the current file hash to equal the
hash written by that transaction. If the user or another process changed the file,
undo refuses to overwrite it. A newly created file is removed by undo; a replaced
text file is atomically restored. Path mutation rollback also verifies a
deterministic post-operation tree hash: unchanged copies/folders are removed and
unchanged moves/renames return to their original path. Trash remains recoverable
through the operating system rather than a transaction ID.

## Verification and approval

All file mutations, including undo, require the normal action approval policy.
The runtime verifier checks filesystem state after mutations and checks the
encrypted transaction status after undo. Failure-like tool output is fail-closed.

Automated coverage lives in `tests/test_file_tools.py` and
`tests/test_file_transactions.py`, including traversal, symlink, size, overwrite,
encryption-at-rest, wrong-key, stale-file, single-use, and failed-write cases.
