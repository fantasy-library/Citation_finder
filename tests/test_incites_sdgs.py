"""Unit tests for InCites SDG parsing (no live API)."""
import json
import unittest
from pathlib import Path

import wos_incites_lib as lib

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "incites_sdg_sample.json"


class InCitesSdgParserTests(unittest.TestCase):
    def test_normalize_wos_ut(self):
        self.assertEqual(lib.normalize_wos_ut("WOS:000259986300005"), "000259986300005")
        self.assertEqual(lib.normalize_wos_ut("000259986300005"), "000259986300005")
        self.assertIsNone(lib.normalize_wos_ut("N/A"))

    def test_resolve_incites_api_key_prefers_dedicated(self):
        self.assertEqual(lib.resolve_incites_api_key("wos", "incites"), "incites")
        self.assertEqual(lib.resolve_incites_api_key("wos", ""), "wos")

    def test_parse_fixture_percentile_sdgs(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        by_ut = lib.parse_incites_sdg_payload(payload)
        labels = by_ut.get("000259986300005") or []
        self.assertEqual(len(labels), 2)
        self.assertTrue(any("SDG 3" in x for x in labels))
        self.assertTrue(any("SDG 16" in x for x in labels))
        self.assertEqual(lib.format_incites_sdg_cell(labels).count(";"), 1)

    def test_incites_row_columns(self):
        cols = lib.incites_sdg_row_columns("SDG 3: Good Health", "Success")
        self.assertEqual(cols["InCites SDGs"], "SDG 3: Good Health")
        self.assertEqual(cols["Status (InCites SDG)"], "Success")


if __name__ == "__main__":
    unittest.main()