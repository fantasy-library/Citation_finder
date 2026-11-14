#!/usr/bin/env python3
"""Print Elsevier X-RateLimit headers from one Scopus API call (no WebSniffer)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fwci_lib import probe_elsevier_scopus_quota  # noqa: E402


def load_credentials(secrets_path: Path) -> tuple[str, str]:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore
    data = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    return (data.get("SCOPUS_API_KEY") or "").strip(), (data.get("SCOPUS_INST_TOKEN") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Scopus/SciVal weekly API quota headers.")
    parser.add_argument(
        "--secrets",
        type=Path,
        default=ROOT / ".streamlit" / "secrets.toml",
    )
    parser.add_argument(
        "--endpoint",
        choices=("citations", "scival_metrics"),
        default="citations",
        help="Which API to probe (quotas are separate per product).",
    )
    args = parser.parse_args()
    key, inst = load_credentials(args.secrets)
    if not key or not inst:
        print("Set SCOPUS_API_KEY and SCOPUS_INST_TOKEN in secrets.", file=sys.stderr)
        return 1
    info = probe_elsevier_scopus_quota(key, inst, endpoint=args.endpoint)
    print(info.get("api_label") or args.endpoint)
    print(f"HTTP {info.get('http_status')}")
    print(f"Remaining: {info.get('remaining')} / {info.get('limit')}")
    print(f"Reset: {info.get('reset_at')}")
    print(f"ELS status: {info.get('els_status')}")
    print(info.get("note") or "")
    return 0 if info.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())