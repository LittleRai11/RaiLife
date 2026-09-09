from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "activity.daily.v1"
DETAIL_SCHEMA_VERSION = "activity.workout_detail.v1"
KJ_PER_KCAL = 4.184


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def parse_health_auto_export_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def value_with_unit(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"value": None, "unit": None}
    return {
        "value": payload.get("qty"),
        "unit": payload.get("units"),
    }


def energy_value(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "value": None,
            "unit": "kcal",
            "source_value": None,
            "source_unit": None,
            "conversion": None,
        }

    source_value = payload.get("qty")
    source_unit = payload.get("units")
    if source_unit == "kJ" and source_value is not None:
        return {
            "value": source_value / KJ_PER_KCAL,
            "unit": "kcal",
            "source_value": source_value,
            "source_unit": source_unit,
            "conversion": "kcal = kJ / 4.184",
        }

    if source_unit == "kcal":
        return {
            "value": source_value,
            "unit": "kcal",
            "source_value": source_value,
            "source_unit": source_unit,
            "conversion": None,
        }

    return {
        "value": None,
        "unit": "kcal",
        "source_value": source_value,
        "source_unit": source_unit,
        "conversion": None,
    }


@dataclass(frozen=True)
class DailyStepCount:
    date: str
    count: int | float
    unit: str
    source_metric: str
    source_date: str
    source_timezone_offset: str
    source: str | None
    raw_snapshot: Path
    source_sha256: str
    json_pointer: str

    @property
    def identity(self) -> tuple[str, int | float, str]:
        return (self.date, self.count, self.unit)

    def to_json(self, raw_snapshot_path: str) -> dict[str, Any]:
        return {
            "count": self.count,
            "unit": self.unit,
            "source_metric": self.source_metric,
            "source_date": self.source_date,
            "source_timezone_offset": self.source_timezone_offset,
            "source": self.source,
            "provenance": {
                "raw_snapshot": raw_snapshot_path,
                "sha256": self.source_sha256,
                "json_pointer": self.json_pointer,
            },
        }


@dataclass(frozen=True)
class WorkoutSummary:
    id: str
    name: str | None
    start: datetime
    end: datetime
    duration_seconds: int | float | None
    location: str | None
    is_indoor: bool | None
    distance: dict[str, Any]
    active_energy: dict[str, Any]
    total_energy: dict[str, Any]
    heart_rate: dict[str, Any]
    raw_snapshot: Path
    source_sha256: str
    json_pointer: str
    raw_workout_sha256: str
    detail_file: Path
    detail_arrays: dict[str, int]

    @property
    def local_date(self) -> str:
        return self.start.date().isoformat()

    @property
    def identity(self) -> tuple[str]:
        return (self.id,)

    def comparable_payload(self) -> dict[str, Any]:
        payload = self.to_json(
            raw_snapshot_path=str(self.raw_snapshot),
            detail_file_path=str(self.detail_file),
        )
        payload["provenance"].pop("raw_snapshot", None)
        payload["provenance"].pop("sha256", None)
        payload.pop("detail_file", None)
        return payload

    def to_json(self, *, raw_snapshot_path: str, detail_file_path: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_seconds": self.duration_seconds,
            "location": self.location,
            "is_indoor": self.is_indoor,
            "distance": self.distance,
            "active_energy": self.active_energy,
            "total_energy": self.total_energy,
            "heart_rate": self.heart_rate,
            "detail_file": detail_file_path,
            "provenance": {
                "raw_snapshot": raw_snapshot_path,
                "sha256": self.source_sha256,
                "json_pointer": self.json_pointer,
                "raw_workout_sha256": self.raw_workout_sha256,
                "detail_arrays": self.detail_arrays,
            },
        }
