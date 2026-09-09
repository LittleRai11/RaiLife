from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from railife.pipelines.generate_week_figures import (
    FIGURE_DIR,
    COLORS,
    FONT,
    HEIGHT,
    WIDTH,
    load_json,
    sleep_duration_data,
    sleep_timing_data,
    steps_data,
    study_subject_data,
    x_linear,
    y_linear,
)


MULTI_WIDTH = WIDTH
MULTI_HEIGHT = 1600
PANEL_LEFT = 155
PANEL_RIGHT = MULTI_WIDTH - 90
PANEL_TOPS = [105, 875]
PANEL_BOTTOMS = [710, 1480]
PANEL_LABEL_X = 76
PANEL_LABEL_DY = -42
PANEL_LABEL_SIZE = 25
PANEL_LABEL_WEIGHT = "700"


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def text(x: float, y: float, value: str, *, size: int = 20, anchor: str = "middle", color: str = COLORS["ink"], weight: str = "400") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}" fill="{color}">{escape(value)}</text>'
    )


def rotated_text(x: float, y: float, value: str, *, size: int = 20) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" text-anchor="middle" '
        f'fill="{COLORS["ink"]}" transform="rotate(-90 {x:.1f} {y:.1f})">{escape(value)}</text>'
    )


def line(x1: float, y1: float, x2: float, y2: float, *, color: str = COLORS["axis"], width: float = 2) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"/>'


def rect(x: float, y: float, w: float, h: float, *, color: str) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{color}"/>'


def panel_label(label: str, x: float, y: float) -> str:
    return text(x, y, label, size=PANEL_LABEL_SIZE, anchor="start", weight=PANEL_LABEL_WEIGHT)


def panel_label_at(label: str, *, panel_index: int) -> str:
    return panel_label(label, PANEL_LABEL_X, PANEL_TOPS[panel_index] + PANEL_LABEL_DY)


def svg_start() -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{MULTI_WIDTH}" height="{MULTI_HEIGHT}" viewBox="0 0 {MULTI_WIDTH} {MULTI_HEIGHT}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]


def render_sleep_duration_panel(rows: list[dict[str, Any]], *, panel_index: int) -> list[str]:
    plot_left, plot_right = PANEL_LEFT, PANEL_RIGHT
    plot_top, plot_bottom = PANEL_TOPS[panel_index], PANEL_BOTTOMS[panel_index]
    max_hours = max(row["main_hours"] + row["nap_hours"] for row in rows)
    y_max = max(8, math.ceil(max_hours + 1))
    bar_w = 76
    gap = (plot_right - plot_left) / len(rows)
    lines = [panel_label_at("a", panel_index=panel_index)]
    for tick in range(0, y_max + 1, 2):
        y = y_linear(tick, (0, y_max), (plot_bottom, plot_top))
        lines.append(line(plot_left, y, plot_right, y, color=COLORS["grid"], width=1))
        lines.append(text(plot_left - 22, y + 7, str(tick), size=17, anchor="end", color=COLORS["muted"]))
    lines.extend([line(plot_left, plot_bottom, plot_right, plot_bottom), line(plot_left, plot_bottom, plot_left, plot_top)])
    for idx, row in enumerate(rows):
        x = plot_left + gap * idx + gap / 2 - bar_w / 2
        main_h = plot_bottom - y_linear(row["main_hours"], (0, y_max), (plot_bottom, plot_top))
        nap_h = plot_bottom - y_linear(row["nap_hours"], (0, y_max), (plot_bottom, plot_top))
        lines.append(rect(x, plot_bottom - main_h, bar_w, main_h, color=COLORS["main"]))
        if row["nap_minutes"]:
            lines.append(rect(x, plot_bottom - main_h - nap_h, bar_w, nap_h, color=COLORS["nap"]))
        lines.append(text(x + bar_w / 2, plot_bottom + 31, row["label"], size=17))
    lines.extend(
        [
            rotated_text(64, (plot_top + plot_bottom) / 2, "Sleep duration (hours)", size=18),
            rect(plot_right - 230, plot_top - 49, 24, 16, color=COLORS["main"]),
            text(plot_right - 198, plot_top - 36, "Main sleep", size=16, anchor="start"),
            rect(plot_right - 92, plot_top - 49, 24, 16, color=COLORS["nap"]),
            text(plot_right - 60, plot_top - 36, "Nap", size=16, anchor="start"),
        ]
    )
    return lines


