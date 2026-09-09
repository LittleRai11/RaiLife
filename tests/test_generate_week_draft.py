from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from railife.pipelines.generate_week_draft import (
    apply_week01_editorial_flags,
    build_draft,
    render_markdown,
    select_bits_candidates,
    select_for_you_candidates,
    write_outputs,
)


class GenerateWeekDraftTests(unittest.TestCase):
    def test_build_draft_separates_self_study_class_and_uncertain_spans(self) -> None:
        notes = {
            "week": {"label": "Week 01", "week_start": "2026-08-30", "week_end": "2026-09-05"},
            "days": [
                {
                    "date": "2026-09-01",
                    "study_entries": [
                        {
                            "type": "explicit_interval",
                            "subject": "英语",
                            "duration_minutes": 60,
                            "intervals": [],
                            "uncertainty": [],
                            "text": "9-10写英语笔记",
                        },
                        {
                            "type": "course_or_class",
                            "subject": "曲式",
                            "duration_minutes": 120,
                            "intervals": [],
                            "uncertainty": ["明确是上课；是否计入自主学习需要人工确认"],
                            "text": "17:00-19:00曲式课",
                        },
                        {
                            "type": "explicit_interval",
                            "subject": "西方音乐史",
                            "duration_minutes": 120,
                            "intervals": [],
                            "uncertainty": ["时间段内断断续续，净学习时长需要人工确认"],
                            "text": "8:00-10:00断断续续背西音史",
                        },
                    ],
                    "piano_entry": {
                        "net_duration_minutes": 90,
                        "recorded_span_minutes": 90,
                        "works": ["平均律"],
                        "technique_observations": [],
                        "performance_psychology_observations": [],
                        "physical_observations": [],
                    },
                    "candidate_quotes": [],
                },
                {
                    "date": "2026-09-04",
                    "study_entries": [],
                    "piano_entry": {
                        "net_duration_minutes": None,
                        "recorded_span_minutes": 225,
                        "works": [],
                        "technique_observations": ["左手手腕还是不太行。"],
                        "performance_psychology_observations": [],
                        "physical_observations": ["左手手腕还是不太行。"],
                        "text": "17:45-21:30 中间有小休息",
                    },
                    "candidate_quotes": [],
                },
            ],
            "manual_confirmation_items": [],
        }
        sleep_week = {
            "statistics": {
                "main_sleep_asleep_minutes": {"mean": 360, "min": 240, "max": 480},
                "all_sleep_asleep_minutes": {"mean": 390, "min": 300, "max": 500},
                "nap_count": 1,
                "nap_asleep_minutes_total": 90,
            },
            "days": [
                {
                    "date": "2026-09-01",
                    "main_sleep": {
                        "asleep_total_minutes": 360,
                        "start": "2026-09-01T01:00:00+08:00",
                        "end": "2026-09-01T07:00:00+08:00",
                    },
                }
            ],
        }
        activity_week = {
            "statistics": {
                "total_steps_display": 1000,
                "average_steps_display": 1000,
                "max_steps": {"date": "2026-09-01", "display_count": 1000},
                "min_steps": {"date": "2026-09-01", "display_count": 1000},
            },
            "days": [{"date": "2026-09-01", "steps": {"count": 1000, "display_count": 1000}}],
            "workouts": [],
        }

        draft = build_draft(notes, sleep_week, activity_week)

        self.assertEqual(draft["study"]["confirmed_self_study_minutes"], 60)
        self.assertEqual(draft["study"]["class_minutes"], 120)
        self.assertEqual(draft["study"]["recorded_but_uncertain_minutes"], 120)
        self.assertEqual(draft["piano"]["confirmed_practice_minutes"], 90)
        self.assertEqual(draft["piano"]["uncertain_span_minutes"], 225)

    def test_render_and_write_outputs(self) -> None:
        notes = {
            "week": {"label": "Week 01", "week_start": "2026-08-30", "week_end": "2026-09-05"},
            "days": [
                {
                    "date": "2026-09-05",
                    "study_entries": [],
                    "piano_entry": {
                        "net_duration_minutes": 90,
                        "recorded_span_minutes": 90,
                        "works": [],
                        "technique_observations": [],
                        "performance_psychology_observations": [],
                        "physical_observations": [],
                    },
                    "candidate_quotes": [],
                }
            ],
            "manual_confirmation_items": [],
        }
        sleep_week = {
            "statistics": {
                "main_sleep_asleep_minutes": {"mean": 360, "min": 240, "max": 480},
                "all_sleep_asleep_minutes": {"mean": 390, "min": 300, "max": 500},
                "nap_count": 0,
                "nap_asleep_minutes_total": 0,
            },
            "days": [
                {
                    "date": "2026-09-05",
                    "main_sleep": {
                        "asleep_total_minutes": 360,
                        "start": "2026-09-05T01:00:00+08:00",
                        "end": "2026-09-05T07:00:00+08:00",
                    },
                }
            ],
        }
        activity_week = {
            "statistics": {
                "total_steps_display": 1000,
                "average_steps_display": 1000,
                "max_steps": {"date": "2026-09-05", "display_count": 1000},
                "min_steps": {"date": "2026-09-05", "display_count": 1000},
            },
            "days": [{"date": "2026-09-05", "steps": {"count": 1000, "display_count": 1000}}],
            "workouts": [],
        }
        draft = build_draft(notes, sleep_week, activity_week)
        markdown = render_markdown(draft)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_outputs(draft, output_dir=Path(tmp))

        self.assertIn("# Week 01", markdown)
        self.assertIn("confirmed_self_study_minutes", markdown)
        self.assertEqual(json_path.name, "week-01_2026-08-30_2026-09-05_draft.json")
        self.assertEqual(md_path.name, "week-01_2026-08-30_2026-09-05_draft.md")

    def test_candidate_selection_prefers_reviewed_anchors_across_dates(self) -> None:
        for_you = [
            {"date": "2026-08-30", "section": "for_you", "text": "小狗姐姐账号的内容。"},
            {"date": "2026-08-30", "section": "for_you", "text": "8/30 另一条。"},
            {"date": "2026-08-31", "section": "for_you", "text": "看到我有改变也会有成就感！"},
            {"date": "2026-09-01", "section": "for_you", "text": "我不希望“在乎我”变成一种必须承担的责任。"},
            {"date": "2026-09-02", "section": "for_you", "text": "老师连累都要等到一个人的时候才说……唉"},
            {"date": "2026-09-04", "section": "for_you", "text": "要是能把老师部署到大脑本地就好了（bushi"},
        ]
        bits = [
            {"date": "2026-08-30", "section": "bits", "text": "发现了一个iPad！"},
            {"date": "2026-08-30", "section": "bits", "text": "还有一部真的真的彻底忘记的iPhone X。"},
            {"date": "2026-09-03", "section": "daily_log", "text": "第一次坐地铁来的万象城。"},
            {"date": "2026-09-04", "section": "bits", "text": "给了我厚厚的黄色毯子，好开心。"},
        ]

        selected_for_you = select_for_you_candidates(for_you)
        selected_bits = select_bits_candidates(bits)

        self.assertIn("2026-09-01", {item["date"] for item in selected_for_you})
        self.assertIn("2026-09-04", {item["date"] for item in selected_for_you})
        self.assertLess(sum(item["date"] == "2026-08-30" for item in selected_for_you), len(selected_for_you))
        self.assertEqual(selected_bits[0]["text"], "发现了一个iPad！")
        self.assertIn("2026-09-03", {item["date"] for item in selected_bits})
        self.assertIn("2026-09-04", {item["date"] for item in selected_bits})

    def test_already_shared_with_ravix_is_flagged_and_deprioritized(self) -> None:
        bits = apply_week01_editorial_flags(
            [
                {"date": "2026-09-01", "section": "bits", "text": "我居然直接，把两万多字的对话发给老师了……"},
                {"date": "2026-08-30", "section": "bits", "text": "我找到了好多已经完全遗忘的东西——我发现了一个iPad！"},
                {"date": "2026-08-30", "section": "bits", "text": "还有一部真的真的彻底忘记的iPhone X。"},
                {"date": "2026-08-30", "section": "bits", "text": "然后，晚上把notion官方MCP接进了codex。"},
                {"date": "2026-08-30", "section": "bits", "text": "从Apple Health直接拿原始数，再生成normalized JSON和weekly aggregate。"},
                {"date": "2026-09-02", "section": "daily_log", "text": "拎了四袋大垃圾，终于见到太阳。"},
                {"date": "2026-09-03", "section": "daily_log", "text": "今天是第一次坐地铁来的万象城。"},
                {"date": "2026-09-03", "section": "daily_log", "text": "朋友散步之后还给我买了甜点。"},
                {"date": "2026-09-04", "section": "bits", "text": "给了我厚厚的黄色毯子，好开心。"},
                {"date": "2026-09-04", "section": "bits", "text": "妈妈说我身材好看多了，好像胖了之后皮肤也好一点了。"},
                {"date": "2026-09-05", "section": "daily_log", "text": "留作补位的普通生活片段。"},
                {"date": "2026-09-05", "section": "bits", "text": "另一条补位片段。"},
            ]
        )

        selected = select_bits_candidates(bits)

        self.assertTrue(bits[0]["already_shared_with_ravix"])
        self.assertNotIn("两万多字", " ".join(item["text"] for item in selected))


if __name__ == "__main__":
    unittest.main()
