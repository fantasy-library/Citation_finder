"""OpenAlex Works API by DOI — metadata, citations, FWCI, SDGs (no Streamlit).

OpenAlex ``fwci`` is a separate field-weighted metric from Elsevier SciVal FWCI.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OPENALEX_WORKS_API = "https://api.openalex.org/works"
REQUEST_TIMEOUT = 20
OPENALEX_LIB_VERSION = "2026.04"

OPENALEX_SDG_SELECT = "id,doi,title,publication_year,sustainable_development_goals"
OPENALEX_WORK_SELECT = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "publication_date",
        "type",
        "type_crossref",
        "cited_by_count",
        "fwci",
        "citation_normalized_percentile",
        "primary_location",
        "best_oa_location",
        "open_access",
        "primary_topic",
        "topics",
        "authorships",
        "authors_count",
        "countries_distinct_count",
        "ids",
        "grants",
        "is_retracted",
        "sustainable_development_goals",
    ]
)

DEFAULT_OPENALEX_PACKS: Dict[str, bool] = {
    "citations_impact": True,
    "bibliographic": True,
    "open_access": True,
    "topics": True,
    "authors": True,
    "ids_grants": True,
    "sdgs": True,
    "retraction": True,
    "openalex_url": True,
}

_SESSION = requests.Session()
_RETRY = Retry(
    total=2,
    backoff_factor=0.8,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
)
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


def normalize_doi(value: str) -> str:
    """Normalize DOI links, doi: prefix, or bare DOI to 10.xxxx/... form."""
    if not isinstance(value, str):
        raise ValueError("DOI must be a string.")
    doi = value.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    doi = doi.strip()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.I):
        raise ValueError("Invalid DOI format (expected e.g. 10.7717/peerj.4375).")
    return doi


def _sdg_number_from_id(raw_id: str) -> Optional[int]:
    if not raw_id:
        return None
    match = re.search(r"(?:/sdgs/|/SDG)(\d+)$", raw_id, flags=re.I)
    if not match:
        match = re.search(r"(?:^|/)(\d+)$", raw_id)
    return int(match.group(1)) if match else None


def format_sdg_label(item: Dict[str, Any]) -> Optional[str]:
    """One SDG line for export: SDG N: Name (score)."""
    raw_id = str(item.get("id") or "")
    sdg_number = _sdg_number_from_id(raw_id)
    display = (item.get("display_name") or "").strip()
    score = item.get("score")
    if sdg_number:
        prefix = f"SDG {sdg_number}"
        if display and display.lower() not in prefix.lower():
            text = f"{prefix}: {display}"
        elif display:
            text = display if display.upper().startswith("SDG") else f"{prefix}: {display}"
        else:
            text = prefix
    elif display:
        text = display
    elif raw_id:
        text = raw_id
    else:
        return None
    if score is not None:
        try:
            text = f"{text} ({float(score):.3f})"
        except (TypeError, ValueError):
            pass
    return text


def sdg_labels_from_work(work: Optional[Dict[str, Any]]) -> List[str]:
    """SDG labels sorted by score descending (OpenAlex already filters score >= 0.4)."""
    if not work:
        return []
    items = work.get("sustainable_development_goals") or []
    if not isinstance(items, list):
        return []
    scored: List[Tuple[float, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = format_sdg_label(item)
        if not label:
            continue
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        scored.append((score, label))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [label for _, label in scored]


def get_openalex_work_by_doi(
    doi: str,
    api_key: str = "",
    *,
    select: Optional[str] = OPENALEX_WORK_SELECT,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetch one OpenAlex work by DOI.
    Returns (work_json, error_message). error_message is set on HTTP/client failures.
    """
    try:
        normalized = normalize_doi(doi)
    except ValueError as exc:
        return None, str(exc)

    url = f"{OPENALEX_WORKS_API}/doi:{quote(normalized, safe='/')}"
    params: Dict[str, str] = {}
    if select:
        params["select"] = select
    key = (api_key or "").strip()
    if key:
        params["api_key"] = key
    try:
        response = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            return None, None
        if response.status_code == 429:
            return None, "OpenAlex rate limit (429); retry later or add a free API key"
        if response.status_code in (401, 403):
            return None, f"OpenAlex API key rejected ({response.status_code})"
        if response.status_code != 200:
            return None, f"OpenAlex HTTP {response.status_code}"
        return response.json(), None
    except requests.RequestException as exc:
        return None, f"OpenAlex request failed: {str(exc)[:100]}"


