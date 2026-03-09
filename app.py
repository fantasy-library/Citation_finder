import streamlit as st
import requests
import pandas as pd
import time
import io
import re
from pathlib import Path
from urllib.parse import quote, unquote

try:
    import streamlit.components.v1 as components
except ImportError:
    components = None

try:
    from serpapi import GoogleSearch as SerpApiGoogleSearch
    SERPAPI_AVAILABLE = True
except ImportError:
    SERPAPI_AVAILABLE = False

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Academic Database Search", page_icon="📚", layout="wide")

# Default from secrets (optional)
try:
    _default_inst_token = st.secrets.get("SCOPUS_INST_TOKEN", "")
except Exception:
    _default_inst_token = ""

# ==========================================
# API KEYS – Template & file parsing
# ==========================================
ALLOWED_API_KEYS = ("WOS_API_KEY", "WOS_JOURNAL_API_KEY", "SCOPUS_API_KEY", "SCOPUS_INST_TOKEN", "SERPAPI_KEY")


def get_api_keys_template_content():
    """Return template file content for download."""
    template_path = Path(__file__).resolve().parent / "api_keys_template.txt"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return """# API Keys Configuration
# 1. Open this file in a text editor.
# 2. Replace the empty values with your API keys. Leave a line empty to skip that platform.
# 3. Save and upload the file in the app.
# Do not share this file or commit it to version control.

WOS_API_KEY=
WOS_JOURNAL_API_KEY=
SCOPUS_API_KEY=
SCOPUS_INST_TOKEN=
SERPAPI_KEY=
"""


def parse_api_keys_file(content, filename="uploaded file"):
    """
    Parse key=value (env-style) or simple KEY=value lines.
    Returns (dict of key -> value, list of error/warning strings).
    """
    result = {}
    errors = []
    if not content or not isinstance(content, str):
        errors.append("File is empty or not valid text.")
        return result, errors
    lines = content.strip().splitlines()
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f"Line {i}: Invalid format. Use KEY=value (one key per line).")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'").strip()
        if not key:
            errors.append(f"Line {i}: Missing key name. Use KEY=value.")
            continue
        if key not in ALLOWED_API_KEYS:
            errors.append(f"Unknown key: '{key}'. Allowed: " + ", ".join(ALLOWED_API_KEYS))
            continue
        result[key] = value
    if not result and not errors:
        errors.append("No valid key=value lines found. Use one key per line: KEY_NAME=value")
    return result, errors


# Session state for API keys (from file upload or manual)
if "api_keys" not in st.session_state:
    st.session_state["api_keys"] = {}
if "api_keys_errors" not in st.session_state:
    st.session_state["api_keys_errors"] = []

# ==========================================
# SIDEBAR – Step 1: API keys (upload or manual)
# ==========================================
_icons_dir = Path(__file__).resolve().parent / "icons"
st.sidebar.markdown("### 🔑 Step 1: API keys")

# 1) Drag and drop file first
uploaded_keys_file = st.sidebar.file_uploader(
    "Drag and drop file here",
    type=["txt", "env"],
    key="api_keys_upload",
    label_visibility="collapsed",
)
if uploaded_keys_file is None:
    st.sidebar.caption("No file chosen")

# 2) Download template below
template_content = get_api_keys_template_content()
st.sidebar.download_button(
    label="📥 Download template (.txt)",
    data=template_content,
    file_name="api_keys_template.txt",
    mime="text/plain",
    key="download_api_template",
)

if uploaded_keys_file is not None:
    try:
        raw = uploaded_keys_file.read().decode("utf-8")
    except UnicodeDecodeError:
        st.sidebar.error("File encoding error. Please save the file as UTF-8.")
    except Exception as e:
        st.sidebar.error(f"Could not read the file: {e}")
    else:
        parsed, parse_errors = parse_api_keys_file(raw, uploaded_keys_file.name)
        if parse_errors:
            for err in parse_errors:
                st.sidebar.error(err)
            st.session_state["api_keys_errors"] = parse_errors
        else:
            st.session_state["api_keys"] = {**st.session_state.get("api_keys", {}), **parsed}
            st.session_state["api_keys_errors"] = []
            st.sidebar.success("API keys loaded from file.")

with st.sidebar.expander("✏️ Enter keys manually"):
    with st.form("manual_api_keys_form", clear_on_submit=False):
        manual_wos = st.text_input("WOS API key", type="password", placeholder="WOS key", key="manual_wos")
        manual_wos_j = st.text_input("WOS Journal API key (optional)", type="password", placeholder="WOS Journal key", key="manual_wos_j")
        manual_scopus = st.text_input("Scopus API key", type="password", placeholder="Scopus key", key="manual_scopus")
        manual_inst = st.text_input("Scopus institutional token", type="password", placeholder="Institutional token", key="manual_inst")
        manual_serp = st.text_input("SerpAPI key", type="password", placeholder="SerpAPI key", key="manual_serp")
        submitted = st.form_submit_button("✓ Apply manual keys", type="primary")
        if submitted:
            keys = st.session_state.get("api_keys", {})
            if manual_wos and manual_wos.strip():
                keys["WOS_API_KEY"] = manual_wos.strip()
            if manual_wos_j and manual_wos_j.strip():
                keys["WOS_JOURNAL_API_KEY"] = manual_wos_j.strip()
            if manual_scopus and manual_scopus.strip():
                keys["SCOPUS_API_KEY"] = manual_scopus.strip()
            if manual_inst and manual_inst.strip():
                keys["SCOPUS_INST_TOKEN"] = manual_inst.strip()
            if manual_serp and manual_serp.strip():
                keys["SERPAPI_KEY"] = manual_serp.strip()
            st.session_state["api_keys"] = keys
            st.success("Manual keys applied.")
    st.caption("Press **Enter** in any field to apply.")

# Derive key variables from session (and secrets fallback)
_keys = st.session_state.get("api_keys", {})
WOS_API_KEY = _keys.get("WOS_API_KEY", "").strip()
WOS_JOURNAL_API_KEY = (_keys.get("WOS_JOURNAL_API_KEY") or "").strip()
SCOPUS_API_KEY = (_keys.get("SCOPUS_API_KEY") or "").strip()
SCOPUS_INST_TOKEN = (_keys.get("SCOPUS_INST_TOKEN") or _default_inst_token or "").strip()
SERPAPI_KEY = (_keys.get("SERPAPI_KEY") or "").strip()

# Platform status (which keys are set)
def _platform_status():
    wos_ok = bool(WOS_API_KEY)
    scopus_ok = bool(SCOPUS_API_KEY and SCOPUS_INST_TOKEN)
    gs_ok = bool(SERPAPI_KEY)
    return wos_ok, scopus_ok, gs_ok

_wos_ok, _scopus_ok, _gs_ok = _platform_status()
st.sidebar.markdown(
    f"**Platforms:** WOS {'✓' if _wos_ok else '—'} · Scopus {'✓' if _scopus_ok else '—'} · Google Scholar {'✓' if _gs_ok else '—'}"
)
st.sidebar.markdown("---")
st.sidebar.markdown("### 🧭 Step 2: Navigation")
try:
    icon_cols = st.sidebar.columns(3)
    icon_cols[0].image(str(_icons_dir / "WoS.png"), caption="WOS", width="stretch")
    icon_cols[1].image(str(_icons_dir / "Scopus.png"), caption="Scopus", width="stretch")
    icon_cols[2].image(str(_icons_dir / "Google.png"), caption="Google Scholar", width="stretch")
except Exception:
    pass
app_mode = st.sidebar.radio(
    "Mode",
    ["Unified citation search", "Web of Science", "Scopus", "Google Scholar", "Crossref"],
    format_func=lambda x: {
        "Unified citation search": "🔍 Unified (WOS + Scopus + Google Scholar)",
        "Web of Science": "📚 Web of Science",
        "Scopus": "📈 Scopus",
        "Google Scholar": "🎓 Google Scholar",
        "Crossref": "🔗 Crossref",
    }[x],
    key="app_mode_radio",
)

# Unlock logic per mode
if app_mode == "Unified citation search":
    api_unlocked = _wos_ok or _scopus_ok or _gs_ok
    api_reminder = "Add at least one platform's API keys (Step 1) to unlock unified search."
elif app_mode == "Google Scholar":
    api_unlocked = bool(SERPAPI_KEY)
    api_reminder = "Please add your SerpAPI key in Step 1 to unlock the search."
elif app_mode == "Web of Science":
    api_unlocked = bool(WOS_API_KEY)
    api_reminder = "Please add your WOS API key in Step 1 to unlock the search."
elif app_mode == "Scopus":
    api_unlocked = bool(SCOPUS_API_KEY and SCOPUS_INST_TOKEN)
    api_reminder = "Please add your Scopus API key and institutional token in Step 1 to unlock the search."
elif app_mode == "Crossref":
    api_unlocked = True  # No API key required
    api_reminder = ""
else:
    api_unlocked = False
    api_reminder = "Please add your API key in Step 1 to unlock the search view."

if not api_unlocked:
    st.sidebar.warning(api_reminder)

# ==========================================
# API ERROR MESSAGES (user-friendly)
# ==========================================
def api_error_message(service, status_code, response_body=None):
    """Return a short user-facing message for API errors."""
    body = (response_body or "").lower() if isinstance(response_body, str) else ""
    if status_code == 400:
        return "Bad request — check your query or identifier format."
    if status_code == 401:
        return "Invalid or missing API key. Check your credentials."
    if status_code == 403:
        if service and str(service).lower() == "scopus":
            return "Access denied. Scopus requires both a valid **API key** and an **institutional token** (from your library). Check that both are correct and your institution has Scopus API access."
        return "Access denied. API key may be invalid or lack permission."
    if status_code == 404:
        return "Not found — no record for this identifier."
    if status_code == 429:
        return "Rate limit or quota exceeded. Try again later or reduce request volume."
    if 500 <= status_code < 600:
        return f"Server error ({status_code}). Try again later."
    return f"Request failed (HTTP {status_code}). Try again later."


