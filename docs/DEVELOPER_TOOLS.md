# Developer tools security contract

The `developer_tools` runtime tool replaces the legacy autonomous project builder.
The legacy tool is not present in the authoritative tool registry, so model output
cannot invoke its automatic dependency installation or direct code-writing loop.

## Workspace and context

- A workspace must be an existing absolute directory inside Desktop, Documents,
  or Downloads. The selected path is stored locally.
- Workspace-relative file paths are required. Parent traversal and every symlink
  component are rejected.
- Code search visits at most 10,000 files, returns at most 100 matches, ignores
  dependency/build/VCS directories, and skips binary or files above 256 KiB.
- File context and diff preview are UTF-8 only and bounded to 256 KiB/32,000 output
  characters.

## Transactional edits

`diff_preview` does not write. `edit` requires runtime approval, calculates the
same preview, and writes atomically through the encrypted file transaction store.
It returns a single-use undo ID. `rollback` requires separate approval, rechecks
the workspace and target symlinks, and refuses to overwrite any later user edit.

## Quality and Git commands

Test, lint, and type-check actions only select known argv arrays; no model-provided
shell command is accepted. They require explicit approval and an operating-system
sandbox with network denied. If the sandbox cannot be applied, execution fails
closed; there is no unsandboxed fallback. The current managed macOS validation
returned `sandbox_apply: Operation not permitted`, so these acceptance items remain
partial until tested in the packaged GUI session or replaced by a verified sandbox.

Git status, diff, and log use fixed read-only argv. Commit messages are suggestions
only. `git_push` uses fixed `git push`, requires explicit approval, is never retried
as a confirmed success without independent remote evidence, and accepts no arbitrary
ref or shell fragment.
