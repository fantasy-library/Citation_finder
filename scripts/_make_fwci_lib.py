from pathlib import Path

root = Path(__file__).resolve().parents[1]
app_lines = (root / "app.py").read_text(encoding="utf-8").splitlines()
chunk = "\n".join(app_lines[1018:1801])

header = '''"""SciVal FWCI helpers (shared by app and CLI bulk check)."""
import re
import time
from urllib.parse import quote

import requests


def scival_api_error_message(service, status_code, response_body=None):
    body = (response_body or "").lower() if isinstance(response_body, str) else ""
    if status_code == 401:
        if service and str(service).lower() == "scival":
            return "SciVal FWCI is not enabled for this API key or institution."
        return "Invalid or missing API key. Check your credentials."
    if status_code == 403:
        if service and str(service).lower() == "scopus":
            return "Access denied. Scopus requires API key and institutional token."
        if service and str(service).lower() == "scival":
            return "SciVal FWCI is not enabled for this API key or institution."
        return "Access denied. API key may be invalid or lack permission."
    if status_code == 404:
        return "Not found — no record for this identifier."
    if status_code == 429:
        return "Rate limit or quota exceeded. Try again later or reduce request volume."
    if 500 <= status_code < 600:
        return f"Server error ({status_code}). Try again later."
    return f"Request failed (HTTP {status_code}). Try again later."


_FWCI_MAX_QUERY_ATTEMPTS = 8


def format_fwci_status(scival_bundle, include_fwci=True):
    """Human-readable FWCI / SciVal status for export columns."""
    if not include_fwci:
        return ""
    fwci = (scival_bundle or {}).get("fwci", "N/A")
    note = ((scival_bundle or {}).get("note") or "").strip()
    if fwci != "N/A":
        return note or "Success"
    return note or "FWCI not available"


'''

body = chunk.replace("api_error_message", "scival_api_error_message")
body = body.replace(
    "    query_attempts = _build_fwci_query_attempts(pub_year)",
    "    query_attempts = _build_fwci_query_attempts(pub_year)[:_FWCI_MAX_QUERY_ATTEMPTS]",
)
body = body.replace(
    'return {"fwci": "N/A", "note": note, "publication": None}',
    'return {"fwci": "N/A", "note": note, "publication": None, "pub_id": None, "match_score": -1}',
)
body = body.replace(
    'return {"fwci": text, "note": "", "publication": publication}',
    'return {"fwci": text, "note": "", "publication": publication, "pub_id": pub_id, "match_score": best_score}',
)
for old in (
    'return {"fwci": "N/A", "note": api_error_message("Scival"',
):
    pass
# append pub_id to remaining fetch_doi_scival returns
tail_replacements = [
    (
        '"publication": publication}',
        '"publication": publication, "pub_id": pub_id, "match_score": best_score}',
    ),
]
for a, b in tail_replacements:
    body = body.replace(a, b)

body = body.replace(
    '"publication": publication,\n    }',
    '"publication": publication,\n        "pub_id": pub_id,\n        "match_score": best_score,\n    }',
    1,
)
(root / "fwci_lib.py").write_text(header + body, encoding="utf-8")
print("Wrote fwci_lib.py")