def render_sleep_timing_panel(rows: list[dict[str, Any]], *, panel_index: int) -> list[str]:
    plot_left, plot_right = PANEL_LEFT, PANEL_RIGHT
    plot_top, plot_bottom = PANEL_TOPS[panel_index], PANEL_BOTTOMS[panel_index]
    domain = (18, 38)
    lines = [panel_label_at("b", panel_index=panel_index)]
    ticks = [(18, "18:00"), (24, "00:00"), (30, "06:00"), (36, "12:00"), (38, "14:00")]
    for value, label in ticks:
        x = x_linear(value, domain, (plot_left, plot_right))
        lines.append(line(x, plot_top, x, plot_bottom, color=COLORS["grid"], width=1))
        lines.append(text(x, plot_bottom + 32, label, size=17))
    row_gap = (plot_bottom - plot_top) / (len(rows) - 1)
    for idx, row in enumerate(rows):
        y = plot_top + idx * row_gap
        x1 = x_linear(row["start_mapped_hour"], domain, (plot_left, plot_right))
        x2 = x_linear(row["end_mapped_hour"], domain, (plot_left, plot_right))
        lines.append(text(plot_left - 30, y + 7, row["label"], size=17, anchor="end"))
        lines.append(line(x1, y, x2, y, color=COLORS["main"], width=22))
        lines.append(f'<circle cx="{x1:.1f}" cy="{y:.1f}" r="9" fill="{COLORS["main"]}"/>')
        lines.append(f'<circle cx="{x2:.1f}" cy="{y:.1f}" r="9" fill="{COLORS["main"]}"/>')
        lines.append(text(x1, y - 23, datetime.fromisoformat(row["start"]).strftime("%H:%M"), size=14, color=COLORS["muted"]))
        lines.append(text(x2, y - 23, datetime.fromisoformat(row["end"]).strftime("%H:%M"), size=14, color=COLORS["muted"]))
    lines.append(line(plot_left, plot_bottom, plot_right, plot_bottom))
    return lines


def render_steps_panel(rows: list[dict[str, Any]], *, panel_index: int) -> list[str]:
    plot_left, plot_right = PANEL_LEFT, PANEL_RIGHT
    plot_top, plot_bottom = PANEL_TOPS[panel_index], PANEL_BOTTOMS[panel_index]
    y_max = math.ceil(max(row["steps"] for row in rows) / 3000) * 3000
    bar_w = 76
    gap = (plot_right - plot_left) / len(rows)
    lines = [panel_label_at("a", panel_index=panel_index)]
    for tick in range(0, y_max + 1, 3000):
        y = y_linear(tick, (0, y_max), (plot_bottom, plot_top))
        lines.append(line(plot_left, y, plot_right, y, color=COLORS["grid"], width=1))
        lines.append(text(plot_left - 22, y + 7, f"{tick:,}", size=17, anchor="end", color=COLORS["muted"]))
    lines.extend([line(plot_left, plot_bottom, plot_right, plot_bottom), line(plot_left, plot_bottom, plot_left, plot_top)])
    for idx, row in enumerate(rows):
        x = plot_left + gap * idx + gap / 2 - bar_w / 2
        h = plot_bottom - y_linear(row["steps"], (0, y_max), (plot_bottom, plot_top))
        lines.append(rect(x, plot_bottom - h, bar_w, h, color=COLORS["single"]))
        lines.append(text(x + bar_w / 2, plot_bottom + 31, row["label"], size=17))
        if row["workout_count"]:
            lines.append(f'<circle cx="{x + bar_w / 2:.1f}" cy="{plot_bottom - h - 17:.1f}" r="4" fill="{COLORS["marker"]}"/>')
    lines.append(rotated_text(64, (plot_top + plot_bottom) / 2, "Steps", size=18))
    return lines


def render_study_panel(rows: list[dict[str, Any]], *, panel_index: int) -> list[str]:
    plot_left, plot_right = 240, PANEL_RIGHT
    plot_top, plot_bottom = PANEL_TOPS[panel_index], PANEL_BOTTOMS[panel_index]
    x_max = max(3.5, math.ceil(max(row["hours"] for row in rows) * 2) / 2)
    row_gap = (plot_bottom - plot_top) / len(rows)
    bar_h = 54
    lines = [panel_label_at("b", panel_index=panel_index)]
    tick_count = int(x_max * 2) + 1
    for i in range(tick_count):
        value = i * 0.5
        x = x_linear(value, (0, x_max), (plot_left, plot_right))
        label = f"{value:.1f}" if value % 1 else f"{int(value)}"
        lines.append(line(x, plot_top, x, plot_bottom, color=COLORS["grid"], width=1))
        lines.append(text(x, plot_bottom + 32, label, size=17, color=COLORS["muted"]))
    lines.extend([line(plot_left, plot_bottom, plot_right, plot_bottom), line(plot_left, plot_bottom, plot_left, plot_top)])
    for idx, row in enumerate(rows):
        y = plot_top + idx * row_gap + row_gap / 2 - bar_h / 2
        w = x_linear(row["hours"], (0, x_max), (plot_left, plot_right)) - plot_left
        lines.append(text(plot_left - 25, y + bar_h / 2 + 7, row["subject"], size=19, anchor="end"))
        lines.append(rect(plot_left, y, w, bar_h, color=COLORS["single"]))
        lines.append(text(plot_left + w + 12, y + bar_h / 2 + 7, f"{row['hours']:.1f} h", size=17, anchor="start", color=COLORS["muted"]))
    lines.append(text((plot_left + plot_right) / 2, plot_bottom + 74, "Hours", size=18))
    return lines


