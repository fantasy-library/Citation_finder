import streamlit as st
import requests
import pandas as pd
import time
import io
from pathlib import Path

try:
    from serpapi import GoogleSearch as SerpApiGoogleSearch
    SERPAPI_AVAILABLE = True
except ImportError:
    SERPAPI_AVAILABLE = False

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Academic Database Search", page_icon="📚", layout="wide")

# Default Scopus institutional token from secrets (optional); user doesn't need to re-enter
try:
    _default_inst_token = st.secrets.get("SCOPUS_INST_TOKEN", "")
except Exception:
    _default_inst_token = ""

# Navigation first so we know which credentials to require
st.sidebar.title("🧭 Navigation")
# Show database icons (Streamlit radio only supports text labels, so we display icons above)
_icons_dir = Path(__file__).resolve().parent / "icons"
try:
    icon_cols = st.sidebar.columns(3)
    icon_cols[0].image(str(_icons_dir / "WoS.png"), caption="Web of Science", use_container_width=True)
    icon_cols[1].image(str(_icons_dir / "Scopus.png"), caption="Scopus", use_container_width=True)
    icon_cols[2].image(str(_icons_dir / "Google.png"), caption="Google Scholar", use_container_width=True)
except Exception:
    pass  # If icons missing, navigation still works with radio only
app_mode = st.sidebar.radio(
    "Select Database API:",
    ["Web of Science", "Scopus", "Google Scholar"],
    format_func=lambda x: {"Web of Science": "📚 Web of Science", "Scopus": "📈 Scopus", "Google Scholar": "🎓 Google Scholar"}[x],
)
st.sidebar.markdown("---")
st.sidebar.header("🔑 API configuration")

# Show only the API key field(s) for the selected database
if app_mode == "Web of Science":
    st.sidebar.info("⬇️ Enter your **WOS API key** below to get started.")
    WOS_API_KEY = st.sidebar.text_input("WOS API key", type="password", placeholder="Your WOS API key")
    SCOPUS_API_KEY = ""
    SCOPUS_INST_TOKEN = _default_inst_token or ""
    SERPAPI_KEY = ""
elif app_mode == "Scopus":
    st.sidebar.info("⬇️ Enter your **Scopus API key** and **institutional token** below.")
    SCOPUS_API_KEY = st.sidebar.text_input("Scopus API key", type="password", placeholder="Your Scopus API key")
    if _default_inst_token:
        SCOPUS_INST_TOKEN = _default_inst_token
    else:
        SCOPUS_INST_TOKEN = st.sidebar.text_input("Scopus institutional token", type="password", placeholder="Your institutional token")
    WOS_API_KEY = ""
    SERPAPI_KEY = ""
else:
    st.sidebar.info("⬇️ Enter your **SerpAPI key** below to get started.")
    SERPAPI_KEY = st.sidebar.text_input("SerpAPI key", type="password", placeholder="Your SerpAPI key")
    WOS_API_KEY = ""
    SCOPUS_API_KEY = ""
    SCOPUS_INST_TOKEN = _default_inst_token or ""

# Require at least the credentials for the selected mode (no need to enter all)
if app_mode == "Google Scholar":
    if not SERPAPI_KEY or not SERPAPI_KEY.strip():
        st.sidebar.warning("Please enter your SerpAPI key for Google Scholar.")
        st.stop()
elif app_mode == "Web of Science":
    if not WOS_API_KEY or not WOS_API_KEY.strip():
        st.sidebar.warning("Please enter your WOS API key to use Web of Science.")
        st.stop()
elif app_mode == "Scopus":
    if not SCOPUS_API_KEY or not SCOPUS_API_KEY.strip() or not SCOPUS_INST_TOKEN or not SCOPUS_INST_TOKEN.strip():
        st.sidebar.warning("Please enter your Scopus API key and institutional token to use Scopus.")
        st.stop()

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
def fetch_wos_data(wos_ids, progress_bar, status_text):
    results = []
    total = len(wos_ids)

    for i, wos_id in enumerate(wos_ids):
        status_text.text(f"Fetching WOS ID {i+1} of {total}: {wos_id}...")
        url = f"https://api.clarivate.com/apis/wos-starter/v1/documents/{wos_id}"
        headers = {"X-ApiKey": WOS_API_KEY}

        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()

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

                results.append({
                    "Unique WOS ID": wos_id,
                    "DOI": doi,
                    "WOS search (DO)": doi_query,
                    "Title": data.get('title', 'N/A'),
                    "Author Full Names": full_names or "N/A",
                    "Query (AU)": query,
                    "Document Type": "; ".join(data.get('types', [])) or "N/A",
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
                    "Unique WOS ID": wos_id, "DOI": "N/A", "WOS search (DO)": "N/A", "Title": "N/A", "Author Full Names": "N/A",
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
                "Unique WOS ID": wos_id, "DOI": "N/A", "WOS search (DO)": "N/A", "Title": "N/A", "Author Full Names": "N/A",
                "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                "Status": msg,
            })
        except Exception as e:
            results.append({
                "Unique WOS ID": wos_id, "DOI": "N/A", "WOS search (DO)": "N/A", "Title": "N/A", "Author Full Names": "N/A",
                "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                "Status": f"Error: {str(e)[:60]}",
            })

        progress_bar.progress((i + 1) / total)
        time.sleep(1)  # Rate limit protection

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
# EXCEL GENERATOR (In-Memory)
# ==========================================
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    return output.getvalue()


