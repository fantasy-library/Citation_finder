import streamlit as st
import requests
import pandas as pd
import time
import io

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
st.sidebar.title("Navigation")
app_mode = st.sidebar.radio("Select Database API:", ["Web of Science", "Scopus", "Google Scholar"])
st.sidebar.markdown("---")
st.sidebar.header("API configuration")

# Highlight which key(s) to enter for the selected mode
if app_mode == "Web of Science":
    st.sidebar.info("⬇️ Enter your **WOS API key** below to get started.")
elif app_mode == "Scopus":
    st.sidebar.info("⬇️ Enter your **Scopus/Elsevier API key** and **institutional token** for citation metrics by DOI.")
else:
    st.sidebar.info("⬇️ Enter your **SerpAPI key** below to get started.")

WOS_API_KEY = st.sidebar.text_input(
    "WOS API key",
    type="password",
    placeholder="Required for Web of Science" if app_mode == "Web of Science" else "",
)
SCOPUS_API_KEY = st.sidebar.text_input(
    "Scopus API key",
    type="password",
    placeholder="Required for Scopus" if app_mode == "Scopus" else "",
)
if _default_inst_token:
    SCOPUS_INST_TOKEN = _default_inst_token  # hidden: use from secrets, no field shown
else:
    SCOPUS_INST_TOKEN = st.sidebar.text_input(
        "Scopus institutional token",
        type="password",
        placeholder="Required for Scopus" if app_mode == "Scopus" else "",
    )
SERPAPI_KEY = st.sidebar.text_input(
    "SerpAPI key",
    type="password",
    placeholder="Required for Google Scholar" if app_mode == "Google Scholar" else "",
)

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
                continue  # Skip appending, user can retry
            else:
                # Same columns as success so DataFrame always has "DOI" etc.
                results.append({
                    "Unique WOS ID": wos_id, "DOI": "N/A", "WOS search (DO)": "N/A", "Title": "N/A", "Author Full Names": "N/A",
                    "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                    "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                    "Status": f"Failed (Code: {response.status_code}) — document not found"
                })
        except Exception as e:
            results.append({
                "Unique WOS ID": wos_id, "DOI": "N/A", "WOS search (DO)": "N/A", "Title": "N/A", "Author Full Names": "N/A",
                "Query (AU)": "N/A", "Document Type": "N/A", "Source Title": "N/A", "Publish Year": "N/A",
                "Volume": "N/A", "Issue": "N/A", "Citation Count": "N/A",
                "Status": f"Error: {str(e)}"
            })

        progress_bar.progress((i + 1) / total)
        time.sleep(1)  # Rate limit protection

    return results

