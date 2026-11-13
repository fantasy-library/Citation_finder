"""SciVal FWCI helpers (shared by app and CLI bulk check)."""
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


def _elsevier_headers(api_key, inst_token):
    return {
        "Accept": "application/json",
        "X-ELS-APIKey": api_key,
        "X-ELS-Insttoken": inst_token,
    }


def scopus_id_year_from_citations_payload(payload):
    """Scopus publication ID + year from Abstract Citations API (same call as citation counts)."""
    if not isinstance(payload, dict):
        return None, None
    acr = payload.get("abstract-citations-response") or {}
    pub_id = None
    pub_year = None

    legend = acr.get("identifier-legend") or {}
    identifiers = legend.get("identifier") or []
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    for item in identifiers:
        if not isinstance(item, dict):
            continue
        for key in ("scopus_id", "scopus-id", "dc:identifier", "eid"):
            text = str(item.get(key) or "").strip()
            match = re.search(r"(\d{8,})", text)
            if match:
                pub_id = match.group(1)
                break
        if pub_id:
            break

    matrix = (acr.get("citeInfoMatrix") or {}).get("citeInfoMatrixXML", {}).get("citationMatrix", {}).get(
        "citeInfo", []
    )
    if isinstance(matrix, dict):
        matrix = [matrix]
    for cite in matrix:
        if not isinstance(cite, dict):
            continue
        if not pub_id:
            for key in ("scopus_id", "scopus-id", "dc:identifier"):
                text = str(cite.get(key) or "").strip()
                match = re.search(r"(\d{8,})", text)
                if match:
                    pub_id = match.group(1)
                    break
        sy = cite.get("sort-year")
        if pub_year is None and sy is not None:
            try:
                pub_year = int(sy)
            except (TypeError, ValueError):
                match = re.search(r"(\d{4})", str(sy))
                if match:
                    pub_year = int(match.group(1))
        if pub_id and pub_year is not None:
            break
    return pub_id, pub_year


def _scopus_id_from_citations_api(doi, api_key, inst_token):
    """Scopus ID via citations endpoint (reliable when citation counts succeed)."""
    encoded = quote(str(doi or "").strip(), safe="")
    if not encoded:
        return None, None
    url = (
        f"https://api.elsevier.com/content/abstract/citations?doi={encoded}"
        f"&apiKey={api_key}&insttoken={inst_token}&httpAccept=application/json&view=STANDARD"
    )
    try:
        response = requests.get(url, headers=_elsevier_headers(api_key, inst_token), timeout=30)
    except requests.RequestException:
        return None, None
    if response.status_code != 200:
        return None, None
    try:
        payload = response.json()
    except ValueError:
        return None, None
    return scopus_id_year_from_citations_payload(payload)


def format_fwci_status(scival_bundle, include_fwci=True):
    """Human-readable FWCI / SciVal status for export columns."""
    if not include_fwci:
        return ""
    fwci = (scival_bundle or {}).get("fwci", "N/A")
    note = ((scival_bundle or {}).get("note") or "").strip()
    if fwci != "N/A":
        return note or "Success"
    return note or "FWCI not available"


def _parse_scopus_publication_id(payload):
    """Numeric Scopus publication ID from Abstract Retrieval JSON."""
    if not isinstance(payload, dict):
        return None
    core = (payload.get("abstracts-retrieval-response") or {}).get("coredata") or payload.get("coredata") or {}
    identifier = str(core.get("dc:identifier") or "").strip()
    if identifier:
        match = re.search(r"(?:SCOPUS_ID:\s*)?(\d{8,})", identifier, re.I)
        if match:
            return match.group(1)
    for key in ("eid", "prism:eid"):
        text = str(core.get(key) or "").strip()
        if not text:
            continue
        match = re.search(r"(\d{8,})", text)
        if match:
            return match.group(1)
    return None


