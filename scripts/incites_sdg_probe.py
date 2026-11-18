#!/usr/bin/env python3
"""Probe WoS Starter DOI resolution + InCites SDG schema (dev / local)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wos_incites_lib as lib  # noqa: E402


def load_secrets(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe InCites SDGs by DOI via WoS UT.")
    parser.add_argument(
        "--doi",
        default="10.1016/S0140-6736(20)32246-8",
        help="DOI with expected WoS + SDG coverage",
    )
    parser.add_argument("--secrets", type=Path, default=ROOT / ".streamlit" / "secrets.toml")
    parser.add_argument("--wos-key", default="", help="Override WOS_API_KEY")
    parser.add_argument("--incites-key", default="", help="Override INCITES_API_KEY")
    parser.add_argument("--dump-json", action="store_true", help="Print raw InCites JSON")
    args = parser.parse_args()

    secrets = load_secrets(args.secrets)
    wos_key = (args.wos_key or secrets.get("WOS_API_KEY") or "").strip()
    incites_key = (args.incites_key or secrets.get("INCITES_API_KEY") or "").strip()
    if not wos_key:
        print("Set WOS_API_KEY in secrets or --wos-key", file=sys.stderr)
        return 1

    doc, status, err = lib.fetch_wos_starter_document_by_doi(args.doi, wos_key)
    print(f"WoS Starter HTTP {status}")
    if err:
        print(f"WoS: {err}")
    if not doc:
        return 1
    ut = lib.normalize_wos_ut(doc.get("uid"))
    print(f"Title: {(doc.get('title') or '')[:80]}")
    print(f"UT: {ut}")

    api_key = lib.resolve_incites_api_key(wos_key, incites_key)
    from urllib.parse import urlencode
    import requests

    params = {"UT": ut, "schema": "sdg", "ver": "2", "esci": "y"}
    url = f"{lib.INCITES_DLM_JSON}?{urlencode(params)}"
    rsp = requests.get(url, headers={"X-ApiKey": api_key}, timeout=45)
    print(f"InCites HTTP {rsp.status_code} (key={'INCITES' if incites_key else 'WOS'})")
    if rsp.status_code != 200:
        print((rsp.text or "")[:400])
        return 1
    try:
        payload = rsp.json()
    except ValueError:
        print("InCites response is not JSON", file=sys.stderr)
        return 1
    if args.dump_json:
        print(json.dumps(payload, indent=2)[:8000])
    sdgs = lib.parse_incites_sdg_payload(payload)
    print(f"Parsed SDGs: {sdgs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())