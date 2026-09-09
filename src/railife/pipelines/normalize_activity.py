from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from railife.models.activity import DETAIL_SCHEMA_VERSION, SCHEMA_VERSION, DailyStepCount, WorkoutSummary
from railife.parsers.health_auto_export_activity import (
    normalized_detail_series,
    parse_step_file,
    parse_workout_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STEP_SOURCE_DIR = (
    Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/RaiHealth/step"
)
DEFAULT_WORKOUT_SOURCE_DIR = (
    Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/RaiHealth/workout"
)
RAW_STEP_DIR = PROJECT_ROOT / "data/raw/health_auto_export/step"
RAW_WORKOUT_DIR = PROJECT_ROOT / "data/raw/health_auto_export/workout"
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/raw_files.json"
NORMALIZED_DIR = PROJECT_ROOT / "data/normalized/activity"
WORKOUT_DETAIL_DIR = NORMALIZED_DIR / "workout_details"


class ActivityConflictError(ValueError):
    """Raised when strict v1 activity merge rules find conflicting source data."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def copy_raw_snapshot(source_path: Path, raw_dir: Path) -> tuple[Path, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(source_path)
    snapshot_name = f"{source_path.stem}__{source_hash[:12]}{source_path.suffix}"
    snapshot_path = raw_dir / snapshot_name
    if not snapshot_path.exists():
        shutil.copy2(source_path, snapshot_path)
    return snapshot_path, source_hash


def update_manifest(entries: list[dict[str, Any]], manifest_path: Path = MANIFEST_PATH) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))

    by_hash = {entry["sha256"]: entry for entry in existing}
    for entry in entries:
        by_hash.setdefault(entry["sha256"], entry)

    manifest = sorted(by_hash.values(), key=lambda item: (item["source_file"], item["sha256"]))
    existing_manifest = json.dumps(existing, indent=2, sort_keys=True) + "\n"
    next_manifest = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if next_manifest != existing_manifest:
        manifest_path.write_text(next_manifest, encoding="utf-8")


def nullable_steps() -> dict[str, Any]:
    return {
        "count": None,
        "unit": "count",
        "source_metric": "step_count",
        "source_date": None,
        "source_timezone_offset": None,
        "source": None,
        "provenance": None,
    }


def merge_steps(steps: list[DailyStepCount]) -> dict[str, DailyStepCount]:
    by_date: dict[str, DailyStepCount] = {}
    for step in steps:
        existing = by_date.get(step.date)
        if existing is None:
            by_date[step.date] = step
            continue
        if existing.identity != step.identity:
            raise ActivityConflictError(
                f"Conflicting step_count values for {step.date}: "
                f"{existing.count} {existing.unit} from {existing.raw_snapshot.name} vs "
                f"{step.count} {step.unit} from {step.raw_snapshot.name}"
            )
    return by_date


def merge_workouts(workouts: list[WorkoutSummary]) -> dict[str, list[WorkoutSummary]]:
    by_id: dict[str, WorkoutSummary] = {}
    for workout in workouts:
        existing = by_id.get(workout.id)
        if existing is None:
            by_id[workout.id] = workout
            continue
        if existing.raw_workout_sha256 != workout.raw_workout_sha256:
            raise ActivityConflictError(
                f"Conflicting workout versions for id {workout.id}: "
                f"{existing.raw_snapshot.name} vs {workout.raw_snapshot.name}"
            )

    by_date: dict[str, list[WorkoutSummary]] = {}
    for workout in by_id.values():
        by_date.setdefault(workout.local_date, []).append(workout)
    for date_workouts in by_date.values():
        date_workouts.sort(key=lambda item: (item.start, item.end, item.id))
    return by_date


def build_source_refs(
    *,
    refs: list[dict[str, Any]],
    source_type: str,
) -> list[dict[str, Any]]:
    return [
        {
            "source_file": ref["source_file"],
            "raw_snapshot": project_relative_path(ref["raw_snapshot"]),
            "sha256": ref["sha256"],
            "exporter": "health_auto_export",
            "provider": "apple_health",
            "type": source_type,
        }
        for ref in refs
    ]


def build_daily_activity(
    *,
    activity_date: str,
    step: DailyStepCount | None,
    workouts: list[WorkoutSummary],
    step_refs: list[dict[str, Any]],
    workout_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "date": activity_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "apple_health",
            "exporter": "health_auto_export",
            "types": ["step", "workout"],
            "step_sources": build_source_refs(refs=step_refs, source_type="step"),
            "workout_sources": build_source_refs(refs=workout_refs, source_type="workout"),
        },
        "steps": (
            step.to_json(project_relative_path(step.raw_snapshot))
            if step is not None
            else nullable_steps()
        ),
        "workouts": [
            workout.to_json(
                raw_snapshot_path=project_relative_path(workout.raw_snapshot),
                detail_file_path=project_relative_path(workout.detail_file),
            )
            for workout in workouts
        ],
    }


def build_workout_detail(
    *,
    workout: WorkoutSummary,
    raw_workout: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": DETAIL_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workout": {
            "id": workout.id,
            "name": workout.name,
            "start": workout.start.isoformat(),
            "end": workout.end.isoformat(),
        },
        "provenance": {
            "provider": "apple_health",
            "exporter": "health_auto_export",
            "raw_snapshot": project_relative_path(workout.raw_snapshot),
            "sha256": workout.source_sha256,
            "json_pointer": workout.json_pointer,
            "raw_workout_sha256": workout.raw_workout_sha256,
        },
        "series": normalized_detail_series(raw_workout),
    }


def existing_daily_semantic_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return comparable_daily_payload(payload)


def comparable_daily_payload(payload: dict[str, Any]) -> dict[str, Any]:
    comparable = dict(payload)
    comparable.pop("generated_at", None)
    return comparable


def write_json_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if comparable_daily_payload(existing) == comparable_daily_payload(payload):
            return False
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def collect_inputs(
    *,
    step_source_dir: Path,
    workout_source_dir: Path,
    raw_step_dir: Path,
    raw_workout_dir: Path,
    workout_detail_dir: Path,
) -> tuple[
    list[DailyStepCount],
    list[WorkoutSummary],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    steps: list[DailyStepCount] = []
    workouts: list[WorkoutSummary] = []
    raw_workouts_by_id: dict[str, dict[str, Any]] = {}
    manifest_entries: list[dict[str, Any]] = []
    step_refs: list[dict[str, Any]] = []
    workout_refs: list[dict[str, Any]] = []

    for source_path in sorted(step_source_dir.glob("*.json")):
        snapshot_path, source_hash = copy_raw_snapshot(source_path, raw_step_dir)
        step_refs.append(
            {"source_file": source_path.name, "raw_snapshot": snapshot_path, "sha256": source_hash}
        )
        manifest_entries.append(manifest_entry(source_path, snapshot_path, source_hash, "step"))
        steps.extend(
            parse_step_file(
                snapshot_path,
                raw_snapshot=snapshot_path,
                source_sha256=source_hash,
            )
        )

    for source_path in sorted(workout_source_dir.glob("*.json")):
        snapshot_path, source_hash = copy_raw_snapshot(source_path, raw_workout_dir)
        workout_refs.append(
            {"source_file": source_path.name, "raw_snapshot": snapshot_path, "sha256": source_hash}
        )
        manifest_entries.append(manifest_entry(source_path, snapshot_path, source_hash, "workout"))
        parsed_workouts = parse_workout_file(
            snapshot_path,
            raw_snapshot=snapshot_path,
            source_sha256=source_hash,
            detail_dir=workout_detail_dir,
        )
        for workout, raw_workout in parsed_workouts:
            existing = raw_workouts_by_id.get(workout.id)
            if existing is not None and workout.raw_workout_sha256 != hashlib.sha256(
                json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest():
                raise ActivityConflictError(f"Conflicting raw workout cache for id {workout.id}")
            raw_workouts_by_id[workout.id] = raw_workout
            workouts.append(workout)

    return steps, workouts, raw_workouts_by_id, manifest_entries, step_refs, workout_refs


def manifest_entry(source_path: Path, snapshot_path: Path, source_hash: str, source_type: str) -> dict[str, Any]:
    return {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "provider": "apple_health",
        "exporter": "health_auto_export",
        "type": source_type,
        "source_file": source_path.name,
        "source_path": str(source_path),
        "raw_snapshot": project_relative_path(snapshot_path),
        "sha256": source_hash,
    }


def run_pipeline(
    *,
    step_source_dir: Path = DEFAULT_STEP_SOURCE_DIR,
    workout_source_dir: Path = DEFAULT_WORKOUT_SOURCE_DIR,
    raw_step_dir: Path = RAW_STEP_DIR,
    raw_workout_dir: Path = RAW_WORKOUT_DIR,
    manifest_path: Path = MANIFEST_PATH,
    normalized_dir: Path = NORMALIZED_DIR,
    workout_detail_dir: Path = WORKOUT_DETAIL_DIR,
) -> list[Path]:
    (
        steps,
        workouts,
        raw_workouts_by_id,
        manifest_entries,
        step_refs,
        workout_refs,
    ) = collect_inputs(
        step_source_dir=step_source_dir,
        workout_source_dir=workout_source_dir,
        raw_step_dir=raw_step_dir,
        raw_workout_dir=raw_workout_dir,
        workout_detail_dir=workout_detail_dir,
    )

    steps_by_date = merge_steps(steps)
    workouts_by_date = merge_workouts(workouts)
    dates = sorted(set(steps_by_date) | set(workouts_by_date))

    output_paths: list[Path] = []
    for activity_date in dates:
        for workout in workouts_by_date.get(activity_date, []):
            detail_payload = build_workout_detail(
                workout=workout,
                raw_workout=raw_workouts_by_id[workout.id],
            )
            if write_json_if_changed(workout.detail_file, detail_payload):
                output_paths.append(workout.detail_file)

        daily_payload = build_daily_activity(
            activity_date=activity_date,
            step=steps_by_date.get(activity_date),
            workouts=workouts_by_date.get(activity_date, []),
            step_refs=step_refs,
            workout_refs=workout_refs,
        )
        daily_path = normalized_dir / f"{activity_date}.json"
        if write_json_if_changed(daily_path, daily_payload):
            output_paths.append(daily_path)

    if manifest_entries:
        update_manifest(manifest_entries, manifest_path)

    return output_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize Health Auto Export activity JSON.")
    parser.add_argument("--step-source-dir", type=Path, default=DEFAULT_STEP_SOURCE_DIR)
    parser.add_argument("--workout-source-dir", type=Path, default=DEFAULT_WORKOUT_SOURCE_DIR)
    parser.add_argument("--raw-step-dir", type=Path, default=RAW_STEP_DIR)
    parser.add_argument("--raw-workout-dir", type=Path, default=RAW_WORKOUT_DIR)
    parser.add_argument("--manifest-path", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--normalized-dir", type=Path, default=NORMALIZED_DIR)
    parser.add_argument("--workout-detail-dir", type=Path, default=WORKOUT_DETAIL_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    outputs = run_pipeline(
        step_source_dir=args.step_source_dir,
        workout_source_dir=args.workout_source_dir,
        raw_step_dir=args.raw_step_dir,
        raw_workout_dir=args.raw_workout_dir,
        manifest_path=args.manifest_path,
        normalized_dir=args.normalized_dir,
        workout_detail_dir=args.workout_detail_dir,
    )
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