def serpapi_error_message(error_str):
    """Map SerpAPI error string to user-friendly message."""
    if not error_str:
        return "SerpAPI request failed."
    e = (error_str or "").lower()
    if "invalid" in e and "key" in e:
        return "Invalid SerpAPI key. Check your key in the sidebar."
    if "rate" in e or "quota" in e or "limit" in e:
        return "SerpAPI rate limit or quota exceeded. Try again later."
    if "not found" in e or "404" in e:
        return "No result found for this DOI."
    return (error_str[:80] + "…") if len(error_str) > 80 else error_str


# ==========================================
# HELPER FUNCTIONS (WOS)
# ==========================================
WOS_STARTER_BASE = "https://api.clarivate.com/apis/wos-starter/v1"


def fetch_wos_data(wos_ids, progress_bar, status_text, wos_api_key=None):
    """Fetch WOS document data. wos_api_key defaults to global WOS_API_KEY if not provided."""
    key = (wos_api_key or "").strip() or WOS_API_KEY
    results = []
    total = len(wos_ids)

    for i, wos_id in enumerate(wos_ids):
        status_text.text(f"Fetching record {i+1} of {total}: {wos_id}...")
        wos_id = (wos_id or "").strip()
        is_doi = wos_id.lower().startswith("10.")

        # Build request: by UID (WOS:...) or by DOI using documents search
        if is_doi:
            url = f"{WOS_STARTER_BASE}/documents"
            params = {
                "db": "WOS",
                "q": f"DO={wos_id}",
                "limit": 10,
                "page": 1,
            }
        else:
            url = f"{WOS_STARTER_BASE}/documents/{wos_id}"
            params = None
        headers = {"X-ApiKey": key}

        try:
            if params is None:
                response = requests.get(url, headers=headers)
            else:
                response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()

                # For DOI search, the API returns a list of hits; pick the best match
                if is_doi:
                    hits = data.get("hits") or []
                    if not hits:
                        results.append({
                            "Unique WOS ID": wos_id,
                            "DOI": wos_id,
                            "WOS search (DO)": f"DO={wos_id}",
                            "Title": "N/A",
                            "Author Full Names": "N/A",
                            "Query (AU)": "N/A",
                            "Document Type": "N/A",
                            "Source Title": "N/A",
                            "Publish Year": "N/A",
                            "Volume": "N/A",
                            "Issue": "N/A",
                            "Citation Count": "N/A",
                            "Status": "No document found for this DOI.",
                        })
                        progress_bar.progress((i + 1) / total)
                        continue
                    data = hits[0]
                    wos_uid = data.get("uid") or "N/A"
                else:
                    wos_uid = wos_id

                # Extract Authors & formatted query (API may return mixed types)
                names = data.get('names') or {}
                authors_data = names.get('authors', []) if isinstance(names, dict) else []
                if not isinstance(authors_data, list):
                    authors_data = []
                authors_list = [a for a in authors_data if isinstance(a, dict)]
                wos_standard = [a.get('wosStandard', '') for a in authors_list if a.get('wosStandard')]
                query = f"not au=({' OR '.join(wos_standard)})" if wos_standard else "N/A"
                full_names = "; ".join([a.get('displayName', a.get('wosStandard', '')) for a in authors_list])

                # Extract DOI per DocumentIdentifiers: identifiers.doi / documentIdentifiers.doi (str, optional)
                def _str_doi(v):
                    return v.strip() if v and isinstance(v, str) and v.strip() else None

                doi_raw = None
                ids = data.get("identifiers") or data.get("documentIdentifiers")
                if isinstance(ids, dict):
                    doi_raw = _str_doi(ids.get("doi"))
                if not doi_raw:
                    doi_raw = _str_doi(data.get("doi"))
                if not doi_raw:
                    # Fallback: identifiers as list of objects
                    for ident in (data.get("identifiers") or []):
                        if isinstance(ident, dict) and (ident.get("identifierType") == "doi" or ident.get("type") == "doi"):
                            doi_raw = _str_doi(ident.get("value") or ident.get("id"))
                            break
                        if isinstance(ident, str) and ident.startswith("10."):
                            doi_raw = ident.strip()
                            break

                doi = doi_raw if doi_raw else "N/A"
                # WOS query string by DOI using official field tag DO
                doi_query = f"DO={doi}" if doi != "N/A" else "N/A"

                source = data.get('source', {}) or {}
                if not isinstance(source, dict):
                    source = {}
                citations = data.get('citations', []) or []
                if not isinstance(citations, list):
                    citations = []

                types_raw = data.get("types") or []
                types_list = types_raw if isinstance(types_raw, list) else [types_raw] if types_raw else []
                doc_type = "; ".join(str(t) for t in types_list) or "N/A"
                results.append({
                    "Unique WOS ID": wos_uid,
                    "DOI": doi,
                    "WOS search (DO)": doi_query,
                    "Title": data.get('title', 'N/A'),
                    "Author Full Names": full_names or "N/A",
                    "Query (AU)": query,
                    "Document Type": doc_type,
                    "Source Title": source.get('sourceTitle', 'N/A'),
                    "Publish Year": source.get('publishYear', 'N/A'),
                    "Volume": source.get('volume', 'N/A'),
                    "Issue": source.get('issue', 'N/A'),
                    "Citation Count": citations[0].get('count', 'N/A') if citations and isinstance(citations[0], dict) else ('N/A' if not citations else 'N/A'),
                    "Status": "Success"
                })
            elif response.status_code == 429:
                status_text.text(f"Rate limit hit at {wos_id}. Sleeping 3s...")
                time.sleep(3)
                results.append({
                    "Unique WOS ID": wos_id,
                    "DOI": "N/A",
                    "WOS search (DO)": "N/A",
                    "Title": "N/A",
                    "Author Full Names": "N/A",
                    "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                    "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                    "Status": api_error_message("WOS", 429),
                })
            else:
                msg = api_error_message("WOS", response.status_code, getattr(response, "text", None))
                results.append({
                    "Unique WOS ID": wos_id, "DOI": "N/A", "WOS search (DO)": "N/A", "Title": "N/A", "Author Full Names": "N/A",
                    "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                    "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                    "Status": msg,
                })
        except requests.RequestException as e:
            code = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            msg = api_error_message("WOS", code, str(e)) if code else f"Request failed: {str(e)[:60]}"
            results.append({
                "Unique WOS ID": wos_id,
                "DOI": "N/A",
                "WOS search (DO)": "N/A",
                "Title": "N/A",
                "Author Full Names": "N/A",
                "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                "Status": msg,
            })
        except Exception as e:
            results.append({
                "Unique WOS ID": wos_id,
                "DOI": "N/A",
                "WOS search (DO)": "N/A",
                "Title": "N/A",
                "Author Full Names": "N/A",
                "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                "Status": f"Error: {str(e)[:60]}",
            })

        progress_bar.progress((i + 1) / total)
        time.sleep(1)  # Rate limit protection

    return results


# ==========================================
# HELPER FUNCTIONS (WOS – Journal metrics by ISSN/title, JCR API)
# ==========================================
WOS_JOURNALS_BASE = "https://api.clarivate.com/apis/wos-journals/v1"


def _parse_wos_journal_entry(entry, query):
    """Parse one journal from WOS Journals API response (JournalListRecord or full journal) into a flat row."""
    if not isinstance(entry, dict):
        return {"Query": query, "Status": "Invalid response"}
    # API returns list items with "name" (journal title), not "title"
    title = (
        entry.get("name")
        or entry.get("title")
        or entry.get("journalTitle")
        or "N/A"
    )
    jcr_id = entry.get("id") or entry.get("jcrAbbrev") or "N/A"
    issn = entry.get("issn") or "N/A"
    eissn = entry.get("eissn") or entry.get("eIssn") or "N/A"
    publisher = entry.get("publisher") or "N/A"
    edition_list = entry.get("edition") or entry.get("editions") or []
    if isinstance(edition_list, list):
        edition_str = "; ".join(str(e) if not isinstance(e, dict) else e.get("name", e.get("id", "")) for e in edition_list)
    else:
        edition_str = str(edition_list)
    edition_str = edition_str or "N/A"
    categories = entry.get("categories") or entry.get("category") or []
    if isinstance(categories, list):
        cat_str = "; ".join(
            c.get("name", c.get("categoryName", str(c))) if isinstance(c, dict) else str(c) for c in categories
        )
    else:
        cat_str = str(categories)
    cat_str = cat_str or "N/A"
    # Metrics can be at top level (impactMetrics) or under metrics.impact_metrics / metrics.impactMetrics
    metrics_block = entry.get("metrics") or {}
    impact = (
        entry.get("impactMetrics")
        or metrics_block.get("impactMetrics")
        or metrics_block.get("impact_metrics")
        or {}
    )
    if not isinstance(impact, dict):
        impact = {}
    jif = impact.get("jif") if impact.get("jif") is not None else impact.get("journalImpactFactor")
    jif = jif if jif is not None else "N/A"
    # Quartiles and percentiles can be in impact, source metrics or in ranks.* (JCR API uses ranks models like RanksJif)
    ranks = entry.get("ranks") or {}
    raw_jif_rank = ranks.get("jif")
    if isinstance(raw_jif_rank, list) and raw_jif_rank:
        _jif_rank = raw_jif_rank[0] if isinstance(raw_jif_rank[0], dict) else {}
    elif isinstance(raw_jif_rank, dict):
        _jif_rank = raw_jif_rank
    else:
        _jif_rank = {}
    raw_jci_rank = ranks.get("jci")
    if isinstance(raw_jci_rank, list) and raw_jci_rank:
        _jci_rank = raw_jci_rank[0] if isinstance(raw_jci_rank[0], dict) else {}
    elif isinstance(raw_jci_rank, dict):
        _jci_rank = raw_jci_rank
    else:
        _jci_rank = {}
    jif_quartile = (
        impact.get("jifQuartile")
        or impact.get("jif_quartile")
        or entry.get("jifQuartile")
        or _jif_rank.get("quartile")
        or "N/A"
    )
    # Percentiles are exposed via source metrics or ranks (RanksJif / RanksJci) when corresponding filters are used
    source_metrics = (
        metrics_block.get("sourceMetrics")
        or metrics_block.get("source_metrics")
        or {}
    )
    if not isinstance(source_metrics, dict):
        source_metrics = {}
    jif_percentile = (
        source_metrics.get("jifPercentile")
        or source_metrics.get("jif_percentile")
        or _jif_rank.get("jif_percentile")
        or _jif_rank.get("jifPercentile")
        or None
    )
    jci = impact.get("jci") or impact.get("journalCitationIndicator")
    jci = jci if jci is not None else "N/A"
    jci_quartile = (
        impact.get("jciQuartile")
        or impact.get("jci_quartile")
        or _jci_rank.get("quartile")
        or "N/A"
    )
    jci_percentile = (
        source_metrics.get("jciPercentile")
        or source_metrics.get("jci_percentile")
        or _jci_rank.get("jci_percentile")
        or _jci_rank.get("jciPercentile")
        or None
    )
    # JCR year: prefer explicit helper marker, then any jcrYear field present
    jcr_year_val = (
        entry.get("_jcr_year")
        or entry.get("jcrYear")
        or entry.get("jcr_year")
        or None
    )
    return {
        "Journal Title": title,
        "JCR ID": jcr_id,
        "JCR Year": jcr_year_val or "N/A",
        "ISSN": issn,
        "eISSN": eissn,
        "Publisher": publisher,
        "Edition(s)": edition_str,
        "Categories": cat_str,
        "JIF": jif,
        "JIF Percentile": jif_percentile or "N/A",
        "JIF Quartile": jif_quartile or "N/A",
        "JCI": jci,
        "JCI Quartile": jci_quartile or "N/A",
        "JCI Percentile": jci_percentile or "N/A",
        "Query": query,
        "Status": "Success",
    }