def format_openalex_sdg_cell(labels: Optional[List[str]]) -> str:
    if not labels:
        return "N/A"
    return "; ".join(labels)


def openalex_sdg_row_columns(sdgs_cell: str, status: str) -> Dict[str, str]:
    return {
        "OpenAlex SDGs": sdgs_cell,
        "Status (OpenAlex SDG)": status,
    }


def _source_display_name(work: Dict[str, Any]) -> str:
    pl = work.get("primary_location")
    if isinstance(pl, dict):
        src = pl.get("source")
        if isinstance(src, dict):
            name = (src.get("display_name") or "").strip()
            if name:
                return name
    bol = work.get("best_oa_location")
    if isinstance(bol, dict):
        src = bol.get("source")
        if isinstance(src, dict):
            name = (src.get("display_name") or "").strip()
            if name:
                return name
    return "N/A"


def format_authorships_summary(work: Dict[str, Any], *, max_names: int = 10) -> Dict[str, str]:
    authorships = work.get("authorships") or []
    if not isinstance(authorships, list):
        authorships = []
    names: List[str] = []
    corresponding: List[str] = []
    institutions: List[str] = []
    seen_inst = set()
    for entry in authorships:
        if not isinstance(entry, dict):
            continue
        author = entry.get("author") or {}
        if isinstance(author, dict):
            nm = (author.get("display_name") or "").strip()
            if nm:
                names.append(nm)
                if entry.get("is_corresponding"):
                    corresponding.append(nm)
        for inst in entry.get("institutions") or []:
            if not isinstance(inst, dict):
                continue
            iname = (inst.get("display_name") or "").strip()
            if iname and iname not in seen_inst:
                seen_inst.add(iname)
                institutions.append(iname)
    total = work.get("authors_count")
    if total is None:
        total = len(names)
    if len(names) > max_names:
        author_str = "; ".join(names[:max_names]) + f" … (+{len(names) - max_names} more)"
    elif names:
        author_str = "; ".join(names)
    else:
        author_str = "N/A"
    return {
        "Authors": author_str,
        "Author count": str(total) if total is not None else "N/A",
        "Corresponding authors": "; ".join(corresponding) if corresponding else "N/A",
        "Affiliations": "; ".join(institutions[:15]) if institutions else "N/A",
        "Countries (distinct)": str(work.get("countries_distinct_count", "N/A"))
        if work.get("countries_distinct_count") is not None
        else "N/A",
    }


def format_topics_summary(work: Dict[str, Any]) -> Dict[str, str]:
    primary = work.get("primary_topic")
    primary_name = "N/A"
    if isinstance(primary, dict):
        primary_name = (primary.get("display_name") or "N/A").strip() or "N/A"
    topics = work.get("topics") or []
    all_names: List[str] = []
    if isinstance(topics, list):
        for t in topics:
            if isinstance(t, dict) and t.get("display_name"):
                all_names.append(str(t["display_name"]).strip())
    return {
        "Primary topic": primary_name,
        "All topics": "; ".join(all_names) if all_names else "N/A",
    }


def format_grants_summary(work: Dict[str, Any]) -> str:
    grants = work.get("grants") or []
    if not isinstance(grants, list) or not grants:
        return "N/A"
    parts: List[str] = []
    for g in grants:
        if not isinstance(g, dict):
            continue
        funder = (g.get("funder_display_name") or "").strip()
        award = (g.get("award_id") or "").strip()
        if funder and award:
            parts.append(f"{funder} ({award})")
        elif funder:
            parts.append(funder)
        elif award:
            parts.append(award)
    return "; ".join(parts) if parts else "N/A"


