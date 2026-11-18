"""Clarivate WoS Starter + InCites Document Level Metrics (SDG schema). No Streamlit dependency."""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

import requests

WOS_STARTER_BASE = "https://api.clarivate.com/apis/wos-starter/v1"
INCITES_DLM_JSON = "https://api.clarivate.com/api/incites/DocumentLevelMetricsByUT/json"
INCITES_BATCH_SIZE = 100
INCITES_MIN_INTERVAL = 0.55

WOS_INCITES_LIB_VERSION = "2026.03"

# Goal number -> short UN title (display when API returns numeric CODE only)
_SDG_NAMES = {
    1: "No Poverty",
    2: "Zero Hunger",
    3: "Good Health and Well-Being",
    4: "Quality Education",
    5: "Gender Equality",
    6: "Clean Water and Sanitation",
    7: "Affordable and Clean Energy",
    8: "Decent Work and Economic Growth",
    9: "Industry, Innovation and Infrastructure",
    10: "Reduced Inequalities",
    11: "Sustainable Cities and Communities",
    12: "Responsible Consumption and Production",
    13: "Climate Action",
    14: "Life Below Water",
    15: "Life on Land",
    16: "Peace, Justice and Strong Institutions",
    17: "Partnerships for the Goals",
}


def normalize_wos_ut(ut: Optional[str]) -> Optional[str]:
    """Strip WOS: prefix and whitespace for InCites UT parameter."""
    if not ut or not isinstance(ut, str):
        return None
    text = ut.strip()
    if not text or text.upper() == "N/A":
        return None
    if text.upper().startswith("WOS:"):
        text = text[4:].strip()
    return text or None


def resolve_incites_api_key(wos_api_key: str = "", incites_api_key: str = "") -> str:
    """Prefer dedicated InCites key; fall back to WoS key (institutional setups vary)."""
    incites = (incites_api_key or "").strip()
    if incites:
        return incites
    return (wos_api_key or "").strip()


def fetch_wos_starter_document_by_doi(
    doi: str,
    wos_api_key: str,
    *,
    timeout: float = 30,
) -> Tuple[Optional[Dict[str, Any]], int, Optional[str]]:
    """
    Resolve DOI to first WoS Starter hit.
    Returns (document_dict, http_status, error_message).
    """
    doi = (doi or "").strip()
    key = (wos_api_key or "").strip()
    if not doi or not doi.lower().startswith("10."):
        return None, 0, "Invalid DOI"
    if not key:
        return None, 0, "Missing WoS API key"
    url = f"{WOS_STARTER_BASE}/documents"
    params = {"db": "WOS", "q": f"DO={doi}", "limit": 10, "page": 1}
    headers = {"X-ApiKey": key}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
    except requests.RequestException as exc:
        return None, 0, str(exc)[:120]
    if response.status_code != 200:
        return None, response.status_code, (response.text or "")[:200]
    try:
        payload = response.json()
    except ValueError:
        return None, response.status_code, "Invalid JSON from WoS Starter"
    hits = payload.get("hits") or []
    if not hits:
        return None, 200, "No WoS document for this DOI"
    doc = hits[0] if isinstance(hits[0], dict) else None
    return doc, 200, None


def _sdg_label_from_percentile_entry(entry: Any) -> Optional[str]:
    if not isinstance(entry, dict):
        return None
    subject = entry.get("SUBJECT") or entry.get("subject") or entry.get("NAME") or entry.get("name")
    code = entry.get("CODE") or entry.get("code") or entry.get("SDG_CODE") or entry.get("sdg_code")
    if subject and isinstance(subject, str) and subject.strip():
        subj = subject.strip()
        if re.match(r"^\d+\s", subj):
            return f"SDG {subj}" if not subj.upper().startswith("SDG") else subj
        if code is not None and str(code).strip().isdigit():
            n = int(str(code).strip())
            name = _SDG_NAMES.get(n)
            if name:
                return f"SDG {n}: {name}"
        if subj.upper().startswith("SDG"):
            return subj
        if code is not None and str(code).strip().isdigit():
            n = int(str(code).strip())
            name = _SDG_NAMES.get(n, subj)
            return f"SDG {n}: {name}"
        return f"SDG: {subj}"
    if code is not None:
        text = str(code).strip()
        if text.isdigit():
            n = int(text)
            name = _SDG_NAMES.get(n)
            return f"SDG {n}: {name}" if name else f"SDG {n}"
    return None


