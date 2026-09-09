from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
NORMALIZED_DIR = PROJECT_ROOT / "data/normalized/sleep"
AGGREGATE_DIR = PROJECT_ROOT / "data/aggregates/sleep"


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


def compact_session(session: dict[str, Any]) -> dict[str, Any]:
    durations = session["duration_minutes"]
    return {
        "start": session["start"],
        "end": session["end"],
        "asleep_total_minutes": durations["asleep_total"],
        "awake_minutes": durations["awake"],
        "elapsed_minutes": durations["elapsed"],
        "stages_minutes": {
            "core": durations["core"],
            "deep": durations["deep"],
            "rem": durations["rem"],
            "asleep_unspecified": durations["asleep_unspecified"],
        },
    }


def timeline_segments(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "kind": session["kind"],
            "state": sample["state"],
            "start": sample["start"],
            "end": sample["end"],
            "duration_minutes": sample["duration_minutes"],
        }
        for sample in session.get("samples", [])
    ]


def aggregate_day(day: date, payload: dict[str, Any]) -> dict[str, Any]:
    main_session = next((session for session in payload["sessions"] if session["kind"] == "main"), None)
    naps = [session for session in payload["sessions"] if session["kind"] == "nap"]
    all_durations = [session["duration_minutes"] for session in payload["sessions"]]

    return {
        "date": day.isoformat(),
        "weekday": day.strftime("%A"),
        "main_sleep": compact_session(main_session) if main_session else None,
        "naps": [compact_session(session) for session in naps],
        "totals": {
            "all_sleep_asleep_minutes": sum(duration["asleep_total"] for duration in all_durations),
            "main_sleep_asleep_minutes": (
                main_session["duration_minutes"]["asleep_total"] if main_session else None
            ),
            "nap_asleep_minutes": sum(session["duration_minutes"]["asleep_total"] for session in naps),
            "awake_minutes": sum(duration["awake"] for duration in all_durations),
        },
        "timeline_segments": [
            segment
            for session in payload["sessions"]
            for segment in timeline_segments(session)
        ],
    }


def summary_stats(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"mean": None, "min": None, "max": None}
    return {
        "mean": mean(values),
        "min": min(values),
        "max": max(values),
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

    main_sleep_values = [
        day_payload["totals"]["main_sleep_asleep_minutes"]
        for day_payload in days
        if day_payload["totals"]["main_sleep_asleep_minutes"] is not None
    ]
    all_sleep_values = [day_payload["totals"]["all_sleep_asleep_minutes"] for day_payload in days]

    return {
        "schema_version": "sleep.weekly.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": {
            "label": week_label,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "week_start": "Sunday",
        },
        "source": {
            "kind": "railife_normalized_sleep",
            "input_files": input_files,
            "missing_dates": missing_dates,
        },
        "days": days,
        "statistics": {
            "observed_days": len(days),
            "missing_days": len(missing_dates),
            "main_sleep_asleep_minutes": summary_stats(main_sleep_values),
            "all_sleep_asleep_minutes": summary_stats(all_sleep_values),
            "nap_count": sum(len(day_payload["naps"]) for day_payload in days),
            "nap_asleep_minutes_total": sum(
                day_payload["totals"]["nap_asleep_minutes"] for day_payload in days
            ),
        },
    }


def project_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def write_week_aggregate(
    aggregate: dict[str, Any],
    *,
    output_dir: Path = AGGREGATE_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    week = aggregate["week"]
    label = week["label"].lower().replace(" ", "-")
    output_path = output_dir / f"{label}_{week['start_date']}_{week['end_date']}.json"
    output_path.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate daily sleep JSON into a weekly sleep dataset.")
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
