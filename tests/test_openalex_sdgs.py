"""Unit tests for OpenAlex SDG parsing (no live API)."""
import unittest

import openalex_lib as lib


class OpenAlexSdgTests(unittest.TestCase):
    def test_normalize_doi(self):
        self.assertEqual(lib.normalize_doi("10.7717/peerj.4375"), "10.7717/peerj.4375")
        self.assertEqual(
            lib.normalize_doi("https://doi.org/10.1038/nature11018"),
            "10.1038/nature11018",
        )
        self.assertEqual(lib.normalize_doi("doi:10.7717/peerj.4375"), "10.7717/peerj.4375")

    def test_sdg_labels_from_work_sorted(self):
        work = {
            "sustainable_development_goals": [
                {
                    "id": "https://metadata.un.org/sdg/3",
                    "display_name": "Good health and well-being",
                    "score": 0.55,
                },
                {
                    "id": "https://metadata.un.org/sdg/13",
                    "display_name": "Climate action",
                    "score": 0.82,
                },
            ]
        }
        labels = lib.sdg_labels_from_work(work)
        self.assertEqual(len(labels), 2)
        self.assertIn("0.820", labels[0])
        self.assertIn("SDG 13", labels[0])

    def test_empty_work_and_row_columns(self):
        labels = lib.sdg_labels_from_work({"sustainable_development_goals": []})
        self.assertEqual(lib.format_openalex_sdg_cell(labels), "N/A")
        cols = lib.openalex_sdg_row_columns("N/A", "No tags")
        self.assertEqual(cols["OpenAlex SDGs"], "N/A")
        self.assertEqual(cols["Status (OpenAlex SDG)"], "No tags")


if __name__ == "__main__":
    unittest.main()