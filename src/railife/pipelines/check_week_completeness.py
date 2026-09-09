from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
NORMALIZED_SLEEP_DIR = PROJECT_ROOT / "data/normalized/sleep"
NORMALIZED_ACTIVITY_DIR = PROJECT_ROOT / "data/normalized/activity"
SLEEP_AGGREGATE_DIR = PROJECT_ROOT / "data/aggregates/sleep"
ACTIVITY_AGGREGATE_DIR = PROJECT_ROOT / "data/aggregates/activity"
REPORT_DIR = PROJECT_ROOT / "data/reports"


def daterange(start_date: date, end_date: date) -> list[date]:
    days = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sleep_snapshot(day: date, *, normalized_sleep_dir: Path) -> dict[str, Any]:
    path = normalized_sleep_dir / f"{day.isoformat()}.json"
    payload = load_json(path)
    if payload is None:
        return {
            "date": day.isoformat(),
            "present": False,
            "path": project_relative_path(path),
            "main_sleep": None,
            "nap_count": None,
            "nap_asleep_minutes": None,
        }
    sessions = payload.get("sessions", [])
    main = next((session for session in sessions if session.get("kind") == "main"), None)
    naps = [session for session in sessions if session.get("kind") == "nap"]
    return {
        "date": day.isoformat(),
        "present": True,
        "path": project_relative_path(path),
        "main_sleep": compact_sleep_session(main) if main else None,
        "nap_count": len(naps),
        "nap_asleep_minutes": sum(nap["duration_minutes"]["asleep_total"] for nap in naps),
    }


def compact_sleep_session(session: dict[str, Any]) -> dict[str, Any]:
    durations = session["duration_minutes"]
    return {
        "start": session["start"],
        "end": session["end"],
        "asleep_total_minutes": durations["asleep_total"],
        "elapsed_minutes": durations["elapsed"],
        "awake_minutes": durations["awake"],
        "stages_minutes": {
            "core": durations["core"],
            "deep": durations["deep"],
            "rem": durations["rem"],
            "asleep_unspecified": durations["asleep_unspecified"],
        },
    }


def activity_snapshot(day: date, *, normalized_activity_dir: Path) -> dict[str, Any]:
    path = normalized_activity_dir / f"{day.isoformat()}.json"
    payload = load_json(path)
    if payload is None:
        return {
            "date": day.isoformat(),
            "present": False,
            "path": project_relative_path(path),
            "steps": None,
            "workout_count": None,
            "workouts": [],
        }
    steps = payload.get("steps", {})
    workouts = payload.get("workouts", [])
    return {
        "date": day.isoformat(),
        "present": True,
        "path": project_relative_path(path),
        "steps": steps.get("count"),
        "steps_display": round(steps["count"]) if steps.get("count") is not None else None,
        "workout_count": len(workouts),
        "workouts": [
            {
                "id": workout.get("id"),
                "name": workout.get("name"),
                "start": workout.get("start"),
                "end": workout.get("end"),
            }
            for workout in workouts
        ],
    }


def aggregate_path(aggregate_dir: Path, week_label: str, start_date: date, end_date: date, *, activity: bool) -> Path:
    label = week_label.lower().replace(" ", "-")
    if activity:
        return aggregate_dir / f"{label}_{start_date.isoformat()}_{end_date.isoformat()}.json"
    return aggregate_dir / f"{label}_{start_date.isoformat()}_{end_date.isoformat()}.json"


