from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = PROJECT_ROOT / "data/reports"
NOTE_SECTIONS = {
    "study": "# 学习 / Study",
    "piano": "# 练琴 / Piano",
    "mood": "# 心情 / Mood",
    "daily_log": "# 今日记录 / Daily Log",
    "for_you": "# 留给老师 / For You",
    "bits": "# 边角料 / Bits & Pieces",
}

SUBJECT_ALIASES = {
    "英语": "英语",
    "政治": "政治",
    "曲式": "曲式",
    "和声": "和声",
    "中音史": "中国音乐史",
    "中国音乐史": "中国音乐史",
    "西音史": "西方音乐史",
    "西方音乐史": "西方音乐史",
    "音乐史": "音乐史",
}
_SUBJECT_UNSET = object()


def extract_sections(page_content: str) -> dict[str, str]:
    sections = {}
    for key, heading in NOTE_SECTIONS.items():
        sections[key] = extract_section(page_content, heading)
    return sections


def extract_section(page_content: str, heading: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(heading)}$")
    match = pattern.search(page_content)
    if not match:
        return ""
    next_heading = re.compile(r"(?m)^# .+$").search(page_content, match.end())
    end = next_heading.start() if next_heading else len(page_content)
    body = page_content[match.end():end].strip()
    return "" if body == "<empty-block/>" else body


def split_records(text: str) -> list[str]:
    if not text:
        return []
    records: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line == "<empty-block/>":
            continue
        parts = [part.strip() for part in re.split(r"(?<=[。！？!？])", line) if part.strip()]
        records.extend(parts or [line])
    return records