def fetch_wos_journal_data(queries, api_key, jcr_year, edition_filter, progress_bar, status_text):
    """Fetch JCR journal metrics by search query (ISSN or title). Uses WOS Journals API."""
    results = []
    total = len(queries)
    headers = {"X-ApiKey": api_key}

    for i, q in enumerate(queries):
        q = (q or "").strip()
        if not q:
            progress_bar.progress((i + 1) / total)
            continue
        status_text.text(f"Fetching journal {i+1} of {total}: {q[:50]}...")
        url = f"{WOS_JOURNALS_BASE}/journals"
        # API expects camelCase only (jcrYear, not jcr_year); snake_case params cause 400 Bad Request
        params = {"q": q, "limit": 50, "page": 1}
        if edition_filter:
            params["edition"] = edition_filter
        if jcr_year:
            year_int = int(jcr_year)
            params["jcrYear"] = year_int
            # Turn on impact metrics (JIF/JCI), percentiles, and quartiles without over-filtering
            params["jif"] = "gte:0"
            params["jifPercentile"] = "gte:0 AND lte:100"
            params["jifQuartile"] = "Q1;Q2;Q3;Q4"
            params["jci"] = "gte:0"
            params["jciPercentile"] = "gte:0 AND lte:100"
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                # WOS Journals API returns list in "hits" (JournalList schema)
                journal_list = (
                    data.get("hits")
                    or data.get("journalList")
                    or data.get("journals")
                    or data.get("data")
                    or []
                )
                if isinstance(journal_list, dict):
                    journal_list = journal_list.get("journal") or journal_list.get("journals") or journal_list.get("hits") or []
                if not journal_list:
                    results.append({"Query": q, "Status": "No journal found"})
                else:
                    first = journal_list[0] if isinstance(journal_list[0], dict) else None
                    if first:
                        # Enrich with journal detail and report data to fill ISSN, publisher, categories, ranks, etc.
                        enriched = dict(first)
                        if jcr_year:
                            try:
                                enriched["_jcr_year"] = int(jcr_year)
                            except Exception:
                                enriched["_jcr_year"] = str(jcr_year)
                        journal_id = first.get("id")

                        if journal_id:
                            # Detail endpoint: /journals/{id}
                            try:
                                detail_resp = requests.get(
                                    f"{WOS_JOURNALS_BASE}/journals/{journal_id}",
                                    headers=headers,
                                    timeout=30,
                                )
                                if detail_resp.status_code == 200:
                                    d_json = detail_resp.json()
                                    detail_entry = (
                                        d_json.get("journal")
                                        or d_json.get("data")
                                        or d_json
                                    )
                                    if isinstance(detail_entry, dict):
                                        for k, v in detail_entry.items():
                                            # Preserve id and name from the list hit
                                            if k in ("id", "name") and k in enriched:
                                                continue
                                            if (
                                                k in enriched
                                                and isinstance(enriched[k], dict)
                                                and isinstance(v, dict)
                                            ):
                                                merged = {**enriched[k], **v}
                                                enriched[k] = merged
                                            else:
                                                enriched[k] = v
                                elif detail_resp.status_code == 429:
                                    # Back off briefly on per-id detail rate limiting
                                    time.sleep(2)
                            except Exception:
                                # Best-effort enrichment; keep base hit if detail fails
                                pass

                            # Year-specific report endpoint: /journals/{id}/reports/year/{year}
                            if jcr_year:
                                try:
                                    year_int = int(jcr_year)
                                    report_resp = requests.get(
                                        f"{WOS_JOURNALS_BASE}/journals/{journal_id}/reports/year/{year_int}",
                                        headers=headers,
                                        timeout=30,
                                    )
                                    if report_resp.status_code == 200:
                                        r_json = report_resp.json()
                                        report_entry = (
                                            r_json.get("journal")
                                            or r_json.get("reports")
                                            or r_json.get("data")
                                            or r_json
                                        )
                                        if isinstance(report_entry, dict):
                                            for k, v in report_entry.items():
                                                if (
                                                    k in enriched
                                                    and isinstance(enriched[k], dict)
                                                    and isinstance(v, dict)
                                                ):
                                                    merged = {**enriched[k], **v}
                                                    enriched[k] = merged
                                                elif k not in enriched:
                                                    enriched[k] = v
                                    elif report_resp.status_code == 429:
                                        time.sleep(2)
                                except Exception:
                                    # If report call fails, we still have list + detail data
                                    pass

                        results.append(_parse_wos_journal_entry(enriched, q))
                    else:
                        results.append({"Query": q, "Status": "No journal data"})
            elif response.status_code == 429:
                status_text.text(f"Rate limit at {q[:30]}. Sleeping 2s...")
                time.sleep(2)
                results.append({"Query": q, "Status": api_error_message("WOS", 429)})
            else:
                msg = api_error_message("WOS", response.status_code, getattr(response, "text", None))
                results.append({"Query": q, "Status": msg})
        except Exception as e:
            results.append({"Query": q, "Status": f"Error: {str(e)[:60]}"})

        progress_bar.progress((i + 1) / total)
        # Sleep a bit longer here to account for the extra detail/report calls per journal
        time.sleep(0.6)

    return results


# ==========================================
# HELPER FUNCTIONS (SCOPUS – Elsevier Citation Metrics by DOI)
# ==========================================
def fetch_elsevier_citations(doi, api_key, inst_token, exclude_self=False, _retry_count=0):
    """Fetches data from the Elsevier Abstract Citations API."""
    url = f"https://api.elsevier.com/content/abstract/citations?doi={doi}&apiKey={api_key}&insttoken={inst_token}&httpAccept=application/json"
    if exclude_self:
        url += "&citation=exclude-self"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    if response.status_code == 429 and _retry_count < 2:
        time.sleep(2)
        return fetch_elsevier_citations(doi, api_key, inst_token, exclude_self, _retry_count + 1)
    response.raise_for_status()
    return response.json()


def process_doi_scopus(doi, api_key, inst_token):
    """Processes a single DOI to get both metadata and citation metrics."""
    try:
        data_total = fetch_elsevier_citations(doi, api_key, inst_token, exclude_self=False)
        cite_header = data_total.get("abstract-citations-response", {}).get("citeColumnTotalXML", {}).get("citeCountHeader", {})
        total_citations = cite_header.get("grandTotal", 0)
        cite_info = data_total.get("abstract-citations-response", {}).get("citeInfoMatrix", {}).get("citeInfoMatrixXML", {}).get("citationMatrix", {}).get("citeInfo", [])
        if isinstance(cite_info, list) and len(cite_info) > 0:
            article_data = cite_info[0]
        else:
            article_data = cite_info if isinstance(cite_info, dict) else {}
        title = article_data.get("dc:title", "Title not available")
        pub_type = article_data.get("citationType", {}).get("$", "Type not available") if isinstance(article_data.get("citationType"), dict) else "Type not available"
        year = article_data.get("sort-year", "Year not available")

        data_exclude = fetch_elsevier_citations(doi, api_key, inst_token, exclude_self=True)
        cite_header_ex = data_exclude.get("abstract-citations-response", {}).get("citeColumnTotalXML", {}).get("citeCountHeader", {})
        exclude_self_citations = cite_header_ex.get("grandTotal", 0)

        return {
            "DOI": doi,
            "Title": title,
            "Year": year,
            "Type": pub_type,
            "Total Citations": total_citations,
            "Exclude self-citations": exclude_self_citations,
            "Status": "Success",
        }
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        msg = api_error_message("Scopus", code, e.response.text if e.response else None)
        return {
            "DOI": doi,
            "Title": "Error",
            "Year": "N/A",
            "Type": "N/A",
            "Total Citations": "0",
            "Exclude self-citations": "0",
            "Status": msg,
        }
    except requests.RequestException as e:
        code = getattr(e.response, "status_code", None) if hasattr(e, "response") and e.response else None
        msg = api_error_message("Scopus", code, str(e)) if code else f"Request failed: {str(e)[:50]}"
        return {
            "DOI": doi,
            "Title": "Error",
            "Year": "N/A",
            "Type": "N/A",
            "Total Citations": "0",
            "Exclude self-citations": "0",
            "Status": msg,
        }
    except Exception as e:
        return {
            "DOI": doi,
            "Title": "Error",
            "Year": "N/A",
            "Type": "N/A",
            "Total Citations": "0",
            "Exclude self-citations": "0",
            "Status": f"Error: {str(e)[:60]}",
        }


