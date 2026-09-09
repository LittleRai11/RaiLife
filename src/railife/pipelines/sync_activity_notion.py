from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
NORMALIZED_ACTIVITY_DIR = PROJECT_ROOT / "data/normalized/activity"
DAILY_RECORDS_DATA_SOURCE_URL = "collection://869e0ef0-32ad-403e-841f-69765d9d0b84"
EXERCISE_HEADING = "# 运动 / Exercise"
ACTIVITY_HEADING = "## 活动数据 / Activity"


class ActivityNotionSyncError(ValueError):
    """Raised when a safe single-date Notion activity sync cannot proceed."""


@dataclass(frozen=True)
class NotionPageMatch:
    url: str
    title: str
    date: str
    is_datetime: int


def page_title_for_date(sync_date: str) -> str:
    parsed = date.fromisoformat(sync_date)
    return parsed.strftime("%Y.%m.%d")


def load_activity_payload(sync_date: str, *, normalized_dir: Path = NORMALIZED_ACTIVITY_DIR) -> dict[str, Any]:
    date.fromisoformat(sync_date)
    path = normalized_dir / f"{sync_date}.json"
    if not path.exists():
        raise ActivityNotionSyncError(f"Normalized activity file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "activity.daily.v1":
        raise ActivityNotionSyncError(f"{path}: expected schema_version activity.daily.v1")
    if payload.get("date") != sync_date:
        raise ActivityNotionSyncError(f"{path}: payload date does not match requested date")
    return payload


def validate_single_page_match(rows: list[dict[str, Any]], *, sync_date: str) -> NotionPageMatch:
    title = page_title_for_date(sync_date)
    matches = [
        row
        for row in rows
        if row.get("Title") == title and row.get("date:Date:start") == sync_date
    ]
    if not matches:
        raise ActivityNotionSyncError(
            f"No Daily Records page found with Title={title!r} and Date={sync_date!r}"
        )
    if len(matches) > 1:
        raise ActivityNotionSyncError(
            f"Multiple Daily Records pages found with Title={title!r} and Date={sync_date!r}"
        )
    row = matches[0]
    return NotionPageMatch(
        url=row["url"],
        title=row["Title"],
        date=row["date:Date:start"],
        is_datetime=row.get("date:Date:is_datetime", 0),
    )


def format_activity_markdown(payload: dict[str, Any]) -> str:
    lines = [ACTIVITY_HEADING]
    steps = payload.get("steps", {})
    step_count = steps.get("count")
    if step_count is not None:
        lines.append(f"- 步数：{int(step_count):,} 步")

    for workout in payload.get("workouts", []):
        workout_lines = format_workout_lines(workout)
        if workout_lines:
            lines.extend(workout_lines)

    return "\n".join(lines)


def format_workout_lines(workout: dict[str, Any]) -> list[str]:
    name = workout.get("name")
    start = parse_iso_datetime(workout.get("start"))
    end = parse_iso_datetime(workout.get("end"))
    if not name or start is None or end is None:
        return []

    lines = [f"- {display_workout_name(name)}：{start:%H:%M}–{end:%H:%M}"]
    duration = workout.get("duration_seconds")
    if duration is not None:
        lines.append(f"\t- 时长：{format_duration(duration)}")

    distance = workout.get("distance", {})
    distance_value = distance.get("value")
    distance_unit = distance.get("unit")
    if distance_value is not None and distance_unit:
        lines.append(f"\t- 距离：{distance_value:.2f} {distance_unit}")

    active_energy = workout.get("active_energy", {})
    active_kcal = active_energy.get("value")
    active_unit = active_energy.get("unit")
    if active_kcal is not None and active_unit == "kcal":
        lines.append(f"\t- 活动消耗：{active_kcal:.1f} kcal")

    heart_rate = workout.get("heart_rate", {})
    average = heart_rate.get("average", {}).get("value")
    minimum = heart_rate.get("minimum", {}).get("value")
    maximum = heart_rate.get("maximum", {}).get("value")
    if average is not None:
        lines.append(f"\t- 平均心率：{round(average)} bpm")
    if minimum is not None and maximum is not None:
        lines.append(f"\t- 心率范围：{round(minimum)}–{round(maximum)} bpm")

    return lines


def display_workout_name(name: str) -> str:
    return "".join(name.split())


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value)


