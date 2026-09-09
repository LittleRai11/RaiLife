from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from railife.models.sleep import SleepSample, SleepSession
from railife.parsers.apple_health_sleep import parse_sleep_file


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_DIR = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/RaiHealth/sleep"
RAW_DIR = PROJECT_ROOT / "data/raw/apple_health/sleep"
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/raw_files.json"
NORMALIZED_DIR = PROJECT_ROOT / "data/normalized/sleep"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_raw_snapshot(source_path: Path, raw_dir: Path = RAW_DIR) -> tuple[Path, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(source_path)
    snapshot_name = f"{source_path.stem}__{source_hash[:12]}{source_path.suffix}"
    snapshot_path = raw_dir / snapshot_name
    if not snapshot_path.exists():
        shutil.copy2(source_path, snapshot_path)
    return snapshot_path, source_hash


def update_manifest(entries: list[dict], manifest_path: Path = MANIFEST_PATH) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))

    by_hash = {entry["sha256"]: entry for entry in existing}
    for entry in entries:
        by_hash[entry["sha256"]] = entry

    manifest = sorted(by_hash.values(), key=lambda item: (item["source_file"], item["sha256"]))
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def group_sessions(samples: list[SleepSample], *, session_gap_minutes: int) -> list[tuple[SleepSample, ...]]:
    if not samples:
        return []

    sessions: list[list[SleepSample]] = [[samples[0]]]
    max_gap_seconds = session_gap_minutes * 60

    for sample in samples[1:]:
        previous_end = max(existing.end for existing in sessions[-1])
        gap_seconds = (sample.start - previous_end).total_seconds()
        if gap_seconds > max_gap_seconds:
            sessions.append([sample])
        else:
            sessions[-1].append(sample)

    return [tuple(session) for session in sessions]


def classify_sessions(grouped_samples: list[tuple[SleepSample, ...]]) -> list[SleepSession]:
    if not grouped_samples:
        return []

    def asleep_minutes(samples: tuple[SleepSample, ...]) -> int:
        return sum(sample.duration_minutes for sample in samples if sample.state != "Awake")

    main_position = max(
        range(len(grouped_samples)),
        key=lambda index: (asleep_minutes(grouped_samples[index]), len(grouped_samples[index])),
    )

    nap_index = 1
    sessions: list[SleepSession] = []
    for position, samples in enumerate(grouped_samples):
        if position == main_position:
            sessions.append(SleepSession(index=0, kind="main", samples=samples))
        else:
            sessions.append(SleepSession(index=nap_index, kind="nap", samples=samples))
            nap_index += 1
    return sessions


def normalize_source(source: str | None) -> str:
    return (source or "").strip()


def sample_identity(sample: SleepSample) -> tuple[str, str, str, str]:
    return (
        sample.state,
        sample.start.isoformat(),
        sample.end.isoformat(),
        normalize_source(sample.source),
    )


def sleep_sample_from_json(payload: dict[str, Any]) -> SleepSample:
    source = normalize_source(payload.get("source"))
    return SleepSample(
        state=payload["state"],
        start=datetime.fromisoformat(payload["start"]),
        end=datetime.fromisoformat(payload["end"]),
        line_number=payload["line_number"],
        raw_line=payload["raw_line"],
        source_file=payload["source_file"],
        source=source or None,
    )


def samples_from_daily_json(payload: dict[str, Any]) -> list[SleepSample]:
    return [
        sleep_sample_from_json(sample)
        for session in payload.get("sessions", [])
        for sample in session.get("samples", [])
    ]


def dedupe_samples(samples: list[SleepSample]) -> list[SleepSample]:
    by_identity: dict[tuple[str, str, str, str], SleepSample] = {}
    for sample in samples:
        by_identity.setdefault(sample_identity(sample), sample)
    return sorted(
        by_identity.values(),
        key=lambda sample: (sample.start, sample.end, sample.state, normalize_source(sample.source)),
    )


def group_sessions_by_wake_date(
    samples: list[SleepSample],
    *,
    session_gap_minutes: int,
) -> dict[str, list[tuple[SleepSample, ...]]]:
    grouped = group_sessions(samples, session_gap_minutes=session_gap_minutes)
    sessions_by_date: dict[str, list[tuple[SleepSample, ...]]] = {}
    for session_samples in grouped:
        session_date = max(sample.end for sample in session_samples).date().isoformat()
        sessions_by_date.setdefault(session_date, []).append(session_samples)
    return sessions_by_date


def build_daily_json(
    sessions: list[SleepSession],
    *,
    daily_date: str,
    source_file: str,
    source_sha256: str,
    raw_snapshot: Path,
    timezone_name: str,
    session_gap_minutes: int,
) -> dict:
    return {
        "schema_version": "sleep.daily.v1",
        "date": daily_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "apple_health",
            "type": "sleep",
            "source_file": source_file,
            "raw_snapshot": project_relative_path(raw_snapshot),
            "sha256": source_sha256,
            "timezone_assumption": timezone_name,
            "session_gap_minutes": session_gap_minutes,
        },
        "sessions": [session.to_json(daily_date) for session in sessions],
    }