def extract_dois_from_df(df):
    """Finds a DOI column in a dataframe and extracts the values."""
    doi_col = next((col for col in df.columns if "doi" in str(col).lower()), None)
    if doi_col:
        return [str(val).strip() for val in df[doi_col] if str(val).strip().startswith("10.")]
    return []


# ==========================================
# SCOPUS – Journal metrics by ISSN (Serial Title API)
# ==========================================
def clean_issn(issn_str):
    """Normalize ISSN: strip whitespace and hyphens, return 8-char uppercase or None."""
    if not issn_str or not isinstance(issn_str, str):
        return None
    cleaned = re.sub(r"[-\s]", "", issn_str.strip().upper())
    return cleaned if len(cleaned) == 8 else None


def fetch_scopus_journal_data(issns, api_key, inst_token, progress_bar, status_text):
    """Fetch journal metadata and metrics (CiteScore, SNIP, SJR, etc.) by ISSN."""
    results = []
    total = len(issns)
    base_url = "https://api.elsevier.com/content/serial/title/issn"

    for i, issn in enumerate(issns):
        status_text.text(f"Fetching ISSN {i+1} of {total}: {issn}...")
        url = f"{base_url}/{issn}?apiKey={api_key}&insttoken={inst_token}&httpAccept=application/json"

        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                try:
                    resp = data.get("serial-metadata-response", {})
                    entries = resp.get("entry") or []
                    if not entries:
                        results.append({"Queried ISSN": issn, "Status": "No journal data found"})
                        progress_bar.progress((i + 1) / total)
                        time.sleep(0.6)
                        continue
                    entry = entries[0] if isinstance(entries, list) else entries

                    # Subject areas
                    subject_areas = entry.get("subject-area") or []
                    if isinstance(subject_areas, list):
                        areas = [s.get("$", s) if isinstance(s, dict) else str(s) for s in subject_areas]
                    else:
                        areas = [str(subject_areas)]
                    subject_str = "; ".join(a for a in areas if a)

                    # SNIP (latest year)
                    snip = "N/A"
                    snip_list = entry.get("SNIPList", {}) or {}
                    snip_items = snip_list.get("SNIP", []) if isinstance(snip_list, dict) else []
                    if snip_items:
                        first = snip_items[0] if isinstance(snip_items[0], dict) else None
                        snip = first.get("$", snip_items[0]) if first else snip_items[0]

                    # SJR (latest year)
                    sjr = "N/A"
                    sjr_list = entry.get("SJRList", {}) or {}
                    sjr_items = sjr_list.get("SJR", []) if isinstance(sjr_list, dict) else []
                    if sjr_items:
                        first = sjr_items[0] if isinstance(sjr_items[0], dict) else None
                        sjr = first.get("$", sjr_items[0]) if first else sjr_items[0]

                    # CiteScore (current metric)
                    cite_score = "N/A"
                    cs_list = entry.get("citeScoreYearInfoList", {}) or {}
                    if isinstance(cs_list, dict):
                        raw_cs = cs_list.get("citeScoreCurrentMetric")
                        if isinstance(raw_cs, dict):
                            cite_score = raw_cs.get("$", "N/A") or "N/A"
                        elif raw_cs is not None:
                            cite_score = raw_cs
                    elif isinstance(cs_list, list) and cs_list:
                        first = cs_list[0]
                        if isinstance(first, dict):
                            raw_cs = first.get("citeScoreCurrentMetric", first.get("$"))
                            cite_score = raw_cs.get("$", raw_cs) if isinstance(raw_cs, dict) else (raw_cs or "N/A")
                        else:
                            cite_score = first

                    results.append({
                        "Journal Title": entry.get("dc:title", "N/A"),
                        "Publisher": entry.get("dc:publisher", "N/A"),
                        "Print ISSN": entry.get("prism:issn", "N/A"),
                        "eISSN": entry.get("prism:eIssn", "N/A"),
                        "CiteScore": cite_score,
                        "SNIP": snip,
                        "SJR": sjr,
                        "Subject Areas": subject_str or "N/A",
                        "Aggregation Type": entry.get("prism:aggregationType", "N/A"),
                        "Queried ISSN": issn,
                        "Status": "Success",
                    })
                except (KeyError, IndexError, TypeError) as e:
                    results.append({"Queried ISSN": issn, "Status": f"No journal data found ({str(e)[:40]})"})
            elif response.status_code == 429:
                status_text.text(f"Rate limit hit at {issn}. Sleeping 3s...")
                time.sleep(3)
                results.append({"Queried ISSN": issn, "Status": api_error_message("Scopus", 429)})
            else:
                msg = api_error_message("Scopus", response.status_code, getattr(response, "text", None))
                results.append({"Queried ISSN": issn, "Status": msg})
        except Exception as e:
            results.append({"Queried ISSN": issn, "Status": f"Error: {str(e)[:60]}"})

        progress_bar.progress((i + 1) / total)
        time.sleep(0.6)

    return results

# ==========================================
# GOOGLE SCHOLAR (SerpAPI) – full result or citation only
# ==========================================
def _parse_gs_organic(first, doi):
    """Build a result row from SerpAPI organic result. Returns dict with Title, Authors, etc."""
    inline = first.get("inline_links") or {}
    cited_by = inline.get("cited_by") or {}
    total = cited_by.get("total")
    try:
        citations = int(total) if total is not None else "N/A"
    except (TypeError, ValueError):
        citations = "N/A"

    title = first.get("title") or "N/A"
    link = first.get("link") or "N/A"
    snippet = (first.get("snippet") or "").strip() or "N/A"

    pub_info = first.get("publication_info") or {}
    if isinstance(pub_info, dict):
        summary = (pub_info.get("summary") or "").strip() or "N/A"
        authors_list = pub_info.get("authors") or []
        if isinstance(authors_list, list):
            names = [a.get("name", "") for a in authors_list if isinstance(a, dict) and a.get("name")]
            authors = "; ".join(names) if names else summary
        else:
            authors = summary
    else:
        summary = "N/A"
        authors = "N/A"

    return {
        "DOI": doi,
        "Title": title,
        "Authors": authors,
        "Publication": summary,
        "Snippet": snippet[:500] + "..." if len(snippet) > 500 else snippet,
        "Link": link,
        "Google Scholar citations": citations,
    }


def fetch_google_scholar_result(doi, api_key):
    """Fetch full Google Scholar result by DOI. Returns dict with Title, Authors, Publication, citations, etc."""
    empty = {"DOI": doi or "N/A", "Title": "N/A", "Authors": "N/A", "Publication": "N/A", "Snippet": "N/A", "Link": "N/A", "Google Scholar citations": "N/A", "Status": "N/A"}
    if not doi or doi == "N/A" or not api_key or not api_key.strip():
        return empty
    if not SERPAPI_AVAILABLE:
        return {**empty, "DOI": doi, "Status": "SerpAPI client not installed (pip install google-search-results)."}
    try:
        params = {
            "engine": "google_scholar",
            "q": doi.strip(),
            "hl": "en",
            "api_key": api_key.strip(),
        }
        search = SerpApiGoogleSearch(params)
        results = search.get_dict()
        # SerpAPI error (quota, invalid key, etc.)
        err = results.get("error") or results.get("error_message")
        if err:
            msg = serpapi_error_message(str(err))
            return {**empty, "DOI": doi, "Status": msg}
        organic = results.get("organic_results") or []
        if not organic:
            return {**empty, "DOI": doi, "Status": "No result found for this DOI."}
        out = _parse_gs_organic(organic[0], doi)
        out["Status"] = "Success"
        return out
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "rate" in err_str or "quota" in err_str:
            msg = serpapi_error_message("Rate limit or quota exceeded.")
        elif "401" in err_str or "403" in err_str or "invalid" in err_str or "key" in err_str:
            msg = serpapi_error_message("Invalid API key.")
        else:
            msg = f"Error: {str(e)[:50]}"
        return {**empty, "DOI": doi, "Status": msg}


def fetch_google_scholar_citation(doi, api_key):
    """Fetch Google Scholar citation count only (for WOS add-on). Returns int or None."""
    row = fetch_google_scholar_result(doi, api_key)
    c = row.get("Google Scholar citations")
    if isinstance(c, int):
        return c
    return None


# ==========================================
# CROSSREF – Works search (DOI + metadata, no API key required)
# ==========================================
CROSSREF_BASE_URL = "https://api.crossref.org/works"


def _crossref_headers(mailto=""):
    """Headers for Crossref API; mailto enters the 'polite pool' for better performance."""
    ua = "AcademicDatabaseSearch/1.0"
    if mailto and str(mailto).strip():
        ua += f" (mailto:{mailto.strip()})"
    return {"User-Agent": ua}


def _flatten_crossref_work(item):
    """Turn one Crossref work item into a flat dict with DOI and key metadata."""
    na = "N/A"
    default = {"DOI": na, "Title": na, "Authors": na, "Journal": na, "Volume": na, "Issue": na, "Page": na, "Type": na, "Year": na, "Publisher": na, "URL": na}
    if not isinstance(item, dict):
        return default
    doi = item.get("DOI") or na
    title_list = item.get("title") or []
    title = title_list[0] if title_list else na
    authors_list = item.get("author") or []
    author_parts = []
    for a in authors_list[:20]:
        if isinstance(a, dict):
            name = a.get("name") or (f"{a.get('given', '')} {a.get('family', '')}".strip()) or "Unknown"
            author_parts.append(name)
    authors = "; ".join(author_parts) if author_parts else na
    container_list = item.get("container-title") or []
    journal = container_list[0] if container_list else na
    def _opt_str(v):
        if v is None or v == "":
            return na
        return str(v)
    volume = _opt_str(item.get("volume"))
    issue = _opt_str(item.get("issue"))
    page = _opt_str(item.get("page"))
    work_type = item.get("type") or na
    issued = item.get("issued") or {}
    date_parts = (issued.get("date-parts") or [[]])[0] if isinstance(issued.get("date-parts"), list) else []
    year = date_parts[0] if date_parts and len(date_parts) > 0 else na
    publisher = item.get("publisher") or na
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi != na else na)
    return {
        "DOI": doi,
        "Title": title,
        "Authors": authors,
        "Journal": journal,
        "Volume": volume,
        "Issue": issue,
        "Page": page,
        "Type": work_type,
        "Year": year,
        "Publisher": publisher,
        "URL": url,
    }


