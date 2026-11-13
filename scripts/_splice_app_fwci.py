from pathlib import Path

root = Path(__file__).resolve().parents[1]
lines = (root / "app.py").read_text(encoding="utf-8").splitlines()
# Remove lines 1019-1801 inclusive (1-based) -> keep 0:1018 and 1801:
new_lines = lines[:1018] + lines[1801:]
import_block = [
    "",
    "from fwci_lib import (",
    "    fetch_doi_scival,",
    "    fetch_doi_fwci,",
    "    format_fwci_status,",
    "    _extract_publication_meta,",
    "    _scival_optional_row_columns,",
    "    _fwci_help_text,",
    "    _SCIVAL_FWCI_LEARN_MORE,",
    ")",
    "",
    "",
    "def fetch_doi_scival_cached(doi, api_key, inst_token):",
    '    """Per-session cache so duplicate DOIs in one run only hit SciVal once."""',
    '    cache = st.session_state.setdefault("_scival_doi_cache", {})',
    '    key = str(doi or "").strip().lower()',
    "    if key not in cache:",
    "        cache[key] = fetch_doi_scival(doi, api_key, inst_token)",
    "    return cache[key]",
    "",
]
# Insert after urllib.parse import (line 17, index 17)
idx = 18
for i, line in enumerate(new_lines):
    if line.startswith("from urllib.parse import"):
        idx = i + 1
        break
final = new_lines[:idx] + import_block + new_lines[idx:]
(root / "app.py").write_text("\n".join(final) + "\n", encoding="utf-8")
print("Spliced app.py:", len(lines), "->", len(final))
