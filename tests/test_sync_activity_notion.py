from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from railife.pipelines.sync_activity_notion import (
    ACTIVITY_HEADING,
    ActivityNotionSyncError,
    exercise_section,
    format_activity_markdown,
    load_activity_payload,
    replace_activity_subsection,
    top_level_sections,
    validate_single_page_match,
)


class SyncActivityNotionTests(unittest.TestCase):
    def activity_payload(self) -> dict:
        return {
            "schema_version": "activity.daily.v1",
            "date": "2026-09-03",
            "steps": {"count": 11003},
            "workouts": [
                {
                    "id": "6D41BA1D-136A-4052-94D6-61921732057F",
                    "name": "户外 步行",
                    "start": "2026-09-03T21:03:57+08:00",
                    "end": "2026-09-03T21:46:37+08:00",
                    "duration_seconds": 2560.569578051567,
                    "distance": {"value": 2.2105575045167933, "unit": "km"},
                    "active_energy": {"value": 87.39598085790463, "unit": "kcal"},
                    "heart_rate": {
                        "average": {"value": 134.38439023098113, "unit": "bpm"},
                        "minimum": {"value": 117, "unit": "bpm"},
                        "maximum": {"value": 148, "unit": "bpm"},
                    },
                }
            ],
        }

    def page_content(self) -> str:
        return "\n".join(
            [
                "# 生活 / Life",
                "生活内容",
                "# 身体与作息 / Health & Routine",
                "## 睡眠 / Sleep",
                "- 睡眠内容",
                "# 运动 / Exercise",
                "今天从家扛着电脑走到了学校再一咬牙走到了地铁站 算是走路很多了",
                "# 练琴 / Piano",
                "练琴内容",
            ]
        )

    def test_format_activity_markdown(self) -> None:
        self.assertEqual(
            format_activity_markdown(self.activity_payload()),
            "\n".join(
                [
                    "## 活动数据 / Activity",
                    "- 步数：11,003 步",
                    "- 户外步行：21:03–21:46",
                    "\t- 时长：42分41秒",
                    "\t- 距离：2.21 km",
                    "\t- 活动消耗：87.4 kcal",
                    "\t- 平均心率：134 bpm",
                    "\t- 心率范围：117–148 bpm",
                ]
            ),
        )

    def test_format_omits_null_fields(self) -> None:
        payload = self.activity_payload()
        payload["steps"]["count"] = None
        payload["workouts"][0]["distance"]["value"] = None
        payload["workouts"][0]["heart_rate"]["minimum"]["value"] = None

        formatted = format_activity_markdown(payload)

        self.assertNotIn("步数", formatted)
        self.assertNotIn("距离", formatted)
        self.assertNotIn("心率范围", formatted)
        self.assertIn("平均心率：134 bpm", formatted)

    def test_replace_inserts_activity_inside_exercise_only(self) -> None:
        generated = format_activity_markdown(self.activity_payload())
        before = self.page_content()
        after = replace_activity_subsection(before, generated)

        self.assertEqual(top_level_sections(after), top_level_sections(before))
        self.assertIn("今天从家扛着电脑走到了学校再一咬牙走到了地铁站 算是走路很多了", after)
        self.assertIn(generated, exercise_section(after))
        self.assertIn("# 练琴 / Piano", after)

    def test_replace_existing_activity_subsection_is_idempotent(self) -> None:
        generated = format_activity_markdown(self.activity_payload())
        once = replace_activity_subsection(self.page_content(), generated)
        twice = replace_activity_subsection(once, generated)

        self.assertEqual(twice, once)
        self.assertEqual(twice.count(ACTIVITY_HEADING), 1)
        self.assertIn("今天从家扛着电脑走到了学校再一咬牙走到了地铁站 算是走路很多了", exercise_section(twice))

    def test_replace_preserves_user_text_after_existing_generated_subsection(self) -> None:
        content = "\n".join(
            [
                "# 运动 / Exercise",
                "before text",
                "## 活动数据 / Activity",
                "- old generated",
                "after text",
                "# 练琴 / Piano",
            ]
        )

        after = replace_activity_subsection(content, format_activity_markdown(self.activity_payload()))

        self.assertIn("before text", exercise_section(after))
        self.assertIn("after text", exercise_section(after))
        self.assertNotIn("- old generated", after)

    def test_missing_exercise_section_raises(self) -> None:
        with self.assertRaises(ActivityNotionSyncError):
            replace_activity_subsection("# 生活 / Life\ntext", format_activity_markdown(self.activity_payload()))

    def test_load_activity_payload_requires_explicit_matching_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalized_dir = Path(tmp)
            (normalized_dir / "2026-09-03.json").write_text(
                json.dumps(self.activity_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            payload = load_activity_payload("2026-09-03", normalized_dir=normalized_dir)

        self.assertEqual(payload["date"], "2026-09-03")

    def test_load_activity_payload_rejects_date_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalized_dir = Path(tmp)
            payload = self.activity_payload()
            payload["date"] = "2026-09-04"
            (normalized_dir / "2026-09-03.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(ActivityNotionSyncError):
                load_activity_payload("2026-09-03", normalized_dir=normalized_dir)

    def test_validate_single_page_match(self) -> None:
        match = validate_single_page_match(
            [
                {
                    "url": "https://app.notion.com/page",
                    "Title": "2026.09.03",
                    "date:Date:start": "2026-09-03",
                    "date:Date:is_datetime": 0,
                }
            ],
            sync_date="2026-09-03",
        )

        self.assertEqual(match.url, "https://app.notion.com/page")
        self.assertEqual(match.title, "2026.09.03")


if __name__ == "__main__":
    unittest.main()
