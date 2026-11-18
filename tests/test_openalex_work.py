"""Unit tests for OpenAlex work export parsing (no live API)."""
import json
import unittest
from pathlib import Path

import openalex_lib as lib

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "openalex_work_sample.json"


class OpenAlexWorkExportTests(unittest.TestCase):
    def setUp(self):
        self.work = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def test_parse_full_row(self):
        row = lib.parse_work_export_row(
            self.work,
            "10.7717/peerj.4375",
            include=lib.DEFAULT_OPENALEX_PACKS,
        )
        self.assertEqual(row["DOI"], "10.7717/peerj.4375")
        self.assertEqual(row["OpenAlex citations"], "382")
        self.assertEqual(row["OpenAlex FWCI"], "12.500")
        self.assertEqual(row["Top 1% cited"], "Yes")
        self.assertEqual(row["OA status"], "gold")
        self.assertEqual(row["Source title"], "PeerJ")
        self.assertIn("Alice Author", row["Authors"])
        self.assertIn("SDG 14", row["OpenAlex SDGs"])
        self.assertEqual(row["Retracted"], "No")
        self.assertIn("National Science Foundation", row["Grants"])

    def test_export_column_order_matches_packs(self):
        packs = {
            "citations_impact": True,
            "bibliographic": False,
            "open_access": False,
            "topics": False,
            "authors": False,
            "ids_grants": False,
            "sdgs": False,
            "retraction": False,
            "openalex_url": False,
        }
        cols = lib.openalex_export_column_order(packs)
        self.assertIn("OpenAlex FWCI", cols)
        self.assertNotIn("OA status", cols)

    def test_build_work_row_not_found(self):
        row = lib.parse_work_export_row(
            None,
            "10.0000/none",
            include={"sdgs": True, **{k: False for k in lib.DEFAULT_OPENALEX_PACKS if k != "sdgs"}},
            lookup_status="Not found in OpenAlex",
        )
        self.assertEqual(row["Status"], "Not found in OpenAlex")
        self.assertEqual(row["OpenAlex SDGs"], "N/A")


if __name__ == "__main__":
    unittest.main()