def format_duration(duration_seconds: int | float) -> str:
    total_seconds = round(duration_seconds)
    minutes, seconds = divmod(total_seconds, 60)
    if seconds:
        return f"{minutes}分{seconds}秒"
    return f"{minutes}分"


def replace_activity_subsection(page_content: str, generated_markdown: str) -> str:
    exercise_start = find_line_start(page_content, EXERCISE_HEADING)
    if exercise_start is None:
        raise ActivityNotionSyncError(f"Missing section heading: {EXERCISE_HEADING}")

    exercise_end = find_next_top_level_heading(page_content, exercise_start + len(EXERCISE_HEADING))
    if exercise_end is None:
        exercise_end = len(page_content)

    exercise_section = page_content[exercise_start:exercise_end]
    activity_start_relative = find_line_start(exercise_section, ACTIVITY_HEADING)

    if activity_start_relative is None:
        insertion = generated_markdown
        if not exercise_section.endswith("\n"):
            insertion = "\n" + insertion
        if not insertion.endswith("\n") and exercise_end < len(page_content):
            insertion += "\n"
        return page_content[:exercise_end] + insertion + page_content[exercise_end:]

    activity_end_relative = find_generated_activity_end(
        exercise_section,
        activity_start_relative + len(ACTIVITY_HEADING),
    )

    replacement = generated_markdown
    if (activity_end_relative < len(exercise_section) or exercise_end < len(page_content)) and not replacement.endswith("\n"):
        replacement += "\n"

    return (
        page_content[: exercise_start + activity_start_relative]
        + replacement
        + page_content[exercise_start + activity_end_relative :]
    )


def find_line_start(text: str, line: str) -> int | None:
    pattern = re.compile(rf"(?m)^{re.escape(line)}$")
    match = pattern.search(text)
    return match.start() if match else None


def find_next_top_level_heading(text: str, start_index: int) -> int | None:
    pattern = re.compile(r"(?m)^# .+$")
    match = pattern.search(text, start_index)
    return match.start() if match else None


def find_next_heading_at_or_above_level(text: str, start_index: int, *, max_level: int) -> int | None:
    pattern = re.compile(r"(?m)^(#{1," + str(max_level) + r"}) .+$")
    match = pattern.search(text, start_index)
    return match.start() if match else None


def find_generated_activity_end(section: str, start_index: int) -> int:
    position = start_index
    while position < len(section) and section[position] == "\n":
        position += 1

    for match in re.finditer(r"(?m)^.*(?:\n|$)", section[position:]):
        line_start = position + match.start()
        line = match.group(0)
        stripped = line.rstrip("\n")
        if stripped.startswith("#"):
            return line_start
        if stripped and not stripped.startswith("- ") and not stripped.startswith("\t"):
            return line_start
    return len(section)


def top_level_sections(page_content: str) -> list[str]:
    return re.findall(r"(?m)^# .+$", page_content)


def exercise_section(page_content: str) -> str:
    exercise_start = find_line_start(page_content, EXERCISE_HEADING)
    if exercise_start is None:
        raise ActivityNotionSyncError(f"Missing section heading: {EXERCISE_HEADING}")
    exercise_end = find_next_top_level_heading(page_content, exercise_start + len(EXERCISE_HEADING))
    if exercise_end is None:
        exercise_end = len(page_content)
    return page_content[exercise_start:exercise_end].rstrip("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a single-date safe Notion activity sync payload. "
            "The actual Notion write is performed by the Notion connector."
        )
    )
    parser.add_argument("--date", required=True, help="Explicit date to sync, e.g. 2026-09-03")
    parser.add_argument("--normalized-dir", type=Path, default=NORMALIZED_ACTIVITY_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = load_activity_payload(args.date, normalized_dir=args.normalized_dir)
    print(format_activity_markdown(payload))


if __name__ == "__main__":
    main()
