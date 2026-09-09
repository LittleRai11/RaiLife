from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from railife.pipelines.aggregate_sleep_week import build_week_aggregate, write_week_aggregate
from railife.parsers.apple_health_sleep import parse_sleep_line
from railife.pipelines.normalize_sleep import group_sessions, normalize_samples, parse_sleep_file, process_file


SOURCE_FILE = Path("data/raw/apple_health/sleep/2026-08-31__80b449042b80.txt")
NEW_SOURCE_FILE = (
    Path.home()
    / "Library/Mobile Documents/com~apple~CloudDocs/RaiHealth/sleep/2026-08-31_10-29-59.txt"
)


class SleepPipelineTests(unittest.TestCase):
    def write_sleep_export(self, directory: Path, name: str, lines: list[str]) -> Path:
        path = directory / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def read_daily(self, normalized_dir: Path, daily_date: str) -> dict:
        return json.loads((normalized_dir / f"{daily_date}.json").read_text(encoding="utf-8"))

    def all_samples(self, payload: dict) -> list[dict]:
        return [
            sample
            for session in payload["sessions"]
            for sample in session["samples"]
        ]

    def test_parser_accepts_current_three_field_format(self) -> None:
        sample = parse_sleep_line(
            "Core | 30 Aug 2026 at 05:58 | 30 Aug 2026 at 06:13",
            line_number=1,
            source_file="sample.txt",
            timezone=ZoneInfo("Asia/Shanghai"),
        )

        self.assertIsNone(sample.source)
        self.assertEqual(sample.state, "Core")
        self.assertEqual(sample.duration_minutes, 15)
        self.assertEqual(sample.start.isoformat(), "2026-08-30T05:58:00+08:00")

    def test_parser_accepts_full_width_pipe_prefix(self) -> None:
        sample = parse_sleep_line(
            "｜Core | 30 Aug 2026 at 05:58 | 30 Aug 2026 at 06:13",
            line_number=1,
            source_file="sample.txt",
            timezone=ZoneInfo("Asia/Shanghai"),
        )

        self.assertIsNone(sample.source)
        self.assertEqual(sample.state, "Core")
        self.assertEqual(sample.raw_line, "｜Core | 30 Aug 2026 at 05:58 | 30 Aug 2026 at 06:13")

    def test_parser_accepts_future_four_field_format(self) -> None:
        sample = parse_sleep_line(
            "Apple Watch | REM | 30 Aug 2026 at 07:32 | 30 Aug 2026 at 07:49",
            line_number=1,
            source_file="sample.txt",
            timezone=ZoneInfo("Asia/Shanghai"),
        )

        self.assertEqual(sample.source, "Apple Watch")
        self.assertEqual(sample.state, "REM")
        self.assertEqual(sample.duration_minutes, 17)

    def test_parse_sleep_file_skips_zero_duration_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_sleep_export(
                Path(tmp),
                "zero-duration.txt",
                [
                    "Core | 2 Sep 2026 at 06:09 | 2 Sep 2026 at 06:09",
                    "Deep | 2 Sep 2026 at 06:09 | 2 Sep 2026 at 06:10",
                ],
            )

            samples = parse_sleep_file(path, timezone_name="Asia/Shanghai")

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].state, "Deep")
        self.assertEqual(samples[0].duration_minutes, 1)

    @unittest.skipUnless(SOURCE_FILE.exists(), "Apple Health source fixture is not available")
    def test_existing_source_groups_expected_sessions(self) -> None:
        samples = parse_sleep_file(SOURCE_FILE, timezone_name="Asia/Shanghai")
        grouped = group_sessions(samples, session_gap_minutes=90)
        normalized = normalize_samples(
            samples,
            source_file=SOURCE_FILE.name,
            source_sha256="test",
            raw_snapshot=Path("data/raw/apple_health/sleep/test.txt"),
            timezone_name="Asia/Shanghai",
            session_gap_minutes=90,
        )

        self.assertEqual(len(samples), 37)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(normalized["schema_version"], "sleep.daily.v1")
        self.assertEqual(normalized["date"], "2026-08-30")
        self.assertEqual(normalized["source"]["timezone_assumption"], "Asia/Shanghai")
        self.assertEqual(normalized["source"]["session_gap_minutes"], 90)

        main, nap = normalized["sessions"]
        self.assertEqual(main["kind"], "main")
        self.assertEqual(main["start"], "2026-08-30T05:58:00+08:00")
        self.assertEqual(main["end"], "2026-08-30T13:24:00+08:00")
        self.assertEqual(
            main["duration_minutes"],
            {
                "asleep_total": 408,
                "asleep_unspecified": 0,
                "awake": 38,
                "core": 236,
                "deep": 70,
                "elapsed": 446,
                "rem": 102,
            },
        )

        self.assertEqual(nap["kind"], "nap")
        self.assertEqual(nap["start"], "2026-08-30T18:30:00+08:00")
        self.assertEqual(nap["end"], "2026-08-30T20:00:00+08:00")
        self.assertEqual(
            nap["duration_minutes"],
            {
                "asleep_total": 81,
                "asleep_unspecified": 81,
                "awake": 9,
                "core": None,
                "deep": None,
                "elapsed": 90,
                "rem": None,
            },
        )

    @unittest.skipUnless(SOURCE_FILE.exists(), "Apple Health source fixture is not available")
    def test_process_file_copies_snapshot_and_writes_normalized_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_copy = tmp_path / "2026-08-31.txt"
            shutil.copy2(SOURCE_FILE, source_copy)

            output_paths = process_file(
                source_copy,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=tmp_path / "normalized",
            )
            self.assertEqual(len(output_paths), 1)
            output_path = output_paths[0]
            payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(output_path.name, "2026-08-30.json")
            self.assertEqual(payload["source"]["source_file"], "2026-08-31.txt")
            self.assertEqual(len(payload["sessions"]), 2)
            self.assertTrue(all("samples" in session for session in payload["sessions"]))

            snapshot_path = Path(payload["source"]["raw_snapshot"])
            self.assertEqual(snapshot_path.parent, tmp_path / "raw")
            self.assertTrue(snapshot_path.exists())

    def test_fully_overlapping_snapshot_does_not_rewrite_daily_json(self) -> None:
        lines = [
            "Core | 30 Aug 2026 at 22:00 | 30 Aug 2026 at 23:00",
            "REM | 30 Aug 2026 at 23:00 | 31 Aug 2026 at 00:00",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = self.write_sleep_export(tmp_path, "first.txt", lines)
            normalized_dir = tmp_path / "normalized"

            first_outputs = process_file(
                source,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )
            before = (normalized_dir / "2026-08-31.json").read_text(encoding="utf-8")

            second_outputs = process_file(
                source,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )
            after = (normalized_dir / "2026-08-31.json").read_text(encoding="utf-8")

        self.assertEqual([path.name for path in first_outputs], ["2026-08-31.json"])
        self.assertEqual(second_outputs, [])
        self.assertEqual(after, before)

    def test_partially_overlapping_snapshot_merges_without_double_counting(self) -> None:
        first_lines = [
            "Core | 30 Aug 2026 at 22:00 | 30 Aug 2026 at 23:00",
        ]
        second_lines = [
            "Core | 30 Aug 2026 at 22:00 | 30 Aug 2026 at 23:00",
            "REM | 30 Aug 2026 at 23:00 | 31 Aug 2026 at 00:00",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            normalized_dir = tmp_path / "normalized"
            first = self.write_sleep_export(tmp_path, "first.txt", first_lines)
            second = self.write_sleep_export(tmp_path, "second.txt", second_lines)

            process_file(
                first,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )
            process_file(
                second,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )
            payload = self.read_daily(normalized_dir, "2026-08-31")

        self.assertEqual(len(self.all_samples(payload)), 2)
        self.assertEqual(payload["sessions"][0]["duration_minutes"]["asleep_total"], 120)

    def test_snapshot_with_two_dates_writes_one_canonical_file_per_date(self) -> None:
        lines = [
            "Core | 30 Aug 2026 at 21:00 | 30 Aug 2026 at 22:00",
            "REM | 30 Aug 2026 at 22:00 | 30 Aug 2026 at 23:00",
            "Core | 31 Aug 2026 at 10:00 | 31 Aug 2026 at 11:00",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = self.write_sleep_export(tmp_path, "rolling.txt", lines)
            normalized_dir = tmp_path / "normalized"

            output_paths = process_file(
                source,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )

        self.assertEqual([path.name for path in output_paths], ["2026-08-30.json", "2026-08-31.json"])

    def test_main_sleep_classification_happens_after_date_partitioning(self) -> None:
        lines = [
            "Core | 30 Aug 2026 at 05:00 | 30 Aug 2026 at 10:00",
            "Core | 31 Aug 2026 at 04:20 | 31 Aug 2026 at 09:42",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = self.write_sleep_export(tmp_path, "two-days.txt", lines)
            normalized_dir = tmp_path / "normalized"

            process_file(
                source,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )
            aug31 = self.read_daily(normalized_dir, "2026-08-31")

        self.assertEqual(len(aug31["sessions"]), 1)
        self.assertEqual(aug31["sessions"][0]["kind"], "main")
        self.assertEqual(aug31["sessions"][0]["start"], "2026-08-31T04:20:00+08:00")
        self.assertEqual(aug31["sessions"][0]["end"], "2026-08-31T09:42:00+08:00")

    def test_duplicate_samples_with_empty_or_missing_source_dedupe(self) -> None:
        lines = [
            "Core | 30 Aug 2026 at 22:00 | 30 Aug 2026 at 23:00",
            " | Core | 30 Aug 2026 at 22:00 | 30 Aug 2026 at 23:00",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = self.write_sleep_export(tmp_path, "duplicates.txt", lines)
            normalized_dir = tmp_path / "normalized"

            process_file(
                source,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )
            payload = self.read_daily(normalized_dir, "2026-08-30")

        self.assertEqual(len(self.all_samples(payload)), 1)
        self.assertEqual(payload["sessions"][0]["duration_minutes"]["asleep_total"], 60)

    @unittest.skipUnless(NEW_SOURCE_FILE.exists(), "New Apple Health source snapshot is not available")
    def test_new_rolling_snapshot_preserves_existing_aug30_canonical_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            normalized_dir = tmp_path / "normalized"
            normalized_dir.mkdir()
            shutil.copy2(Path("data/normalized/sleep/2026-08-30.json"), normalized_dir / "2026-08-30.json")
            before = (normalized_dir / "2026-08-30.json").read_text(encoding="utf-8")

            output_paths = process_file(
                NEW_SOURCE_FILE,
                timezone_name="Asia/Shanghai",
                session_gap_minutes=90,
                raw_dir=tmp_path / "raw",
                manifest_path=tmp_path / "manifest.json",
                normalized_dir=normalized_dir,
            )
            after = (normalized_dir / "2026-08-30.json").read_text(encoding="utf-8")
            aug31 = self.read_daily(normalized_dir, "2026-08-31")

        self.assertEqual(after, before)
        self.assertEqual([path.name for path in output_paths], ["2026-08-31.json"])
        self.assertEqual(aug31["sessions"][0]["kind"], "main")
        self.assertEqual(aug31["sessions"][0]["start"], "2026-08-31T04:20:00+08:00")
        self.assertEqual(aug31["sessions"][0]["end"], "2026-08-31T09:42:00+08:00")
        self.assertEqual(aug31["sessions"][0]["duration_minutes"]["asleep_total"], 317)
        self.assertEqual(aug31["sessions"][0]["duration_minutes"]["awake"], 5)

    @unittest.skipUnless(SOURCE_FILE.exists(), "Apple Health source fixture is not available")
    def test_weekly_aggregate_preserves_daily_chart_ready_values(self) -> None:
        samples = parse_sleep_file(SOURCE_FILE, timezone_name="Asia/Shanghai")
        normalized = normalize_samples(
            samples,
            source_file=SOURCE_FILE.name,
            source_sha256="test",
            raw_snapshot=Path("data/raw/apple_health/sleep/test.txt"),
            timezone_name="Asia/Shanghai",
            session_gap_minutes=90,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            normalized_dir = tmp_path / "normalized"
            normalized_dir.mkdir()
            (normalized_dir / "2026-08-30.json").write_text(
                json.dumps(normalized), encoding="utf-8"
            )

            aggregate = build_week_aggregate(
                week_label="Week 01",
                start_date=date(2026, 8, 30),
                end_date=date(2026, 9, 5),
                normalized_dir=normalized_dir,
            )

        self.assertEqual(aggregate["schema_version"], "sleep.weekly.v1")
        self.assertEqual(aggregate["week"]["week_start"], "Sunday")
        self.assertEqual(aggregate["source"]["missing_dates"], [
            "2026-08-31",
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
            "2026-09-04",
            "2026-09-05",
        ])
        self.assertEqual(len(aggregate["days"]), 1)

        day_payload = aggregate["days"][0]
        self.assertEqual(day_payload["date"], "2026-08-30")
        self.assertEqual(day_payload["weekday"], "Sunday")
        self.assertEqual(day_payload["main_sleep"]["asleep_total_minutes"], 408)
        self.assertEqual(day_payload["main_sleep"]["stages_minutes"]["core"], 236)
        self.assertEqual(len(day_payload["naps"]), 1)
        self.assertIsNone(day_payload["naps"][0]["stages_minutes"]["core"])
        self.assertIsNone(day_payload["naps"][0]["stages_minutes"]["deep"])
        self.assertIsNone(day_payload["naps"][0]["stages_minutes"]["rem"])
        self.assertEqual(day_payload["naps"][0]["stages_minutes"]["asleep_unspecified"], 81)
        self.assertEqual(day_payload["totals"]["all_sleep_asleep_minutes"], 489)
        self.assertEqual(day_payload["totals"]["main_sleep_asleep_minutes"], 408)
        self.assertEqual(day_payload["totals"]["nap_asleep_minutes"], 81)
        self.assertEqual(len(day_payload["timeline_segments"]), 37)
        self.assertEqual(day_payload["timeline_segments"][0], {
            "kind": "main",
            "state": "Core",
            "start": "2026-08-30T05:58:00+08:00",
            "end": "2026-08-30T06:13:00+08:00",
            "duration_minutes": 15,
        })

        self.assertEqual(aggregate["statistics"]["observed_days"], 1)
        self.assertEqual(aggregate["statistics"]["missing_days"], 6)
        self.assertEqual(aggregate["statistics"]["main_sleep_asleep_minutes"], {
            "mean": 408,
            "min": 408,
            "max": 408,
        })
        self.assertEqual(aggregate["statistics"]["all_sleep_asleep_minutes"], {
            "mean": 489,
            "min": 489,
            "max": 489,
        })
        self.assertEqual(aggregate["statistics"]["nap_count"], 1)
        self.assertEqual(aggregate["statistics"]["nap_asleep_minutes_total"], 81)

    def test_weekly_aggregate_missing_week_has_null_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            aggregate = build_week_aggregate(
                week_label="Week 02",
                start_date=date(2026, 9, 6),
                end_date=date(2026, 9, 12),
                normalized_dir=Path(tmp),
            )
            output_path = write_week_aggregate(aggregate, output_dir=Path(tmp) / "out")

        self.assertEqual(aggregate["days"], [])
        self.assertEqual(aggregate["statistics"]["observed_days"], 0)
        self.assertEqual(aggregate["statistics"]["missing_days"], 7)
        self.assertEqual(aggregate["statistics"]["main_sleep_asleep_minutes"], {
            "mean": None,
            "min": None,
            "max": None,
        })
        self.assertEqual(output_path.name, "week-02_2026-09-06_2026-09-12.json")


if __name__ == "__main__":
    unittest.main()
