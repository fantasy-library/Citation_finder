import streamlit as st
import requests
import pandas as pd
import time
import io
import re

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Academic Database Search", page_icon="📚", layout="wide")

# Securely load API keys from Streamlit Secrets (fall back to empty strings if not found)
try:
    WOS_API_KEY = st.secrets["WOS_API_KEY"]
    SCOPUS_API_KEY = st.secrets["SCOPUS_API_KEY"]
    SCOPUS_INST_TOKEN = st.secrets["SCOPUS_INST_TOKEN"]
except KeyError:
    st.error("⚠️ Secrets not found! Please configure your .streamlit/secrets.toml file.")
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

                # Extract Authors & formatted query
                authors_data = data.get('names', {}).get('authors', [])
                wos_standard = [a.get('wosStandard', '') for a in authors_data if a.get('wosStandard')]
                query = f"not au=({' OR '.join(wos_standard)})" if wos_standard else "N/A"
                full_names = "; ".join([a.get('displayName', a.get('wosStandard', '')) for a in authors_data if a])

                # Extract DOI
                doi = next((ident.get('value', 'N/A') for ident in data.get('identifiers', [])
                            if ident.get('identifierType') == 'doi' or ident.get('type') == 'doi'), "N/A")

                source = data.get('source', {})
                citations = data.get('citations', [])

                results.append({
                    "Unique WOS ID": wos_id,
                    "DOI": doi,
                    "Title": data.get('title', 'N/A'),
                    "Author Full Names": full_names or "N/A",
                    "Query": query,
                    "Document Type": "; ".join(data.get('types', [])) or "N/A",
                    "Source Title": source.get('sourceTitle', 'N/A'),
                    "Publish Year": source.get('publishYear', 'N/A'),
                    "Volume": source.get('volume', 'N/A'),
                    "Issue": source.get('issue', 'N/A'),
                    "Citation Count": citations[0].get('count', 'N/A') if citations else 'N/A',
                    "Status": "Success"
                })
            elif response.status_code == 429:
                status_text.text(f"Rate limit hit at {wos_id}. Sleeping 3s...")
                time.sleep(3)
                continue  # Skip appending, user can retry
            else:
                results.append({"Unique WOS ID": wos_id, "Status": f"Failed (Code: {response.status_code})"})
        except Exception as e:
            results.append({"Unique WOS ID": wos_id, "Status": f"Error: {str(e)}"})

        progress_bar.progress((i + 1) / total)
        time.sleep(1)  # Rate limit protection

    return results

# ==========================================
# HELPER FUNCTIONS (SCOPUS)
# ==========================================
def clean_issn(issn_str):
    # Strip whitespace and hyphens, uppercase
    cleaned = re.sub(r'[-\s]', '', issn_str.upper())
    if len(cleaned) == 8:
        return cleaned
    return None

def fetch_scopus_data(issns, progress_bar, status_text):
    results = []
    total = len(issns)

    base_url = "https://api.elsevier.com/content/serial/title/issn/"

    for i, issn in enumerate(issns):
        status_text.text(f"Fetching ISSN {i+1} of {total}: {issn}...")
        url = f"{base_url}{issn}?apiKey={SCOPUS_API_KEY}&insttoken={SCOPUS_INST_TOKEN}&httpAccept=application/json"

        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                try:
                    entry = data['serial-metadata-response']['entry'][0]

                    # Safe extraction of nested data
                    subject_areas = [s.get('$', '') for s in entry.get('subject-area', [])]
                    snip = entry.get('SNIPList', {}).get('SNIP', [{}])[0].get('$', 'N/A')
                    sjr = entry.get('SJRList', {}).get('SJR', [{}])[0].get('$', 'N/A')
                    c_score = entry.get('citeScoreYearInfoList', {}).get('citeScoreCurrentMetric', 'N/A')

                    results.append({
                        "Journal Title": entry.get('dc:title', 'N/A'),
                        "Publisher": entry.get('dc:publisher', 'N/A'),
                        "Print ISSN": entry.get('prism:issn', 'N/A'),
                        "eISSN": entry.get('prism:eIssn', 'N/A'),
                        "CiteScore": c_score,
                        "SNIP": snip,
                        "SJR": sjr,
                        "Subject Areas": "; ".join(subject_areas),
                        "Aggregation Type": entry.get('prism:aggregationType', 'N/A'),
                        "Queried ISSN": issn,
                        "Status": "Success"
                    })
                except (KeyError, IndexError):
                    results.append({"Queried ISSN": issn, "Status": "No journal data found"})
            elif response.status_code == 429:
                status_text.text(f"Rate limit hit at {issn}. Sleeping 3s...")
                time.sleep(3)
            else:
                results.append({"Queried ISSN": issn, "Status": f"Failed (Code: {response.status_code})"})

        except Exception as e:
            results.append({"Queried ISSN": issn, "Status": f"Error: {str(e)}"})

        progress_bar.progress((i + 1) / total)
        time.sleep(0.6)  # Approx 100 requests / minute max

    return results

# ==========================================
# EXCEL GENERATOR (In-Memory)
# ==========================================
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    return output.getvalue()


# ==========================================
# USER INTERFACE
# ==========================================
st.sidebar.title("Navigation")
app_mode = st.sidebar.radio("Select Database API:", ["Web of Science (Documents)", "Scopus (Journals)"])

st.sidebar.markdown("---")
st.sidebar.info("The APIs run securely on the server backend. Keys are not exposed to the browser.")

if app_mode == "Web of Science (Documents)":
    st.title("Web of Science Document Fetcher")
    st.markdown("Fetch article metadata, full authors, and citation counts using Unique WOS IDs.")

    raw_wos_text = st.text_area("Paste WOS IDs here (One per line):", height=200, placeholder="WOS:001681025100006\nWOS:001596381600014")

    if st.button("Search Web of Science", type="primary"):
        wos_ids = [line.strip() for line in raw_wos_text.split('\n') if line.strip()]
        if wos_ids and "unique wos id" in wos_ids[0].lower():
            wos_ids.pop(0)  # remove header if pasted

        if not wos_ids:
            st.warning("Please enter valid WOS IDs.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()

            wos_data = fetch_wos_data(wos_ids, progress_bar, status_text)

            status_text.success(f"✅ Finished processing {len(wos_data)} records!")
            df_wos = pd.DataFrame(wos_data)

            st.dataframe(df_wos)  # Preview

            excel_data = to_excel(df_wos)
            st.download_button(
                label="📥 Download WOS Excel File",
                data=excel_data,
                file_name="wos_bulk_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

elif app_mode == "Scopus (Journals)":
    st.title("Scopus Institutional Journal Lookup")
    st.markdown("Fetch journal metrics (CiteScore, SNIP, SJR) using ISSNs.")

    raw_issn_text = st.text_area("Enter ISSN Numbers (One per line):", height=200, placeholder="2161-797X\n1755-0645")

    if st.button("Search Scopus Journals", type="primary"):
        raw_lines = [line.strip() for line in raw_issn_text.split('\n') if line.strip()]
        clean_issns = [clean_issn(issn) for issn in raw_lines if clean_issn(issn)]

        if not clean_issns:
            st.warning("Please enter valid ISSNs.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()

            scopus_data = fetch_scopus_data(clean_issns, progress_bar, status_text)

            status_text.success(f"✅ Finished processing {len(scopus_data)} records!")
            df_scopus = pd.DataFrame(scopus_data)

            st.dataframe(df_scopus)  # Preview

            excel_data = to_excel(df_scopus)
            st.download_button(
                label="📥 Download Scopus Excel File",
                data=excel_data,
                file_name="scopus_journal_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