# ==========================================
# HELPER FUNCTIONS (SCOPUS – Elsevier Citation Metrics by DOI)
# ==========================================
def fetch_elsevier_citations(doi, api_key, inst_token, exclude_self=False):
    """Fetches data from the Elsevier Abstract Citations API."""
    url = f"https://api.elsevier.com/content/abstract/citations?doi={doi}&apiKey={api_key}&insttoken={inst_token}&httpAccept=application/json"
    if exclude_self:
        url += "&citation=exclude-self"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 429:
        time.sleep(2)
        return fetch_elsevier_citations(doi, api_key, inst_token, exclude_self)
    else:
        response.raise_for_status()


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
            "Non-Self Citations": exclude_self_citations,
            "Status": "Success",
        }
    except Exception as e:
        return {
            "DOI": doi,
            "Title": "Error",
            "Year": "N/A",
            "Type": "N/A",
            "Total Citations": "0",
            "Non-Self Citations": "0",
            "Status": (str(e)[:50] + "..."),
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
    if not doi or doi == "N/A" or not api_key or not api_key.strip():
        return {"DOI": doi or "N/A", "Title": "N/A", "Authors": "N/A", "Publication": "N/A", "Snippet": "N/A", "Link": "N/A", "Google Scholar citations": "N/A"}
    if not SERPAPI_AVAILABLE:
        return {"DOI": doi, "Title": "N/A", "Authors": "N/A", "Publication": "N/A", "Snippet": "N/A", "Link": "N/A", "Google Scholar citations": "N/A"}
    try:
        params = {
            "engine": "google_scholar",
            "q": doi.strip(),
            "hl": "en",
            "api_key": api_key.strip(),
        }
        search = SerpApiGoogleSearch(params)
        results = search.get_dict()
        organic = results.get("organic_results") or []
        if not organic:
            return {"DOI": doi, "Title": "N/A", "Authors": "N/A", "Publication": "N/A", "Snippet": "N/A", "Link": "N/A", "Google Scholar citations": "N/A"}
        return _parse_gs_organic(organic[0], doi)
    except Exception:
        return {"DOI": doi, "Title": "N/A", "Authors": "N/A", "Publication": "N/A", "Snippet": "N/A", "Link": "N/A", "Google Scholar citations": "N/A"}


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
# USER INTERFACE
# ==========================================
st.markdown(
    """<style> .stButton > button { padding: 0.5rem 1.5rem; font-size: 1.05rem; font-weight: 600; } </style>""",
    unsafe_allow_html=True,
)
st.sidebar.markdown("---")
st.sidebar.info("You only need to enter the API key(s) for the database you select above. Keys are not saved to disk.")

if app_mode == "Web of Science":
    st.title("Web of Science Document Fetcher")
    st.markdown("Fetch article metadata, full authors, and citation counts using Unique WOS IDs.")

    raw_wos_text = st.text_area("Paste WOS IDs here (One per line):", height=200, placeholder="WOS:001681025100006\nWOS:001596381600014")

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
            _gc1, _gc2, _gc3 = st.columns([1, 1, 1])
            with _gc2:
                _gs_clicked = st.button("📊 Add Google Scholar citations", type="secondary", use_container_width=True)
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
            st.dataframe(st.session_state["wos_df"])
            excel_data = to_excel(st.session_state["wos_df"])
            st.download_button(
                label="📥 Download WOS Excel File",
                data=excel_data,
                file_name="wos_bulk_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="wos_download_btn",
            )

elif app_mode == "Scopus":
    st.title("Citation Metrics Finder")
    st.markdown("Discover citation metrics for research articles using Digital Object Identifiers (DOIs). Powered by Elsevier.")

    tab1, tab2 = st.tabs(["Single Article", "Bulk Processing"])

    with tab1:
        st.subheader("Search a Single DOI")
        col1, col2 = st.columns([3, 1])
        with col1:
            doi_input = st.text_input("Enter article DOI:", placeholder="e.g., 10.5194/bg-18-2755-2021", key="scopus_doi_input")
        with col2:
            st.write("")
            st.write("")
            search_btn = st.button("Search", type="primary", use_container_width=True, key="scopus_single_btn")
        st.caption("Examples: `10.5194/bg-18-2755-2021` | `10.3389/fmars.2021.615929` | `10.1038/s41586-020-2008-3`")

        if search_btn and doi_input:
            if not doi_input.strip().startswith("10."):
                st.error("Please enter a valid DOI (should start with '10.')")
            else:
                with st.spinner("Retrieving citation data from Elsevier API..."):
                    result = process_doi_scopus(doi_input.strip(), SCOPUS_API_KEY, SCOPUS_INST_TOKEN)
                    if result["Status"] == "Success":
                        st.success("Article located successfully!")
                        st.markdown(f"### {result['Title']}")
                        m_col1, m_col2, m_col3 = st.columns(3)
                        m_col1.metric("Publication Type", result["Type"])
                        m_col2.metric("Publication Year", result["Year"])
                        m_col3.metric("DOI", result["DOI"])
                        st.divider()
                        c_col1, c_col2 = st.columns(2)
                        with c_col1:
                            st.metric("Total Citations", result["Total Citations"], help="Includes all citations to this research article")
                        with c_col2:
                            st.metric("Non-Self Citations", result["Non-Self Citations"], help="Citations from other researchers only")
                    else:
                        st.error(f"Failed to fetch data: {result['Status']}")

    with tab2:
        st.subheader("Process Multiple DOIs")
        st.markdown("##### 1. Paste DOIs")
        raw_dois = st.text_area("Enter one DOI per line:", height=150, placeholder="10.5194/bg-18-2755-2021\n10.3389/fmars.2021.615929", key="scopus_bulk_dois")
        st.markdown("##### 2. Or Upload a File (.csv, .xlsx)")
        uploaded_file = st.file_uploader("Upload a spreadsheet containing a 'DOI' column", type=["csv", "xlsx", "xls"], key="scopus_upload")

        if st.button("Process Bulk DOIs", type="primary", key="scopus_bulk_btn"):
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
                status_text.success("Bulk processing complete!")
                df_results = pd.DataFrame(results_list)
                df_results = df_results[["DOI", "Title", "Year", "Total Citations", "Non-Self Citations", "Status"]]
                st.dataframe(df_results, use_container_width=True)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_results.to_excel(writer, index=False, sheet_name="Citation Results")
                excel_data = output.getvalue()
                st.download_button(
                    label="Download Results (.xlsx)",
                    data=excel_data,
                    file_name="citation_metrics_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="scopus_download_btn",
                )

elif app_mode == "Google Scholar":
    st.title("Google Scholar Citation Lookup")
    st.markdown("Fetch citation counts by DOI using SerpAPI (Google Scholar). Enter one DOI per line.")

    if not SERPAPI_AVAILABLE:
        st.warning("Install the SerpAPI client: **pip install google-search-results**")
    elif not SERPAPI_KEY or not SERPAPI_KEY.strip():
        st.info("Enter your **SerpAPI key** in the sidebar to use Google Scholar search.")
    else:
        raw_doi_text = st.text_area("Paste DOIs here (one per line):", height=200, placeholder="10.1038/s41593-021-00969-4\n10.1109/TMI.2025.3605219")

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
                status_gs.success(f"✅ Finished {len(gs_results)} DOIs.")
                df_gs = pd.DataFrame(gs_results)
                st.dataframe(df_gs)
                excel_data = to_excel(df_gs)
                st.download_button(
                    label="📥 Download Google Scholar Excel File",
                    data=excel_data,
                    file_name="google_scholar_citations.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="gs_download_btn",
                )
