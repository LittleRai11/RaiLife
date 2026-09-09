from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from railife.models.activity import KJ_PER_KCAL
from railife.parsers.health_auto_export_activity import parse_step_file, parse_workout_file
from railife.pipelines.normalize_activity import ActivityConflictError, run_pipeline


class ActivityPipelineTests(unittest.TestCase):
    def write_json(self, directory: Path, name: str, payload: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def step_payload(self, count: int = 11003) -> dict:
        return {
            "data": {
                "metrics": [
                    {
                        "name": "step_count",
                        "units": "count",
                        "data": [
                            {
                                "source": "Waai的Apple Watch|Rai’s iPhone",
                                "date": "2026-09-03 00:00:00 +0800",
                                "qty": count,
                            }
                        ],
                    }
                ]
            }
        }

    def workout_payload(self, *, workout_id: str = "workout-1", energy_kj: float = 365.664783909473) -> dict:
        return {
            "data": {
                "metrics": [],
                "workouts": [
                    {
                        "id": workout_id,
                        "name": "户外 步行",
                        "start": "2026-09-03 21:03:57 +0800",
                        "end": "2026-09-03 21:46:37 +0800",
                        "duration": 2560.569578051567,
                        "location": "户外",
                        "isIndoor": False,
                        "distance": {"units": "km", "qty": 2.2105575045167933},
                        "activeEnergyBurned": {"qty": energy_kj, "units": "kJ"},
                        "totalEnergy": {"qty": 524.347167909473, "units": "kJ"},
                        "heartRate": {
                            "avg": {"units": "bpm", "qty": 134.38439023098113},
                            "min": {"qty": 117, "units": "bpm"},
                            "max": {"qty": 148, "units": "bpm"},
                        },
                        "heartRateData": [
                            {
                                "Min": 126,
                                "date": "2026-09-03 21:03:00 +0800",
                                "Max": 126,
                                "units": "bpm",
                                "Avg": 126,
                            }
                        ],
                        "heartRateRecovery": [],
                        "activeEnergy": [
                            {
                                "qty": 8.249635281597364,
                                "date": "2026-09-03 21:03:57 +0800",
                                "source": "Waai的Apple Watch",
                                "units": "kJ",
                            }
                        ],
                        "basalEnergy": [],
                        "stepCount": [
                            {
                                "qty": 18.862874192596582,
                                "source": "Rai’s iPhone",
                                "date": "2026-09-03 21:09:57 +0800",
                                "units": "步",
                            }
                        ],
                        "walkingAndRunningDistance": [],
                    }
                ],
            }
        }

    def test_step_parser_uses_daily_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = self.write_json(tmp_path, "steps.json", self.step_payload())
            steps = parse_step_file(source, raw_snapshot=source, source_sha256="hash")

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].date, "2026-09-03")
        self.assertEqual(steps[0].count, 11003)
        self.assertEqual(steps[0].unit, "count")

    def test_workout_parser_extracts_summary_and_energy_kcal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = self.write_json(tmp_path, "workout.json", self.workout_payload())
            parsed = parse_workout_file(
                source,
                raw_snapshot=source,
                source_sha256="hash",
                detail_dir=tmp_path / "details",
            )

        workout, _ = parsed[0]
        self.assertEqual(workout.local_date, "2026-09-03")
        self.assertEqual(workout.id, "workout-1")
        self.assertEqual(workout.duration_seconds, 2560.569578051567)
        self.assertAlmostEqual(workout.active_energy["value"], 365.664783909473 / KJ_PER_KCAL)
        self.assertEqual(workout.active_energy["source_unit"], "kJ")
        self.assertEqual(workout.heart_rate["minimum"], {"value": 117, "unit": "bpm"})

    def test_pipeline_writes_daily_and_detail_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            step_dir = tmp_path / "step"
            workout_dir = tmp_path / "workout"
            step_dir.mkdir()
            workout_dir.mkdir()
            self.write_json(step_dir, "steps.json", self.step_payload())
            self.write_json(workout_dir, "workout.json", self.workout_payload())

            outputs = run_pipeline(
                step_source_dir=step_dir,
                workout_source_dir=workout_dir,
                raw_step_dir=tmp_path / "raw-step",
                raw_workout_dir=tmp_path / "raw-workout",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=tmp_path / "normalized",
                workout_detail_dir=tmp_path / "normalized" / "workout_details",
            )

            daily_path = tmp_path / "normalized" / "2026-09-03.json"
            detail_path = tmp_path / "normalized" / "workout_details" / "2026-09-03" / "workout-1.json"
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
            manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(sorted(path.name for path in outputs), ["2026-09-03.json", "workout-1.json"])
        self.assertEqual(daily["schema_version"], "activity.daily.v1")
        self.assertEqual(daily["steps"]["count"], 11003)
        self.assertEqual(len(daily["workouts"]), 1)
        self.assertEqual(daily["workouts"][0]["detail_file"], str(detail_path))
        self.assertEqual(detail["schema_version"], "activity.workout_detail.v1")
        self.assertEqual(len(detail["series"]["heartRateData"]), 1)
        self.assertEqual(detail["series"]["heartRateData"][0]["average"], 126)
        self.assertEqual({entry["type"] for entry in manifest}, {"step", "workout"})

    def test_rerun_identical_sources_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            step_dir = tmp_path / "step"
            workout_dir = tmp_path / "workout"
            step_dir.mkdir()
            workout_dir.mkdir()
            self.write_json(step_dir, "steps.json", self.step_payload())
            self.write_json(workout_dir, "workout.json", self.workout_payload())
            kwargs = {
                "step_source_dir": step_dir,
                "workout_source_dir": workout_dir,
                "raw_step_dir": tmp_path / "raw-step",
                "raw_workout_dir": tmp_path / "raw-workout",
                "manifest_path": tmp_path / "manifest.json",
                "normalized_dir": tmp_path / "normalized",
                "workout_detail_dir": tmp_path / "normalized" / "workout_details",
            }

            first = run_pipeline(**kwargs)
            daily_before = (tmp_path / "normalized" / "2026-09-03.json").read_text(encoding="utf-8")
            manifest_before = (tmp_path / "manifest.json").read_text(encoding="utf-8")
            second = run_pipeline(**kwargs)
            daily_after = (tmp_path / "normalized" / "2026-09-03.json").read_text(encoding="utf-8")
            manifest_after = (tmp_path / "manifest.json").read_text(encoding="utf-8")

        self.assertTrue(first)
        self.assertEqual(second, [])
        self.assertEqual(daily_after, daily_before)
        self.assertEqual(manifest_after, manifest_before)

    def test_identical_step_values_from_multiple_exports_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            step_dir = tmp_path / "step"
            workout_dir = tmp_path / "workout"
            step_dir.mkdir()
            workout_dir.mkdir()
            self.write_json(step_dir, "steps-a.json", self.step_payload())
            self.write_json(step_dir, "steps-b.json", self.step_payload())

            run_pipeline(
                step_source_dir=step_dir,
                workout_source_dir=workout_dir,
                raw_step_dir=tmp_path / "raw-step",
                raw_workout_dir=tmp_path / "raw-workout",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=tmp_path / "normalized",
                workout_detail_dir=tmp_path / "normalized" / "workout_details",
            )
            daily = json.loads((tmp_path / "normalized" / "2026-09-03.json").read_text())

        self.assertEqual(daily["steps"]["count"], 11003)
        self.assertEqual(daily["workouts"], [])

    def test_conflicting_step_values_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            step_dir = tmp_path / "step"
            workout_dir = tmp_path / "workout"
            step_dir.mkdir()
            workout_dir.mkdir()
            self.write_json(step_dir, "steps-a.json", self.step_payload(11003))
            self.write_json(step_dir, "steps-b.json", self.step_payload(11004))

            with self.assertRaises(ActivityConflictError):
                run_pipeline(
                    step_source_dir=step_dir,
                    workout_source_dir=workout_dir,
                    raw_step_dir=tmp_path / "raw-step",
                    raw_workout_dir=tmp_path / "raw-workout",
                    manifest_path=tmp_path / "manifest.json",
                    normalized_dir=tmp_path / "normalized",
                    workout_detail_dir=tmp_path / "normalized" / "workout_details",
                )

    def test_conflicting_duplicate_workout_ids_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            step_dir = tmp_path / "step"
            workout_dir = tmp_path / "workout"
            step_dir.mkdir()
            workout_dir.mkdir()
            self.write_json(workout_dir, "workout-a.json", self.workout_payload(energy_kj=365))
            self.write_json(workout_dir, "workout-b.json", self.workout_payload(energy_kj=366))

            with self.assertRaises(ActivityConflictError):
                run_pipeline(
                    step_source_dir=step_dir,
                    workout_source_dir=workout_dir,
                    raw_step_dir=tmp_path / "raw-step",
                    raw_workout_dir=tmp_path / "raw-workout",
                    manifest_path=tmp_path / "manifest.json",
                    normalized_dir=tmp_path / "normalized",
                    workout_detail_dir=tmp_path / "normalized" / "workout_details",
                )

    def test_workout_without_steps_writes_nullable_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            step_dir = tmp_path / "step"
            workout_dir = tmp_path / "workout"
            step_dir.mkdir()
            workout_dir.mkdir()
            self.write_json(workout_dir, "workout.json", self.workout_payload())

            run_pipeline(
                step_source_dir=step_dir,
                workout_source_dir=workout_dir,
                raw_step_dir=tmp_path / "raw-step",
                raw_workout_dir=tmp_path / "raw-workout",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=tmp_path / "normalized",
                workout_detail_dir=tmp_path / "normalized" / "workout_details",
            )
            daily = json.loads((tmp_path / "normalized" / "2026-09-03.json").read_text())

        self.assertIsNone(daily["steps"]["count"])
        self.assertEqual(len(daily["workouts"]), 1)


if __name__ == "__main__":
    unittest.main()
