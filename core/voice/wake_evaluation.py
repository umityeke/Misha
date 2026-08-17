from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence


WakeLabel = Literal["positive", "negative"]
WakeEnvironment = Literal["silent", "office", "noisy"]


@dataclass(frozen=True)
class WakeEvaluationSample:
    sample_id: str
    label: WakeLabel
    environment: WakeEnvironment
    speaker_id: str
    detected: bool
    duration_seconds: float
    latency_ms: float | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "WakeEvaluationSample":
        if not isinstance(value, dict):
            raise ValueError("Each wake sample must be an object.")
        required = {
            "sample_id",
            "label",
            "environment",
            "speaker_id",
            "detected",
            "duration_seconds",
        }
        missing = required.difference(value)
        if missing:
            raise ValueError(f"Wake sample is missing fields: {', '.join(sorted(missing))}.")
        sample_id = str(value["sample_id"]).strip()
        speaker_id = str(value["speaker_id"]).strip()
        label = str(value["label"]).strip()
        environment = str(value["environment"]).strip()
        detected = value["detected"]
        if not sample_id or not speaker_id:
            raise ValueError("Sample and speaker identifiers must not be empty.")
        if label not in {"positive", "negative"}:
            raise ValueError("Wake label must be positive or negative.")
        if environment not in {"silent", "office", "noisy"}:
            raise ValueError("Wake environment must be silent, office or noisy.")
        if not isinstance(detected, bool):
            raise ValueError("Wake detected must be a boolean.")
        duration = float(value["duration_seconds"])
        if duration <= 0 or duration > 3600:
            raise ValueError("Sample duration must be between 0 and 3600 seconds.")
        raw_latency = value.get("latency_ms")
        latency = None if raw_latency is None else float(raw_latency)
        if latency is not None and (latency < 0 or latency > 60_000):
            raise ValueError("Wake latency must be between 0 and 60000 ms.")
        return cls(
            sample_id=sample_id,
            label=label,  # type: ignore[arg-type]
            environment=environment,  # type: ignore[arg-type]
            speaker_id=speaker_id,
            detected=detected,
            duration_seconds=duration,
            latency_ms=latency,
        )


def load_wake_samples(path: str | Path) -> list[WakeEvaluationSample]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Wake evaluation manifest schema_version must be 1.")
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list):
        raise ValueError("Wake evaluation manifest must contain a samples list.")
    samples = [WakeEvaluationSample.from_mapping(item) for item in raw_samples]
    identifiers = [sample.sample_id for sample in samples]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Wake sample identifiers must be unique.")
    return samples


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def evaluate_wake_samples(samples: Sequence[WakeEvaluationSample]) -> dict[str, object]:
    positive = [sample for sample in samples if sample.label == "positive"]
    negative = [sample for sample in samples if sample.label == "negative"]
    false_wakes = sum(sample.detected for sample in negative)
    negative_hours = sum(sample.duration_seconds for sample in negative) / 3600
    false_wakes_per_hour = None if negative_hours == 0 else round(false_wakes / negative_hours, 4)
    environments: dict[str, dict[str, object]] = {}
    for environment in ("silent", "office", "noisy"):
        candidates = [sample for sample in positive if sample.environment == environment]
        hits = sum(sample.detected for sample in candidates)
        environments[environment] = {
            "positive_samples": len(candidates),
            "detected": hits,
            "success_rate": _rate(hits, len(candidates)),
        }
    latencies = sorted(
        sample.latency_ms
        for sample in positive
        if sample.detected and sample.latency_ms is not None
    )
    median_latency = None
    if latencies:
        middle = len(latencies) // 2
        median_latency = (
            latencies[middle]
            if len(latencies) % 2
            else round((latencies[middle - 1] + latencies[middle]) / 2, 2)
        )
    silent_rate = environments["silent"]["success_rate"]
    office_rate = environments["office"]["success_rate"]
    thresholds_measured = all(
        value is not None for value in (silent_rate, office_rate, false_wakes_per_hour)
    )
    passed = bool(
        thresholds_measured
        and float(silent_rate) >= 0.95
        and float(office_rate) >= 0.90
        and float(false_wakes_per_hour) < 1.0
    )
    return {
        "schema_version": 1,
        "sample_count": len(samples),
        "speaker_count": len({sample.speaker_id for sample in samples}),
        "environments": environments,
        "negative_samples": len(negative),
        "negative_audio_hours": round(negative_hours, 4),
        "false_wakes": false_wakes,
        "false_wakes_per_hour": false_wakes_per_hour,
        "median_detection_latency_ms": median_latency,
        "thresholds_measured": thresholds_measured,
        "passed": passed,
        "thresholds": {
            "silent_success_rate": 0.95,
            "office_success_rate": 0.90,
            "false_wakes_per_hour_exclusive_maximum": 1.0,
        },
        "privacy": "The report contains aggregate labels only; raw audio is not embedded.",
    }


def write_wake_manifest(
    path: str | Path,
    samples: Iterable[WakeEvaluationSample],
) -> None:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "samples": [asdict(sample) for sample in samples]}
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
