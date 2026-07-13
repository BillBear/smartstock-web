#!/usr/bin/env python3
"""Audit immutable full-market feature sources without fetching data."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.data_inventory import audit_source_fields, resolve_raw_asset_root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    raw_root, manifest_path = resolve_raw_asset_root(Path(args.asset_root))
    report = audit_source_fields(raw_root, manifest_path)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, prefix=".inventory-", suffix=".tmp", delete=False
    ) as handle:
        json.dump(report, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(f"r4a_ready={str(report['r4a_ready']).lower()}")
    print(f"blocking_codes={','.join(report['blocking_codes']) or 'none'}")
    print(f"experimental_only_blocks={','.join(report['experimental_only_blocks']) or 'none'}")
    print(f"output={output}")
    return 0 if report["r4a_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
