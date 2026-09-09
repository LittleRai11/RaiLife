from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
NORMALIZED_DIR = PROJECT_ROOT / "data/normalized/activity"
AGGREGATE_DIR = PROJECT_ROOT / "data/aggregates/activity"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def daterange(start_date: date, end_date: date) -> list[date]:
    days = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def project_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def aggregate_day(day: date, payload: dict[str, Any]) -> dict[str, Any]:
    steps = payload.get("steps", {})
    step_count = steps.get("count")
    workouts = payload.get("workouts", [])
    return {
        "date": day.isoformat(),
        "weekday": day.strftime("%A"),
        "steps": {
            "count": step_count,
            "unit": steps.get("unit"),
            "display_count": round(step_count) if step_count is not None else None,
            "display_rule": "round(count) for presentation only; count preserves normalized source value",
            "source_metric": steps.get("source_metric"),
        },
        "workout_count": len(workouts),
        "workouts": [compact_workout(workout) for workout in workouts],
    }


def compact_workout(workout: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": workout.get("id"),
        "name": workout.get("name"),
        "start": workout.get("start"),
        "end": workout.get("end"),
        "duration_seconds": workout.get("duration_seconds"),
        "distance": workout.get("distance"),
        "active_energy": workout.get("active_energy"),
        "heart_rate": workout.get("heart_rate"),
        "detail_file": workout.get("detail_file"),
    }


def extrema(days: list[dict[str, Any]], *, fn) -> dict[str, Any]:
    observed = [day for day in days if day["steps"]["count"] is not None]
    if not observed:
        return {"date": None, "count": None, "display_count": None}
    selected = fn(observed, key=lambda day: day["steps"]["count"])
    return {
        "date": selected["date"],
        "count": selected["steps"]["count"],
        "display_count": selected["steps"]["display_count"],
    }


def build_week_aggregate(
    *,
    week_label: str,
    start_date: date,
    end_date: date,
    normalized_dir: Path = NORMALIZED_DIR,
) -> dict[str, Any]:
    input_files: list[dict[str, str]] = []
    missing_dates: list[str] = []
    days: list[dict[str, Any]] = []

    for day in daterange(start_date, end_date):
        path = normalized_dir / f"{day.isoformat()}.json"
        if not path.exists():
            missing_dates.append(day.isoformat())
            continue

        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "activity.daily.v1":
            raise ValueError(f"{path}: expected schema_version activity.daily.v1")
        if payload.get("date") != day.isoformat():
            raise ValueError(f"{path}: payload date does not match filename date")

        input_files.append(
            {
                "date": day.isoformat(),
                "path": project_relative_path(path),
                "sha256": sha256_file(path),
            }
        )
        days.append(aggregate_day(day, payload))

    step_values = [day["steps"]["count"] for day in days if day["steps"]["count"] is not None]
    workouts = [workout for day in days for workout in day["workouts"]]
    total_steps = sum(step_values) if step_values else None
    return {
        "schema_version": "activity.weekly.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": {
            "label": week_label,
            "week_start": start_date.isoformat(),
            "week_end": end_date.isoformat(),
            "week_start_day": "Sunday",
        },
        "source": {
            "kind": "railife_normalized_activity",
            "input_files": input_files,
            "missing_dates": missing_dates,
        },
        "days": days,
        "statistics": {
            "observed_days": len(days),
            "missing_days": len(missing_dates),
            "total_steps": total_steps,
            "total_steps_display": round(total_steps) if total_steps is not None else None,
            "average_steps": mean(step_values) if step_values else None,
            "average_steps_display": round(mean(step_values)) if step_values else None,
            "display_rule": "display step fields are rounded with round(); raw statistics preserve normalized values",
            "max_steps": extrema(days, fn=max),
            "min_steps": extrema(days, fn=min),
            "workout_count": len(workouts),
        },
        "workouts": workouts,
    }


def write_week_aggregate(
    aggregate: dict[str, Any],
    *,
    output_dir: Path = AGGREGATE_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    week = aggregate["week"]
    label = week["label"].lower().replace(" ", "-")
    output_path = output_dir / f"{label}_{week['week_start']}_{week['week_end']}.json"
    output_path.write_text(json.dumps(aggregate, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate daily activity JSON into a weekly activity dataset.")
    parser.add_argument("--week-label", required=True)
    parser.add_argument("--start-date", required=True, type=parse_date)
    parser.add_argument("--end-date", required=True, type=parse_date)
    parser.add_argument("--normalized-dir", type=Path, default=NORMALIZED_DIR)
    parser.add_argument("--output-dir", type=Path, default=AGGREGATE_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    aggregate = build_week_aggregate(
        week_label=args.week_label,
        start_date=args.start_date,
        end_date=args.end_date,
        normalized_dir=args.normalized_dir,
    )
    output_path = write_week_aggregate(aggregate, output_dir=args.output_dir)
    print(output_path)


if __name__ == "__main__":
    main()