def _format_ids(work: Dict[str, Any]) -> Dict[str, str]:
    ids = work.get("ids") or {}
    if not isinstance(ids, dict):
        ids = {}
    pmid = ids.get("pmid") or "N/A"
    pmcid = ids.get("pmcid") or "N/A"
    oa_id = ids.get("openalex") or work.get("id") or "N/A"
    return {
        "PMID": str(pmid) if pmid else "N/A",
        "PMCID": str(pmcid) if pmcid else "N/A",
        "OpenAlex ID": str(oa_id) if oa_id else "N/A",
    }


def _format_citation_impact(work: Dict[str, Any]) -> Dict[str, str]:
    cb = work.get("cited_by_count")
    fwci = work.get("fwci")
    cnp = work.get("citation_normalized_percentile") or {}
    if not isinstance(cnp, dict):
        cnp = {}
    pct_val = cnp.get("value")
    return {
        "OpenAlex citations": str(cb) if cb is not None else "N/A",
        "OpenAlex FWCI": f"{float(fwci):.3f}" if fwci is not None else "N/A",
        "Citation percentile": f"{float(pct_val):.6f}" if pct_val is not None else "N/A",
        "Top 1% cited": "Yes" if cnp.get("is_in_top_1_percent") else ("No" if pct_val is not None else "N/A"),
        "Top 10% cited": "Yes" if cnp.get("is_in_top_10_percent") else ("No" if pct_val is not None else "N/A"),
    }


def _format_open_access(work: Dict[str, Any]) -> Dict[str, str]:
    oa = work.get("open_access") or {}
    if not isinstance(oa, dict):
        oa = {}
    is_oa = oa.get("is_oa")
    return {
        "OA status": str(oa.get("oa_status") or "N/A"),
        "Is open access": "Yes" if is_oa is True else ("No" if is_oa is False else "N/A"),
        "OA URL": str(oa.get("oa_url") or "N/A"),
    }


def parse_work_export_row(
    work: Optional[Dict[str, Any]],
    normalized_doi: str,
    *,
    include: Optional[Mapping[str, bool]] = None,
    lookup_status: str = "Success",
) -> Dict[str, str]:
    """Build export columns from an OpenAlex Work object."""
    packs = dict(DEFAULT_OPENALEX_PACKS)
    if include:
        packs.update({k: bool(v) for k, v in include.items()})

    if work is None:
        row = {
            "DOI": normalized_doi,
            "Title": "N/A",
            "Year": "N/A",
            "Status": lookup_status or "Not found in OpenAlex",
        }
        order = openalex_export_column_order(packs)
        return {k: row.get(k, "N/A") for k in order}

    title = (work.get("title") or work.get("display_name") or "N/A") or "N/A"
    pub_year = work.get("publication_year")
    year = str(pub_year) if pub_year is not None else "N/A"
    row = {
        "DOI": normalized_doi,
        "Title": title,
        "Year": year,
        "Status": lookup_status,
    }

    if packs.get("bibliographic"):
        row["Publication date"] = str(work.get("publication_date") or "N/A")
        row["Type"] = str(work.get("type") or "N/A")
        row["Type (Crossref)"] = str(work.get("type_crossref") or "N/A")
        row["Source title"] = _source_display_name(work)

    if packs.get("citations_impact"):
        row.update(_format_citation_impact(work))
    if packs.get("open_access"):
        row.update(_format_open_access(work))
    if packs.get("topics"):
        row.update(format_topics_summary(work))
    if packs.get("authors"):
        row.update(format_authorships_summary(work))
    if packs.get("ids_grants"):
        row.update(_format_ids(work))
        row["Grants"] = format_grants_summary(work)
    if packs.get("openalex_url"):
        row["OpenAlex URL"] = str(work.get("id") or "N/A")
    if packs.get("retraction"):
        retr = work.get("is_retracted")
        row["Retracted"] = "Yes" if retr is True else ("No" if retr is False else "N/A")
    if packs.get("sdgs"):
        labels = sdg_labels_from_work(work)
        sdg_cell = format_openalex_sdg_cell(labels)
        sdg_status = (
            "Success"
            if labels
            else "No OpenAlex SDG tags (unclassified or below 0.4 threshold)"
        )
        row.update(openalex_sdg_row_columns(sdg_cell, sdg_status))

    order = openalex_export_column_order(packs)
    return {k: row.get(k, "N/A") for k in order}


