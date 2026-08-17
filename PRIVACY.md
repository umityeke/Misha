# Misha Privacy Notice

Misha is designed as a private, local-first personal assistant for its owner.

## Local processing

- Text intelligence uses the owner's local Ollama service by default.
- Speech recognition uses a local `whisper.cpp` model.
- Speech output uses the local macOS `say` command.
- Hands-free audio is processed locally after PIN unlock.
- Temporary wake/command WAV files are deleted after processing.
- Non-owner speech and speech without the wake phrase are not dispatched as
  agent commands.

## Data stored on this Mac

Misha may store the following under `~/.misha/`:

- `config.db`: local application configuration and PIN verifier.
- `learning.db`: user-taught operating rules.
- `memory.db`: local working, episodic, decision, and long-term memory. User
  content fields are authenticated and encrypted; the key is held separately
  in macOS Keychain.
- `voice/owner.json`: a derived voice-feature vector; no enrollment WAV files.
- `models/`: local speech models installed by the owner.
- `transactions/`: rollback metadata for supported code edits.

Memory exports are intentionally readable JSON so the owner can inspect and
move them. They are created with owner-only (`0600`) permissions but must still
be handled like private documents. Deleting the Keychain memory key without an
export makes the encrypted database unrecoverable.

The voice feature is biometric-adjacent data and must remain private. Its file
mode is restricted to the local owner (`0600`). Voice matching does not replace
the PIN or explicit approval for risky actions.

## Network behavior

The active provider accepts only a localhost Ollama address during normal
configuration. Remote configuration sync is off unless the owner explicitly
sets `MISHA_REMOTE_CONFIG_ENABLED=1`. Individual tools such as web search can
access the internet when the requested task requires it.

An optional PostgreSQL connection URL is stored in macOS Keychain, never in the
local configuration database. A legacy `.env` value is removed only after a
write-and-read Keychain verification succeeds.

## Owner controls

- Use the microphone control or `F4` to pause hands-free listening.
- Close Misha to stop the listener completely.
- Learned rules and memory remain local and inspectable. Memory records can be
  listed, deleted by record or category, cleared, and exported/imported through
  the local memory service.
- Back up `~/.misha/` before deleting it; deletion removes local configuration,
  memory, and the enrolled owner voice profile.

Misha must not upload recordings, credentials, private screen content, or IDE
context without an explicit feature and a clear owner-controlled consent path.