def _parse_scopus_publication_year(payload):
    """Publication year from Abstract Retrieval coredata (for FWCI valueByYear)."""
    if not isinstance(payload, dict):
        return None
    core = (payload.get("abstracts-retrieval-response") or {}).get("coredata") or payload.get("coredata") or {}
    for key in ("prism:coverDate", "coverDate", "prism:coverDisplayDate"):
        match = re.search(r"(\d{4})", str(core.get(key) or ""))
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    return None


def _scopus_id_from_search(doi, api_key, inst_token):
    """Resolve Scopus publication ID via Scopus Search API (DOI query)."""
    doi_text = str(doi or "").strip()
    if not doi_text:
        return None
    params = {
        "query": f"DOI({doi_text})",
        "field": "eid,dc:identifier",
        "count": 1,
        "httpAccept": "application/json",
        "apiKey": api_key,
        "insttoken": inst_token,
    }
    try:
        response = requests.get(
            "https://api.elsevier.com/content/search/scopus",
            params=params,
            headers=_elsevier_headers(api_key, inst_token),
            timeout=30,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    entries = (payload.get("search-results") or {}).get("entry") or []
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key in ("dc:identifier", "eid"):
            text = str(entry.get(key) or "").strip()
            match = re.search(r"(\d{8,})", text)
            if match:
                return match.group(1)
    return None


def fetch_scopus_publication_id(doi, api_key, inst_token, _retry_count=0, view="META"):
    """Map a DOI to a Scopus publication ID (Abstract Retrieval)."""
    encoded = quote(str(doi or "").strip(), safe="")
    if not encoded:
        return None, None, None, "Missing DOI"
    url = (
        f"https://api.elsevier.com/content/abstract/doi/{encoded}"
        f"?apiKey={api_key}&insttoken={inst_token}&httpAccept=application/json"
    )
    if view:
        url += f"&view={quote(str(view), safe='')}"
    try:
        response = requests.get(url, headers=_elsevier_headers(api_key, inst_token), timeout=30)
    except requests.RequestException as exc:
        return None, None, None, str(exc)[:120]
    if response.status_code == 429 and _retry_count < 2:
        time.sleep(2)
        return fetch_scopus_publication_id(doi, api_key, inst_token, _retry_count + 1, view=view)
    if response.status_code != 200:
        return None, None, response.status_code, response.text
    try:
        payload = response.json()
    except ValueError:
        return None, None, response.status_code, response.text
    pub_id = _parse_scopus_publication_id(payload)
    pub_year = _parse_scopus_publication_year(payload)
    return pub_id, pub_year, response.status_code, None


def _coerce_fwci_number(raw):
    """Extract a single FWCI float from SciVal metric value shapes."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    if isinstance(raw, dict):
        if not raw:
            return None
        direct = raw.get("value")
        if direct is not None:
            parsed = _coerce_fwci_number(direct)
            if parsed is not None:
                return parsed
        vby = raw.get("valueByYear") or raw.get("valuesByYear")
        if isinstance(vby, dict) and vby:
            ordered = sorted(vby.items(), key=lambda item: str(item[0]))
            for _, year_val in reversed(ordered):
                parsed = _coerce_fwci_number(year_val)
                if parsed is not None:
                    return parsed
        for key in ("total", "overall", "default"):
            if key in raw:
                parsed = _coerce_fwci_number(raw[key])
                if parsed is not None:
                    return parsed
        return None
    if isinstance(raw, list):
        for item in raw:
            parsed = _coerce_fwci_number(item)
            if parsed is not None:
                return parsed
    return None


def _year_from_metric_key(key):
    match = re.search(r"(\d{4})", str(key))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _fwci_from_value_by_year(raw, publication_year=None):
    """Pick FWCI from SciVal valueByYear; prefer the document's publication year."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return _coerce_fwci_number(raw)
    if publication_year is not None:
        target = int(publication_year)
        for ykey, yval in raw.items():
            parsed = _coerce_fwci_number(yval)
            if parsed is None:
                continue
            year = _year_from_metric_key(ykey)
            if year == target:
                return parsed
        for ykey in (publication_year, str(publication_year)):
            if ykey in raw:
                parsed = _coerce_fwci_number(raw[ykey])
                if parsed is not None:
                    return parsed
        closest = None
        closest_gap = None
        for ykey, yval in raw.items():
            year = _year_from_metric_key(ykey)
            if year is None:
                continue
            parsed = _coerce_fwci_number(yval)
            if parsed is None:
                continue
            gap = abs(year - target)
            if closest_gap is None or gap < closest_gap:
                closest_gap = gap
                closest = parsed
        if closest is not None and closest_gap is not None and closest_gap <= 2:
            return closest
    for ykey in sorted(raw.keys(), key=lambda k: str(k), reverse=True):
        parsed = _coerce_fwci_number(raw[ykey])
        if parsed is not None:
            return parsed
    return None


def _publication_id_from_result_block(block):
    """Scopus publication id from a SciVal result block, if present."""
    if not isinstance(block, dict):
        return None
    publication = block.get("publication")
    if isinstance(publication, dict):
        pub_num = publication.get("id")
        if pub_num is not None:
            text = str(pub_num).strip()
            match = re.search(r"(\d{8,})", text)
            if match:
                return match.group(1)
    for key in ("publicationId", "id", "entityId", "scopusId"):
        text = str(block.get(key) or "").strip()
        if text:
            match = re.search(r"(\d{8,})", text)
            if match:
                return match.group(1)
    link = block.get("link")
    if isinstance(link, list):
        link = link[0] if link else None
    if isinstance(link, dict):
        for field in ("@ref", "@href", "href", "ref"):
            text = str(link.get(field) or "")
            match = re.search(r"(\d{8,})", text)
            if match:
                return match.group(1)
    return None


def _extract_fwci_from_metric(metric, publication_year=None):
    if not isinstance(metric, dict):
        return None
    mtype = (metric.get("metricType") or metric.get("type") or metric.get("@type") or "").strip()
    if mtype == "FieldWeightedCitationImpact":
        parsed = (
            _coerce_fwci_number(metric.get("value"))
            or _fwci_from_value_by_year(metric.get("valueByYear"), publication_year)
        )
        if parsed is not None:
            return parsed
        values = metric.get("values")
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                item_type = (item.get("metricType") or item.get("type") or mtype or "").strip()
                if item_type and item_type != "FieldWeightedCitationImpact":
                    continue
                parsed = (
                    _coerce_fwci_number(item.get("value"))
                    or _fwci_from_value_by_year(item.get("valueByYear"), publication_year)
                )
                if parsed is not None:
                    return parsed
        return _coerce_fwci_number(values)
    nested = metric.get("FieldWeightedCitationImpact")
    if nested is not None:
        if isinstance(nested, dict):
            return _extract_fwci_from_metric(nested, publication_year) or _coerce_fwci_number(nested)
        return _coerce_fwci_number(nested)
    return None


def _fwci_from_metric_list(metrics, publication_year=None):
    if isinstance(metrics, dict):
        metrics = [metrics]
    if not isinstance(metrics, list):
        return None
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        mtype = (metric.get("metricType") or metric.get("type") or metric.get("@type") or "").strip()
        if mtype == "FieldWeightedCitationImpact":
            parsed = _extract_fwci_from_metric(metric, publication_year)
            if parsed is not None:
                return parsed
        for key, val in metric.items():
            if key != "FieldWeightedCitationImpact":
                continue
            parsed = (
                _extract_fwci_from_metric(val, publication_year) if isinstance(val, dict) else _coerce_fwci_number(val)
            )
            if parsed is not None:
                return parsed
    for metric in metrics:
        parsed = _extract_fwci_from_metric(metric, publication_year)
        if parsed is not None:
            return parsed
    return None


def _deep_scan_fwci_payload(obj, publication_year=None, _depth=0):
    if _depth > 14:
        return None
    if isinstance(obj, dict):
        mtype = str(obj.get("metricType") or obj.get("type") or obj.get("@type") or "")
        if "FieldWeightedCitationImpact" in mtype:
            parsed = _extract_fwci_from_metric(obj, publication_year)
            if parsed is not None:
                return parsed
        if "FieldWeightedCitationImpact" in obj:
            branch = obj["FieldWeightedCitationImpact"]
            parsed = (
                _extract_fwci_from_metric(branch, publication_year)
                if isinstance(branch, dict)
                else _coerce_fwci_number(branch)
            )
            if parsed is not None:
                return parsed
        for val in obj.values():
            parsed = _deep_scan_fwci_payload(val, publication_year, _depth + 1)
            if parsed is not None:
                return parsed
    elif isinstance(obj, list):
        for item in obj:
            parsed = _deep_scan_fwci_payload(item, publication_year, _depth + 1)
            if parsed is not None:
                return parsed
    return None


def _fwci_from_result_block(block, publication_year=None):
    if not isinstance(block, dict):
        return None
    parsed = _fwci_from_metric_list(block.get("metrics") or [], publication_year)
    if parsed is not None:
        return parsed
    single = block.get("metric")
    if isinstance(single, dict):
        return _extract_fwci_from_metric(single, publication_year)
    return None


def _parse_fwci_metrics(payload, requested_ids=None, publication_year=None):
    """Publication ID -> FWCI from SciVal publication metrics JSON."""
    found = {}
    if not isinstance(payload, dict):
        return found
    blocks = payload.get("results") or payload.get("result") or []
    if isinstance(blocks, dict):
        blocks = [blocks]
    per_block_values = []
    for block in blocks:
        fwci_val = _fwci_from_result_block(block, publication_year)
        per_block_values.append(fwci_val)
        pub_id = _publication_id_from_result_block(block)
        if pub_id and fwci_val is not None:
            found[str(pub_id)] = fwci_val

    req_ids = [str(i).strip() for i in (requested_ids or []) if str(i).strip()]
    if req_ids:
        for index, rid in enumerate(req_ids):
            if rid in found or found.get(rid.lstrip("0")):
                continue
            if index < len(per_block_values) and per_block_values[index] is not None:
                found[rid] = per_block_values[index]
        if len(req_ids) == 1 and len(per_block_values) == 1 and per_block_values[0] is not None:
            found.setdefault(req_ids[0], per_block_values[0])

    if not found and isinstance(payload.get("metrics"), list):
        top_val = _fwci_from_result_block({"metrics": payload.get("metrics")}, publication_year)
        if top_val is not None and len(req_ids) == 1:
            found[req_ids[0]] = top_val
    if not found and req_ids:
        deep_val = _deep_scan_fwci_payload(payload, publication_year)
        if deep_val is not None:
            for rid in req_ids:
                found.setdefault(rid, deep_val)
    return found


# SciVal Publication Lookup — defaults match Elsevier console / OpenAPI (5yrs, byYear=true).
_SCIVAL_FWCI_PARAMS = {
    "metricTypes": "FieldWeightedCitationImpact",
    "yearRange": "5yrs",
    "byYear": "true",
    "includedDocs": "AllPublicationTypes",
    "journalImpactType": "CiteScore",
}

_FWCI_YEAR_RANGES = (
    "5yrs",
    "10yrs",
    "5yrsAndCurrent",
    "5yrsAndCurrentAndFuture",
    "3yrs",
    "3yrsAndCurrent",
)


def _build_fwci_query_attempts(publication_year=None):
    """Order SciVal metric queries to maximize FWCI match rate."""
    by_true = [{"byYear": "true", "yearRange": yr} for yr in _FWCI_YEAR_RANGES]
    by_false = [{"byYear": "false", "yearRange": yr} for yr in _FWCI_YEAR_RANGES]
    pinned = [
        {"byYear": "true", "yearRange": "5yrs"},
        {"byYear": "true", "yearRange": "10yrs"},
        {"byYear": "false", "yearRange": "10yrs"},
    ]
    if publication_year is not None and publication_year < 2016:
        return pinned + by_true + [None] + by_false[:3]
    return pinned + [None] + by_true[2:] + by_false[:2]


def _collect_fwci_candidates(payload):
    """All numeric FWCI candidates from a SciVal metrics payload."""
    found = []
    seen = set()

    def _add(value, source):
        num = _coerce_fwci_number(value)
        if num is None:
            return
        key = (round(num, 8), source)
        if key in seen:
            return
        seen.add(key)
        found.append((num, source))

    if not isinstance(payload, dict):
        return found

    blocks = payload.get("results") or []
    if isinstance(blocks, dict):
        blocks = [blocks]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        metrics = block.get("metrics") or []
        if isinstance(metrics, dict):
            metrics = [metrics]
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            mtype = (metric.get("metricType") or metric.get("type") or metric.get("@type") or "").strip()
            if mtype and mtype != "FieldWeightedCitationImpact":
                continue
            if metric.get("value") is not None:
                _add(metric.get("value"), "aggregate")
            vby = metric.get("valueByYear") or {}
            if isinstance(vby, dict):
                for year_key, year_val in vby.items():
                    _add(year_val, f"year:{year_key}")
            values = metric.get("values")
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        if item.get("value") is not None:
                            _add(item.get("value"), "aggregate-nested")
                        nested_vby = item.get("valueByYear") or {}
                        if isinstance(nested_vby, dict):
                            for year_key, year_val in nested_vby.items():
                                _add(year_val, f"year:{year_key}")
                    else:
                        _add(item, "values-list")

    deep = _deep_scan_fwci_payload(payload, None)
    if deep is not None:
        _add(deep, "deep-scan")
    return found


def _score_fwci_candidate(source, publication_year=None):
    """Higher score = better match to the paper's cohort FWCI."""
    if publication_year is None:
        return 50 if source == "aggregate" else 30
    if str(source).startswith("year:"):
        year = _year_from_metric_key(source.split(":", 1)[1])
        if year is None:
            return 35
        if year == int(publication_year):
            return 100
        gap = abs(year - int(publication_year))
        if gap == 1:
            return 92
        if gap <= 3:
            return 80 - gap * 5
        return max(10, 60 - gap)
    if source == "aggregate":
        return 78 if int(publication_year) >= 2016 else 45
    return 40


def _best_fwci_from_payload(payload, publication_year=None):
    candidates = _collect_fwci_candidates(payload)
    if not candidates:
        return None, -1
    best_val = None
    best_score = -1
    for num, source in candidates:
        score = _score_fwci_candidate(source, publication_year)
        if score > best_score:
            best_score = score
            best_val = num
    return best_val, best_score


def _fwci_value_from_response(metrics, payload, pub_id, publication_year=None):
    """Resolve FWCI from parsed metrics map or raw SciVal payload."""
    value = _pick_fwci_from_metrics(metrics, pub_id)
    if value is not None:
        return value, _score_fwci_candidate("aggregate", publication_year)
    if not payload:
        return None, -1
    best, score = _best_fwci_from_payload(payload, publication_year)
    if best is not None:
        return best, score
    value = _deep_scan_fwci_payload(payload, publication_year)
    if value is not None:
        return value, 45
    blocks = (payload.get("results") or []) if isinstance(payload, dict) else []
    if isinstance(blocks, dict):
        blocks = [blocks]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        value = _fwci_from_result_block(block, publication_year)
        if value is not None:
            return value, 50
    return None, -1


def _refresh_publication_year_from_payload(payload, pub_id, pub_year):
    pub_meta = _extract_publication_meta(payload, pub_id)
    if not pub_meta:
        return pub_year
    scival_year = pub_meta.get("publicationYear")
    if scival_year is None:
        return pub_year
    try:
        return int(scival_year)
    except (TypeError, ValueError):
        return pub_year


def lookup_scopus_publication_id_for_doi(doi, api_key, inst_token):
    """Step 1 for FWCI: DOI → numeric Scopus publication ID."""
    for view in ("META", "STANDARD", ""):
        pub_id, pub_year, status, body = fetch_scopus_publication_id(doi, api_key, inst_token, view=view or None)
        if pub_id:
            return pub_id, pub_year, status, body
        if status in (401, 403, 429):
            return None, None, status, body
    cite_id, cite_year = _scopus_id_from_citations_api(doi, api_key, inst_token)
    if cite_id:
        return cite_id, cite_year, 200, None
    search_id = _scopus_id_from_search(doi, api_key, inst_token)
    if search_id:
        return search_id, cite_year, 200, None
    return None, None, status, body


def fetch_fwci_for_publication_ids(
    publication_ids,
    api_key,
    inst_token,
    _retry_count=0,
    *,
    byYear=None,
    yearRange=None,
    journalImpactType=None,
    showAsFieldWeighted=None,
    publication_year=None,
    includedDocs=None,
):
    """Step 2 for FWCI: SciVal publication/metrics by Scopus publication ID(s)."""
    ids = []
    for item in publication_ids or []:
        text = str(item or "").strip()
        if text and text not in ids:
            ids.append(text)
    if not ids:
        return {}, None, "No publication IDs", None
    params = {
        **_SCIVAL_FWCI_PARAMS,
        "publicationIds": ",".join(ids),
        "httpAccept": "application/json",
        "apiKey": api_key,
        "insttoken": inst_token,
    }
    if byYear is not None:
        params["byYear"] = byYear
    if yearRange is not None:
        params["yearRange"] = yearRange
    if journalImpactType is not None:
        params["journalImpactType"] = journalImpactType
    if showAsFieldWeighted is not None:
        params["showAsFieldWeighted"] = showAsFieldWeighted
    if includedDocs is not None:
        params["includedDocs"] = includedDocs
    headers = _elsevier_headers(api_key, inst_token)
    try:
        response = requests.get(
            "https://api.elsevier.com/analytics/scival/publication/metrics",
            params=params,
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        return {}, None, str(exc)[:120], None
    if response.status_code == 429 and _retry_count < 2:
        time.sleep(2)
        return fetch_fwci_for_publication_ids(
            publication_ids,
            api_key,
            inst_token,
            _retry_count + 1,
            byYear=params.get("byYear"),
            yearRange=params.get("yearRange"),
            journalImpactType=params.get("journalImpactType"),
            showAsFieldWeighted=params.get("showAsFieldWeighted"),
            publication_year=publication_year,
        )
    if response.status_code != 200:
        return {}, response.status_code, response.text, None
    try:
        payload = response.json()
    except ValueError:
        return {}, response.status_code, response.text, None
    metrics = _parse_fwci_metrics(payload, requested_ids=ids, publication_year=publication_year)
    return metrics, response.status_code, None, payload


def _extract_publication_meta(payload, pub_id):
    """SciVal publication block from publication/metrics JSON (same response as FWCI)."""
    if not isinstance(payload, dict):
        return None
    blocks = payload.get("results") or []
    if isinstance(blocks, dict):
        blocks = [blocks]
    matched = None
    fallback = None
    for block in blocks:
        if not isinstance(block, dict):
            continue
        pub = block.get("publication")
        if not isinstance(pub, dict):
            continue
        if fallback is None:
            fallback = pub
        bid = pub.get("id")
        if bid is not None and str(bid).lstrip("0") == str(pub_id).lstrip("0"):
            matched = pub
            break
    return matched or fallback


def _scival_optional_row_columns(publication, include_details=False, include_sdg=False):
    """Optional export columns from SciVal publication metadata (no extra API calls)."""
    cols = {}
    if include_details:
        if isinstance(publication, dict):
            cols["SciVal Year"] = publication.get("publicationYear", "N/A")
            cols["SciVal Type"] = publication.get("type", "N/A")
            cols["SciVal Source"] = publication.get("sourceTitle", "N/A")
            topic = publication.get("topicName") or ""
            tid = publication.get("topicId")
            cols["SciVal Topic"] = f"{topic} (ID {tid})" if topic and tid is not None else (topic or "N/A")
            cluster = publication.get("topicClusterName") or ""
            cid = publication.get("topicClusterId")
            cols["SciVal Topic cluster"] = (
                f"{cluster} (ID {cid})" if cluster and cid is not None else (cluster or "N/A")
            )
        else:
            for name in (
                "SciVal Year",
                "SciVal Type",
                "SciVal Source",
                "SciVal Topic",
                "SciVal Topic cluster",
            ):
                cols[name] = "N/A"
    if include_sdg:
        if isinstance(publication, dict):
            sdgs = publication.get("sdg") or []
            cols["SciVal SDGs"] = "; ".join(str(s) for s in sdgs) if sdgs else "N/A"
        else:
            cols["SciVal SDGs"] = "N/A"
    return cols


_SCIVAL_FWCI_LEARN_MORE = (
    "https://www.elsevier.support/scopus/answer/what-is-fieldweighted-citation-impact"
)


def _fwci_help_text():
    return (
        "Field-Weighted Citation Impact is the ratio of citations received relative to the "
        "expected world average for the subject field, publication type, and publication year. "
        f"Learn more: {_SCIVAL_FWCI_LEARN_MORE}"
    )


def _pick_fwci_from_metrics(metrics, pub_id):
    if not metrics:
        return None
    value = metrics.get(str(pub_id))
    if value is None:
        for key, metric_value in metrics.items():
            if key.lstrip("0") == str(pub_id).lstrip("0"):
                value = metric_value
                break
    if value is None and len(metrics) == 1:
        value = next(iter(metrics.values()))
    return value


def _coerce_year(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    match = re.search(r"(\d{4})", text)
    if match:
        return int(match.group(1))
    return None


def _fwci_metrics_empty(payload):
    if not isinstance(payload, dict):
        return True
    blocks = payload.get("results") or []
    if isinstance(blocks, dict):
        blocks = [blocks]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        metrics = block.get("metrics") or []
        if isinstance(metrics, dict):
            metrics = [metrics]
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            mtype = (metric.get("metricType") or metric.get("type") or "").strip()
            if mtype and mtype != "FieldWeightedCitationImpact":
                continue
            if metric.get("value") is not None or metric.get("valueByYear"):
                return False
    return _deep_scan_fwci_payload(payload, None) is None


def fetch_doi_scival(doi, api_key, inst_token, publication_id=None, publication_year=None):
    """DOI → SciVal publication/metrics bundle: FWCI value, status note, optional publication metadata."""
    pub_id = str(publication_id).strip() if publication_id else None
    pub_year = _coerce_year(publication_year)
    status = None
    body = None
    if not pub_id:
        pub_id, pub_year, status, body = lookup_scopus_publication_id_for_doi(doi, api_key, inst_token)
    elif pub_year is None:
        _, meta_year, _, _ = fetch_scopus_publication_id(doi, api_key, inst_token, view="META")
        if meta_year is None:
            _, cite_year = _scopus_id_from_citations_api(doi, api_key, inst_token)
            meta_year = cite_year
        pub_year = _coerce_year(meta_year)
    if not pub_id:
        note = "Could not resolve a Scopus publication ID for this DOI."
        if status == 404:
            note = "No Scopus record for this DOI."
        elif status in (401, 403):
            note = scival_api_error_message("Scopus", status, body)
        elif status == 429:
            note = scival_api_error_message("Scopus", 429, body)
        elif status is None and body:
            note = f"Scopus ID lookup failed: {body}"
        return {"fwci": "N/A", "note": note, "publication": None, "pub_id": None, "match_score": -1}

    query_attempts = _build_fwci_query_attempts(pub_year)[:_FWCI_MAX_QUERY_ATTEMPTS]
    last_scival_status = None
    last_scival_body = None
    last_payload = None
    best_value = None
    best_score = -1
    best_publication = None

    for index, attempt in enumerate(query_attempts):
        if attempt is None:
            metrics, scival_status, scival_body, payload = fetch_fwci_for_publication_ids(
                [pub_id], api_key, inst_token, publication_year=pub_year
            )
        else:
            metrics, scival_status, scival_body, payload = fetch_fwci_for_publication_ids(
                [pub_id],
                api_key,
                inst_token,
                byYear=attempt["byYear"],
                yearRange=attempt["yearRange"],
                publication_year=pub_year,
            )
        last_scival_status = scival_status
        last_scival_body = scival_body
        if payload:
            last_payload = payload
            pub_year = _refresh_publication_year_from_payload(payload, pub_id, pub_year)
            best_publication = _extract_publication_meta(payload, pub_id) or best_publication
        if scival_status in (401, 403, 429):
            break
        if scival_status and scival_status != 200:
            continue
        value, score = _fwci_value_from_response(metrics, payload, pub_id, pub_year)
        if value is not None and score > best_score:
            best_value = value
            best_score = score
        if best_score >= 92:
            break
        if index < len(query_attempts) - 1:
            time.sleep(0.1)

    if best_value is None and pub_id and last_scival_status == 200 and _fwci_metrics_empty(last_payload):
        for docs in ("ArticlesReviews", "ArticlesOnly", "AllPublicationTypes"):
            metrics, scival_status, scival_body, payload = fetch_fwci_for_publication_ids(
                [pub_id],
                api_key,
                inst_token,
                byYear="true",
                yearRange="5yrs",
                includedDocs=docs,
                publication_year=pub_year,
            )
            last_scival_status = scival_status
            last_scival_body = scival_body
            if payload:
                last_payload = payload
            if scival_status == 200 and payload:
                value, score = _fwci_value_from_response(metrics, payload, pub_id, pub_year)
                if value is not None and score > best_score:
                    best_value = value
                    best_score = score
                    break

    if best_value is not None:
        text = f"{best_value:.3f}".rstrip("0").rstrip(".")
        publication = best_publication or (
            _extract_publication_meta(last_payload, pub_id) if last_payload else None
        )
        return {"fwci": text, "note": "", "publication": publication, "pub_id": pub_id, "match_score": best_score}

    publication = _extract_publication_meta(last_payload, pub_id) if last_payload else None
    if last_scival_status in (401, 403):
        return {"fwci": "N/A", "note": scival_api_error_message("Scival", last_scival_status, last_scival_body), "publication": publication, "pub_id": pub_id, "match_score": best_score}
    if last_scival_status == 429:
        return {"fwci": "N/A", "note": scival_api_error_message("Scival", 429, last_scival_body), "publication": publication, "pub_id": pub_id, "match_score": best_score}
    if last_scival_status and last_scival_status != 200:
        return {"fwci": "N/A", "note": scival_api_error_message("Scival", last_scival_status, last_scival_body), "publication": publication, "pub_id": pub_id, "match_score": best_score}

    year_hint = f" (publication year {pub_year})" if pub_year else ""
    api_hint = (
        "SciVal API may not expose FWCI for some older papers even when Scopus.com shows it."
        if pub_year and pub_year < 2016
        else "Try yearRange=10yrs with byYear=false or byYear=true in Publication Lookup."
    )
    return {
        "fwci": "N/A",
        "note": f"FWCI not returned for Scopus ID {pub_id}{year_hint}. {api_hint}",
        "publication": publication,
        "pub_id": pub_id,
        "match_score": best_score,
    }


def fetch_doi_fwci(doi, api_key, inst_token):
    """Backward-compatible wrapper: (FWCI display value, status note)."""
    bundle = fetch_doi_scival(doi, api_key, inst_token)
    return bundle.get("fwci", "N/A"), bundle.get("note", "")