"""Unit tests for FWCI parsing (no API calls)."""
import unittest

import fwci_lib as lib


class FwciParserTests(unittest.TestCase):
    def test_parse_fwci_metrics_publication_block(self):
        payload = {
            "results": [
                {
                    "publication": {"id": 85092481765, "publicationYear": 2020},
                    "metrics": [
                        {
                            "metricType": "FieldWeightedCitationImpact",
                            "value": 1.214,
                            "valueByYear": {"2020": 1.1, "2021": 1.214},
                        }
                    ],
                }
            ]
        }
        found = lib._parse_fwci_metrics(payload, requested_ids=["85092481765"], publication_year=2020)
        self.assertAlmostEqual(found["85092481765"], 1.1)

    def test_scopus_id_from_citations_legend(self):
        payload = {
            "abstract-citations-response": {
                "identifier-legend": {
                    "identifier": [{"scopus_id": "85092481765"}],
                },
                "citeInfoMatrix": {
                    "citeInfoMatrixXML": {
                        "citationMatrix": {
                            "citeInfo": [{"sort-year": "2020", "dc:title": "Example"}],
                        }
                    }
                },
            }
        }
        pub_id, year = lib.scopus_id_year_from_citations_payload(payload)
        self.assertEqual(pub_id, "85092481765")
        self.assertEqual(year, 2020)

    def test_build_fwci_query_attempts_unique(self):
        attempts = lib._build_fwci_query_attempts(2020)
        keys = [(a["byYear"], a["yearRange"]) for a in attempts]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(attempts[0], {"byYear": "true", "yearRange": "5yrs"})

    def test_parse_rate_limit_headers(self):
        headers = {
            "X-RateLimit-Limit": "20000",
            "X-RateLimit-Remaining": "1227",
            "X-RateLimit-Reset": "1692342443",
            "X-ELS-Status": "OK",
        }
        parsed = lib.parse_elsevier_rate_limit_headers(headers)
        self.assertEqual(parsed["remaining"], 1227)
        self.assertEqual(parsed["limit"], 20000)
        self.assertEqual(parsed["els_status"], "OK")
        self.assertIn("UTC", parsed["reset_at"])

    def test_collect_multiple_sdgs(self):
        publication = {
            "sdg": [
                "SDG 3: Good Health and Well-being",
                "SDG 16: Peace, Justice and Strong Institutions",
            ]
        }
        self.assertEqual(len(lib._collect_publication_sdgs(publication)), 2)
        cols = lib._scival_optional_row_columns(publication, include_sdg=True)
        self.assertIn("SDG 3", cols["SciVal SDGs"])
        self.assertIn("SDG 16", cols["SciVal SDGs"])
        self.assertIn(";", cols["SciVal SDGs"])


if __name__ == "__main__":
    unittest.main()
