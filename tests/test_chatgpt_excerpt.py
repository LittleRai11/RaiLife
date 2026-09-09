from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from railife.models.chatgpt_excerpt import (
    ChatGPTExcerptValidationError,
    build_excerpt,
    save_excerpt,
    validate_excerpt,
)


class ChatGPTExcerptTests(unittest.TestCase):
    def test_build_excerpt_defaults_to_private(self) -> None:
        payload = build_excerpt(
            excerpt_date="2026-09-02",
            title="睡眠数据更新",
            user_text="请执行今天的 RaiLife 睡眠数据更新。",
            assistant_text="完成了。",
        )

        self.assertEqual(payload["schema_version"], "chatgpt.excerpt.v1")
        self.assertEqual(payload["date"], "2026-09-02")
        self.assertEqual(payload["status"], "private")
        self.assertEqual(payload["user_text"], "请执行今天的 RaiLife 睡眠数据更新。")
        self.assertEqual(payload["assistant_text"], "完成了。")

    def test_save_excerpt_uses_date_and_three_digit_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            excerpts_dir = Path(tmp)
            first = build_excerpt(
                excerpt_date="2026-09-02",
                user_text="原话 1",
                assistant_text="回复 1",
            )
            second = build_excerpt(
                excerpt_date="2026-09-02",
                user_text="原话 2",
                assistant_text="回复 2",
                status="weekly_candidate",
            )

            first_path = save_excerpt(first, excerpts_dir=excerpts_dir)
            second_path = save_excerpt(second, excerpts_dir=excerpts_dir)

            saved_second = json.loads(second_path.read_text(encoding="utf-8"))

        self.assertEqual(first_path.name, "2026-09-02_001.json")
        self.assertEqual(second_path.name, "2026-09-02_002.json")
        self.assertEqual(saved_second["status"], "weekly_candidate")

    def test_validation_rejects_bad_schema_version(self) -> None:
        with self.assertRaises(ChatGPTExcerptValidationError):
            validate_excerpt(
                {
                    "schema_version": "wrong",
                    "date": "2026-09-02",
                    "status": "private",
                    "user_text": "原话",
                    "assistant_text": "回复",
                }
            )

    def test_validation_rejects_bad_date(self) -> None:
        with self.assertRaises(ChatGPTExcerptValidationError):
            validate_excerpt(
                {
                    "schema_version": "chatgpt.excerpt.v1",
                    "date": "2026/09/02",
                    "status": "private",
                    "user_text": "原话",
                    "assistant_text": "回复",
                }
            )

    def test_validation_rejects_bad_status(self) -> None:
        with self.assertRaises(ChatGPTExcerptValidationError):
            validate_excerpt(
                {
                    "schema_version": "chatgpt.excerpt.v1",
                    "date": "2026-09-02",
                    "status": "published",
                    "user_text": "原话",
                    "assistant_text": "回复",
                }
            )

    def test_validation_requires_text_fields(self) -> None:
        with self.assertRaises(ChatGPTExcerptValidationError):
            validate_excerpt(
                {
                    "schema_version": "chatgpt.excerpt.v1",
                    "date": "2026-09-02",
                    "status": "private",
                    "user_text": "原话",
                }
            )


if __name__ == "__main__":
    unittest.main()