def _sdg_labels_from_field_block(block: Any) -> List[str]:
    labels: List[str] = []
    if block is None:
        return labels
    if isinstance(block, list):
        for item in block:
            label = _sdg_label_from_percentile_entry(item)
            if not label and isinstance(item, str) and item.strip():
                label = item.strip() if item.strip().upper().startswith("SDG") else None
            if label:
                labels.append(label)
    elif isinstance(block, dict):
        label = _sdg_label_from_percentile_entry(block)
        if label:
            labels.append(label)
        else:
            nested = block.get("PERCENTILE") or block.get("percentile")
            labels.extend(_sdg_labels_from_field_block(nested))
    elif isinstance(block, str) and block.strip():
        for part in re.split(r"[;|]", block):
            p = part.strip()
            if p:
                labels.append(p if p.upper().startswith("SDG") else p)
    return labels


def parse_incites_sdg_groups(record_groups: Sequence[Any]) -> Dict[str, List[str]]:
    """
    Parse InCites DocumentLevelMetricsByUT JSON (`api[0].rval` list).

    Each group is a dict whose values are often single-element lists, e.g.
    {"ACCESSION_NUMBER": ["..."], "PERCENTILE": [{SUBJECT, CODE}, ...]}.
    """
    by_ut: Dict[str, List[str]] = {}
    if not record_groups:
        return by_ut
    for grp in record_groups:
        if not isinstance(grp, dict):
            continue
        ut_raw = grp.get("ACCESSION_NUMBER") or grp.get("accession_number")
        if isinstance(ut_raw, list) and ut_raw:
            ut_raw = ut_raw[0]
        ut = normalize_wos_ut(str(ut_raw) if ut_raw is not None else "")
        if not ut:
            continue
        labels: List[str] = []
        for key in ("PERCENTILE", "percentile", "SDG", "sdg", "SUSTAINABLE_DEVELOPMENT_GOALS"):
            if key in grp:
                block = grp[key]
                if isinstance(block, list) and block and not isinstance(block[0], (dict, str)):
                    block = block[0]
                labels.extend(_sdg_labels_from_field_block(block))
        # Flatten one-element list wrappers on nested field dicts (InCites v2 style)
        if not labels:
            for field_val in grp.values():
                if isinstance(field_val, list) and field_val and isinstance(field_val[0], dict):
                    if any(k in field_val[0] for k in ("SUBJECT", "CODE", "subject", "code")):
                        labels.extend(_sdg_labels_from_field_block(field_val))
        # Dedupe stable order
        seen = set()
        unique: List[str] = []
        for lab in labels:
            if lab not in seen:
                seen.add(lab)
                unique.append(lab)
        by_ut[ut] = unique
    return by_ut


def parse_incites_sdg_payload(payload: Any) -> Dict[str, List[str]]:
    """Extract UT -> SDG labels from full InCites JSON body."""
    if not isinstance(payload, dict):
        return {}
    api = payload.get("api")
    if not isinstance(api, list) or not api:
        return {}
    first = api[0] if isinstance(api[0], dict) else {}
    rval = first.get("rval") or first.get("RVAL") or []
    if not isinstance(rval, list):
        return {}
    return parse_incites_sdg_groups(rval)


