#!/usr/bin/env python3
"""Compress and verify superseded local ML research process data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.run_archive import archive_research_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--path", action="append", required=True, dest="paths", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--delete-after-verify", action="store_true")
    args = parser.parse_args(argv)
    manifest = archive_research_paths(
        args.source_root,
        args.paths,
        args.output,
        delete_after_verify=args.delete_after_verify,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "verification_status": manifest["verification_status"],
                "file_count": manifest["file_count"],
                "archive_bytes": manifest["archive_bytes"],
                "archive_sha256": manifest["archive_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