def extract_study_entries(study_text: str, *, entry_overrides: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if entry_overrides is not None:
        return [
            classify_study_record(item["text"], item["subject"] if "subject" in item else _SUBJECT_UNSET)
            for item in entry_overrides
        ]
    return [classify_study_record(record) for record in split_records(study_text)]


def classify_study_record(text: str, subject_override: Any = _SUBJECT_UNSET) -> dict[str, Any]:
    normalized = unescape_notion_time(text)
    intervals = parse_intervals(normalized)
    explicit_duration = parse_explicit_duration(normalized)
    subject = infer_subject(normalized) if subject_override is _SUBJECT_UNSET else subject_override
    entry_type = "unknown"
    duration_minutes = None
    uncertainty: list[str] = []

    if intervals:
        duration_minutes = sum(interval["duration_minutes"] for interval in intervals)
        entry_type = "explicit_interval"
        if "课" in normalized or "上课" in normalized:
            entry_type = "course_or_class"
            uncertainty.append("明确是上课；是否计入自主学习需要人工确认")
        if "断断续续" in normalized:
            uncertainty.append("时间段内断断续续，净学习时长需要人工确认")
    elif explicit_duration is not None:
        duration_minutes = explicit_duration
        entry_type = "explicit_duration"
    elif "课" in normalized or "上课" in normalized:
        entry_type = "course_or_class"
        uncertainty.append("课程/上课记录没有可安全计算的起止时间")
    elif has_vague_duration(normalized):
        entry_type = "vague_duration"
        uncertainty.append("模糊时间描述，不估算分钟数")
    else:
        entry_type = "unknown"

    if intervals and subject is None:
        uncertainty.append("时间段存在，但科目不明确")

    return {
        "type": entry_type,
        "text": text,
        "subject": subject,
        "duration_minutes": duration_minutes,
        "intervals": intervals,
        "uncertainty": uncertainty,
    }


def extract_piano_entry(piano_text: str) -> dict[str, Any]:
    normalized = unescape_notion_time(piano_text)
    intervals = parse_intervals(normalized)
    has_breaks = any(token in normalized for token in ("休息", "中间", "断断续续"))
    recorded_span_minutes = sum(item["duration_minutes"] for item in intervals) if intervals else None
    explicit_duration = parse_explicit_duration(normalized)
    if recorded_span_minutes is None:
        recorded_span_minutes = explicit_duration
    net_duration_minutes = None if has_breaks else recorded_span_minutes
    return {
        "text": piano_text,
        "intervals": intervals,
        "recorded_span_minutes": recorded_span_minutes,
        "has_breaks": has_breaks,
        "net_duration_minutes": net_duration_minutes,
        "works": extract_works(normalized),
        "technique_observations": extract_keyword_fragments(
            normalized,
            ["左手", "慢练", "音色", "手感", "力度", "糊", "沉不下心", "机能"],
        ),
        "performance_psychology_observations": extract_keyword_fragments(
            normalized,
            ["紧张", "录像", "完整", "心里阴影", "放得开"],
        ),
        "physical_observations": extract_keyword_fragments(
            normalized,
            ["手腕", "背痛", "痛"],
        ),
    }


def parse_intervals(text: str) -> list[dict[str, Any]]:
    text = unescape_notion_time(text)
    patterns = [
        r"(?<!\d)(\d{1,2})(?:[:：](\d{2}))?\s*[-–—~]\s*(\d{1,2})(?:[:：](\d{2}))?(?!\d)",
        r"(?<!\d)(\d{1,2})(?:[:：](\d{2}))?[^0-9\n]{1,30}?[-–—~]\s*(\d{1,2})(?:[:：](\d{2}))?(?!\d)",
        r"(?<!\d)(\d{1,2})(?:[:：](\d{2}))?[^0-9\n]{0,30}?到\s*(\d{1,2})(?:[:：](\d{2}))?(?!\d)",
    ]
    intervals = []
    seen = set()
    for match in (match for pattern in patterns for match in re.finditer(pattern, text)):
        start_hour = int(match.group(1))
        start_minute = int(match.group(2) or "0")
        end_hour = int(match.group(3))
        end_minute = int(match.group(4) or "0")
        duration = (end_hour * 60 + end_minute) - (start_hour * 60 + start_minute)
        if duration < 0:
            duration += 24 * 60
        key = (start_hour, start_minute, end_hour, end_minute)
        if key in seen:
            continue
        seen.add(key)
        intervals.append(
            {
                "start": f"{start_hour:02d}:{start_minute:02d}",
                "end": f"{end_hour:02d}:{end_minute:02d}",
                "duration_minutes": duration,
            }
        )
    return intervals


def parse_explicit_duration(text: str) -> int | None:
    if "半个小时" in text:
        return 30
    match = re.search(r"([一二两三四五六七八九十\d]+)\s*(?:个)?小时", text)
    if match:
        return chinese_or_int(match.group(1)) * 60
    match = re.search(r"(\d+)\s*分钟", text)
    if match:
        return int(match.group(1))
    return None


def chinese_or_int(value: str) -> int:
    if value.isdecimal():
        return int(value)
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return mapping[value]


def has_vague_duration(text: str) -> bool:
    return any(token in text for token in ("一点", "一会", "上午", "中午", "下午", "晚上", "断断续续", "没做完"))


def infer_subject(text: str) -> str | None:
    for needle, subject in SUBJECT_ALIASES.items():
        if needle in text:
            return subject
    return None


def extract_works(text: str) -> list[str]:
    works = []
    for needle, label in [
        ("Fuga", "Fuga"),
        ("平均律", "平均律"),
        ("贝2", "贝多芬第二奏鸣曲"),
        ("第三乐章", "第三乐章"),
        ("abg", "abg"),
    ]:
        if needle in text:
            works.append(label)
    return works


def extract_keyword_fragments(text: str, keywords: list[str]) -> list[str]:
    fragments = []
    for record in split_records(text):
        if any(keyword in record for keyword in keywords):
            fragments.append(record)
    return fragments


def unescape_notion_time(text: str) -> str:
    return text.replace("\\:", ":")


def candidate_quotes(date_text: str, section: str, text: str) -> list[dict[str, str]]:
    return [
        {"date": date_text, "section": section, "text": record}
        for record in split_records(text)
    ]


def build_notes(
    *,
    week_label: str,
    start_date: date,
    end_date: date,
    daily_records: list[dict[str, Any]],
) -> dict[str, Any]:
    days = []
    manual_confirmation_items = []
    for record in daily_records:
        sections = record["sections"]
        study_entries = extract_study_entries(
            sections.get("study", ""),
            entry_overrides=record.get("study_entry_overrides"),
        )
        piano_entry = extract_piano_entry(sections.get("piano", ""))
        quotes = [
            quote
            for section in ("mood", "daily_log", "for_you", "bits")
            for quote in candidate_quotes(record["date"], section, sections.get(section, ""))
        ]
        days.append(
            {
                "date": record["date"],
                "page": record.get("page", {}),
                "sections": {key: sections.get(key, "") for key in NOTE_SECTIONS},
                "study_entries": study_entries,
                "piano_entry": piano_entry,
                "candidate_quotes": quotes,
            }
        )
        for entry in study_entries:
            if entry["uncertainty"]:
                manual_confirmation_items.append(
                    {
                        "date": record["date"],
                        "section": "study",
                        "text": entry["text"],
                        "reasons": entry["uncertainty"],
                    }
                )
        if piano_entry["has_breaks"] or (
            piano_entry["recorded_span_minutes"] is not None and piano_entry["net_duration_minutes"] is None
        ):
            manual_confirmation_items.append(
                {
                    "date": record["date"],
                    "section": "piano",
                    "text": piano_entry["text"],
                    "reasons": ["记录时段含休息/中断，不能等同净练琴时长"],
                }
            )
    return {
        "schema_version": "week.notes.review.v1",
        "format_note": "Review/intermediate format only; not a long-term stable schema.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": {
            "label": week_label,
            "week_start": start_date.isoformat(),
            "week_end": end_date.isoformat(),
            "week_start_day": "Sunday",
        },
        "days": days,
        "manual_confirmation_items": manual_confirmation_items,
        "counts": counts(days, manual_confirmation_items),
    }


def counts(days: list[dict[str, Any]], manual_confirmation_items: list[dict[str, Any]]) -> dict[str, Any]:
    study = {"explicit_interval": 0, "explicit_duration": 0, "vague_duration": 0, "course_or_class": 0, "unknown": 0}
    piano_intervals = 0
    piano_break_or_unclear = 0
    for day in days:
        for entry in day["study_entries"]:
            study[entry["type"]] += 1
        if day["piano_entry"]["intervals"]:
            piano_intervals += len(day["piano_entry"]["intervals"])
        if day["piano_entry"]["has_breaks"] or (
            day["piano_entry"]["recorded_span_minutes"] is not None
            and day["piano_entry"]["net_duration_minutes"] is None
        ):
            piano_break_or_unclear += 1
    return {
        "study": study,
        "piano": {
            "explicit_intervals": piano_intervals,
            "entries_with_breaks_or_unclear_net_duration": piano_break_or_unclear,
        },
        "manual_confirmation_items": len(manual_confirmation_items),
    }


def render_markdown(notes: dict[str, Any]) -> str:
    lines = [
        f"# {notes['week']['label']} Notes Review",
        "",
        f"Period: {notes['week']['week_start']} -- {notes['week']['week_end']}",
        "",
        "> Review/intermediate material only. This is not final weekly report prose.",
        "",
    ]
    for day in notes["days"]:
        lines.extend([f"## {day['date']}", ""])
        for key, heading in NOTE_SECTIONS.items():
            lines.extend([f"### {heading.removeprefix('# ')}", ""])
            text = day["sections"].get(key) or ""
            lines.extend(["原文：", "", text or "(empty)", ""])
            if key == "study":
                lines.append("提取：")
                for entry in day["study_entries"]:
                    lines.append(
                        f"- type={entry['type']}; subject={entry['subject']}; "
                        f"duration_minutes={entry['duration_minutes']}; text={entry['text']}"
                    )
                    if entry["uncertainty"]:
                        lines.append(f"  - uncertainty={'；'.join(entry['uncertainty'])}")
                if not day["study_entries"]:
                    lines.append("- (none)")
                lines.append("")
            elif key == "piano":
                piano = day["piano_entry"]
                lines.append("提取：")
                lines.append(
                    f"- recorded_span_minutes={piano['recorded_span_minutes']}; "
                    f"has_breaks={str(piano['has_breaks']).lower()}; "
                    f"net_duration_minutes={piano['net_duration_minutes']}"
                )
                lines.append(f"- intervals={piano['intervals']}")
                lines.append(f"- works={piano['works']}")
                lines.append(f"- technique_observations={piano['technique_observations']}")
                lines.append(f"- performance_psychology_observations={piano['performance_psychology_observations']}")
                lines.append(f"- physical_observations={piano['physical_observations']}")
                lines.append("")
    lines.extend(["## Manual Confirmation Items", ""])
    for item in notes["manual_confirmation_items"]:
        lines.append(f"- {item['date']} [{item['section']}]: {item['text']}")
        lines.append(f"  - reasons: {'；'.join(item['reasons'])}")
    if not notes["manual_confirmation_items"]:
        lines.append("- (none)")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(notes: dict[str, Any], *, output_dir: Path = REPORT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    week = notes["week"]
    label = week["label"].lower().replace(" ", "-")
    stem = f"{label}_{week['week_start']}_{week['week_end']}_notes"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(notes, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(notes), encoding="utf-8")
    return json_path, markdown_path


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract review notes from Week Daily Records section text.")
    parser.add_argument("--week-label", required=True)
    parser.add_argument("--start-date", required=True, type=parse_date)
    parser.add_argument("--end-date", required=True, type=parse_date)
    parser.add_argument("--daily-records", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    daily_records = json.loads(args.daily_records.read_text(encoding="utf-8"))
    notes = build_notes(
        week_label=args.week_label,
        start_date=args.start_date,
        end_date=args.end_date,
        daily_records=daily_records,
    )
    for path in write_outputs(notes, output_dir=args.output_dir):
        print(path)


if __name__ == "__main__":
    main()
