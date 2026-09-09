from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from railife.pipelines.aggregate_activity_week import build_week_aggregate, write_week_aggregate
from railife.pipelines.check_week_completeness import build_report, write_report


class WeeklyReportDataPrepTests(unittest.TestCase):
    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def activity_payload(self, day: str, steps: float | int, workouts: list[dict] | None = None) -> dict:
        return {
            "schema_version": "activity.daily.v1",
            "date": day,
            "steps": {
                "count": steps,
                "unit": "count",
                "source_metric": "step_count",
            },
            "workouts": workouts or [],
        }

    def sleep_payload(self, day: str, *, naps: list[dict] | None = None) -> dict:
        return {
            "schema_version": "sleep.daily.v1",
            "date": day,
            "sessions": [
                {
                    "kind": "main",
                    "start": f"{day}T01:00:00+08:00",
                    "end": f"{day}T08:00:00+08:00",
                    "duration_minutes": {
                        "asleep_total": 420,
                        "elapsed": 420,
                        "awake": 0,
                        "core": 240,
                        "deep": 60,
                        "rem": 120,
                        "asleep_unspecified": 0,
                    },
                    "samples": [],
                },
                *(naps or []),
            ],
        }

    def nap_session(self, day: str) -> dict:
        return {
            "kind": "nap",
            "start": f"{day}T13:00:00+08:00",
            "end": f"{day}T14:00:00+08:00",
            "duration_minutes": {
                "asleep_total": 60,
                "elapsed": 60,
                "awake": 0,
                "core": None,
                "deep": None,
                "rem": None,
                "asleep_unspecified": 60,
            },
            "samples": [],
        }

    def test_activity_weekly_aggregate_preserves_raw_and_display_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            normalized = tmp_path / "activity"
            self.write_json(normalized / "2026-09-01.json", self.activity_payload("2026-09-01", 1000.7))
            self.write_json(
                normalized / "2026-09-02.json",
                self.activity_payload(
                    "2026-09-02",
                    2000,
                    workouts=[
                        {
                            "id": "workout-1",
                            "name": "户外 步行",
                            "start": "2026-09-02T21:00:00+08:00",
                            "end": "2026-09-02T21:30:00+08:00",
                            "duration_seconds": 1800,
                            "distance": {"value": 2.0, "unit": "km"},
                            "active_energy": {"value": 80.0, "unit": "kcal"},
                            "heart_rate": {},
                            "detail_file": "details.json",
                        }
                    ],
                ),
            )

            aggregate = build_week_aggregate(
                week_label="Week 01",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 3),
                normalized_dir=normalized,
            )

        self.assertEqual(aggregate["schema_version"], "activity.weekly.v1")
        self.assertEqual(aggregate["source"]["missing_dates"], ["2026-09-03"])
        self.assertEqual(aggregate["statistics"]["observed_days"], 2)
        self.assertEqual(aggregate["statistics"]["missing_days"], 1)
        self.assertEqual(aggregate["days"][0]["steps"]["count"], 1000.7)
        self.assertEqual(aggregate["days"][0]["steps"]["display_count"], 1001)
        self.assertEqual(aggregate["statistics"]["total_steps"], 3000.7)
        self.assertEqual(aggregate["statistics"]["total_steps_display"], 3001)
        self.assertEqual(aggregate["statistics"]["max_steps"]["date"], "2026-09-02")
        self.assertEqual(aggregate["statistics"]["min_steps"]["date"], "2026-09-01")
        self.assertEqual(aggregate["statistics"]["workout_count"], 1)
        self.assertEqual(aggregate["workouts"][0]["id"], "workout-1")

    def test_write_activity_weekly_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            aggregate = {
                "week": {
                    "label": "Week 01",
                    "week_start": "2026-08-30",
                    "week_end": "2026-09-05",
                }
            }

            path = write_week_aggregate(aggregate, output_dir=tmp_path)

        self.assertEqual(path.name, "week-01_2026-08-30_2026-09-05.json")

    def test_completeness_report_detects_presence_workouts_and_notion_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sleep_dir = tmp_path / "sleep"
            activity_dir = tmp_path / "activity"
            sleep_aggregate_dir = tmp_path / "sleep-aggregate"
            activity_aggregate_dir = tmp_path / "activity-aggregate"
            self.write_json(
                sleep_dir / "2026-09-01.json",
                self.sleep_payload("2026-09-01", naps=[self.nap_session("2026-09-01")]),
            )
            self.write_json(
                activity_dir / "2026-09-01.json",
                self.activity_payload(
                    "2026-09-01",
                    1200,
                    workouts=[{"id": "workout-1", "name": "步行", "start": "s", "end": "e"}],
                ),
            )
            self.write_json(
                sleep_aggregate_dir / "week-01_2026-09-01_2026-09-02.json",
                {
                    "schema_version": "sleep.weekly.v1",
                    "source": {"missing_dates": ["2026-09-02"]},
                    "days": [{"date": "2026-09-01"}],
                },
            )
            self.write_json(
                activity_aggregate_dir / "week-01_2026-09-01_2026-09-02.json",
                {
                    "schema_version": "activity.weekly.v1",
                    "source": {"missing_dates": []},
                    "days": [{"date": "2026-09-01"}, {"date": "2026-09-02"}],
                },
            )

            report = build_report(
                week_label="Week 01",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 2),
                normalized_sleep_dir=sleep_dir,
                normalized_activity_dir=activity_dir,
                sleep_aggregate_dir=sleep_aggregate_dir,
                activity_aggregate_dir=activity_aggregate_dir,
                notion_daily_records={
                    "2026-09-01": {"sleep_section_text": "- 小睡：无。"},
                },
            )

        self.assertEqual(report["schema_version"], "railife.week_completeness.v1")
        self.assertEqual(report["sleep"]["observed_days"], 1)
        self.assertEqual(report["activity"]["observed_days"], 1)
        self.assertEqual(report["activity"]["workout_days"][0]["date"], "2026-09-01")
        self.assertTrue(any(issue["kind"] == "sleep_nap_conflict" for issue in report["issues"]))
        self.assertTrue(report["sleep"]["aggregate"]["issues"])

    def test_write_completeness_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = {
                "week": {
                    "label": "Week 01",
                    "week_start": "2026-08-30",
                    "week_end": "2026-09-05",
                }
            }

            path = write_report(report, output_dir=tmp_path)

        self.assertEqual(path.name, "week-01_2026-08-30_2026-09-05_completeness.json")


if __name__ == "__main__":
    unittest.main()