def get_crossref_work_by_doi(doi, mailto=""):
    """
    Fetch a single work by DOI from Crossref (GET /works/{doi}).
    Returns (list of one flattened item, 1, None) or ([], 0, error_message).
    """
    if not doi or not str(doi).strip():
        return [], 0, "Please enter a DOI."
    raw = str(doi).strip()
    if raw.startswith("https://doi.org/"):
        raw = raw.replace("https://doi.org/", "", 1)
    if not raw.startswith("10."):
        return [], 0, "DOI should start with 10. (e.g. 10.1016/j.jinorgbio.2021.111634)."
    encoded_doi = quote(raw, safe="")
    url = f"{CROSSREF_BASE_URL}/{encoded_doi}"
    try:
        response = requests.get(url, headers=_crossref_headers(mailto), timeout=30)
        if response.status_code == 404:
            return [], 0, "Not found — no record for this DOI."
        if response.status_code != 200:
            return [], 0, api_error_message("Crossref", response.status_code, response.text)
        data = response.json()
        msg = data.get("message")
        if not msg or not isinstance(msg, dict):
            return [], 0, "Invalid response from Crossref."
        row = _flatten_crossref_work(msg)
        return [row], 1, None
    except requests.RequestException as e:
        return [], 0, f"Request failed: {str(e)[:80]}"
    except Exception as e:
        return [], 0, f"Error: {str(e)[:80]}"


