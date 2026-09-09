from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from railife.pipelines.generate_week_multipanel_figures import (
    MULTI_HEIGHT,
    MULTI_WIDTH,
    PANEL_LABEL_DY,
    PANEL_LABEL_SIZE,
    PANEL_LABEL_WEIGHT,
    PANEL_LABEL_X,
    PANEL_TOPS,
    build_multipanel_figures,
    print_wrapper_html,
    render_activity_study_multipanel_svg,
    render_sleep_multipanel_svg,
)
from test_generate_week_figures import sample_activity_week, sample_sleep_week


class GenerateWeekMultipanelFiguresTests(unittest.TestCase):
    def test_sleep_multipanel_uses_panel_labels_without_figure_title(self) -> None:
        svg = render_sleep_multipanel_svg(sample_sleep_week())

        self.assertNotIn("Figure 1.", svg)
        self.assertNotIn("Daily Sleep Duration", svg)
        self.assertIn(">a</text>", svg)
        self.assertIn(">b</text>", svg)
        self.assertIn('stroke-width="22"', svg)
        self.assertIn(
            f'x="{PANEL_LABEL_X:.1f}" y="{PANEL_TOPS[0] + PANEL_LABEL_DY:.1f}"',
            svg,
        )
        self.assertIn(
            f'x="{PANEL_LABEL_X:.1f}" y="{PANEL_TOPS[1] + PANEL_LABEL_DY:.1f}"',
            svg,
        )
        self.assertIn(f'font-size="{PANEL_LABEL_SIZE}"', svg)
        self.assertIn(f'font-weight="{PANEL_LABEL_WEIGHT}"', svg)

    def test_activity_study_multipanel_excludes_technical_subtitles(self) -> None:
        draft = {"study": {"confirmed_study_minutes_by_subject": {"音乐史": 440, "英语": 265}}}
        svg = render_activity_study_multipanel_svg(sample_activity_week(), draft)

        self.assertNotIn("Rounded presentation", svg)
        self.assertNotIn("Class time and uncertain spans excluded", svg)
        self.assertNotIn(">workout<", svg)
        self.assertIn(">a</text>", svg)
        self.assertIn(">b</text>", svg)

    def test_build_multipanel_writes_svg_manifest_without_conversion_for_tests(self) -> None:
        draft = {"study": {"confirmed_study_minutes_by_subject": {"音乐史": 440}}}
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_multipanel_figures(
                sample_sleep_week(),
                sample_activity_week(),
                draft,
                output_dir=Path(tmp),
                convert_outputs=False,
            )
            files = sorted(path.name for path in Path(tmp).iterdir())

        self.assertEqual(len(manifest["figures"]), 2)
        self.assertIn("fig01_sleep_multipanel.svg", files)
        self.assertIn("fig02_activity_study_multipanel.svg", files)
        self.assertIn("multipanel_figure_manifest.json", files)

    def test_pdf_print_wrapper_preserves_full_canvas_size(self) -> None:
        wrapper = print_wrapper_html("<svg></svg>")

        self.assertIn("@page", wrapper)
        self.assertIn(f"size: {MULTI_WIDTH}px {MULTI_HEIGHT}px;", wrapper)
        self.assertIn("margin: 0;", wrapper)
        self.assertIn(f"width: {MULTI_WIDTH}px;", wrapper)
        self.assertIn(f"height: {MULTI_HEIGHT}px;", wrapper)


if __name__ == "__main__":
    unittest.main()
