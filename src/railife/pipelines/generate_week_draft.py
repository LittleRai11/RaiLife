from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = PROJECT_ROOT / "data/reports"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def minutes_to_hm(minutes: float | int | None) -> str:
    if minutes is None:
        return "unknown"
    rounded = int(round(minutes))
    hours, mins = divmod(rounded, 60)
    if hours and mins:
        return f"{hours}小时{mins}分钟"
    if hours:
        return f"{hours}小时"
    return f"{mins}分钟"


def time_hm(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.strftime("%H:%M")


def date_label(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    return parsed.strftime("%m/%d")


def workout_time_range(workout: dict[str, Any]) -> str:
    return f"{time_hm(workout.get('start'))}-{time_hm(workout.get('end'))}"


def workout_duration_minutes(workout: dict[str, Any]) -> int:
    return int(round((workout.get("duration_seconds") or 0) / 60))


def has_uncertain_net(entry: dict[str, Any]) -> bool:
    return any("净学习时长" in reason or "断断续续" in reason for reason in entry.get("uncertainty", []))


def summarize_study(notes: dict[str, Any]) -> dict[str, Any]:
    confirmed_by_subject: dict[str, int] = defaultdict(int)
    class_by_subject: dict[str, int] = defaultdict(int)
    confirmed_entries = []
    class_entries = []
    uncertain_spans = []
    vague_records = []
    unknown_records = []

    for day in notes["days"]:
        for entry in day["study_entries"]:
            dated = {"date": day["date"], **entry}
            if entry["type"] in ("explicit_interval", "explicit_duration"):
                if entry["duration_minutes"] is not None and not has_uncertain_net(entry):
                    subject = entry["subject"] or "unknown"
                    confirmed_by_subject[subject] += entry["duration_minutes"]
                    confirmed_entries.append(dated)
                elif entry["duration_minutes"] is not None:
                    uncertain_spans.append(dated)
            elif entry["type"] == "course_or_class":
                if entry["duration_minutes"] is not None:
                    subject = entry["subject"] or "unknown"
                    class_by_subject[subject] += entry["duration_minutes"]
                class_entries.append(dated)
            elif entry["type"] == "vague_duration":
                vague_records.append(dated)
            else:
                unknown_records.append(dated)

    return {
        "confirmed_self_study_minutes": sum(confirmed_by_subject.values()),
        "class_minutes": sum(class_by_subject.values()),
        "confirmed_study_minutes_by_subject": dict(sorted(confirmed_by_subject.items())),
        "class_minutes_by_subject": dict(sorted(class_by_subject.items())),
        "confirmed_entries": confirmed_entries,
        "class_entries": class_entries,
        "recorded_but_uncertain_minutes": sum(item["duration_minutes"] for item in uncertain_spans),
        "recorded_but_uncertain_spans": uncertain_spans,
        "vague_records": vague_records,
        "unknown_records": unknown_records,
    }


def summarize_piano(notes: dict[str, Any]) -> dict[str, Any]:
    confirmed_minutes = 0
    daily = []
    uncertain_spans = []
    works = set()
    technique = []
    psychology = []
    physical = []

    for day in notes["days"]:
        entry = day["piano_entry"]
        net = entry["net_duration_minutes"]
        span = entry["recorded_span_minutes"]
        if net is not None:
            confirmed_minutes += net
        elif span is not None:
            uncertain_spans.append({"date": day["date"], "recorded_span_minutes": span, "text": entry["text"]})
        daily.append(
            {
                "date": day["date"],
                "confirmed_practice_minutes": net,
                "recorded_span_minutes": span,
                "uncertain_net_duration": net is None and span is not None,
            }
        )
        works.update(entry.get("works", []))
        technique.extend({"date": day["date"], "text": text} for text in entry.get("technique_observations", []))
        psychology.extend(
            {"date": day["date"], "text": text} for text in entry.get("performance_psychology_observations", [])
        )
        physical.extend({"date": day["date"], "text": text} for text in entry.get("physical_observations", []))

    return {
        "confirmed_practice_minutes": confirmed_minutes,
        "uncertain_span_minutes": sum(item["recorded_span_minutes"] for item in uncertain_spans),
        "uncertain_spans": uncertain_spans,
        "daily_confirmed_piano_minutes": daily,
        "works": sorted(works),
        "technique_observations": technique,
        "performance_psychology_observations": psychology,
        "physical_observations": physical,
    }


def summarize_sleep(sleep_week: dict[str, Any]) -> dict[str, Any]:
    days = sleep_week["days"]
    main = [
        {
            "date": day["date"],
            "minutes": day["main_sleep"]["asleep_total_minutes"] if day.get("main_sleep") else None,
        }
        for day in days
    ]
    start_end = [
        {
            "date": day["date"],
            "start": day["main_sleep"]["start"] if day.get("main_sleep") else None,
            "end": day["main_sleep"]["end"] if day.get("main_sleep") else None,
        }
        for day in days
    ]
    starts = [item for item in start_end if item["start"]]
    ends = [item for item in start_end if item["end"]]
    return {
        "statistics": sleep_week["statistics"],
        "daily_sleep_minutes": main,
        "daily_sleep_start_end": start_end,
        "earliest_main_start": min(starts, key=lambda x: x["start"]) if starts else None,
        "latest_main_start": max(starts, key=lambda x: x["start"]) if starts else None,
        "earliest_main_end": min(ends, key=lambda x: x["end"]) if ends else None,
        "latest_main_end": max(ends, key=lambda x: x["end"]) if ends else None,
    }


def summarize_activity(activity_week: dict[str, Any]) -> dict[str, Any]:
    return {
        "statistics": activity_week["statistics"],
        "daily_steps": [
            {
                "date": day["date"],
                "steps": None if day.get("steps") is None else day["steps"].get("count"),
                "display_steps": None if day.get("steps") is None else day["steps"].get("display_count"),
            }
            for day in activity_week["days"]
        ],
        "workouts": activity_week.get("workouts", []),
    }


def manual_items(notes: dict[str, Any], study: dict[str, Any], piano: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(notes.get("manual_confirmation_items", []))
    for entry in study["unknown_records"]:
        items.append(
            {
                "date": entry["date"],
                "section": "study",
                "text": entry["text"],
                "reasons": ["无法可靠分类或不能进入学习时长统计"],
            }
        )
    for span in piano["uncertain_spans"]:
        if not any(item.get("date") == span["date"] and item.get("section") == "piano" for item in items):
            items.append(
                {
                    "date": span["date"],
                    "section": "piano",
                    "text": span["text"],
                    "reasons": ["存在明确跨度，但净练琴时长未知"],
                }
            )
    return items


def quote_matches(quote: dict[str, str], keywords: tuple[str, ...]) -> bool:
    return any(keyword in quote["text"] for keyword in keywords)


def apply_week01_editorial_flags(quotes: list[dict[str, str]]) -> list[dict[str, Any]]:
    flagged = []
    for quote in quotes:
        item = dict(quote)
        item["already_shared_with_ravix"] = "两万多字的对话发给老师" in quote["text"]
        flagged.append(item)
    return flagged


def first_matching_quote(quotes: list[dict[str, str]], keywords: tuple[str, ...]) -> dict[str, str] | None:
    for quote in (quote for quote in quotes if not quote.get("already_shared_with_ravix", False)):
        if quote_matches(quote, keywords):
            return quote
    return None


def append_unique_quote(selected: list[dict[str, str]], quote: dict[str, str] | None) -> None:
    if quote is None:
        return
    key = (quote["date"], quote["section"], quote["text"])
    if key not in {(item["date"], item["section"], item["text"]) for item in selected}:
        selected.append(quote)


def select_diverse_quotes(
    quotes: list[dict[str, str]],
    keyword_groups: list[tuple[str, ...]],
    *,
    limit: int,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for keywords in keyword_groups:
        append_unique_quote(selected, first_matching_quote(quotes, keywords))
        if len(selected) >= limit:
            return selected

    remaining = [
        quote
        for quote in quotes
        if (quote["date"], quote["section"], quote["text"])
        not in {(item["date"], item["section"], item["text"]) for item in selected}
    ]
    for pool in (
        [quote for quote in remaining if not quote.get("already_shared_with_ravix", False)],
        [quote for quote in remaining if quote.get("already_shared_with_ravix", False)],
    ):
        dates = sorted({quote["date"] for quote in pool})
        while len(selected) < limit and pool:
            appended = False
            for current_date in dates:
                quote = next((item for item in pool if item["date"] == current_date), None)
                if quote is None:
                    continue
                selected.append(quote)
                pool.remove(quote)
                appended = True
                if len(selected) >= limit:
                    break
            if not appended:
                break
        if len(selected) >= limit:
            break
    return selected


def select_for_you_candidates(quotes: list[dict[str, str]]) -> list[dict[str, str]]:
    return select_diverse_quotes(
        quotes,
        [
            ("改变也会有成就感",),
            ("正向的反馈",),
            ("九月", "心理准备"),
            ("没有尽头",),
            ("必须承担的责任",),
            ("偶尔跑来讲话",),
            ("连累都要等到一个人的时候才说",),
            ("每天和老师说晚安",),
            ("部署到大脑本地",),
            ("账号",),
        ],
        limit=10,
    )


def select_bits_candidates(quotes: list[dict[str, str]]) -> list[dict[str, str]]:
    return select_diverse_quotes(
        quotes,
        [
            ("iPad",),
            ("iPhone X",),
            ("notion官方MCP",),
            ("Apple Health", "normalized JSON", "weekly aggregate"),
            ("第一次坐地铁", "万象城"),
            ("朋友散步", "甜点"),
            ("黄色毯子",),
            ("身材好看多了", "皮肤"),
            ("四袋大垃圾", "见到太阳"),
            ("两万多字",),
        ],
        limit=10,
    )


def build_draft(notes: dict[str, Any], sleep_week: dict[str, Any], activity_week: dict[str, Any]) -> dict[str, Any]:
    sleep = summarize_sleep(sleep_week)
    activity = summarize_activity(activity_week)
    study = summarize_study(notes)
    piano = summarize_piano(notes)
    for_you_quotes = apply_week01_editorial_flags([
        quote for day in notes["days"] for quote in day["candidate_quotes"] if quote["section"] == "for_you"
    ])
    bits_candidates = apply_week01_editorial_flags([
        quote
        for day in notes["days"]
        for quote in day["candidate_quotes"]
        if quote["section"] in ("daily_log", "bits")
    ])
    return {
        "schema_version": "week.draft.review.v1",
        "format_note": "Review draft only; not final weekly report prose.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": notes["week"],
        "sleep": sleep,
        "activity": activity,
        "study": study,
        "piano": piano,
        "emotion_and_state_sources": [
            quote
            for day in notes["days"]
            for quote in day["candidate_quotes"]
            if quote["section"] in ("mood", "daily_log", "for_you")
        ],
        "for_you_quotes": for_you_quotes,
        "selected_for_you_candidates": select_for_you_candidates(for_you_quotes),
        "bits_candidates": bits_candidates,
        "selected_bits_candidates": select_bits_candidates(bits_candidates),
        "manual_confirmation_items": manual_items(notes, study, piano),
        "figure_tables": {
            "daily_sleep_minutes": sleep["daily_sleep_minutes"],
            "daily_sleep_start_end": sleep["daily_sleep_start_end"],
            "daily_steps": activity["daily_steps"],
            "confirmed_study_minutes_by_subject": study["confirmed_study_minutes_by_subject"],
            "class_minutes_by_subject": study["class_minutes_by_subject"],
            "daily_confirmed_piano_minutes": piano["daily_confirmed_piano_minutes"],
        },
    }


def render_workout(workout: dict[str, Any]) -> str:
    parts = [
        f"{workout.get('name')} {date_label(workout['start'])} {workout_time_range(workout)}",
        f"{workout_duration_minutes(workout)}分钟",
    ]
    distance = workout.get("distance") or {}
    if distance.get("value") is not None:
        parts.append(f"{distance['value']:.2f} {distance.get('unit', '')}".strip())
    energy = workout.get("active_energy") or {}
    if energy.get("value") is not None:
        parts.append(f"{energy['value']:.1f} {energy.get('unit', '')}".strip())
    return "，".join(parts)


def render_markdown(draft: dict[str, Any]) -> str:
    sleep = draft["sleep"]
    sleep_stats = sleep["statistics"]
    activity = draft["activity"]
    activity_stats = activity["statistics"]
    study = draft["study"]
    piano = draft["piano"]
    week = draft["week"]
    lines = [
        "# Week 01",
        "",
        f"{week['week_start']} ～ {week['week_end']}",
        "",
        "## 本周概览",
        "",
        (
            "这一周从开学前的低学习量，转入英语、曲式、和声、音乐史同时出现的节奏。"
            "睡眠数据覆盖完整 7 天，8/30 受前一晚通宵影响明显后移，随后有过向正常白天活动恢复的过程，但后半周又出现缩短。"
            "活动量整体不高，9/3 是步数峰值且有一次正式户外步行。"
            "练琴记录同时保留两个尺度：整体演奏/练琴心理阴影较此前有所松动，具体到完整演奏和录像情境时，后半程压力开始更清楚地暴露出来。"
        ),
        "",
        "## 睡眠与作息",
        "",
        f"- 主睡眠平均：{minutes_to_hm(sleep_stats['main_sleep_asleep_minutes']['mean'])}",
        f"- 总睡眠平均：{minutes_to_hm(sleep_stats['all_sleep_asleep_minutes']['mean'])}",
        f"- 最短主睡眠：{minutes_to_hm(sleep_stats['main_sleep_asleep_minutes']['min'])}",
        f"- 最长主睡眠：{minutes_to_hm(sleep_stats['main_sleep_asleep_minutes']['max'])}",
        f"- 午睡：{sleep_stats['nap_count']} 次，共 {minutes_to_hm(sleep_stats['nap_asleep_minutes_total'])}",
        "",
        (
            "8/30 受到前一晚通宵影响，主睡眠为 05:58-13:24，并在傍晚有一次午睡。"
            "随后作息尝试向正常白天活动恢复，9/1 出现一次明显的节律重置，主睡眠为 23:36-07:58。"
            "后半周主睡眠再次缩短，其中 9/4 为 01:02-05:07，并与赶早班飞机的 Daily Log 相互印证。"
            "因此本周最终仍表现为较大波动，但中间确实出现过作息调整过程。"
            "午睡出现在 8/30 和 9/4，其中 9/4 午睡采用 normalized sleep 数据。"
        ),
        "",
        "## 活动量",
        "",
        f"- 总步数：{activity_stats['total_steps_display']:,} 步",
        f"- 日均步数：{activity_stats['average_steps_display']:,} 步",
        f"- 最高：{activity_stats['max_steps']['date']}，{activity_stats['max_steps']['display_count']:,} 步",
        f"- 最低：{activity_stats['min_steps']['date']}，{activity_stats['min_steps']['display_count']:,} 步",
    ]
    for workout in activity["workouts"]:
        lines.append(f"- 正式 workout：{render_workout(workout)}")
    lines.extend(
        [
            "",
            "本周步数峰值集中在 9/3，并且当天存在一次正式户外步行；其余日期多为日常移动量。这里只把 9/3 的户外步行视为 workout，不把普通走路自动写成正式运动。",
            "",
            "## 学习",
            "",
            f"- confirmed_self_study_minutes：{study['confirmed_self_study_minutes']} 分钟",
            f"- class_minutes：{study['class_minutes']} 分钟",
            f"- recorded_but_uncertain_minutes：{study['recorded_but_uncertain_minutes']} 分钟",
            f"- 按科目可确认自主学习：{format_subject_minutes(study['confirmed_study_minutes_by_subject'])}",
            f"- 按科目课程/上课：{format_subject_minutes(study['class_minutes_by_subject'])}",
            "",
            "模糊但值得保留的学习记录：",
        ]
    )
    lines.extend(format_record_list(study["vague_records"], fallback="- (none)"))
    lines.extend(
        [
            "",
            (
                "Study 校对结果显示，8/30 没有学习记录，8/31 已出现英语自主学习和两门学校课程，"
                "9/1 之后英语、曲式、和声、音乐史开始并行出现。"
                "可精确统计的自主学习主要集中在 9/1、9/2、9/3、9/4；课程时间单独列出，未与自主学习合并。"
                "9/4 的钢琴课按课程记录保留，不进入自主学习或练琴净时长统计。"
            ),
            "",
            "## 练琴",
            "",
            f"- confirmed_practice_minutes：{piano['confirmed_practice_minutes']} 分钟",
            f"- uncertain_net_duration：{piano['uncertain_span_minutes']} 分钟记录跨度，净时长 unknown",
            f"- 本周出现的作品/曲目：{', '.join(piano['works']) if piano['works'] else '(none)'}",
            "",
            "有明确时间跨度但净时长未知的记录：",
        ]
    )
    lines.extend(
        [
            f"- {item['date']}：recorded_span_minutes={item['recorded_span_minutes']}；net_duration_minutes=unknown"
            for item in piano["uncertain_spans"]
        ]
        or ["- (none)"]
    )
    lines.extend(
        [
            "",
            "跨日变化候选：",
            "- 左手/左手腕：9/1 写到左手机能问题，9/4 写到左手手腕还是不太行。",
            "- 慢练：9/1 提到“得慢练”，9/4 写到“一直在慢练也没上力量”。",
            "- 音色控制：9/3 听录音后记录“音色可炸了”“一点都没有控制”。",
            "- 完整演奏/录像：9/2 记录完整过一遍并录像，9/3 记录录像时越到后面越紧张。",
            "- 整体演奏/练琴心理阴影：8/30 写到“练琴的时候没有紧张，感觉心里阴影在慢慢变淡”，9/4 有外部反馈“比之前放得开咯”。",
            "- 特定情境下的完整演奏压力：9/3 写到录像且前面完成得较好时越到后面越紧张；一旦已经出现错音，紧张反而消失。这个线索不应写成简单的“改善后反复”。",
            "",
            "## 情绪与状态",
            "",
            (
                "Mood 与 Daily Log 中多次主动记录“平静”“稳定”一类表达。"
                "期间仍存在由具体事件触发的明显情绪，例如 8/31 与妈妈关于睡眠数据的对话、9/1 关于九月的思考、9/3 的“略酸”、9/4 龚爽老师去世带来的难受。"
                "更稳妥的候选观察是：具体情绪仍然会发生，但从本周记录看，它们较少继续占据余下的一整天；总体状态与局部情绪波动可以同时存在。"
                "这部分不做量化，不写成“没有情绪”或“情绪已经改善”。For You 中的关系内容先不整体并入本节。"
            ),
            "",
            "## 留给老师",
            "",
            "本周 For You 原文索引：",
        ]
    )
    for quote in draft["for_you_quotes"]:
        lines.append(f"- {quote['date']}：{quote['text']}")
    lines.extend(["", "可能值得周末人工回看的原文片段："])
    for quote in draft["selected_for_you_candidates"]:
        lines.append(f"- {quote['date']}：{quote['text']}")
    lines.extend(["", "[人工填写最终版本]", "", "## 边角料", ""])
    selected_bits = draft["selected_bits_candidates"]
    lines.extend([f"- {quote['date']} [{quote['section']}]：{quote['text']}" for quote in selected_bits])
    lines.extend(["", "## 人工确认", ""])
    for item in draft["manual_confirmation_items"]:
        lines.append(f"- {item['date']} [{item['section']}] {'；'.join(item['reasons'])}：{item['text']}")
    return "\n".join(lines).rstrip() + "\n"


def format_subject_minutes(values: dict[str, int]) -> str:
    if not values:
        return "(none)"
    return "；".join(f"{subject} {minutes}分钟" for subject, minutes in values.items())


def format_record_list(records: list[dict[str, Any]], *, fallback: str) -> list[str]:
    if not records:
        return [fallback]
    return [f"- {record['date']}：{record['text']}" for record in records]


def write_outputs(draft: dict[str, Any], *, output_dir: Path = REPORT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    week = draft["week"]
    stem = f"{week['label'].lower().replace(' ', '-')}_{week['week_start']}_{week['week_end']}_draft"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(draft), encoding="utf-8")
    return json_path, markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a reviewable Week draft from structured data and notes.")
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--sleep-week", type=Path, required=True)
    parser.add_argument("--activity-week", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    draft = build_draft(load_json(args.notes), load_json(args.sleep_week), load_json(args.activity_week))
    for path in write_outputs(draft, output_dir=args.output_dir):
        print(path)


if __name__ == "__main__":
    main()