def _normalize_crossref_doi_input(value: str) -> str:
    """Normalize DOI input (accepts DOI, doi.org URL, or Crossref works URL)."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    low = raw.lower()
    if low.startswith("doi:"):
        raw = raw[4:].strip()
        low = raw.lower()
    if "api.crossref.org/works/" in low:
        part = raw.split("api.crossref.org/works/", 1)[1]
        part = part.split("?", 1)[0].split("#", 1)[0]
        raw = unquote(part).strip()
        low = raw.lower()
    for prefix in ("https://doi.org/", "http://doi.org/"):
        if low.startswith(prefix):
            raw = raw[len(prefix):].strip()
            break
    return raw


def bulk_crossref_lookup_by_dois(dois, mailto=""):
    """
    Bulk lookup via Crossref single-work endpoint (/works/{doi}).
    Returns (rows, error_message). Each row includes a Status column.
    """
    rows = []
    for d in (dois or []):
        norm = _normalize_crossref_doi_input(d)
        if not norm or not norm.startswith("10."):
            row = _flatten_crossref_work({})
            row["DOI"] = norm or (str(d).strip() if d is not None else "N/A") or "N/A"
            row["Status"] = "Invalid DOI"
            rows.append(row)
            continue
        encoded = quote(norm, safe="")
        url = f"{CROSSREF_BASE_URL}/{encoded}"
        try:
            resp = requests.get(url, headers=_crossref_headers(mailto), timeout=30)
            if resp.status_code == 404:
                row = _flatten_crossref_work({})
                row["DOI"] = norm
                row["URL"] = f"https://doi.org/{norm}"
                row["Status"] = "Not found"
                rows.append(row)
                continue
            if resp.status_code != 200:
                row = _flatten_crossref_work({})
                row["DOI"] = norm
                row["URL"] = f"https://doi.org/{norm}"
                row["Status"] = api_error_message("Crossref", resp.status_code, getattr(resp, "text", None))
                rows.append(row)
                continue
            data = resp.json()
            msg = data.get("message")
            row = _flatten_crossref_work(msg if isinstance(msg, dict) else {})
            row["Status"] = "Success"
            rows.append(row)
        except requests.RequestException as e:
            row = _flatten_crossref_work({})
            row["DOI"] = norm
            row["URL"] = f"https://doi.org/{norm}"
            row["Status"] = f"Request failed: {str(e)[:80]}"
            rows.append(row)
        except Exception as e:
            row = _flatten_crossref_work({})
            row["DOI"] = norm
            row["URL"] = f"https://doi.org/{norm}"
            row["Status"] = f"Error: {str(e)[:80]}"
            rows.append(row)
    return rows, None


def search_crossref_works(
    query=None,
    query_author=None,
    query_title=None,
    query_bibliographic=None,
    rows=20,
    offset=0,
    sort="relevance",
    order="desc",
    mailto="",
):
    """
    Search Crossref works API. Returns (list of flattened items, total_results, error_message).
    Uses query param and/or query.author, query.bibliographic (title/journal), etc.
    """
    rows_val = min(max(1, int(rows)), 1000)
    query_parts = []
    if query and str(query).strip():
        query_parts.append(f"query={quote(str(query).strip())}")
    if query_author and str(query_author).strip():
        query_parts.append(f"query.author={quote(str(query_author).strip())}")
    bib = (query_title or query_bibliographic or "").strip()
    if bib:
        query_parts.append(f"query.bibliographic={quote(bib)}")

    if not query_parts:
        return [], 0, "Please provide at least one search term (query, author, or title)."

    url = f"{CROSSREF_BASE_URL}?{'&'.join(query_parts)}&rows={rows_val}&offset={offset}&sort={sort}&order={order}"

    try:
        response = requests.get(url, headers=_crossref_headers(mailto), timeout=30)
        if response.status_code != 200:
            return [], 0, api_error_message("Crossref", response.status_code, response.text)
        data = response.json()
        msg = data.get("message") or {}
        items = msg.get("items") or []
        total = msg.get("total-results") or 0
        flattened = [_flatten_crossref_work(it) for it in items]
        return flattened, total, None
    except requests.RequestException as e:
        return [], 0, f"Request failed: {str(e)[:80]}"
    except Exception as e:
        return [], 0, f"Error: {str(e)[:80]}"


# ==========================================
# EXCEL GENERATOR (In-Memory)
# ==========================================
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    return output.getvalue()


# ==========================================
# USER INTERFACE – Consistent, accessible styling
# ==========================================
st.markdown("""
<style>
    /* ----- Main container & typography ----- */
    .main .block-container { padding-top: 1.75rem; padding-bottom: 2.5rem; max-width: 1100px; }
    .main .block-container > * { margin-bottom: 0.5rem; }
    h1 { font-weight: 700; letter-spacing: -0.02em; color: #0f172a; margin-bottom: 0.35rem !important; font-size: 1.65rem !important; line-height: 1.3 !important; }
    h2 { font-weight: 600; color: #1e293b; font-size: 1.2rem !important; margin-top: 1.25rem !important; margin-bottom: 0.5rem !important; line-height: 1.4 !important; }
    h3 { font-weight: 600; color: #334155; font-size: 1.05rem !important; line-height: 1.4 !important; }
    p { color: #475569; line-height: 1.5; margin-bottom: 0.5rem !important; }

    /* ----- Sidebar: consistent hierarchy & spacing ----- */
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%); }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"],
    [data-testid="stSidebar"] .block-container { padding-top: 0 !important; }
    /* Reduce sidebar header / logo spacer so Step 1 sits higher */
    [data-testid="stSidebarHeader"] { min-height: 0 !important; padding-top: 0.5rem !important; padding-bottom: 0.25rem !important; }
    [data-testid="stLogoSpacer"] { height: 0 !important; min-height: 0 !important; display: none !important; }
    [data-testid="stSidebar"] .stMarkdown { color: #334155; line-height: 1.45; }
    [data-testid="stSidebar"] h1 { font-size: 1.2rem !important; font-weight: 600 !important; color: #1e293b !important; margin-bottom: 0.5rem !important; }
    [data-testid="stSidebar"] h3 { font-size: 1.2rem !important; font-weight: 700 !important; color: #0f172a !important; margin-top: 0.75rem !important; margin-bottom: 0.5rem !important; }
    [data-testid="stSidebar"] .stRadio label { font-weight: 500; font-size: 0.95rem !important; }
    [data-testid="stSidebar"] .stExpander { border-radius: 8px; border: 1px solid #e2e8f0; }
    [data-testid="stSidebar"] .stExpander summary { font-weight: 600; color: #334155; padding: 0.4rem 0; }

    /* ----- Labels: consistent, readable ----- */
    [data-testid="stWidgetLabel"] { font-weight: 600 !important; color: #334155 !important; font-size: 0.95rem !important; }
    .stTextArea label, .stTextInput label { font-weight: 600 !important; color: #334155 !important; }

    /* ----- Cards / sections ----- */
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; margin-bottom: 1.25rem; }
    .stTabs [data-baseweb="tab"] { padding: 0.6rem 1.2rem; font-weight: 600; border-radius: 8px; font-size: 0.95rem !important; }
    .stTabs [aria-selected="true"] { background: #0ea5e9 !important; color: white !important; }

    /* ----- Metrics ----- */
    [data-testid="stMetric"] { background: #f8fafc; padding: 1rem 1.25rem; border-radius: 10px; border: 1px solid #e2e8f0; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; font-weight: 600 !important; color: #64748b !important; text-transform: uppercase; letter-spacing: 0.03em; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; font-weight: 700 !important; color: #0f172a !important; }

    /* ----- Buttons: consistent size and focus ----- */
    .stButton > button { padding: 0.6rem 1.5rem; font-size: 0.95rem; font-weight: 600; border-radius: 8px; transition: transform 0.15s ease, box-shadow 0.15s ease; min-height: 2.5rem; }
    .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(14, 165, 233, 0.25); }
    .stButton > button:focus-visible { outline: 2px solid #0ea5e9; outline-offset: 2px; }
    .stButton > button[kind="primary"],
    .stButton > button[kind="primary"] * { background: transparent !important; color: white !important; border: none !important; }
    .stButton > button[kind="primary"] { background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important; }
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stFormSubmitButton"] button * { color: white !important; }
    [data-testid="stFormSubmitButton"] button:focus-visible { outline: 2px solid #0ea5e9; outline-offset: 2px; }

    /* ----- Inputs: consistent box and focus ----- */
    .stTextInput input, .stTextArea textarea { border-radius: 8px; border: 1px solid #e2e8f0; font-size: 0.95rem !important; line-height: 1.5 !important; }
    .stTextInput input:focus, .stTextArea textarea:focus { border-color: #0ea5e9; box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.2); outline: none; }
    .stTextArea textarea { min-height: 8rem; }

    /* ----- Dataframe ----- */
    .stDataFrame { border-radius: 10px; overflow: hidden; border: 1px solid #e2e8f0; }

    /* ----- Alerts & captions ----- */
    .stAlert { border-radius: 8px; border: 1px solid transparent; }
    .stCaption { color: #64748b !important; font-size: 0.875rem !important; line-height: 1.45 !important; margin-top: 0.25rem !important; }

    /* ----- Divider ----- */
    hr { margin: 1.25rem 0 !important; border-color: #e2e8f0 !important; }

    /* ----- Hide file uploader limit text ----- */
    [data-testid="stFileUploader"] small,
    [data-testid="stFileUploader"] [class*="caption"],
    [data-testid="stFileUploader"] p,
    [data-testid="stFileUploader"] [class*="help"],
    [data-testid="stFileUploader"] [class*="limit"] { display: none !important; }

    /* ----- Step 1 API keys: card-style layout and drop zone ----- */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] {
        margin-bottom: 0.75rem;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"],
    [data-testid="stSidebar"] [data-testid="stFileUploader"] section {
        border: 2px dashed #cbd5e1 !important;
        border-radius: 10px !important;
        background: #f8fafc !important;
        padding: 1rem 0.75rem !important;
        min-height: 4rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"]:hover,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] section:hover {
        border-color: #0ea5e9 !important;
        background: #f0f9ff !important;
    }
    [data-testid="stSidebar"] .stDownloadButton {
        margin-top: 0.5rem;
        margin-bottom: 0.5rem;
    }
    [data-testid="stSidebar"] .stDownloadButton > button {
        width: 100%;
        border: 1px solid #e2e8f0;
        background: #fff;
        color: #1e293b;
    }
    [data-testid="stSidebar"] .stDownloadButton > button:hover {
        border-color: #0ea5e9;
        background: #f0f9ff;
        color: #0284c7;
    }
    [data-testid="stSidebar"] .stExpander {
        margin-top: 0.25rem;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# Hide file uploader "Limit 200MB per file • TXT, ENV" via JS (runs in iframe, modifies parent DOM)
_hide_uploader_limit_script = """
<script>
(function() {
  var doc = window.parent && window.parent.document ? window.parent.document : document;
  function hideLimit() {
    try {
      var uploaders = doc.querySelectorAll('[data-testid="stFileUploader"]');
      for (var i = 0; i < uploaders.length; i++) {
        var walk = function(node) {
          if (node.nodeType === Node.TEXT_NODE && node.textContent && /Limit|200MB|per file|TXT.*ENV/.test(node.textContent)) {
            if (node.parentElement) node.parentElement.style.setProperty('display', 'none', 'important');
            return;
          }
          for (var j = 0; j < node.childNodes.length; j++) walk(node.childNodes[j]);
        };
        walk(uploaders[i]);
      }
    } catch (e) {}
  }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', hideLimit);
  else hideLimit();
  setTimeout(hideLimit, 400);
  setTimeout(hideLimit, 1200);
})();
</script>
"""
if components is not None:
    components.html(_hide_uploader_limit_script, height=0)

st.sidebar.markdown("---")
st.sidebar.caption("🔐 Keys are used only in this session and are not stored on disk.")


def _title_with_icon(icon_filename, title_text):
    """Render page title with icon from icons folder."""
    icon_path = _icons_dir / icon_filename
    if icon_path.exists():
        col_icon, col_title = st.columns([0.08, 0.92])
        with col_icon:
            st.image(str(icon_path), width="stretch")
        with col_title:
            st.title(title_text)
    else:
        st.title(title_text)


def _locked_view(reminder_message):
    """Show locked state: reminder to enter API key."""
    st.markdown("<br>", unsafe_allow_html=True)
    st.info(f"🔒 {reminder_message}")
    st.caption("Add your API keys in **Step 1** in the sidebar to unlock the search view.")


# ==========================================
# UNIFIED CITATION SEARCH (all three platforms)
# ==========================================
if app_mode == "Unified citation search":
    _title_with_icon("Merge.png", "Unified Citation Search")
    st.markdown("Search citation counts from **Web of Science**, **Scopus**, and **Google Scholar** in one go.")
    st.caption(f"Paste DOIs (one per line). Platforms with keys in Step 1 will be queried: WOS {'✓' if _wos_ok else '—'} · Scopus {'✓' if _scopus_ok else '—'} · Google Scholar {'✓' if _gs_ok else '—'}.")

    if not api_unlocked:
        _locked_view(api_reminder)
    else:
        raw_input = st.text_area(
            "📋 Paste DOIs (one per line)",
            height=200,
            placeholder="10.3390/cancers16050984\n10.1038/s41593-021-00969-4",
            key="unified_input",
        )
        _uc1, _uc2, _uc3 = st.columns([1, 1, 1])
        with _uc2:
            unified_clicked = st.button("🔍 Search all platforms", type="primary", use_container_width=True, key="unified_btn")

        if unified_clicked:
            lines = [line.strip() for line in raw_input.split("\n") if line.strip()]
            if not lines:
                st.warning("Please enter at least one DOI or WOS ID.")
            else:
                # Resolve WOS IDs to DOIs where needed; build list of (user_id, doi or None)
                identifiers = []
                dois_to_fetch = set()
                for line in lines:
                    if line.lower().startswith("10."):
                        identifiers.append((line, line))
                        dois_to_fetch.add(line)
                    else:
                        identifiers.append((line, None))  # WOS ID, resolve later

                # Resolve WOS IDs to DOIs if we have WOS key
                if _wos_ok and any(id_[1] is None for id_ in identifiers):
                    wos_ids_to_resolve = [id_[0] for id_ in identifiers if id_[1] is None]
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    wos_resolve = fetch_wos_data(wos_ids_to_resolve, progress_bar, status_text, wos_api_key=WOS_API_KEY)
                    resolved_dois = {}
                    for r in wos_resolve:
                        uid = r.get("Unique WOS ID", "")
                        doi = r.get("DOI", "N/A")
                        if uid and doi and doi != "N/A":
                            resolved_dois[uid] = doi
                    new_identifiers = []
                    for user_id, doi in identifiers:
                        if doi is not None:
                            new_identifiers.append((user_id, doi))
                        else:
                            resolved = resolved_dois.get(user_id)
                            new_identifiers.append((user_id, resolved if resolved else user_id))
                    identifiers = new_identifiers
                    for _, d in identifiers:
                        if d and d != "N/A" and str(d).startswith("10."):
                            dois_to_fetch.add(d)
                else:
                    for user_id, doi in identifiers:
                        if doi and str(doi).startswith("10."):
                            dois_to_fetch.add(doi)
                    if not dois_to_fetch and any(id_[1] for id_ in identifiers):
                        dois_to_fetch = {id_[1] for id_ in identifiers if id_[1] and str(id_[1]).startswith("10.")}

                progress_bar = st.progress(0)
                status_text = st.empty()
                total_steps = len(identifiers) * ( (_wos_ok and 1 or 0) + (_scopus_ok and 1 or 0) + (_gs_ok and 1 or 0) )
                if total_steps == 0:
                    total_steps = 1
                step = 0
                unified_rows = []
                for user_id, doi in identifiers:
                    row = {
                        "Identifier": user_id,
                        "DOI": doi if doi else "N/A",
                        "Title": "N/A",
                        "WOS Citation Count": "N/A",
                        "Scopus Total Citations": "N/A",
                        "Scopus Excl. self": "N/A",
                        "Google Scholar citations": "N/A",
                        "Status (WOS)": "N/A",
                        "Status (Scopus)": "N/A",
                        "Status (Google Scholar)": "N/A",
                    }
                    effective_doi = doi if doi and str(doi).startswith("10.") else None
                    if _wos_ok and effective_doi:
                        status_text.text(f"WOS: {user_id[:50]}...")
                        wos_list = fetch_wos_data([effective_doi], progress_bar, status_text, wos_api_key=WOS_API_KEY)
                        if wos_list:
                            w = wos_list[0]
                            row["Title"] = w.get("Title", "N/A")
                            row["WOS Citation Count"] = w.get("Citation Count", "N/A")
                            row["Status (WOS)"] = w.get("Status", "N/A")
                        step += 1
                        progress_bar.progress(min(step / total_steps, 1.0))
                    if _scopus_ok and effective_doi:
                        status_text.text(f"Scopus: {user_id[:50]}...")
                        try:
                            s = process_doi_scopus(effective_doi, SCOPUS_API_KEY, SCOPUS_INST_TOKEN)
                            row["Title"] = row["Title"] if row["Title"] != "N/A" else s.get("Title", "N/A")
                            row["Scopus Total Citations"] = s.get("Total Citations", "N/A")
                            row["Scopus Excl. self"] = s.get("Exclude self-citations", "N/A")
                            row["Status (Scopus)"] = s.get("Status", "N/A")
                        except Exception:
                            row["Status (Scopus)"] = "Error"
                        step += 1
                        progress_bar.progress(min(step / total_steps, 1.0))
                        time.sleep(0.5)
                    if _gs_ok and effective_doi:
                        status_text.text(f"Google Scholar: {user_id[:50]}...")
                        gs = fetch_google_scholar_result(effective_doi, SERPAPI_KEY)
                        row["Title"] = row["Title"] if row["Title"] != "N/A" else gs.get("Title", "N/A")
                        row["Google Scholar citations"] = gs.get("Google Scholar citations", "N/A")
                        row["Status (Google Scholar)"] = gs.get("Status", "N/A")
                        step += 1
                        progress_bar.progress(min(step / total_steps, 1.0))
                        time.sleep(0.3)
                    unified_rows.append(row)
                status_text.success(f"✅ Finished processing {len(unified_rows)} records!")
                df_unified = pd.DataFrame(unified_rows)
                st.session_state["unified_df"] = df_unified

        if "unified_df" in st.session_state:
            df_show = st.session_state["unified_df"]
            st.divider()
            st.dataframe(df_show, width="stretch")
            excel_data = to_excel(df_show)
            st.download_button(
                label="📥 Download results (.xlsx)",
                data=excel_data,
                file_name="unified_citation_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="unified_download_btn",
            )

elif app_mode == "Web of Science":
    _title_with_icon("WoS.png", "Web of Science (includes SCIE, SSCI and CPCI) Citation Finder")

    if not api_unlocked:
        _locked_view(api_reminder)
    else:
        wos_search_mode = st.radio(
            "Search type:",
            ["Citation finder (by WOS ID or DOI)", "Journal metrics (JCR by ISSN/title)"],
            format_func=lambda x: "📄 Citation finder (by WOS ID or DOI)" if x == "Citation finder (by WOS ID or DOI)" else "📰 Journal metrics (JCR by ISSN/title)",
            horizontal=True,
            key="wos_mode",
        )

        if wos_search_mode == "Citation finder (by WOS ID or DOI)":
            st.markdown("Fetch article metadata, authors, and citation counts by **WOS ID** or **DOI**.")
            st.caption("Paste one identifier per line (e.g. `WOS:000267144200002` or `10.3390/cancers16050984`).")
            raw_wos_text = st.text_area(
                "📋 Paste WOS IDs or DOIs (one per line)",
                height=200,
                placeholder="WOS:001681025100006\n10.3390/cancers16050984",
            )

            _c1, _c2, _c3 = st.columns([1, 1, 1])
            with _c2:
                _wos_clicked = st.button("🔍 Search Web of Science", type="primary", use_container_width=True)

            if _wos_clicked:
                wos_ids = [line.strip() for line in raw_wos_text.split('\n') if line.strip()]
                if wos_ids and "unique wos id" in wos_ids[0].lower():
                    wos_ids.pop(0)  # remove header if pasted

                if not wos_ids:
                    st.warning("Please enter at least one WOS ID or DOI.")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    wos_data = fetch_wos_data(wos_ids, progress_bar, status_text)

                    success_count = sum(1 for r in wos_data if r.get("Status") == "Success")
                    status_text.success(f"✅ Finished processing {len(wos_data)} records!")
                    if success_count == 0:
                        st.warning("**Cannot find DOI — no documents could be found.** Please check your WOS IDs (format like `WOS:001681025100006`) and that your API key has access to these documents.")
                    df_wos = pd.DataFrame(wos_data)
                    st.session_state["wos_df"] = df_wos

            if "wos_df" in st.session_state and wos_search_mode == "Citation finder (by WOS ID or DOI)":
                df_show = st.session_state["wos_df"]
                st.divider()
                _gs_clicked = False
                if SERPAPI_KEY and SERPAPI_KEY.strip():
                    st.divider()
                    st.subheader("📊 Enrich with Google Scholar")
                    _gc1, _gc2, _gc3 = st.columns([1, 1, 1])
                    with _gc2:
                        _gs_clicked = st.button("🎓 Add Google Scholar citations", type="secondary", use_container_width=True)
                elif not SERPAPI_AVAILABLE:
                    st.sidebar.caption("Install `google-search-results` for Google Scholar: pip install google-search-results")
                else:
                    st.caption("Add a SerpAPI key in the sidebar to fetch Google Scholar citation counts by DOI.")

                if _gs_clicked and SERPAPI_KEY and SERPAPI_KEY.strip() and SERPAPI_AVAILABLE:
                    dois = df_show["DOI"].astype(str).tolist()
                    total = len(dois)
                    progress_gs = st.progress(0)
                    status_gs = st.empty()
                    gs_citations = []
                    for i, doi in enumerate(dois):
                        status_gs.text(f"Google Scholar {i+1}/{total}: {doi[:40]}...")
                        cnt = fetch_google_scholar_citation(doi, SERPAPI_KEY)
                        gs_citations.append(cnt if cnt is not None else "N/A")
                        progress_gs.progress((i + 1) / total)
                        time.sleep(0.3)
                    status_gs.success("✅ Google Scholar citations added.")
                    df_show = df_show.copy()
                    df_show["Google Scholar citations"] = gs_citations
                    st.session_state["wos_df"] = df_show

                if "Google Scholar citations" in df_show.columns or not _gs_clicked:
                    st.dataframe(st.session_state["wos_df"], width="stretch")
                    excel_data = to_excel(st.session_state["wos_df"])
                    st.download_button(
                        label="📥 Download results (.xlsx)",
                        data=excel_data,
                        file_name="wos_bulk_results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="wos_download_btn",
                    )

        else:
            st.markdown("Fetch **journal metrics** (JCR) by **ISSN** or **journal title**.")
            st.caption("Enter one ISSN or title per line.")
            raw_journal_text = st.text_area(
                "📋 Enter ISSNs or journal titles (one per line)",
                height=200,
                placeholder="0000-0000\n1363-2434\nJournal of Marketing",
                key="wos_journal_queries",
            )
            jcr_year = st.text_input("JCR year (e.g. 2019, 2023)", value="", key="wos_jcr_year")
            edition_options = ["SCIE", "SSCI", "AHCI", "ESCI"]
            selected_editions = st.multiselect(
                "Edition filter (optional, Web of Science index):",
                edition_options,
                default=[],
                help="Matches the Journals API `edition` parameter. Leave empty to include all editions.",
            )

            _j1, _j2, _j3 = st.columns([1, 1, 1])
            with _j2:
                _wos_journal_clicked = st.button("🔍 Search WOS Journals (JCR)", type="primary", use_container_width=True, key="wos_journal_btn")

            if _wos_journal_clicked:
                if not (WOS_JOURNAL_API_KEY and WOS_JOURNAL_API_KEY.strip()):
                    st.warning("Please enter your **WOS Journal API key** in the sidebar to search journal metrics.")
                else:
                    queries = [line.strip() for line in raw_journal_text.split("\n") if line.strip()]
                    if not queries:
                        st.warning("Please enter at least one ISSN or journal title.")
                    else:
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        # Default to latest JCR year (e.g. 2023) if blank, because jcrYear is required for metrics
                        jcr_year_val = (jcr_year or "").strip() or "2023"
                        edition_filter = ";".join(selected_editions) if selected_editions else None
                        journal_rows = fetch_wos_journal_data(
                            queries,
                            WOS_JOURNAL_API_KEY.strip(),
                            jcr_year_val,
                            edition_filter,
                            progress_bar,
                            status_text,
                        )
                        status_text.success(f"✅ Finished processing {len(journal_rows)} records!")
                        df_wos_journal = pd.DataFrame(journal_rows)
                        st.session_state["wos_journal_df"] = df_wos_journal

            if "wos_journal_df" in st.session_state and wos_search_mode == "Journal metrics (JCR by ISSN/title)":
                st.divider()
                st.dataframe(st.session_state["wos_journal_df"], width="stretch")
                excel_jcr = to_excel(st.session_state["wos_journal_df"])
                st.download_button(
                    label="📥 Download journal metrics (.xlsx)",
                    data=excel_jcr,
                    file_name="wos_journal_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="wos_journal_download_btn",
                )

elif app_mode == "Scopus":
    _title_with_icon("Scopus.png", "Scopus Citation Finder")
    if not api_unlocked:
        _locked_view(api_reminder)
    else:
        scopus_search_mode = st.radio(
            "Search type:",
            ["Citation finder (by DOI)", "Journal metrics (by ISSN)"],
            format_func=lambda x: "📄 Citation finder (by DOI)" if x == "Citation finder (by DOI)" else "📰 Journal metrics (by ISSN)",
            horizontal=True,
            key="scopus_mode",
        )

        if scopus_search_mode == "Citation finder (by DOI)":
            st.markdown("Fetch **citation metrics** (total and exclude self-citations) by **DOI**.")
            st.caption("Paste DOIs (one per line) or upload a CSV/Excel file with a DOI column.")
            raw_dois = st.text_area("📋 Paste DOIs (one per line)", height=200, placeholder="10.5194/bg-18-2755-2021\n10.3389/fmars.2021.615929", key="scopus_bulk_dois")
            uploaded_file = st.file_uploader("📎 Or upload file (.csv, .xlsx)", type=["csv", "xlsx", "xls"], key="scopus_upload")

            _c1, _c2, _c3 = st.columns([1, 1, 1])
            with _c2:
                _scopus_clicked = st.button("🔍 Search Scopus", type="primary", use_container_width=True, key="scopus_bulk_btn")

            if _scopus_clicked:
                text_dois = [d.strip() for d in raw_dois.split("\n") if d.strip().startswith("10.")]
                file_dois = []
                if uploaded_file is not None:
                    try:
                        if uploaded_file.name.endswith(".csv"):
                            df = pd.read_csv(uploaded_file)
                        else:
                            df = pd.read_excel(uploaded_file)
                        file_dois = extract_dois_from_df(df)
                    except Exception as e:
                        st.error(f"Error reading file: {e}")
                all_dois = list(set(text_dois + file_dois))

                if not all_dois:
                    st.warning("No valid DOIs found. Please ensure they start with '10.'")
                else:
                    st.info(f"Processing {len(all_dois)} unique DOIs...")
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results_list = []
                    sleep_time = 1.25
                    for i, doi in enumerate(all_dois):
                        status_text.text(f"Fetching {i+1} of {len(all_dois)}: {doi}")
                        result = process_doi_scopus(doi, SCOPUS_API_KEY, SCOPUS_INST_TOKEN)
                        results_list.append(result)
                        progress_bar.progress((i + 1) / len(all_dois))
                        time.sleep(sleep_time)
                    status_text.success(f"✅ Finished processing {len(results_list)} records!")
                    df_results = pd.DataFrame(results_list)
                    df_results = df_results[["DOI", "Title", "Year", "Total Citations", "Exclude self-citations", "Status"]]
                    st.session_state["scopus_df"] = df_results

            if "scopus_df" in st.session_state and scopus_search_mode == "Citation finder (by DOI)":
                st.divider()
                st.dataframe(st.session_state["scopus_df"], width="stretch")
                excel_data = to_excel(st.session_state["scopus_df"])
                st.download_button(
                    label="📥 Download results (.xlsx)",
                    data=excel_data,
                    file_name="scopus_citation_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="scopus_download_btn",
                )

        else:
            st.markdown("Fetch **journal metrics** (CiteScore, SNIP, SJR, subject areas) by **ISSN**.")
            st.caption("Enter one ISSN per line (with or without hyphen).")
            raw_issn_text = st.text_area("📋 Enter ISSNs (one per line)", height=200, placeholder="2161-797X\n1755-0645\n0309-0566", key="scopus_issn_bulk")

            _j1, _j2, _j3 = st.columns([1, 1, 1])
            with _j2:
                _journal_clicked = st.button("🔍 Search Scopus Journals", type="primary", use_container_width=True, key="scopus_journal_btn")

            if _journal_clicked:
                raw_lines = [line.strip() for line in raw_issn_text.split("\n") if line.strip()]
                clean_issns = [clean_issn(issn) for issn in raw_lines if clean_issn(issn)]
                if not clean_issns:
                    st.warning("Please enter valid 8-character ISSNs (with or without hyphen).")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    journal_data = fetch_scopus_journal_data(clean_issns, SCOPUS_API_KEY, SCOPUS_INST_TOKEN, progress_bar, status_text)
                    status_text.success(f"✅ Finished processing {len(journal_data)} records!")
                    df_journal = pd.DataFrame(journal_data)
                    st.session_state["scopus_journal_df"] = df_journal

            if "scopus_journal_df" in st.session_state:
                st.divider()
                st.dataframe(st.session_state["scopus_journal_df"], width="stretch")
                excel_journal = to_excel(st.session_state["scopus_journal_df"])
                st.download_button(
                    label="📥 Download journal metrics (.xlsx)",
                    data=excel_journal,
                    file_name="scopus_journal_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="scopus_journal_download_btn",
                )

elif app_mode == "Google Scholar":
    _title_with_icon("Google.png", "Google Scholar Citation Finder")
    st.markdown("Fetch **citation counts** by **DOI** (via SerpAPI).")
    st.caption("Paste one DOI per line.")

    if not api_unlocked:
        _locked_view(api_reminder)
    elif not SERPAPI_AVAILABLE:
        st.warning("⚠️ Install the SerpAPI client: **pip install google-search-results**")
    else:
        raw_doi_text = st.text_area("📋 Paste DOIs (one per line)", height=200, placeholder="10.1038/s41593-021-00969-4\n10.1109/TMI.2025.3605219")

        _c1, _c2, _c3 = st.columns([1, 1, 1])
        with _c2:
            _gs_search_clicked = st.button("🔍 Search Google Scholar", type="primary", use_container_width=True)

        if _gs_search_clicked:
            dois = [line.strip() for line in raw_doi_text.split("\n") if line.strip()]
            dois = [d for d in dois if d and d != "N/A"]
            if not dois:
                st.warning("Please enter at least one DOI.")
            else:
                progress_gs = st.progress(0)
                status_gs = st.empty()
                gs_results = []
                for i, doi in enumerate(dois):
                    status_gs.text(f"Fetching {i+1}/{len(dois)}: {doi[:50]}...")
                    row = fetch_google_scholar_result(doi, SERPAPI_KEY)
                    gs_results.append(row)
                    progress_gs.progress((i + 1) / len(dois))
                    time.sleep(0.3)
                status_gs.success(f"✅ Finished processing {len(gs_results)} records!")
                df_gs = pd.DataFrame(gs_results)
                st.divider()
                st.dataframe(df_gs)
                excel_data = to_excel(df_gs)
                st.download_button(
                    label="📥 Download results (.xlsx)",
                    data=excel_data,
                    file_name="google_scholar_citations.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="gs_download_btn",
                )

elif app_mode == "Crossref":
    _cr_icon_path = _icons_dir / "Crossref.png"
    if _cr_icon_path.exists():
        _cr_icon_col, _cr_title_col = st.columns([0.22, 0.78])  # larger icon for prominence
        with _cr_icon_col:
            st.image(str(_cr_icon_path), width="stretch")
            st.caption("Metadata from Crossref")
        with _cr_title_col:
            st.title("Crossref Search")
    else:
        st.title("Crossref Search")
    st.markdown("Search **DOI** and metadata (title, authors, journal, type, year, publisher, volume, issue, pages) via the [Crossref Works API](https://api.crossref.org/). No API key required (optional mailto for polite pool).")

    _cr_tab_lookup, _cr_tab_search = st.tabs(["🔎 Lookup by DOI(s)", "📄 Search by query"])

    with _cr_tab_lookup:
        _cr_mailto_lookup = st.text_input("Mailto (optional, for polite pool)", placeholder="your.email@example.com", key="crossref_mailto_lookup")
        _cr_single_doi = st.text_input(
            "Single DOI",
            placeholder="e.g. 10.1016/j.jinorgbio.2021.111634",
            key="crossref_single_doi",
            help="Accepts a DOI, a doi.org URL, or a Crossref works URL.",
        )
        _cr_bulk = st.text_area(
            "Bulk DOIs (one per line)",
            height=180,
            placeholder="10.1016/j.jinorgbio.2021.111634\n10.1038/nature12373\nhttps://doi.org/10.3390/cancers16050984",
            key="crossref_bulk_dois",
            help="Paste multiple DOIs (one per line). We'll fetch each one using Crossref's /works/{doi} endpoint.",
        )
        _cr_bulk_btn_col1, _cr_bulk_btn_col2, _cr_bulk_btn_col3 = st.columns([1, 1, 1])
        with _cr_bulk_btn_col2:
            _cr_bulk_clicked = st.button("Fetch DOI metadata", type="primary", use_container_width=True, key="crossref_bulk_btn")

        if _cr_bulk_clicked:
            lines = [l.strip() for l in (_cr_bulk or "").splitlines() if l.strip()]
            dois = lines if lines else ([_cr_single_doi.strip()] if _cr_single_doi and _cr_single_doi.strip() else [])
            if not dois:
                st.warning("Please enter at least one DOI (single or bulk list).")
            else:
                max_n = 200
                if len(dois) > max_n:
                    st.warning(f"Too many DOIs ({len(dois)}). Processing the first {max_n} only.")
                    dois = dois[:max_n]
                progress = st.progress(0)
                status = st.empty()
                out_rows = []
                for i, d in enumerate(dois, 1):
                    status.text(f"Crossref DOI {i}/{len(dois)}: {str(d)[:60]}...")
                    rows, _ = bulk_crossref_lookup_by_dois([d], mailto=(_cr_mailto_lookup or "").strip())
                    out_rows.extend(rows)
                    progress.progress(i / len(dois))
                    time.sleep(0.2)
                status.success(f"✅ Finished processing {len(out_rows)} DOI(s).")
                df = pd.DataFrame(out_rows)
                st.dataframe(df, width="stretch")
                st.download_button(
                    label="📥 Download Crossref DOI results (.xlsx)",
                    data=to_excel(df),
                    file_name="crossref_doi_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="crossref_doi_download_btn",
                )

    with _cr_tab_search:
        _cr_query = st.text_input("Search query (general)", placeholder="e.g. machine learning climate", key="crossref_query")
        _cr_author = st.text_input("Author (query.author)", placeholder="e.g. Richard Feynman", key="crossref_author")
        _cr_title = st.text_input("Title / bibliographic (query.bibliographic)", placeholder="e.g. Quantum Electrodynamics", key="crossref_title")
        _cr_row1, _cr_row2 = st.columns(2)
        with _cr_row1:
            _cr_rows = st.number_input("Results per page", min_value=1, max_value=100, value=20, key="crossref_rows")
            _cr_sort = st.selectbox(
                "Sort by",
                ["relevance", "score", "updated", "deposited", "indexed", "published", "published-online", "published-print", "issued", "is-referenced-by-count", "references-count", "created"],
                key="crossref_sort",
            )
        with _cr_row2:
            _cr_offset = st.number_input("Offset (skip N results)", min_value=0, value=0, key="crossref_offset")
            _cr_mailto = st.text_input("Mailto (optional, for polite pool)", placeholder="your.email@example.com", key="crossref_mailto")

        _cr_btn_col1, _cr_btn_col2, _cr_btn_col3 = st.columns([1, 1, 1])
        with _cr_btn_col2:
            _cr_clicked = st.button("Search Crossref", type="primary", use_container_width=True, key="crossref_search_btn")

        if _cr_clicked:
            items, total, err = search_crossref_works(
                query=_cr_query or None,
                query_author=_cr_author or None,
                query_title=_cr_title or None,
                rows=_cr_rows,
                offset=int(_cr_offset),
                sort=_cr_sort,
                mailto=(_cr_mailto or "").strip(),
            )
            if err:
                st.error(err)
            else:
                st.success(f"Found **{total}** result(s). Showing {len(items)} on this page.")
                if items:
                    _cr_df = pd.DataFrame(items)
                    st.dataframe(_cr_df, width="stretch")
                    _cr_excel = to_excel(_cr_df)
                    st.download_button(
                        label="📥 Download Crossref search results (.xlsx)",
                        data=_cr_excel,
                        file_name="crossref_works_results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="crossref_download_btn",
                    )
                else:
                    st.info("No works returned for this page. Try different terms or increase the offset.")