def openalex_export_column_order(include: Mapping[str, bool]) -> List[str]:
    """Stable export column order for enabled packs."""
    packs = dict(DEFAULT_OPENALEX_PACKS)
    packs.update({k: bool(v) for k, v in include.items()})
    cols = ["DOI", "Title", "Year", "Status"]
    if packs.get("bibliographic"):
        cols.extend(["Publication date", "Type", "Type (Crossref)", "Source title"])
    if packs.get("openalex_url"):
        cols.append("OpenAlex URL")
    if packs.get("citations_impact"):
        cols.extend(
            [
                "OpenAlex citations",
                "OpenAlex FWCI",
                "Citation percentile",
                "Top 1% cited",
                "Top 10% cited",
            ]
        )
    if packs.get("open_access"):
        cols.extend(["OA status", "Is open access", "OA URL"])
    if packs.get("topics"):
        cols.extend(["Primary topic", "All topics"])
    if packs.get("authors"):
        cols.extend(
            [
                "Authors",
                "Author count",
                "Corresponding authors",
                "Affiliations",
                "Countries (distinct)",
            ]
        )
    if packs.get("ids_grants"):
        cols.extend(["PMID", "PMCID", "OpenAlex ID", "Grants"])
    if packs.get("retraction"):
        cols.append("Retracted")
    if packs.get("sdgs"):
        cols.extend(["OpenAlex SDGs", "Status (OpenAlex SDG)"])
    return cols


def build_openalex_work_row(
    doi: str,
    api_key: str = "",
    include: Optional[Mapping[str, bool]] = None,
) -> Dict[str, str]:
    """Fetch work by DOI and return export row for selected field packs."""
    input_doi = (doi or "").strip()
    packs = dict(DEFAULT_OPENALEX_PACKS)
    if include:
        packs.update({k: bool(v) for k, v in include.items()})
    try:
        normalized = normalize_doi(input_doi)
    except ValueError as exc:
        return parse_work_export_row(
            None,
            input_doi,
            include=packs,
            lookup_status=str(exc)[:80],
        )
    work, err = get_openalex_work_by_doi(normalized, api_key, select=OPENALEX_WORK_SELECT)
    if err:
        return parse_work_export_row(None, normalized, include=packs, lookup_status=err)
    if work is None:
        return parse_work_export_row(
            None,
            normalized,
            include=packs,
            lookup_status="Not found in OpenAlex",
        )
    return parse_work_export_row(work, normalized, include=packs, lookup_status="Success")


def build_openalex_sdg_result_row(doi: str, api_key: str = "") -> Dict[str, str]:
    """Backward-compatible SDG-only row (+ DOI, Title, Year, Status)."""
    return build_openalex_work_row(
        doi,
        api_key,
        include={
            "citations_impact": False,
            "bibliographic": False,
            "open_access": False,
            "topics": False,
            "authors": False,
            "ids_grants": False,
            "sdgs": True,
            "retraction": False,
            "openalex_url": False,
        },
    )


def fetch_openalex_sdgs_by_doi(doi: str, api_key: str = "") -> Tuple[str, str]:
    """Lookup stored OpenAlex SDG tags for a DOI. Returns (sdgs_cell, status_message)."""
    work, err = get_openalex_work_by_doi(doi, api_key, select=OPENALEX_SDG_SELECT)
    if err:
        return "N/A", err
    if work is None:
        return "N/A", "Not found in OpenAlex"
    labels = sdg_labels_from_work(work)
    if not labels:
        return (
            "N/A",
            "No OpenAlex SDG tags (unclassified or below 0.4 threshold)",
        )
    return format_openalex_sdg_cell(labels), "Success"