def render_sleep_multipanel_svg(sleep_week: dict[str, Any]) -> str:
    lines = svg_start()
    lines.extend(render_sleep_duration_panel(sleep_duration_data(sleep_week), panel_index=0))
    lines.extend(render_sleep_timing_panel(sleep_timing_data(sleep_week), panel_index=1))
    lines.append("</svg>")
    return "\n".join(lines)


def render_activity_study_multipanel_svg(activity_week: dict[str, Any], draft: dict[str, Any]) -> str:
    lines = svg_start()
    lines.extend(render_steps_panel(steps_data(activity_week), panel_index=0))
    lines.extend(render_study_panel(study_subject_data(draft), panel_index=1))
    lines.append("</svg>")
    return "\n".join(lines)


def chrome_path() -> Path:
    return Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def render_png(svg_path: Path) -> Path:
    svg_path = svg_path.resolve()
    png_path = svg_path.with_suffix(".png")
    subprocess.run(
        [
            str(chrome_path()),
            "--headless",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--force-device-scale-factor=2",
            f"--screenshot={png_path}",
            f"--window-size={MULTI_WIDTH},{MULTI_HEIGHT}",
            svg_path.as_uri(),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return png_path


def render_pdf(svg_path: Path) -> Path:
    svg_path = svg_path.resolve()
    pdf_path = svg_path.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / f"{svg_path.stem}.html"
        html_path.write_text(print_wrapper_html(svg_path.read_text(encoding="utf-8")), encoding="utf-8")
        subprocess.run(
            [
                str(chrome_path()),
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--print-to-pdf={pdf_path}",
                "--no-pdf-header-footer",
                "--disable-print-preview",
                html_path.as_uri(),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    return pdf_path


def print_wrapper_html(svg: str) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
  size: {MULTI_WIDTH}px {MULTI_HEIGHT}px;
  margin: 0;
}}
html, body {{
  width: {MULTI_WIDTH}px;
  height: {MULTI_HEIGHT}px;
  margin: 0;
  padding: 0;
  background: #ffffff;
}}
svg {{
  display: block;
  width: {MULTI_WIDTH}px;
  height: {MULTI_HEIGHT}px;
}}
</style>
</head>
<body>{svg}</body>
</html>
"""


def build_multipanel_figures(
    sleep_week: dict[str, Any],
    activity_week: dict[str, Any],
    draft: dict[str, Any],
    *,
    output_dir: Path = FIGURE_DIR,
    convert_outputs: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        {
            "figure_id": "fig01_sleep_multipanel",
            "title": "Sleep duration and timing",
            "svg": render_sleep_multipanel_svg(sleep_week),
            "caption_candidate": "Panel a shows daily main sleep and nap duration. Panel b shows main sleep intervals mapped across midnight.",
            "source_data": ["data/aggregates/sleep/week-01_2026-08-30_2026-09-05.json"],
            "notes": ["Figure body intentionally omits figure numbering and long technical subtitles."],
        },
        {
            "figure_id": "fig02_activity_study_multipanel",
            "title": "Activity and confirmed self-study",
            "svg": render_activity_study_multipanel_svg(activity_week, draft),
            "caption_candidate": "Panel a shows daily step counts. Panel b includes only confirmed self-study intervals; class time and uncertain spans are excluded.",
            "source_data": [
                "data/aggregates/activity/week-01_2026-08-30_2026-09-05.json",
                "data/reports/week-01_2026-08-30_2026-09-05_draft.json",
            ],
            "notes": ["The small marker in panel a indicates the day with a formal workout; details should be stated in the caption."],
        },
    ]
    manifest = {"figures": []}
    for spec in specs:
        svg_path = output_dir / f"{spec['figure_id']}.svg"
        svg_path.write_text(spec["svg"], encoding="utf-8")
        output_files = {"svg": str(svg_path.resolve())}
        if convert_outputs:
            output_files["png"] = str(render_png(svg_path))
            output_files["pdf"] = str(render_pdf(svg_path))
        manifest["figures"].append(
            {
                "figure_id": spec["figure_id"],
                "title": spec["title"],
                "source_data": spec["source_data"],
                "output_files": output_files,
                "caption_candidate": spec["caption_candidate"],
                "notes": spec["notes"],
            }
        )
    manifest_path = output_dir / "multipanel_figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Week 01 multi-panel figure previews.")
    parser.add_argument("--sleep-week", type=Path, required=True)
    parser.add_argument("--activity-week", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=FIGURE_DIR)
    parser.add_argument("--no-convert", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = build_multipanel_figures(
        load_json(args.sleep_week),
        load_json(args.activity_week),
        load_json(args.draft),
        output_dir=args.output_dir,
        convert_outputs=not args.no_convert,
    )
    print(json.dumps({"figures": [item["output_files"] for item in manifest["figures"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
