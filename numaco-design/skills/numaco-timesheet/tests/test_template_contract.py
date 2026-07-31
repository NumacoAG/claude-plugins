#!/usr/bin/env python3
"""Regression contract for the approved Numaco timesheet table layout."""

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "build_timesheet.py"
SAMPLE_PAYLOAD = SKILL_DIR / "sample" / "sample_payload.json"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_timesheet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TimesheetTemplateContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load_builder()
        cls.payload = json.loads(SAMPLE_PAYLOAD.read_text(encoding="utf-8"))

    def test_activity_cells_are_vertically_centered(self):
        css = self.builder._TS_CSS
        self.assertIn("table.data td.tse{", css)
        self.assertIn("vertical-align:middle", css)

    def test_date_size_tracks_owner_size(self):
        css = self.builder._TS_CSS
        self.assertIn(
            "table.data td.tse.ref{ font-size:var(--fs-table_body,9pt) !important;",
            css,
        )

    def test_work_mix_has_explicit_page_boundaries(self):
        section = self.builder._work_mix_section(self.payload)
        self.assertTrue(section.startswith('<div class="pagebreak"></div>'))
        self.assertTrue(section.endswith('<div class="pagebreak"></div>'))
        self.assertIn('<div class="work-mix-page">', section)

    def test_work_mix_cards_cannot_fragment(self):
        css = self.builder._TS_CSS
        self.assertIn(
            ".category-grid{ display:grid; grid-template-columns:1fr 1fr; gap:3mm;"
            " margin:5mm 0 7mm; page-break-inside:avoid; break-inside:avoid-page;",
            css,
        )
        self.assertIn(
            "page-break-inside:avoid; break-inside:avoid-page; }",
            css,
        )


if __name__ == "__main__":
    unittest.main()