def aggregate_status(
    *,
    path: Path,
    expected_schema: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    payload = load_json(path)
    if payload is None:
        return {"present": False, "path": project_relative_path(path), "issues": ["aggregate file missing"]}
    issues = []
    if payload.get("schema_version") != expected_schema:
        issues.append(f"schema_version is {payload.get('schema_version')!r}, expected {expected_schema!r}")
    expected_dates = [day.isoformat() for day in daterange(start_date, end_date)]
    observed_dates = [day["date"] for day in payload.get("days", [])]
    missing = [day for day in expected_dates if day not in observed_dates]
    if missing:
        issues.append(f"aggregate missing dates: {', '.join(missing)}")
    source_missing = payload.get("source", {}).get("missing_dates", [])
    if source_missing:
        issues.append(f"aggregate source reports missing dates: {', '.join(source_missing)}")
    return {
        "present": True,
        "path": project_relative_path(path),
        "observed_days": len(observed_dates),
        "missing_dates": missing,
        "issues": issues,
    }


def detect_notion_conflicts(
    *,
    sleep_days: list[dict[str, Any]],
    notion_daily_records: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not notion_daily_records:
        return []
    conflicts = []
    for day in sleep_days:
        notion = notion_daily_records.get(day["date"])
        if not notion:
            continue
        sleep_text = notion.get("sleep_section_text", "")
        if day["nap_count"] and "小睡：无" in sleep_text:
            conflicts.append(
                {
                    "date": day["date"],
                    "kind": "sleep_nap_conflict",
                    "normalized": {
                        "nap_count": day["nap_count"],
                        "nap_asleep_minutes": day["nap_asleep_minutes"],
                    },
                    "notion_text_excerpt": "小睡：无",
                    "recommendation": "Use normalized sleep data for Week 01; do not use the stale Notion sleep text.",
                }
            )
    return conflicts


def build_report(
    *,
    week_label: str,
    start_date: date,
    end_date: date,
    normalized_sleep_dir: Path = NORMALIZED_SLEEP_DIR,
    normalized_activity_dir: Path = NORMALIZED_ACTIVITY_DIR,
    sleep_aggregate_dir: Path = SLEEP_AGGREGATE_DIR,
    activity_aggregate_dir: Path = ACTIVITY_AGGREGATE_DIR,
    notion_daily_records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sleep_days = [
        sleep_snapshot(day, normalized_sleep_dir=normalized_sleep_dir)
        for day in daterange(start_date, end_date)
    ]
    activity_days = [
        activity_snapshot(day, normalized_activity_dir=normalized_activity_dir)
        for day in daterange(start_date, end_date)
    ]
    sleep_missing = [day["date"] for day in sleep_days if not day["present"]]
    activity_missing = [day["date"] for day in activity_days if not day["present"]]
    workout_days = [
        {
            "date": day["date"],
            "workout_count": day["workout_count"],
            "workouts": day["workouts"],
        }
        for day in activity_days
        if day["present"] and day["workout_count"]
    ]
    issues = []
    if sleep_missing:
        issues.append({"kind": "missing_sleep_days", "dates": sleep_missing})
    if activity_missing:
        issues.append({"kind": "missing_activity_days", "dates": activity_missing})
    notion_conflicts = detect_notion_conflicts(
        sleep_days=sleep_days,
        notion_daily_records=notion_daily_records,
    )
    issues.extend(notion_conflicts)
    return {
        "schema_version": "railife.week_completeness.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": {
            "label": week_label,
            "week_start": start_date.isoformat(),
            "week_end": end_date.isoformat(),
            "week_start_day": "Sunday",
        },
        "sleep": {
            "observed_days": len([day for day in sleep_days if day["present"]]),
            "missing_days": sleep_missing,
            "days": sleep_days,
            "aggregate": aggregate_status(
                path=aggregate_path(sleep_aggregate_dir, week_label, start_date, end_date, activity=False),
                expected_schema="sleep.weekly.v1",
                start_date=start_date,
                end_date=end_date,
            ),
        },
        "activity": {
            "observed_days": len([day for day in activity_days if day["present"]]),
            "missing_days": activity_missing,
            "days": activity_days,
            "workout_days": workout_days,
            "aggregate": aggregate_status(
                path=aggregate_path(activity_aggregate_dir, week_label, start_date, end_date, activity=True),
                expected_schema="activity.weekly.v1",
                start_date=start_date,
                end_date=end_date,
            ),
        },
        "notion_natural_language_intermediate_layer_proposal": {
            "format": "reviewable Markdown plus lightweight JSON index, not a rigid schema yet",
            "fields": [
                "date",
                "sections: mapping of Daily Records section title to original text",
                "explicit_time_ranges: extracted ranges with source section and confidence",
                "fuzzy_time_descriptions: source text that mentions time but is not safely computable",
                "cross_day_observation_candidates",
                "for_you_candidate_excerpts",
                "manual_confirmation_items",
            ],
        },
        "issues": issues,
    }


def project_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def write_report(report: dict[str, Any], *, output_dir: Path = REPORT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    week = report["week"]
    label = week["label"].lower().replace(" ", "-")
    output_path = output_dir / f"{label}_{week['week_start']}_{week['week_end']}_completeness.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Week completeness report for report preparation.")
    parser.add_argument("--week-label", required=True)
    parser.add_argument("--start-date", required=True, type=parse_date)
    parser.add_argument("--end-date", required=True, type=parse_date)
    parser.add_argument("--normalized-sleep-dir", type=Path, default=NORMALIZED_SLEEP_DIR)
    parser.add_argument("--normalized-activity-dir", type=Path, default=NORMALIZED_ACTIVITY_DIR)
    parser.add_argument("--sleep-aggregate-dir", type=Path, default=SLEEP_AGGREGATE_DIR)
    parser.add_argument("--activity-aggregate-dir", type=Path, default=ACTIVITY_AGGREGATE_DIR)
    parser.add_argument("--notion-daily-records", type=Path)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    notion_daily_records = None
    if args.notion_daily_records:
        notion_daily_records = json.loads(args.notion_daily_records.read_text(encoding="utf-8"))
    report = build_report(
        week_label=args.week_label,
        start_date=args.start_date,
        end_date=args.end_date,
        normalized_sleep_dir=args.normalized_sleep_dir,
        normalized_activity_dir=args.normalized_activity_dir,
        sleep_aggregate_dir=args.sleep_aggregate_dir,
        activity_aggregate_dir=args.activity_aggregate_dir,
        notion_daily_records=notion_daily_records,
    )
    output_path = write_report(report, output_dir=args.output_dir)
    print(output_path)


if __name__ == "__main__":
    main()
