from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = PROJECT_ROOT / "data/reports"
FIGURE_DIR = REPORT_DIR / "week-01_2026-08-30_2026-09-05_figures"
WEEK_DATES = ["2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"]
WIDTH = 1500
HEIGHT = 900
MARGIN = {"left": 150, "right": 90, "top": 105, "bottom": 120}
FONT = "Arial, Helvetica, sans-serif"
COLORS = {
    "ink": "#222222",
    "muted": "#666666",
    "grid": "#dddddd",
    "axis": "#333333",
    "main": "#506f8f",
    "nap": "#a9bfd2",
    "single": "#6f879f",
    "marker": "#8d9aaa",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_week_days(days: list[dict[str, Any]], *, source: str) -> None:
    actual = [day["date"] for day in days]
    if actual != WEEK_DATES:
        raise ValueError(f"{source} must contain Week 01 dates in order: expected {WEEK_DATES}, got {actual}")


def sleep_duration_data(sleep_week: dict[str, Any]) -> list[dict[str, Any]]:
    validate_week_days(sleep_week["days"], source="sleep_week")
    rows = []
    for day in sleep_week["days"]:
        main_minutes = day["main_sleep"]["asleep_total_minutes"]
        nap_minutes = sum(nap["asleep_total_minutes"] for nap in day.get("naps", []))
        rows.append(
            {
                "date": day["date"],
                "label": day["date"][5:].replace("-", "/"),
                "main_minutes": main_minutes,
                "nap_minutes": nap_minutes,
                "main_hours": main_minutes / 60,
                "nap_hours": nap_minutes / 60,
            }
        )
    return rows


def map_sleep_time(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    hour = parsed.hour + parsed.minute / 60 + parsed.second / 3600
    return hour if hour >= 18 else hour + 24


def sleep_timing_data(sleep_week: dict[str, Any]) -> list[dict[str, Any]]:
    validate_week_days(sleep_week["days"], source="sleep_week")
    rows = []
    for day in sleep_week["days"]:
        main = day["main_sleep"]
        start_mapped = map_sleep_time(main["start"])
        end_mapped = map_sleep_time(main["end"])
        if end_mapped < start_mapped:
            end_mapped += 24
        rows.append(
            {
                "date": day["date"],
                "label": day["date"][5:].replace("-", "/"),
                "start": main["start"],
                "end": main["end"],
                "start_mapped_hour": start_mapped,
                "end_mapped_hour": end_mapped,
            }
        )
    return rows


def steps_data(activity_week: dict[str, Any]) -> list[dict[str, Any]]:
    validate_week_days(activity_week["days"], source="activity_week")
    return [
        {
            "date": day["date"],
            "label": day["date"][5:].replace("-", "/"),
            "steps": day["steps"]["display_count"],
            "workout_count": day.get("workout_count", 0),
        }
        for day in activity_week["days"]
    ]


def study_subject_data(draft: dict[str, Any]) -> list[dict[str, Any]]:
    values = draft["study"]["confirmed_study_minutes_by_subject"]
    return [
        {"subject": subject, "minutes": minutes, "hours": minutes / 60}
        for subject, minutes in sorted(values.items(), key=lambda item: item[1], reverse=True)
    ]


def x_linear(value: float, domain: tuple[float, float], plot: tuple[float, float]) -> float:
    start, end = domain
    left, right = plot
    return left + (value - start) / (end - start) * (right - left)


def y_linear(value: float, domain: tuple[float, float], plot: tuple[float, float]) -> float:
    start, end = domain
    bottom, top = plot
    return bottom - (value - start) / (end - start) * (bottom - top)


def svg_header(title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="75" y="58" font-family="{FONT}" font-size="34" font-weight="600" fill="{COLORS["ink"]}">{escape(title)}</text>',
    ]


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def text(x: float, y: float, value: str, *, size: int = 20, anchor: str = "middle", color: str = COLORS["ink"]) -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" text-anchor="{anchor}" fill="{color}">{escape(value)}</text>'


def rotated_text(x: float, y: float, value: str, *, size: int = 20, color: str = COLORS["ink"]) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" text-anchor="middle" '
        f'fill="{color}" transform="rotate(-90 {x:.1f} {y:.1f})">{escape(value)}</text>'
    )


def line(x1: float, y1: float, x2: float, y2: float, *, color: str = COLORS["axis"], width: float = 2) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"/>'


def rect(x: float, y: float, w: float, h: float, *, color: str) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{color}"/>'


def render_sleep_duration_svg(rows: list[dict[str, Any]]) -> str:
    plot_left, plot_right = MARGIN["left"], WIDTH - MARGIN["right"]
    plot_top, plot_bottom = MARGIN["top"], HEIGHT - MARGIN["bottom"]
    max_hours = max(row["main_hours"] + row["nap_hours"] for row in rows)
    y_max = max(8, math.ceil(max_hours + 1))
    bar_w = 92
    gap = (plot_right - plot_left) / len(rows)
    lines = svg_header("Daily Sleep Duration")
    for tick in range(0, y_max + 1, 2):
        y = y_linear(tick, (0, y_max), (plot_bottom, plot_top))
        lines.extend([line(plot_left, y, plot_right, y, color=COLORS["grid"], width=1), text(plot_left - 22, y + 7, str(tick), size=18, anchor="end", color=COLORS["muted"])])
    lines.extend([line(plot_left, plot_bottom, plot_right, plot_bottom), line(plot_left, plot_bottom, plot_left, plot_top)])
    for idx, row in enumerate(rows):
        x = plot_left + gap * idx + gap / 2 - bar_w / 2
        main_h = plot_bottom - y_linear(row["main_hours"], (0, y_max), (plot_bottom, plot_top))
        nap_h = plot_bottom - y_linear(row["nap_hours"], (0, y_max), (plot_bottom, plot_top))
        lines.append(rect(x, plot_bottom - main_h, bar_w, main_h, color=COLORS["main"]))
        if row["nap_minutes"]:
            lines.append(rect(x, plot_bottom - main_h - nap_h, bar_w, nap_h, color=COLORS["nap"]))
        lines.append(text(x + bar_w / 2, plot_bottom + 34, row["label"], size=19))
    lines.extend(
        [
            rotated_text(62, (plot_top + plot_bottom) / 2, "Sleep duration (hours)", size=20),
            rect(plot_right - 235, 55, 28, 18, color=COLORS["main"]),
            text(plot_right - 197, 71, "Main sleep", size=18, anchor="start"),
            rect(plot_right - 95, 55, 28, 18, color=COLORS["nap"]),
            text(plot_right - 57, 71, "Nap", size=18, anchor="start"),
            "</svg>",
        ]
    )
    return "\n".join(lines)


def render_sleep_timing_svg(rows: list[dict[str, Any]]) -> str:
    plot_left, plot_right = MARGIN["left"], WIDTH - MARGIN["right"]
    plot_top, plot_bottom = MARGIN["top"], HEIGHT - MARGIN["bottom"]
    domain = (18, 38)
    lines = svg_header("Sleep Timing Across the Week")
    ticks = [(18, "18:00"), (24, "00:00"), (30, "06:00"), (36, "12:00"), (38, "14:00")]
    for value, label in ticks:
        x = x_linear(value, domain, (plot_left, plot_right))
        lines.extend([line(x, plot_top, x, plot_bottom, color=COLORS["grid"], width=1), text(x, plot_bottom + 34, label, size=18)])
    row_gap = (plot_bottom - plot_top) / (len(rows) - 1)
    for idx, row in enumerate(rows):
        y = plot_top + idx * row_gap
        x1 = x_linear(row["start_mapped_hour"], domain, (plot_left, plot_right))
        x2 = x_linear(row["end_mapped_hour"], domain, (plot_left, plot_right))
        lines.append(text(plot_left - 30, y + 7, row["label"], size=19, anchor="end"))
        lines.append(line(x1, y, x2, y, color=COLORS["main"], width=15))
        lines.append(f'<circle cx="{x1:.1f}" cy="{y:.1f}" r="7" fill="{COLORS["main"]}"/>')
        lines.append(f'<circle cx="{x2:.1f}" cy="{y:.1f}" r="7" fill="{COLORS["main"]}"/>')
        lines.append(text(x1, y - 19, datetime.fromisoformat(row["start"]).strftime("%H:%M"), size=15, color=COLORS["muted"]))
        lines.append(text(x2, y - 19, datetime.fromisoformat(row["end"]).strftime("%H:%M"), size=15, color=COLORS["muted"]))
    lines.extend([line(plot_left, plot_bottom, plot_right, plot_bottom), "</svg>"])
    return "\n".join(lines)


def render_steps_svg(rows: list[dict[str, Any]]) -> str:
    plot_left, plot_right = MARGIN["left"], WIDTH - MARGIN["right"]
    plot_top, plot_bottom = MARGIN["top"], HEIGHT - MARGIN["bottom"]
    y_max = math.ceil(max(row["steps"] for row in rows) / 3000) * 3000
    bar_w = 92
    gap = (plot_right - plot_left) / len(rows)
    lines = svg_header("Daily Steps")
    for tick in range(0, y_max + 1, 3000):
        y = y_linear(tick, (0, y_max), (plot_bottom, plot_top))
        lines.extend([line(plot_left, y, plot_right, y, color=COLORS["grid"], width=1), text(plot_left - 22, y + 7, f"{tick:,}", size=18, anchor="end", color=COLORS["muted"])])
    lines.extend([line(plot_left, plot_bottom, plot_right, plot_bottom), line(plot_left, plot_bottom, plot_left, plot_top)])
    for idx, row in enumerate(rows):
        x = plot_left + gap * idx + gap / 2 - bar_w / 2
        h = plot_bottom - y_linear(row["steps"], (0, y_max), (plot_bottom, plot_top))
        lines.append(rect(x, plot_bottom - h, bar_w, h, color=COLORS["single"]))
        lines.append(text(x + bar_w / 2, plot_bottom + 34, row["label"], size=19))
        if row["workout_count"]:
            lines.append(f'<circle cx="{x + bar_w / 2:.1f}" cy="{plot_bottom - h - 17:.1f}" r="4" fill="{COLORS["marker"]}"/>')
    lines.extend([rotated_text(62, (plot_top + plot_bottom) / 2, "Steps", size=20), "</svg>"])
    return "\n".join(lines)


def render_study_svg(rows: list[dict[str, Any]]) -> str:
    plot_left, plot_right = 240, WIDTH - MARGIN["right"]
    plot_top, plot_bottom = MARGIN["top"], HEIGHT - MARGIN["bottom"]
    x_max = math.ceil(max(row["hours"] for row in rows) * 2) / 2
    x_max = max(3.5, x_max)
    row_gap = (plot_bottom - plot_top) / len(rows)
    bar_h = 58
    lines = svg_header("Confirmed Self-study Time by Subject")
    tick_count = int(x_max * 2) + 1
    for i in range(tick_count):
        value = i * 0.5
        x = x_linear(value, (0, x_max), (plot_left, plot_right))
        label = f"{value:.1f}" if value % 1 else f"{int(value)}"
        lines.extend([line(x, plot_top, x, plot_bottom, color=COLORS["grid"], width=1), text(x, plot_bottom + 34, label, size=18, color=COLORS["muted"])])
    lines.extend([line(plot_left, plot_bottom, plot_right, plot_bottom), line(plot_left, plot_bottom, plot_left, plot_top)])
    for idx, row in enumerate(rows):
        y = plot_top + idx * row_gap + row_gap / 2 - bar_h / 2
        w = x_linear(row["hours"], (0, x_max), (plot_left, plot_right)) - plot_left
        lines.append(text(plot_left - 25, y + bar_h / 2 + 7, row["subject"], size=20, anchor="end"))
        lines.append(rect(plot_left, y, w, bar_h, color=COLORS["single"]))
        lines.append(text(plot_left + w + 12, y + bar_h / 2 + 7, f"{row['hours']:.1f} h", size=18, anchor="start", color=COLORS["muted"]))
    lines.extend([text((plot_left + plot_right) / 2, plot_bottom + 78, "Hours", size=20), "</svg>"])
    return "\n".join(lines)


def write_svg(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def convert_svg_to_png(svg_path: Path, *, size: int = 2400) -> Path:
    svg_path = svg_path.resolve()
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    png_path = svg_path.with_suffix(".png")
    if chrome.exists():
        subprocess.run(
            [
                str(chrome),
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--force-device-scale-factor=2",
                f"--screenshot={png_path}",
                f"--window-size={WIDTH},{HEIGHT}",
                svg_path.as_uri(),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return png_path
    subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", str(svg_path.parent), str(svg_path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    generated = svg_path.with_name(svg_path.name + ".png")
    if generated.exists():
        shutil.move(str(generated), str(png_path))
    if not png_path.exists():
        raise RuntimeError(f"PNG conversion did not produce {png_path}")
    return png_path


def build_figures(sleep_week: dict[str, Any], activity_week: dict[str, Any], draft: dict[str, Any], *, output_dir: Path = FIGURE_DIR, convert_png: bool = True) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_specs = [
        {
            "figure_id": "fig01_sleep_duration",
            "title": "Daily Sleep Duration",
            "data": sleep_duration_data(sleep_week),
            "renderer": render_sleep_duration_svg,
            "source_data": ["data/aggregates/sleep/week-01_2026-08-30_2026-09-05.json"],
            "metric_definition": "Daily main sleep asleep_total_minutes plus nap asleep_total_minutes, displayed in hours.",
            "caption_candidate": "Daily main sleep and nap duration for Week 01. Durations use asleep minutes from normalized sleep data, not total time in bed.",
            "notes": ["Naps are present on 2026-08-30 and 2026-09-04."],
        },
        {
            "figure_id": "fig02_sleep_timing",
            "title": "Sleep Timing Across the Week",
            "data": sleep_timing_data(sleep_week),
            "renderer": render_sleep_timing_svg,
            "source_data": ["data/aggregates/sleep/week-01_2026-08-30_2026-09-05.json"],
            "metric_definition": "Main sleep start and end timestamps mapped onto a continuous 18:00 to next day 14:00 axis.",
            "caption_candidate": "Main sleep timing across Week 01. Intervals are mapped across midnight to avoid splitting overnight sleep.",
            "notes": ["Only main sleep is shown; naps are excluded to keep timing readable."],
        },
        {
            "figure_id": "fig03_daily_steps",
            "title": "Daily Steps",
            "data": steps_data(activity_week),
            "renderer": render_steps_svg,
            "source_data": ["data/aggregates/activity/week-01_2026-08-30_2026-09-05.json"],
            "metric_definition": "Daily display_count from activity.weekly.v1.",
            "caption_candidate": "Daily step counts for Week 01. Rounded presentation values are used; 2026-09-03 includes one formal outdoor walking workout.",
            "notes": ["No target line is shown."],
        },
        {
            "figure_id": "fig04_study_by_subject",
            "title": "Confirmed Self-study Time by Subject",
            "data": study_subject_data(draft),
            "renderer": render_study_svg,
            "source_data": ["data/reports/week-01_2026-08-30_2026-09-05_draft.json"],
            "metric_definition": "Confirmed self-study minutes by subject from draft.json, converted to hours for display.",
            "caption_candidate": "Only confirmed self-study intervals are included; class time and uncertain spans are excluded.",
            "notes": ["Subjects are sorted by confirmed self-study minutes descending."],
        },
    ]
    manifest = {"figures": []}
    for spec in figure_specs:
        svg_path = output_dir / f"{spec['figure_id']}.svg"
        write_svg(svg_path, spec["renderer"](spec["data"]))
        output_files = {"svg": str(svg_path)}
        if convert_png:
            output_files["png"] = str(convert_svg_to_png(svg_path))
        manifest["figures"].append(
            {
                "figure_id": spec["figure_id"],
                "title": spec["title"],
                "source_data": spec["source_data"],
                "metric_definition": spec["metric_definition"],
                "output_files": output_files,
                "caption_candidate": spec["caption_candidate"],
                "notes": spec["notes"],
                "data": spec["data"],
            }
        )
    manifest_path = output_dir / "figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Week 01 report figures.")
    parser.add_argument("--sleep-week", type=Path, required=True)
    parser.add_argument("--activity-week", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=FIGURE_DIR)
    parser.add_argument("--no-png", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = build_figures(
        load_json(args.sleep_week),
        load_json(args.activity_week),
        load_json(args.draft),
        output_dir=args.output_dir,
        convert_png=not args.no_png,
    )
    print(json.dumps({"figures": [item["output_files"] for item in manifest["figures"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