def normalize_samples(
    samples: list[SleepSample],
    *,
    source_file: str,
    source_sha256: str,
    raw_snapshot: Path,
    timezone_name: str,
    session_gap_minutes: int,
) -> dict:
    sessions_by_date = group_sessions_by_wake_date(
        samples,
        session_gap_minutes=session_gap_minutes,
    )
    if not sessions_by_date:
        raise ValueError("Cannot normalize an empty sleep sample set")

    daily_date = min(sessions_by_date)
    sessions = classify_sessions(sessions_by_date[daily_date])
    return build_daily_json(
        sessions,
        daily_date=daily_date,
        source_file=source_file,
        source_sha256=source_sha256,
        raw_snapshot=raw_snapshot,
        timezone_name=timezone_name,
        session_gap_minutes=session_gap_minutes,
    )


def project_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def normalize_snapshot_by_date(
    samples: list[SleepSample],
    *,
    source_file: str,
    source_sha256: str,
    raw_snapshot: Path,
    timezone_name: str,
    session_gap_minutes: int,
    normalized_dir: Path = NORMALIZED_DIR,
) -> dict[str, dict]:
    incoming_sessions_by_date = group_sessions_by_wake_date(
        samples,
        session_gap_minutes=session_gap_minutes,
    )
    normalized_by_date: dict[str, dict] = {}

    for daily_date, incoming_sessions in sorted(incoming_sessions_by_date.items()):
        output_path = normalized_dir / f"{daily_date}.json"
        existing_samples: list[SleepSample] = []
        existing_keys: set[tuple[str, str, str, str]] = set()
        if output_path.exists():
            existing_payload = json.loads(output_path.read_text(encoding="utf-8"))
            existing_samples = samples_from_daily_json(existing_payload)
            existing_keys = {sample_identity(sample) for sample in existing_samples}

        incoming_samples = [sample for session in incoming_sessions for sample in session]
        merged_samples = dedupe_samples(existing_samples + incoming_samples)
        merged_keys = {sample_identity(sample) for sample in merged_samples}
        if existing_keys and merged_keys == existing_keys:
            continue

        daily_grouped = group_sessions(merged_samples, session_gap_minutes=session_gap_minutes)
        daily_sessions = classify_sessions(daily_grouped)
        normalized_by_date[daily_date] = build_daily_json(
            daily_sessions,
            daily_date=daily_date,
            source_file=source_file,
            source_sha256=source_sha256,
            raw_snapshot=raw_snapshot,
            timezone_name=timezone_name,
            session_gap_minutes=session_gap_minutes,
        )

    return normalized_by_date


def process_file(
    source_path: Path,
    *,
    timezone_name: str,
    session_gap_minutes: int,
    raw_dir: Path = RAW_DIR,
    manifest_path: Path = MANIFEST_PATH,
    normalized_dir: Path = NORMALIZED_DIR,
) -> list[Path]:
    snapshot_path, source_hash = copy_raw_snapshot(source_path, raw_dir)
    samples = parse_sleep_file(snapshot_path, timezone_name=timezone_name)
    normalized_by_date = normalize_snapshot_by_date(
        samples,
        source_file=source_path.name,
        source_sha256=source_hash,
        raw_snapshot=snapshot_path,
        timezone_name=timezone_name,
        session_gap_minutes=session_gap_minutes,
        normalized_dir=normalized_dir,
    )

    normalized_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    for normalized in normalized_by_date.values():
        output_path = normalized_dir / f"{normalized['date']}.json"
        output_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output_paths.append(output_path)

    update_manifest(
        [
            {
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "source_file": source_path.name,
                "source_path": str(source_path),
                "raw_snapshot": project_relative_path(snapshot_path),
                "sha256": source_hash,
            }
        ],
        manifest_path,
    )
    return output_paths


def run_pipeline(source_dir: Path, *, timezone_name: str, session_gap_minutes: int) -> list[Path]:
    source_files = sorted(source_dir.glob("*.txt"))
    output_paths: list[Path] = []
    for source_file in source_files:
        output_paths.extend(
            process_file(
                source_file,
                timezone_name=timezone_name,
                session_gap_minutes=session_gap_minutes,
            )
        )
    return output_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize Apple Health sleep exports.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--timezone", required=True, help="Timezone for source timestamps, e.g. Asia/Shanghai")
    parser.add_argument("--session-gap-minutes", type=int, default=90)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    outputs = run_pipeline(
        args.source_dir,
        timezone_name=args.timezone,
        session_gap_minutes=args.session_gap_minutes,
    )
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