def fetch_incites_sdgs_for_uts(
    uts: Sequence[str],
    api_key: str,
    *,
    include_esci: bool = True,
    schema: str = "sdg",
    timeout: float = 45,
    sleep_between_batches: float = INCITES_MIN_INTERVAL,
) -> Tuple[Dict[str, List[str]], Dict[str, Any]]:
    """
    Batch-fetch SDGs for WoS UTs. Returns (ut -> labels, meta with http_status, error).
    """
    key = (api_key or "").strip()
    meta: Dict[str, Any] = {"http_status": None, "error": None, "batches": 0}
    out: Dict[str, List[str]] = {}
    normalized: List[str] = []
    for ut in uts:
        n = normalize_wos_ut(ut)
        if n and n not in normalized:
            normalized.append(n)
    if not normalized:
        meta["error"] = "No valid WoS UTs"
        return out, meta
    if not key:
        meta["error"] = "Missing InCites/WoS API key"
        return out, meta

    headers = {"X-ApiKey": key}
    for i in range(0, len(normalized), INCITES_BATCH_SIZE):
        batch = normalized[i : i + INCITES_BATCH_SIZE]
        params = {
            "UT": ",".join(batch),
            "schema": schema,
            "ver": "2",
        }
        if include_esci:
            params["esci"] = "y"
        url = f"{INCITES_DLM_JSON}?{urlencode(params)}"
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            meta["error"] = str(exc)[:120]
            meta["http_status"] = 0
            return out, meta
        meta["http_status"] = response.status_code
        meta["batches"] = meta.get("batches", 0) + 1
        if response.status_code == 429:
            time.sleep(3)
            meta["error"] = "InCites rate limit (429)"
            return out, meta
        if response.status_code in (401, 403):
            meta["error"] = f"InCites auth denied ({response.status_code})"
            return out, meta
        if response.status_code != 200:
            meta["error"] = (response.text or f"HTTP {response.status_code}")[:200]
            return out, meta
        try:
            payload = response.json()
        except ValueError:
            meta["error"] = "Invalid JSON from InCites"
            return out, meta
        parsed = parse_incites_sdg_payload(payload)
        for ut, labels in parsed.items():
            out[ut] = labels
        if i + INCITES_BATCH_SIZE < len(normalized) and sleep_between_batches > 0:
            time.sleep(sleep_between_batches)
    return out, meta


def format_incites_sdg_cell(labels: Optional[List[str]]) -> str:
    if not labels:
        return "N/A"
    return "; ".join(labels)


def fetch_wos_incites_sdgs_by_doi(
    doi: str,
    wos_api_key: str,
    incites_api_key: str = "",
    *,
    wos_document: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, Optional[str]]:
    """
    DOI -> WoS UT -> InCites SDGs.
    Returns (sdgs_cell, status_message, wos_ut).
    """
    doi = (doi or "").strip()
    doc = wos_document
    ut: Optional[str] = None
    if doc and isinstance(doc, dict):
        ut = normalize_wos_ut(doc.get("uid"))
    elif doc is None:
        doc, wos_status, wos_err = fetch_wos_starter_document_by_doi(doi, wos_api_key)
        if not doc:
            if wos_status == 401:
                return "N/A", "WoS API key rejected", None
            if wos_status == 403:
                return "N/A", "WoS API access denied", None
            return "N/A", wos_err or "No WoS record", None
        ut = normalize_wos_ut(doc.get("uid"))
    if not ut:
        return "N/A", "No WoS UT for InCites lookup", None

    incites_key = resolve_incites_api_key(wos_api_key, incites_api_key)
    sdgs_map, meta = fetch_incites_sdgs_for_uts([ut], incites_key)
    labels = sdgs_map.get(ut, [])
    if meta.get("error"):
        err = meta["error"]
        if "auth denied" in err.lower() or meta.get("http_status") in (401, 403):
            return "N/A", err, ut
        return "N/A", err, ut
    if not labels:
        return "N/A", "No InCites SDG mapping for this record", ut
    return format_incites_sdg_cell(labels), "Success", ut


def incites_sdg_row_columns(sdgs_cell: str, status: str) -> Dict[str, str]:
    return {
        "InCites SDGs": sdgs_cell,
        "Status (InCites SDG)": status,
    }