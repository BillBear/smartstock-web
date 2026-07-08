from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Collect read-only TuShare enhanced panels for historical candidate dates.")
    parser.add_argument("--candidate-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--endpoints", default="daily,daily_basic,adj_factor,stk_limit,suspend_d,moneyflow,index_daily")
    parser.add_argument("--index-codes", default="000001.SH,399001.SZ,399006.SZ,000300.SH,000905.SH,000852.SH")
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--max-dates", type=int, default=0)
    parser.add_argument("--fixture", action="store_true", help="Use deterministic fake TuShare client for CLI smoke tests.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    backend_root = _bootstrap_paths()
    from app.evaluation.tushare_enhanced_panel_collection import (
        candidate_dates_and_symbols,
        collect_tushare_enhanced_panels,
        write_tushare_panel_collection_artifacts,
    )

    args = parse_args(argv)
    candidate_df = pd.read_csv(args.candidate_csv)
    scope = candidate_dates_and_symbols(candidate_df)
    trade_dates = scope["trade_dates"]
    if args.max_dates and args.max_dates > 0:
        trade_dates = trade_dates[-int(args.max_dates) :]
    pro_client = _fake_pro_client() if args.fixture else _build_tushare_client(backend_root)
    collection = collect_tushare_enhanced_panels(
        pro_client,
        trade_dates=trade_dates,
        symbols=scope["symbols"],
        endpoints=_split_csv(args.endpoints),
        index_codes=_split_csv(args.index_codes),
        sleep_seconds=0.0 if args.fixture else float(args.sleep_seconds),
    )
    paths = write_tushare_panel_collection_artifacts(collection, args.output_dir)
    summary = collection.get("summary") or {}
    print(
        json.dumps(
            {
                "status": "tushare_enhanced_panel_collection_completed",
                "trade_date_count": summary.get("trade_date_count"),
                "symbol_count": summary.get("symbol_count"),
                "production_evidence": summary.get("production_evidence"),
                "strategy_impact": summary.get("strategy_impact"),
                "output_dir": str(args.output_dir),
                "artifacts": paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _build_tushare_client(backend_root: Path):
    token = _load_token(backend_root)
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured in environment or local secret file")
    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()


def _load_token(backend_root: Path) -> str:
    for env_path in [
        backend_root / ".env",
        backend_root.parent / ".local-secrets" / "smartstock.env",
        Path("/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env"),
    ]:
        _load_env_file(env_path)
    return os.environ.get("TUSHARE_TOKEN", "").strip()


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _fake_pro_client():
    class FakePro:
        def daily(self, **kwargs):
            trade_date = kwargs["trade_date"]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "close": 10.0, "vol": 100, "amount": 200}])

        def daily_basic(self, **kwargs):
            trade_date = kwargs["trade_date"]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "turnover_rate": 2.5}])

        def adj_factor(self, **kwargs):
            trade_date = kwargs["trade_date"]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "adj_factor": 1.0}])

        def stk_limit(self, **kwargs):
            trade_date = kwargs["trade_date"]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "up_limit": 11.0, "down_limit": 9.0}])

        def suspend_d(self, **kwargs):
            return pd.DataFrame()

        def moneyflow(self, **kwargs):
            trade_date = kwargs["trade_date"]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "net_mf_amount": 1000.0}])

        def index_daily(self, **kwargs):
            return pd.DataFrame([{"ts_code": kwargs["ts_code"], "trade_date": kwargs["start_date"], "close": 3000.0}])

    return FakePro()


if __name__ == "__main__":
    raise SystemExit(main())
