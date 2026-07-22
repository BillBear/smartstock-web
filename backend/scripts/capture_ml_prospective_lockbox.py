#!/usr/bin/env python3
"""Capture a future-only TuShare raw-data batch for ML research validation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Callable

import pandas as pd


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.ml_prospective_lockbox import call_with_retries, capture_prospective_batch, normalize_trade_date
from app.evaluation.ml_recovery_acceptance import verify_recovery_inputs


class TuShareProspectiveFetcher:
    """Thin local adapter that keeps the token outside the repository and manifest."""

    def __init__(self, token: str):
        try:
            import tushare as ts
        except ImportError as error:
            raise RuntimeError("tushare must be installed in the local ML environment") from error
        self._pro = ts.pro_api(token)

    def open_trade_dates(self, start_date: str, end_date: str) -> tuple[str, ...]:
        calendar = call_with_retries(
            lambda: self._pro.trade_cal(
                exchange="",
                start_date=normalize_trade_date(start_date, "start date").replace("-", ""),
                end_date=normalize_trade_date(end_date, "end date").replace("-", ""),
                fields="cal_date,is_open",
            )
        )
        required = {"cal_date", "is_open"}
        if not isinstance(calendar, pd.DataFrame) or not required.issubset(calendar.columns):
            raise RuntimeError("TuShare trade_cal response misses cal_date or is_open")
        return tuple(
            sorted(
                {
                    normalize_trade_date(value, "TuShare calendar")
                    for value in calendar.loc[calendar["is_open"].eq(1), "cal_date"].tolist()
                }
            )
        )

    def fetch(self, endpoint: str, trade_date: str) -> pd.DataFrame:
        requests: dict[str, Callable[[], pd.DataFrame]] = {
            "daily": lambda: self._pro.daily(trade_date=trade_date),
            "daily_basic": lambda: self._pro.daily_basic(trade_date=trade_date),
            "adj_factor": lambda: self._pro.adj_factor(trade_date=trade_date),
            "stk_limit": lambda: self._pro.stk_limit(trade_date=trade_date),
            "suspend_d": lambda: self._pro.suspend_d(trade_date=trade_date),
        }
        if endpoint not in requests:
            raise ValueError(f"unsupported TuShare endpoint: {endpoint}")
        return call_with_retries(requests[endpoint])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-root", required=True, help="sealed R1 label asset directory")
    parser.add_argument("--feature-asset-root", required=True, help="sealed R2 feature asset directory")
    parser.add_argument("--panel-root", required=True, help="certified SH/SZ panel directory")
    parser.add_argument("--development-cutoff", required=True, help="last development signal date")
    parser.add_argument("--start-date", required=True, help="first prospective calendar date")
    parser.add_argument("--end-date", required=True, help="last prospective calendar date")
    parser.add_argument("--output-dir", required=True, help="new immutable local batch directory")
    parser.add_argument("--code-commit", required=True, help="Git commit that defines the capture implementation")
    args = parser.parse_args()

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required through the local environment")
    inputs = verify_recovery_inputs(args.label_root, args.feature_asset_root, args.panel_root)
    fetcher = TuShareProspectiveFetcher(token)
    report = capture_prospective_batch(
        fetcher=fetcher,
        trade_dates=fetcher.open_trade_dates(args.start_date, args.end_date),
        development_cutoff=args.development_cutoff,
        output_dir=args.output_dir,
        code_commit=args.code_commit,
        input_provenance={
            "r1_label_registry_sha256": str(inputs["input_manifest"]["label_registry_sha256"]),
            "r1_split_sha256": str(inputs["input_manifest"]["label_split_sha256"]),
            "r2_feature_asset_manifest_sha256": str(inputs["input_manifest"]["feature_asset_manifest_sha256"]),
            "panel_rebuild_manifest_sha256": str(inputs["input_manifest"]["panel_rebuild_manifest_sha256"]),
        },
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