# ==========================================
# USER INTERFACE – Professional styling & icons
# ==========================================
st.markdown("""
<style>
    /* Main container & typography */
    .main .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1100px; }
    h1 { font-weight: 700; letter-spacing: -0.02em; color: #1e293b; margin-bottom: 0.25rem !important; }
    h2 { font-weight: 600; color: #334155; font-size: 1.25rem !important; margin-top: 1.5rem !important; }
    h3 { font-weight: 600; color: #475569; font-size: 1.1rem !important; }
    p { color: #64748b; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%); }
    [data-testid="stSidebar"] .stMarkdown { color: #334155; }
    [data-testid="stSidebar"] h1 { font-size: 1.35rem !important; }
    [data-testid="stSidebar"] .stRadio label { font-weight: 500; }

    /* Cards / sections */
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; margin-bottom: 1.5rem; }
    .stTabs [data-baseweb="tab"] { padding: 0.6rem 1.2rem; font-weight: 600; border-radius: 8px; }
    .stTabs [aria-selected="true"] { background: #0ea5e9 !important; color: white !important; }

    /* Metrics */
    [data-testid="stMetric"] { background: #f8fafc; padding: 1rem 1.25rem; border-radius: 10px; border: 1px solid #e2e8f0; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; font-weight: 600 !important; color: #64748b !important; text-transform: uppercase; letter-spacing: 0.03em; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; font-weight: 700 !important; color: #0f172a !important; }

    /* Buttons */
    .stButton > button { padding: 0.6rem 1.5rem; font-size: 1rem; font-weight: 600; border-radius: 8px; transition: transform 0.15s ease, box-shadow 0.15s ease; }
    .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(14, 165, 233, 0.25); }
    .stButton > button[kind="primary"] { background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%); border: none; }

    /* Inputs */
    .stTextInput input, .stTextArea textarea { border-radius: 8px; border: 1px solid #e2e8f0; }
    .stTextInput input:focus, .stTextArea textarea:focus { border-color: #0ea5e9; box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.2); }

    /* Dataframe */
    .stDataFrame { border-radius: 10px; overflow: hidden; border: 1px solid #e2e8f0; }

    /* Alerts & captions */
    .stAlert { border-radius: 8px; }
    .stCaption { color: #94a3b8 !important; font-size: 0.85rem !important; }

    /* Divider */
    hr { margin: 1.5rem 0 !important; border-color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.caption("🔐 Enter only the API key(s) for the selected database. Keys are not stored on disk.")

if app_mode == "Web of Science":
    st.title("📚 Web of Science citation finder")
    st.markdown("Fetch article metadata, full authors, and citation counts using **Unique WOS IDs**.")

    raw_wos_text = st.text_area("📋 Paste WOS IDs here (one per line):", height=200, placeholder="WOS:001681025100006\nWOS:001596381600014")

    _c1, _c2, _c3 = st.columns([1, 1, 1])
    with _c2:
        _wos_clicked = st.button("🔍 Search Web of Science", type="primary", use_container_width=True)

    if _wos_clicked:
        wos_ids = [line.strip() for line in raw_wos_text.split('\n') if line.strip()]
        if wos_ids and "unique wos id" in wos_ids[0].lower():
            wos_ids.pop(0)  # remove header if pasted

        if not wos_ids:
            st.warning("Please enter valid WOS IDs.")
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

    # Show stored WOS results and optional Google Scholar citations
    if "wos_df" in st.session_state:
        df_show = st.session_state["wos_df"]
        _gs_clicked = False
        if SERPAPI_KEY and SERPAPI_KEY.strip():
            st.markdown("---")
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
            st.dataframe(st.session_state["wos_df"], use_container_width=True)
            excel_data = to_excel(st.session_state["wos_df"])
            st.download_button(
                label="📥 Download results (.xlsx)",
                data=excel_data,
                file_name="wos_bulk_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="wos_download_btn",
            )

elif app_mode == "Scopus":
    st.title("📈 Scopus Citation Metrics Finder")
    st.markdown("Fetch **citation metrics** (total and non-self) for articles using DOIs. Paste DOIs or upload a file.")

    raw_dois = st.text_area("📋 Paste DOIs here (one per line):", height=200, placeholder="10.5194/bg-18-2755-2021\n10.3389/fmars.2021.615929", key="scopus_bulk_dois")
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

    if "scopus_df" in st.session_state:
        st.dataframe(st.session_state["scopus_df"], use_container_width=True)
        excel_data = to_excel(st.session_state["scopus_df"])
        st.download_button(
            label="📥 Download results (.xlsx)",
            data=excel_data,
            file_name="scopus_citation_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="scopus_download_btn",
        )

elif app_mode == "Google Scholar":
    st.title("🎓 Google Scholar Citation Lookup")
    st.markdown("Fetch **citation counts** by DOI using SerpAPI. Paste one DOI per line.")

    if not SERPAPI_AVAILABLE:
        st.warning("⚠️ Install the SerpAPI client: **pip install google-search-results**")
    elif not SERPAPI_KEY or not SERPAPI_KEY.strip():
        st.info("🔑 Enter your **SerpAPI key** in the sidebar to use Google Scholar search.")
    else:
        raw_doi_text = st.text_area("📋 Paste DOIs here (one per line):", height=200, placeholder="10.1038/s41593-021-00969-4\n10.1109/TMI.2025.3605219")

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
                st.dataframe(df_gs)
                excel_data = to_excel(df_gs)
                st.download_button(
                    label="📥 Download results (.xlsx)",
                    data=excel_data,
                    file_name="google_scholar_citations.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="gs_download_btn",
                )
