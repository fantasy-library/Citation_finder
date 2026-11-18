#!/usr/bin/env python3
"""Probe OpenAlex Work export by DOI (local dev)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import openalex_lib as lib  # noqa: E402


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
    parser = argparse.ArgumentParser(description="OpenAlex work row probe by DOI.")
    parser.add_argument("--doi", default="10.7717/peerj.4375")
    parser.add_argument("--secrets", type=Path, default=ROOT / ".streamlit" / "secrets.toml")
    parser.add_argument("--json", action="store_true", help="Print raw OpenAlex JSON")
    args = parser.parse_args()
    secrets = load_secrets(args.secrets)
    api_key = (secrets.get("OPENALEX_API_KEY") or "").strip()
    if args.json:
        work, err = lib.get_openalex_work_by_doi(args.doi, api_key)
        if err:
            print("Error:", err, file=sys.stderr)
            return 1
        print(json.dumps(work, indent=2)[:12000])
        return 0
    row = lib.build_openalex_work_row(args.doi, api_key, include=lib.DEFAULT_OPENALEX_PACKS)
    for k, v in row.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())