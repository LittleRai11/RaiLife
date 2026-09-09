from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from railife.models.activity import (
    DailyStepCount,
    WorkoutSummary,
    canonical_json_sha256,
    energy_value,
    parse_health_auto_export_datetime,
    value_with_unit,
)


DETAIL_ARRAY_NAMES = (
    "heartRateData",
    "heartRateRecovery",
    "activeEnergy",
    "basalEnergy",
    "stepCount",
    "walkingAndRunningDistance",
)


class ActivityParseError(ValueError):
    """Raised when a Health Auto Export activity file cannot be parsed."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ActivityParseError(f"{path.name}: invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ActivityParseError(f"{path.name}: expected top-level JSON object")
    return payload


def parse_step_file(
    path: Path,
    *,
    raw_snapshot: Path,
    source_sha256: str,
) -> list[DailyStepCount]:
    payload = load_json(path)
    metrics = payload.get("data", {}).get("metrics", [])
    if not isinstance(metrics, list):
        raise ActivityParseError(f"{path.name}: data.metrics must be a list")

    steps: list[DailyStepCount] = []
    for metric_index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            continue
        if metric.get("name") != "step_count":
            continue
        unit = metric.get("units")
        records = metric.get("data", [])
        if not isinstance(records, list):
            raise ActivityParseError(f"{path.name}: step_count data must be a list")
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            if "qty" not in record or "date" not in record:
                raise ActivityParseError(
                    f"{path.name}: step_count record {record_index} missing qty/date"
                )
            source_date = record["date"]
            timestamp = parse_health_auto_export_datetime(source_date)
            steps.append(
                DailyStepCount(
                    date=timestamp.date().isoformat(),
                    count=record["qty"],
                    unit=unit,
                    source_metric="step_count",
                    source_date=source_date,
                    source_timezone_offset=timestamp.strftime("%z"),
                    source=record.get("source"),
                    raw_snapshot=raw_snapshot,
                    source_sha256=source_sha256,
                    json_pointer=f"/data/metrics/{metric_index}/data/{record_index}",
                )
            )

    return steps


def heart_rate_summary(workout: dict[str, Any]) -> dict[str, Any]:
    nested = workout.get("heartRate")
    if isinstance(nested, dict):
        return {
            "average": value_with_unit(nested.get("avg")),
            "minimum": value_with_unit(nested.get("min")),
            "maximum": value_with_unit(nested.get("max")),
        }

    return {
        "average": value_with_unit(workout.get("avgHeartRate")),
        "minimum": {"value": None, "unit": None},
        "maximum": value_with_unit(workout.get("maxHeartRate")),
    }


def detail_array_counts(workout: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in DETAIL_ARRAY_NAMES:
        value = workout.get(name)
        if isinstance(value, list):
            counts[name] = len(value)
    return counts


def parse_workout_file(
    path: Path,
    *,
    raw_snapshot: Path,
    source_sha256: str,
    detail_dir: Path,
) -> list[tuple[WorkoutSummary, dict[str, Any]]]:
    payload = load_json(path)
    workouts = payload.get("data", {}).get("workouts", [])
    if not isinstance(workouts, list):
        raise ActivityParseError(f"{path.name}: data.workouts must be a list")

    parsed: list[tuple[WorkoutSummary, dict[str, Any]]] = []
    for workout_index, workout in enumerate(workouts):
        if not isinstance(workout, dict):
            continue
        try:
            start = parse_health_auto_export_datetime(workout["start"])
            end = parse_health_auto_export_datetime(workout["end"])
        except KeyError as exc:
            raise ActivityParseError(f"{path.name}: workout {workout_index} missing start/end") from exc

        workout_id = workout.get("id")
        if not workout_id:
            workout_id = canonical_json_sha256(
                {
                    "name": workout.get("name"),
                    "start": workout.get("start"),
                    "end": workout.get("end"),
                    "duration": workout.get("duration"),
                }
            )

        local_date = start.date().isoformat()
        detail_file = detail_dir / local_date / f"{workout_id}.json"
        summary = WorkoutSummary(
            id=workout_id,
            name=workout.get("name"),
            start=start,
            end=end,
            duration_seconds=workout.get("duration"),
            location=workout.get("location"),
            is_indoor=workout.get("isIndoor"),
            distance=value_with_unit(workout.get("distance")),
            active_energy=energy_value(workout.get("activeEnergyBurned")),
            total_energy=energy_value(workout.get("totalEnergy")),
            heart_rate=heart_rate_summary(workout),
            raw_snapshot=raw_snapshot,
            source_sha256=source_sha256,
            json_pointer=f"/data/workouts/{workout_index}",
            raw_workout_sha256=canonical_json_sha256(workout),
            detail_file=detail_file,
            detail_arrays=detail_array_counts(workout),
        )
        parsed.append((summary, workout))

    return parsed


def normalized_detail_series(workout: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    series: dict[str, list[dict[str, Any]]] = {}
    for name in DETAIL_ARRAY_NAMES:
        values = workout.get(name)
        if not isinstance(values, list):
            series[name] = []
            continue
        series[name] = [normalize_series_point(point) for point in values if isinstance(point, dict)]
    return series


def normalize_series_point(point: dict[str, Any]) -> dict[str, Any]:
    timestamp = point.get("date")
    normalized: dict[str, Any] = {
        "timestamp": (
            parse_health_auto_export_datetime(timestamp).isoformat()
            if isinstance(timestamp, str)
            else None
        ),
        "source_date": timestamp,
        "unit": point.get("units"),
        "source": point.get("source"),
    }
    if "qty" in point:
        normalized["value"] = point.get("qty")
    else:
        normalized["average"] = point.get("Avg")
        normalized["minimum"] = point.get("Min")
        normalized["maximum"] = point.get("Max")
    return normalized
