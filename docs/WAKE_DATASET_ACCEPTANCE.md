# Wake data set and acceptance

Misha does not claim acoustic wake accuracy from transcript-only unit tests. Real local
recordings must be labelled outside the repository and evaluated with the deterministic
acceptance command below. Raw recordings, names and transcripts must never be committed.

```bash
python scripts/evaluate_wake_dataset.py /private/path/wake-manifest.json \
  --output /private/path/wake-report.json
```

The JSON manifest uses `schema_version: 1` and a `samples` list. Each item contains a
non-identifying `sample_id`, `positive` or `negative` label, `silent`, `office` or `noisy`
environment, pseudonymous `speaker_id`, measured duration, boolean detection result and
optional latency. The evaluator rejects duplicate identifiers and invalid bounds.

Acceptance requires all three measurements: at least 95% silent positive success, at
least 90% office positive success, and fewer than one false wake per hour of negative
audio. A report cannot pass when any required class is absent. The report contains only
aggregate measurements and never embeds audio.

Collect multiple Turkish and English pronunciations, accents, distances and microphone
angles. Include near-words and ordinary conversation in negative audio. Keep recordings
in an owner-controlled directory with restrictive permissions and delete them after the
needed model/evaluation artefacts have been produced.
