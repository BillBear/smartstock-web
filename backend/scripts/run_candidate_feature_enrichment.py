from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Enrich historical SmartStock candidates with read-only rule features.")
    parser.add_argument("--candidate-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--history-panel-path", default="", help="Optional CSV/parquet history panel for offline runs.")
    parser.add_argument("--history-cache-root", default="", help="Cache root for explicit history range fetches.")
    parser.add_argument("--lookback-calendar-days", type=int, default=240)
    parser.add_argument("--min-history-rows", type=int, default=61)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--round-trip-cost-pct", type=float, default=0.13)
    parser.add_argument("--min-margin-pct", type=float, default=0.30)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    backend_root = _bootstrap_paths()
    from app.evaluation.candidate_feature_enrichment import enrich_candidate_features, write_candidate_feature_artifacts

    args = parse_args(argv)
    candidates = pd.read_csv(args.candidate_csv)
    if args.history_panel_path:
        history_panel = _read_frame(Path(args.history_panel_path))
        provider = None
    else:
        history_panel = None
        provider = _build_cached_history_provider(backend_root, args)

    enrichment = enrich_candidate_features(
        candidates,
        history_provider=provider,
        history_panel_df=history_panel,
        lookback_calendar_days=int(args.lookback_calendar_days),
        min_history_rows=int(args.min_history_rows),
        workers=int(args.workers),
    )
    paths = write_candidate_feature_artifacts(
        enrichment,
        args.output_dir,
        horizon=int(args.horizon),
        round_trip_cost_pct=float(args.round_trip_cost_pct),
        min_margin_pct=float(args.min_margin_pct),
    )
    summary = enrichment["summary"]
    print(
        json.dumps(
            {
                "status": "candidate_feature_enrichment_completed",
                "candidate_row_count": summary.get("candidate_row_count"),
                "feature_complete_row_count": summary.get("feature_complete_row_count"),
                "feature_complete_row_rate": summary.get("feature_complete_row_rate"),
                "blocking_reasons": summary.get("blocking_reasons"),
                "output_dir": str(args.output_dir),
                "artifacts": paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _build_cached_history_provider(backend_root: Path, args):
    from app.evaluation.ml_history_cache import MLHistoryCache
    from app.main import data_source_manager

    cache_root = Path(args.history_cache_root) if args.history_cache_root else backend_root.parent / "runtime" / "candidate_feature_history_cache"
    return MLHistoryCache(
        data_source_manager,
        cache_root=cache_root,
        retry_count=2,
        sleep_seconds=1.0,
        inter_request_sleep_seconds=0.05,
        circuit_sleep_seconds=65.0,
    )


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


if __name__ == "__main__":
    raise SystemExit(main())
