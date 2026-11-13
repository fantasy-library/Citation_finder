#!/usr/bin/env python3
"""Batch FWCI lookup: summary stats + CSV for tuning match rate."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fwci_lib import fetch_doi_scival  # noqa: E402


def load_credentials(secrets_path: Path) -> tuple[str, str]:
    if not secrets_path.is_file():
        raise FileNotFoundError(f"Missing secrets file: {secrets_path}")
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore
    data = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    api_key = (data.get("SCOPUS_API_KEY") or "").strip()
    inst = (data.get("SCOPUS_INST_TOKEN") or "").strip()
    if not api_key or not inst:
        raise ValueError("SCOPUS_API_KEY and SCOPUS_INST_TOKEN must be set in secrets.")
    return api_key, inst


def load_dois(path: Path | None, doi_args: list[str]) -> list[str]:
    dois: list[str] = [d.strip() for d in doi_args if d.strip().startswith("10.")]
    if path:
        if path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path)
        col = next((c for c in df.columns if "doi" in str(c).lower()), None)
        if col is None:
            raise ValueError(f"No DOI column in {path}")
        dois.extend(
            str(v).strip()
            for v in df[col]
            if str(v).strip().startswith("10.")
        )
    seen: set[str] = set()
    unique: list[str] = []
    for d in dois:
        key = d.lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk SciVal FWCI check for a DOI list.")
    parser.add_argument(
        "--secrets",
        type=Path,
        default=ROOT / ".streamlit" / "secrets.toml",
        help="Path to Streamlit secrets.toml (default: .streamlit/secrets.toml)",
    )
    parser.add_argument("--file", type=Path, help="CSV/Excel file with a DOI column")
    parser.add_argument("--out", type=Path, default=Path("fwci_bulk_results.csv"))
    parser.add_argument("--delay", type=float, default=0.35, help="Seconds between DOIs")
    parser.add_argument("dois", nargs="*", help="DOIs (or use --file)")
    args = parser.parse_args()

    api_key, inst = load_credentials(args.secrets)
    dois = load_dois(args.file, args.dois)
    if not dois:
        print("No DOIs to process.", file=sys.stderr)
        return 1

    rows = []
    for i, doi in enumerate(dois, start=1):
        print(f"[{i}/{len(dois)}] {doi}")
        bundle = fetch_doi_scival(doi, api_key, inst)
        pub = bundle.get("publication") or {}
        year = pub.get("publicationYear") if isinstance(pub, dict) else None
        rows.append(
            {
                "DOI": doi,
                "FWCI": bundle.get("fwci", "N/A"),
                "FWCI Status": (bundle.get("note") or "").strip() or ("Success" if bundle.get("fwci") != "N/A" else ""),
                "Scopus ID": bundle.get("pub_id"),
                "Publication year": year,
                "Match score": bundle.get("match_score"),
            }
        )
        if i < len(dois):
            time.sleep(max(0.0, args.delay))

    df = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    matched = (df["FWCI"] != "N/A").sum()
    total = len(df)
    pct = 100.0 * matched / total if total else 0.0
    print(f"\nMatched FWCI: {matched}/{total} ({pct:.1f}%)")
    print(f"Wrote: {args.out.resolve()}")
    if matched < total:
        na = df[df["FWCI"] == "N/A"]
        by_year = na.groupby("Publication year", dropna=False).size().sort_index()
        print("\nN/A by publication year (from SciVal metadata when available):")
        print(by_year.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
