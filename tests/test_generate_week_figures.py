from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from railife.pipelines.generate_week_figures import (
    build_figures,
    map_sleep_time,
    render_sleep_duration_svg,
    render_steps_svg,
    render_study_svg,
    sleep_duration_data,
    sleep_timing_data,
    steps_data,
    study_subject_data,
)


def sample_sleep_week() -> dict:
    return {
        "days": [
            {
                "date": "2026-08-30",
                "main_sleep": {"asleep_total_minutes": 408, "elapsed_minutes": 446, "start": "2026-08-30T05:58:00+08:00", "end": "2026-08-30T13:24:00+08:00"},
                "naps": [{"asleep_total_minutes": 81, "elapsed_minutes": 90}],
            },
            {
                "date": "2026-08-31",
                "main_sleep": {"asleep_total_minutes": 317, "elapsed_minutes": 330, "start": "2026-08-31T04:20:00+08:00", "end": "2026-08-31T09:42:00+08:00"},
                "naps": [],
            },
            {
                "date": "2026-09-01",
                "main_sleep": {"asleep_total_minutes": 496, "elapsed_minutes": 502, "start": "2026-08-31T23:36:00+08:00", "end": "2026-09-01T07:58:00+08:00"},
                "naps": [],
            },
            {
                "date": "2026-09-02",
                "main_sleep": {"asleep_total_minutes": 350, "elapsed_minutes": 357, "start": "2026-09-02T02:21:00+08:00", "end": "2026-09-02T08:18:00+08:00"},
                "naps": [],
            },
            {
                "date": "2026-09-03",
                "main_sleep": {"asleep_total_minutes": 300, "elapsed_minutes": 301, "start": "2026-09-03T03:17:00+08:00", "end": "2026-09-03T08:18:00+08:00"},
                "naps": [],
            },
            {
                "date": "2026-09-04",
                "main_sleep": {"asleep_total_minutes": 245, "elapsed_minutes": 245, "start": "2026-09-04T01:02:00+08:00", "end": "2026-09-04T05:07:00+08:00"},
                "naps": [{"asleep_total_minutes": 187, "elapsed_minutes": 201}],
            },
            {
                "date": "2026-09-05",
                "main_sleep": {"asleep_total_minutes": 427, "elapsed_minutes": 428, "start": "2026-09-05T01:20:00+08:00", "end": "2026-09-05T08:27:00+08:00"},
                "naps": [],
            },
        ]
    }


def sample_activity_week() -> dict:
    return {
        "days": [
            {"date": "2026-08-30", "steps": {"count": 4502, "display_count": 4502}, "workout_count": 0},
            {"date": "2026-08-31", "steps": {"count": 4381.2, "display_count": 4381}, "workout_count": 0},
            {"date": "2026-09-01", "steps": {"count": 6105, "display_count": 6105}, "workout_count": 0},
            {"date": "2026-09-02", "steps": {"count": 3536.7, "display_count": 3537}, "workout_count": 0},
            {"date": "2026-09-03", "steps": {"count": 11003, "display_count": 11003}, "workout_count": 1},
            {"date": "2026-09-04", "steps": {"count": 3228.4, "display_count": 3228}, "workout_count": 0},
            {"date": "2026-09-05", "steps": {"count": 6838, "display_count": 6838}, "workout_count": 0},
        ],
        "workouts": [],
    }


class GenerateWeekFiguresTests(unittest.TestCase):
    def test_sleep_duration_uses_asleep_minutes_and_preserves_naps(self) -> None:
        rows = sleep_duration_data(sample_sleep_week())

        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0]["main_minutes"], 408)
        self.assertEqual(rows[0]["nap_minutes"], 81)
        self.assertNotEqual(rows[0]["main_minutes"], 446)
        self.assertEqual(rows[5]["nap_minutes"], 187)

    def test_sleep_timing_maps_cross_midnight_to_evening_next_day_axis(self) -> None:
        rows = sleep_timing_data(sample_sleep_week())

        self.assertEqual(len(rows), 7)
        self.assertAlmostEqual(map_sleep_time("2026-08-31T23:36:00+08:00"), 23.6)
        self.assertGreater(rows[2]["end_mapped_hour"], 24)
        self.assertAlmostEqual(rows[0]["start_mapped_hour"], 29 + 58 / 60)

    def test_steps_use_activity_weekly_display_values(self) -> None:
        rows = steps_data(sample_activity_week())

        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[4]["steps"], 11003)
        self.assertEqual(rows[3]["steps"], 3537)
        self.assertEqual(rows[6]["steps"], 6838)
        self.assertEqual(rows[4]["workout_count"], 1)

    def test_study_subject_data_only_uses_confirmed_self_study(self) -> None:
        draft = {
            "study": {
                "confirmed_study_minutes_by_subject": {"中国音乐史": 190, "和声": 180, "英语": 135, "音乐史": 130, "曲式": 20},
                "class_minutes_by_subject": {"曲式": 120, "unknown": 120},
                "recorded_but_uncertain_minutes": 120,
            }
        }

        rows = study_subject_data(draft)

        self.assertEqual([row["subject"] for row in rows], ["中国音乐史", "和声", "英语", "音乐史", "曲式"])
        self.assertEqual(sum(row["minutes"] for row in rows), 655)
        self.assertNotIn("unknown", {row["subject"] for row in rows})

    def test_build_figures_writes_svg_manifest_without_png_for_tests(self) -> None:
        draft = {
            "study": {"confirmed_study_minutes_by_subject": {"英语": 60}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_figures(sample_sleep_week(), sample_activity_week(), draft, output_dir=Path(tmp), convert_png=False)
            files = sorted(path.name for path in Path(tmp).iterdir())

        self.assertEqual(len(manifest["figures"]), 4)
        self.assertIn("figure_manifest.json", files)
        self.assertIn("fig01_sleep_duration.svg", files)
        self.assertIn("fig04_study_by_subject.svg", files)

    def test_svg_titles_are_caption_ready_without_figure_numbers_or_technical_subtitles(self) -> None:
        sleep_svg = render_sleep_duration_svg(sleep_duration_data(sample_sleep_week()))
        steps_svg = render_steps_svg(steps_data(sample_activity_week()))
        study_svg = render_study_svg(study_subject_data({"study": {"confirmed_study_minutes_by_subject": {"音乐史": 440}}}))

        combined = "\n".join([sleep_svg, steps_svg, study_svg])
        self.assertNotIn("Figure 1.", combined)
        self.assertNotIn("Rounded presentation values", combined)
        self.assertNotIn("Class time and uncertain spans excluded", combined)
        self.assertNotIn(">workout<", steps_svg)
        self.assertIn("Daily Sleep Duration", sleep_svg)
        self.assertIn("Daily Steps", steps_svg)


if __name__ == "__main__":
    unittest.main()
