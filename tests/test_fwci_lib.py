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


if __name__ == "__main__":
    unittest.main()
