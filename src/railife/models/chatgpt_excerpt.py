from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "chatgpt.excerpt.v1"
ALLOWED_STATUSES = {"private", "weekly_candidate"}
DEFAULT_STATUS = "private"


class ChatGPTExcerptValidationError(ValueError):
    """Raised when a ChatGPT excerpt does not match the raw excerpt schema."""


def validate_excerpt(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ChatGPTExcerptValidationError("schema_version must be chatgpt.excerpt.v1")

    try:
        parsed_date = date.fromisoformat(payload["date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ChatGPTExcerptValidationError("date must be YYYY-MM-DD") from exc

    if parsed_date.isoformat() != payload["date"]:
        raise ChatGPTExcerptValidationError("date must be YYYY-MM-DD")

    if payload.get("status") not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise ChatGPTExcerptValidationError(f"status must be one of: {allowed}")

    for field_name in ("user_text", "assistant_text"):
        if field_name not in payload:
            raise ChatGPTExcerptValidationError(f"{field_name} is required")
        if not isinstance(payload[field_name], str) or not payload[field_name].strip():
            raise ChatGPTExcerptValidationError(f"{field_name} must be a non-empty string")


def build_excerpt(
    *,
    excerpt_date: str,
    user_text: str,
    assistant_text: str,
    time: str | None = None,
    title: str | None = None,
    topic: str | None = None,
    status: str = DEFAULT_STATUS,
    notes: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "date": excerpt_date,
        "status": status,
        "user_text": user_text,
        "assistant_text": assistant_text,
    }
    for key, value in {
        "time": time,
        "title": title,
        "topic": topic,
        "notes": notes,
    }.items():
        if value is not None:
            payload[key] = value

    validate_excerpt(payload)
    return payload


def next_excerpt_path(excerpts_dir: Path, excerpt_date: str) -> Path:
    date.fromisoformat(excerpt_date)
    existing = sorted(excerpts_dir.glob(f"{excerpt_date}_*.json"))
    next_index = 1
    if existing:
        indexes = []
        for path in existing:
            suffix = path.stem.removeprefix(f"{excerpt_date}_")
            if suffix.isdecimal():
                indexes.append(int(suffix))
        if indexes:
            next_index = max(indexes) + 1
    return excerpts_dir / f"{excerpt_date}_{next_index:03d}.json"


def save_excerpt(payload: dict[str, Any], *, excerpts_dir: Path) -> Path:
    validate_excerpt(payload)
    excerpts_dir.mkdir(parents=True, exist_ok=True)
    output_path = next_excerpt_path(excerpts_dir, payload["date"])
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
