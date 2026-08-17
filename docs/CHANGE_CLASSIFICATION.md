# Working Tree Change Classification

This document prevents unrelated or user-owned work from being overwritten
while Misha is developed on the dirty working tree.

## User/project work preserved

- Existing `actions/`, `agent/`, `core/`, UI, memory, IDE-extension, and helper
  implementations predating the local foundation work.
- Existing tracked edits whose authorship cannot be proven from the current
  working tree.
- Legacy integrations and prototypes are preserved unless the owner explicitly
  authorizes their removal. The paid Gemini runtime was explicitly retired in
  favor of Misha's local-only architecture.

These files must not be reset, reformatted in bulk, or deleted merely to obtain
a clean diff.

## Local Misha foundation work

- `core/ai/`: Ollama-only provider runtime.
- `core/voice/`: device selection, recording, VAD, owner verification, local
  Whisper, TTS, and hands-free wake flow.
- Central approval policy and related executor/planner safety tests.
- Local learning store, secret scanner, CI quality workflow, Railway health
  service, documentation, and macOS packaging changes.

## Approved removals in the working tree

The owner explicitly approved removing eight sensitive or one-off artifacts
from the current tree: `gh_code.txt`, `gh_tokens.png`, `railway_tab.png`,
`get_railway_url.py`, `pw_deep_search.py`, `pw_extract_db.py`,
`pw_extract_react.py`, and `pw_intercept.py`.

The owner subsequently authorized completing every remaining remediation item.
The sensitive artifacts and retired one-off account/chat/debug helpers are absent
from the sanitized root history. A local owner-only bundle is retained for rollback.

## Resolved cleanup decisions

- `ask_db_url.py` and `ask_tokens.py` were retired; credentials are accepted only
  through the product's secure-store-backed integration surfaces.
- The Railway screenshot formerly named `logo.png` is not part of the product tree.
- The legacy Gemini live class, API-key compatibility helpers, model IDs, and
  action-level cloud fallbacks have been removed. A source regression test keeps
  paid-provider runtime markers from returning.
- Old chat/debug/migration helpers were inventoried, confirmed unused by the runtime,
  and removed from the product tree.

## Backup artifacts

Tracked changes and new files are mirrored outside the repository in the Codex
task `outputs/` directory. Old generated `.app` bundles are retained with a
`.disabled` suffix under the task's `work/misha-app-backups/` directory.
