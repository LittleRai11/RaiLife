from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from railife.pipelines.extract_week_notes import (
    build_notes,
    classify_study_record,
    extract_piano_entry,
    extract_sections,
    parse_intervals,
    render_markdown,
    write_outputs,
)


class ExtractWeekNotesTests(unittest.TestCase):
    def test_extract_sections_records_empty_blocks_as_empty(self) -> None:
        content = "\n".join(
            [
                "# 学习 / Study",
                "<empty-block/>",
                "# 今日记录 / Daily Log",
                "今天15:30出门。",
                "# 练琴 / Piano",
                "9\\:30-11\\:00",
                "# 心情 / Mood",
                "-",
                "# 留给老师 / For You",
                "<empty-block/>",
                "# 边角料 / Bits & Pieces",
                "太困了……",
            ]
        )

        sections = extract_sections(content)

        self.assertEqual(sections["study"], "")
        self.assertEqual(sections["daily_log"], "今天15:30出门。")
        self.assertEqual(sections["for_you"], "")

    def test_parse_intervals_handles_notion_escaped_times_and_hour_ranges(self) -> None:
        self.assertEqual(
            parse_intervals("9:00-10:00，11\\:30-12\\:45，20-22上课"),
            [
                {"start": "09:00", "end": "10:00", "duration_minutes": 60},
                {"start": "11:30", "end": "12:45", "duration_minutes": 75},
                {"start": "20:00", "end": "22:00", "duration_minutes": 120},
            ],
        )

    def test_parse_intervals_handles_subject_between_times_and_lian_dao(self) -> None:
        self.assertEqual(
            parse_intervals("17\\:30背中国音乐史-19\\:10。19\\:00下课耶耶耶我练到21\\:20"),
            [
                {"start": "17:30", "end": "19:10", "duration_minutes": 100},
                {"start": "19:00", "end": "21:20", "duration_minutes": 140},
            ],
        )

    def test_classify_study_record_types(self) -> None:
        self.assertEqual(classify_study_record("14:00-15:00 音乐史")["type"], "explicit_interval")
        self.assertEqual(classify_study_record("做了一个小时英语")["type"], "explicit_duration")
        self.assertEqual(classify_study_record("上午写了一点英语作业")["type"], "vague_duration")
        self.assertEqual(classify_study_record("下午上了英语课…")["type"], "course_or_class")
        self.assertEqual(classify_study_record("20-22上课")["type"], "course_or_class")
        self.assertEqual(classify_study_record("0学习……")["type"], "unknown")

    def test_build_notes_override_can_force_unclear_subject_to_null(self) -> None:
        notes = build_notes(
            week_label="Week 01",
            start_date=date(2026, 8, 30),
            end_date=date(2026, 9, 5),
            daily_records=[
                {
                    "date": "2026-09-01",
                    "sections": {
                        "study": "",
                        "piano": "",
                        "mood": "",
                        "daily_log": "",
                        "for_you": "",
                        "bits": "",
                    },
                    "study_entry_overrides": [
                        {"text": "我的政治和音乐史感觉要来不及背了。", "subject": None},
                    ],
                }
            ],
        )

        self.assertIsNone(notes["days"][0]["study_entries"][0]["subject"])

    def test_piano_breaks_preserve_recorded_span_but_not_net_duration(self) -> None:
        entry = extract_piano_entry("17\\:45-21\\:30 中间有小休息了一下，今天把琴盖打开了。左手手腕还是不太行，就一直在慢练。")

        self.assertEqual(entry["recorded_span_minutes"], 225)
        self.assertTrue(entry["has_breaks"])
        self.assertIsNone(entry["net_duration_minutes"])
        self.assertIn("左手手腕还是不太行，就一直在慢练。", entry["technique_observations"])
        self.assertIn("左手手腕还是不太行，就一直在慢练。", entry["physical_observations"])

    def test_build_notes_counts_entries_and_manual_confirmation_items(self) -> None:
        notes = build_notes(
            week_label="Week 01",
            start_date=date(2026, 8, 30),
            end_date=date(2026, 9, 5),
            daily_records=[
                {
                    "date": "2026-09-04",
                    "sections": {
                        "study": "8\\:00-10\\:00断断续续在飞机上背掉了西音史的部分，效率好低哦\n14\\:20-15\\:30改和声",
                        "piano": "17\\:45-21\\:30 中间有小休息了一下",
                        "mood": "平静。",
                        "daily_log": "",
                        "for_you": "",
                        "bits": "",
                    },
                    "study_entry_overrides": [
                        {"text": "8\\:00-10\\:00断断续续在飞机上背掉了西音史的部分，效率好低哦", "subject": "西方音乐史"},
                        {"text": "14\\:20-15\\:30改和声", "subject": "和声"},
                    ],
                }
            ],
        )

        self.assertEqual(notes["schema_version"], "week.notes.review.v1")
        self.assertEqual(notes["counts"]["study"]["explicit_interval"], 2)
        self.assertEqual(notes["counts"]["piano"]["explicit_intervals"], 1)
        self.assertEqual(notes["counts"]["piano"]["entries_with_breaks_or_unclear_net_duration"], 1)
        self.assertTrue(notes["manual_confirmation_items"])

    def test_render_and_write_outputs(self) -> None:
        notes = build_notes(
            week_label="Week 01",
            start_date=date(2026, 8, 30),
            end_date=date(2026, 9, 5),
            daily_records=[
                {
                    "date": "2026-09-05",
                    "sections": {
                        "study": "",
                        "piano": "9\\:30-11\\:00",
                        "mood": "",
                        "daily_log": "",
                        "for_you": "",
                        "bits": "",
                    },
                }
            ],
        )
        markdown = render_markdown(notes)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_outputs(notes, output_dir=Path(tmp))

        self.assertIn("## 2026-09-05", markdown)
        self.assertEqual(json_path.name, "week-01_2026-08-30_2026-09-05_notes.json")
        self.assertEqual(md_path.name, "week-01_2026-08-30_2026-09-05_notes.md")


if __name__ == "__main__":
    unittest.main()
