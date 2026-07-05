from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def _load_local_env(backend_root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    from app.evaluation.local_ml_environment import local_secret_candidates

    repo_root = backend_root.parent
    candidates = [str(backend_root / ".env"), *local_secret_candidates(repo_root)]
    for item in candidates:
        path = Path(item)
        if path.exists():
            load_dotenv(path, override=False)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run local core ML experiment.")
    parser.add_argument("--model-family", default="local_core_v1")
    parser.add_argument("--model-display-name", default="Local Core ML v1 - 700 symbols")
    parser.add_argument("--train-start", default="2025-01-01")
    parser.add_argument("--train-end", default=None)
    parser.add_argument("--target-valid-symbols", type=int, default=700)
    parser.add_argument("--oversample-symbols", type=int, default=760)
    parser.add_argument("--min-formal-model-symbols", type=int, default=700)
    parser.add_argument("--sample-step", type=int, default=2)
    parser.add_argument("--primary-horizon", type=int, default=10)
    parser.add_argument("--exclude-news-features", action="store_true", default=False)
    parser.add_argument("--exclude-market-state-features", action="store_true", default=False)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args(argv)


def build_config_from_args(args) -> Dict[str, Any]:
    from app.evaluation.local_ml_config import build_local_ml_config

    is_v2 = str(args.model_family or "") == "local_core_v2"
    payload = {
        "model_family": args.model_family,
        "model_display_name": args.model_display_name if not is_v2 else "Local Core ML v2 - strict labels and tree diagnostics",
        "train_start": args.train_start,
        "target_valid_symbols": args.target_valid_symbols,
        "oversample_symbols": args.oversample_symbols,
        "min_formal_model_symbols": args.min_formal_model_symbols,
        "sample_step": 1 if is_v2 and args.sample_step == 2 else args.sample_step,
        "primary_horizon": args.primary_horizon,
        "primary_label": f"label_rank_top10_{int(args.primary_horizon)}d" if is_v2 else f"label_top20_{int(args.primary_horizon)}d",
        "candidate_set": "core_v2" if is_v2 else "default",
        "min_daily_panel_count": 500 if is_v2 else 0,
        "exclude_news_features": True if args.exclude_news_features else True,
        "exclude_market_state_features": True if args.exclude_market_state_features else True,
    }
    if args.train_end:
        payload["train_end"] = args.train_end
    if args.output_root:
        payload["output_root"] = args.output_root
    return build_local_ml_config(payload)


def history_window_for_config(cfg: Dict[str, Any]) -> tuple[str, str]:
    start_dt = datetime.strptime(str(cfg["train_start"]), "%Y-%m-%d")
    end_dt = datetime.strptime(str(cfg["train_end"]), "%Y-%m-%d")
    warmup_days = int(cfg.get("feature_warmup_calendar_days") or 365)
    lookahead_days = int(cfg.get("label_lookahead_calendar_days") or max(30, int(cfg["primary_horizon"]) * 4 + 20))
    return (
        (start_dt - timedelta(days=warmup_days)).strftime("%Y-%m-%d"),
        (end_dt + timedelta(days=lookahead_days)).strftime("%Y-%m-%d"),
    )


def history_cache_root_for_config(cfg: Dict[str, Any]) -> Path:
    if cfg.get("history_cache_root"):
        return Path(str(cfg["history_cache_root"]))
    return Path(str(cfg["output_root"])).parent / "history_cache"


def main(argv=None) -> int:
    backend_root = _bootstrap_paths()
    args = parse_args(argv)
    _load_local_env(backend_root)
    cfg = build_config_from_args(args)
    run_dir = Path(cfg["output_root"]) / cfg["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    run_config_path = run_dir / "run_config.json"
    run_config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "production_enabled": False,
                    "run_config_path": str(run_config_path),
                    "target_valid_symbols": cfg["target_valid_symbols"],
                    "output_root": cfg["output_root"],
                },
                ensure_ascii=False,
            )
        )
        return 0

    result = run_experiment(cfg, run_dir)
    print(json.dumps({"run_dir": str(run_dir), "recommendation": result.get("recommendation")}, ensure_ascii=False))
    return 0 if result.get("recommendation") != "blocked" else 2


def run_experiment(cfg: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    from app.evaluation.local_ml_environment import evaluate_environment_report
    from app.evaluation.ml_feature_audit import audit_features
    from app.evaluation.ml_history_cache import MLHistoryCache
    from app.evaluation.local_ml_labels import add_local_core_labels
    from app.evaluation.local_ml_v2 import (
        V2_FEATURE_NAMES,
        add_local_core_v2_labels,
        build_local_core_v2_features,
    )
    from app.evaluation.ml_splits import build_ml_split_plan
    from app.evaluation.ml_symbol_sampler import sample_training_symbols
    from app.evaluation.ml_training_reviewer import review_local_ml_run
    from app.evaluation.local_ml_trainer import train_local_models
    from app.main import data_source_manager
    from app.services.ml_dataset_builder import MLDatasetBuilder

    preflight = evaluate_environment_report(cfg, data_source_manager, ["002415", "600519", "300750"])
    _write_json(run_dir / "preflight_report.json", preflight)
    if not preflight.get("ready"):
        _write_json(run_dir / "post_run_review.json", {"recommendation": "blocked", "blocking_reasons": preflight["blocking_codes"]})
        return {"recommendation": "blocked", "blocking_reasons": preflight["blocking_codes"]}

    snapshot = data_source_manager.get_a_share_snapshot() or []
    sampled = sample_training_symbols(
        snapshot,
        target_count=int(cfg["target_valid_symbols"]),
        oversample_count=int(cfg["oversample_symbols"]),
        seed=int(cfg["seed"]),
    )
    _write_json(run_dir / "symbol_sample_manifest.json", {"count": len(sampled), "symbols": sampled})

    history_cache = MLHistoryCache(
        data_source_manager,
        cache_root=history_cache_root_for_config(cfg),
        retry_count=int(cfg["history_retry_count"]),
        sleep_seconds=float(cfg["history_retry_sleep_seconds"]),
        inter_request_sleep_seconds=float(cfg.get("history_inter_request_sleep_seconds") or 0.0),
        circuit_sleep_seconds=float(cfg.get("history_circuit_sleep_seconds") or 0.0),
    )
    history_start, history_end = history_window_for_config(cfg)
    cache_result = history_cache.fetch_many(
        [row["symbol"] for row in sampled],
        history_start,
        history_end,
        workers=int(cfg["history_fetch_workers"]),
    )
    candidate_valid_symbols = list(cache_result["valid_symbols"] or [])
    _write_json(run_dir / "history_cache_manifest.json", history_cache.manifest())
    if len(candidate_valid_symbols) < int(cfg["min_formal_model_symbols"]):
        dataset_meta = {
            "valid_symbol_count": len(candidate_valid_symbols),
            "required_valid_symbol_count": int(cfg["min_formal_model_symbols"]),
            "sample_count": 0,
            "blocked": True,
            "blocking_reason": "valid_symbols_below_required",
        }
        _write_json(run_dir / "dataset_meta.json", dataset_meta)
        _write_json(run_dir / "feature_audit.json", {"leakage_violations": [], "features": {}})
        _write_json(run_dir / "model_comparison.json", {"best_model": "", "models": {}})
        return review_local_ml_run(run_dir)

    excluded_features = _excluded_features(cfg)
    dataset = MLDatasetBuilder(data_source_manager).build_dataset(
        {
            "train_start": cfg["train_start"],
            "train_end": cfg["train_end"],
            "symbols": candidate_valid_symbols,
            "history_source": history_cache,
            "horizon_days": int(cfg["primary_horizon"]),
            "sample_step": 1,
            "exclude_feature_names": excluded_features,
            "include_raw_columns": True,
            "include_samples": False,
            "final_time_holdout_months": 3,
            "stock_holdout_ratio": 0.20,
            "walk_forward_splits": 5,
        }
    )
    if str(cfg.get("model_family")) == "local_core_v2":
        featured, feature_specs = build_local_core_v2_features(dataset["df"])
        frame, feature_names, label_col, split_plan, v2_report = _prepare_v2_training_inputs(
            featured,
            primary_horizon=int(cfg["primary_horizon"]),
            auxiliary_horizons=list(cfg.get("auxiliary_horizons") or []),
            sample_step=int(cfg["sample_step"]),
            min_daily_panel_count=int(cfg.get("min_daily_panel_count") or 500),
            target_symbols=candidate_valid_symbols,
            target_count=int(cfg["target_valid_symbols"]),
            final_time_holdout_months=3,
            stock_holdout_ratio=0.20,
            walk_forward_splits=5,
            labeler=add_local_core_v2_labels,
        )
        extra_dataset_meta = {
            "v2_report": v2_report,
            "feature_specs": feature_specs,
            "split_plan": split_plan,
        }
    else:
        frame = _prepare_local_training_frame(
            dataset["df"],
            horizons=list(cfg.get("auxiliary_horizons") or []) + [int(cfg["primary_horizon"])],
            primary_horizon=int(cfg["primary_horizon"]),
            sample_step=int(cfg["sample_step"]),
            labeler=add_local_core_labels,
        )
        frame = _limit_frame_to_target_symbols(
            frame,
            symbol_order=candidate_valid_symbols,
            target_count=int(cfg["target_valid_symbols"]),
        )
        feature_names = list(dataset.get("feature_names") or [])
        label_col = f"label_top20_{int(cfg['primary_horizon'])}d"
        split_plan = build_ml_split_plan(
            frame,
            final_holdout_months=3,
            stock_holdout_ratio=0.20,
            walk_forward_splits=5,
        ) if not frame.empty else (dataset.get("meta") or {}).get("split_plan")
        extra_dataset_meta = {"split_plan": split_plan}
    frame = _apply_symbol_names(frame, sampled)
    frame = _assign_split_labels(frame, split_plan)
    dataset_meta = {
        **(dataset.get("meta") or {}),
        "model_family": cfg.get("model_family"),
        "model_display_name": cfg.get("model_display_name"),
        "valid_symbol_count": int(frame["symbol"].nunique()) if not frame.empty else 0,
        "candidate_valid_symbol_count": len(candidate_valid_symbols),
        "required_valid_symbol_count": int(cfg["min_formal_model_symbols"]),
        "sample_count": int(len(frame)),
        "excluded_features": excluded_features,
        "sample_step": int(cfg["sample_step"]),
        "feature_names": feature_names,
        "label_columns": _label_columns(frame),
        "primary_label": label_col,
        "auxiliary_horizons": list(cfg.get("auxiliary_horizons") or []),
        **extra_dataset_meta,
    }
    dataset_meta["training_sample_artifacts"] = _write_training_sample_artifacts(run_dir, frame)
    _write_json(run_dir / "dataset_meta.json", dataset_meta)

    return_col = f"future_return_{int(cfg['primary_horizon'])}d_pct"
    feature_audit = audit_features(frame, feature_names, label_col=label_col, return_col=return_col)
    _write_json(run_dir / "feature_audit.json", feature_audit)

    model_comparison = train_local_models(
        frame,
        feature_names=feature_names,
        label_col=label_col,
        return_col=return_col,
        split_plan=dataset_meta.get("split_plan"),
        candidate_set=str(cfg.get("candidate_set") or "default"),
        artifact_dir=Path(cfg.get("artifact_root") or run_dir / "artifact") / cfg["run_id"],
        prediction_output_path=run_dir / "holdout_predictions.csv",
        model_metadata={
            "run_id": cfg["run_id"],
            "model_family": cfg["model_family"],
            "model_display_name": cfg["model_display_name"],
            "train_start": cfg["train_start"],
            "train_end": cfg["train_end"],
            "target_valid_symbols": cfg["target_valid_symbols"],
            "valid_symbol_count": dataset_meta["valid_symbol_count"],
            "sample_count": dataset_meta["sample_count"],
        },
    )
    _write_json(run_dir / "model_comparison.json", model_comparison)
    (run_dir / "training_report.md").write_text(_training_report_markdown(cfg, dataset_meta, model_comparison), encoding="utf-8")
    return review_local_ml_run(run_dir)


def _prepare_v2_training_inputs(
    df,
    primary_horizon: int,
    auxiliary_horizons: List[int],
    sample_step: int,
    min_daily_panel_count: int,
    target_symbols: List[str],
    target_count: int,
    final_time_holdout_months: int,
    stock_holdout_ratio: float,
    walk_forward_splits: int,
    labeler,
):
    import pandas as pd
    from app.evaluation.local_ml_v2 import V2_FEATURE_NAMES, filter_daily_cross_section
    from app.evaluation.ml_splits import build_ml_split_plan

    if df is None or df.empty:
        return pd.DataFrame(), list(V2_FEATURE_NAMES), f"label_rank_top10_{int(primary_horizon)}d", {}, {
            "daily_panel_gate": {"dropped_date_count": 0},
        }
    frame = _prepare_local_training_frame(
        df,
        horizons=list(auxiliary_horizons or []) + [int(primary_horizon)],
        primary_horizon=int(primary_horizon),
        sample_step=max(1, int(sample_step or 1)),
        labeler=labeler,
    )
    frame = _limit_frame_to_target_symbols(
        frame,
        symbol_order=target_symbols,
        target_count=int(target_count),
    )
    frame, daily_gate = filter_daily_cross_section(frame, min_daily_count=int(min_daily_panel_count))
    label_col = f"label_rank_top10_{int(primary_horizon)}d"
    split_plan = build_ml_split_plan(
        frame,
        final_holdout_months=int(final_time_holdout_months),
        stock_holdout_ratio=float(stock_holdout_ratio),
        walk_forward_splits=int(walk_forward_splits),
        label_horizon_days=int(primary_horizon),
    ) if not frame.empty else {}
    report = {
        "daily_panel_gate": daily_gate,
        "primary_label": label_col,
        "feature_set": "local_core_v2",
        "feature_count": len(V2_FEATURE_NAMES),
    }
    return frame, list(V2_FEATURE_NAMES), label_col, split_plan, report


def _prepare_local_training_frame(df, horizons: List[int], primary_horizon: int, sample_step: int, labeler):
    import pandas as pd

    if df is None or df.empty:
        return pd.DataFrame()
    labeled = labeler(df, horizons=horizons, primary_horizon=primary_horizon)
    suffix = f"{int(primary_horizon)}d"
    primary_return = f"future_return_{suffix}_pct"
    labeled = labeled[labeled["tradability_flag"] & labeled[primary_return].notna()].copy()
    labeled = labeled.sort_values(["symbol", "date"]).reset_index(drop=True)
    step = max(1, int(sample_step or 1))
    if step <= 1:
        return labeled.sort_values(["date", "symbol"]).reset_index(drop=True)
    sampled = []
    for _, group in labeled.groupby("symbol", sort=False):
        sampled.append(group.iloc[::step].copy())
    if not sampled:
        return pd.DataFrame(columns=labeled.columns)
    return pd.concat(sampled, ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)


def _limit_frame_to_target_symbols(frame, symbol_order: List[str], target_count: int):
    import pandas as pd

    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    present = set(frame["symbol"].astype(str).unique())
    selected = [symbol for symbol in symbol_order if str(symbol) in present][: max(1, int(target_count))]
    if not selected:
        return frame.iloc[0:0].copy()
    limited = frame[frame["symbol"].astype(str).isin(selected)].copy()
    return limited.sort_values(["date", "symbol"]).reset_index(drop=True)


def _label_columns(frame) -> List[str]:
    if frame is None or frame.empty:
        return []
    prefixes = (
        "future_return_",
        "future_max_gain_",
        "future_max_drawdown_",
        "future_risk_adjusted_return_",
        "label_top20_",
        "label_bottom20_",
        "label_up_",
        "label_tp_before_sl_",
    )
    return [column for column in frame.columns if column.startswith(prefixes)]


def _write_training_sample_artifacts(run_dir: Path, frame) -> Dict[str, str]:
    import json

    run_dir.mkdir(parents=True, exist_ok=True)
    columns_path = run_dir / "training_sample_columns.json"
    preview_path = run_dir / "training_samples_labeled_preview.csv"
    sample_path = run_dir / "training_samples_labeled.parquet"
    fallback_path = run_dir / "training_samples_labeled.csv"
    columns_path.write_text(json.dumps(list(frame.columns), ensure_ascii=False, indent=2), encoding="utf-8")
    frame.head(1000).to_csv(preview_path, index=False)
    try:
        frame.to_parquet(sample_path, index=False)
        chosen_sample_path = sample_path
    except Exception:
        frame.to_csv(fallback_path, index=False)
        chosen_sample_path = fallback_path
    return {
        "columns_path": str(columns_path),
        "preview_csv_path": str(preview_path),
        "sample_path": str(chosen_sample_path),
    }


def _assign_split_labels(frame, split_plan: Dict[str, Any]):
    import pandas as pd

    if frame is None or frame.empty or not split_plan:
        return pd.DataFrame() if frame is None else frame
    local = frame.copy()
    local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local["symbol"] = local["symbol"].astype(str)
    date_text = local["date"].astype(str)
    symbol_text = local["symbol"].astype(str)
    training_dates = set(str(item) for item in split_plan.get("training_dates") or [])
    training_symbols = set(str(item) for item in split_plan.get("training_symbols") or [])
    final_dates = set(str(item) for item in ((split_plan.get("final_holdout") or {}).get("dates") or []))
    stock_symbols = set(str(item) for item in ((split_plan.get("stock_holdout") or {}).get("symbols") or []))
    embargo_dates = set(str(item) for item in ((split_plan.get("embargo") or {}).get("final_holdout_embargo_dates") or []))

    local["split"] = "unused_or_gap"
    local.loc[date_text.isin(training_dates) & symbol_text.isin(training_symbols), "split"] = "train"
    local.loc[date_text.isin(final_dates) & symbol_text.isin(training_symbols), "split"] = "final_holdout"
    local.loc[date_text.isin(training_dates) & symbol_text.isin(stock_symbols), "split"] = "stock_holdout"
    local.loc[date_text.isin(embargo_dates), "split"] = "embargo_gap"
    return local


def _apply_symbol_names(frame, sampled_symbols: List[Dict[str, Any]]):
    if frame is None or frame.empty:
        return frame
    local = frame.copy()
    name_map = {
        str(item.get("symbol")): str(item.get("name") or item.get("symbol"))
        for item in sampled_symbols
        if item.get("symbol")
    }
    if not name_map or "symbol" not in local.columns:
        return local
    local["symbol"] = local["symbol"].astype(str)
    local["name"] = local["symbol"].map(name_map).fillna(local.get("name", local["symbol"]))
    return local


def _excluded_features(cfg: Dict[str, Any]) -> List[str]:
    excluded = []
    if cfg.get("exclude_news_features"):
        excluded.extend(["news_total_score", "news_net_score"])
    if cfg.get("exclude_market_state_features"):
        excluded.extend(["market_state_score", "market_offensive", "market_defensive"])
    return excluded


def _training_report_markdown(cfg: Dict[str, Any], dataset_meta: Dict[str, Any], model_comparison: Dict[str, Any]) -> str:
    family = str(cfg.get("model_family") or "local_core_v1")
    version = "V2" if family.endswith("_v2") else "V1"
    return "\n".join(
        [
            f"# Local Core ML {version} Training Report",
            "",
            f"model_family: {cfg.get('model_family')}",
            f"target_valid_symbols: {cfg.get('target_valid_symbols')}",
            f"valid_symbol_count: {dataset_meta.get('valid_symbol_count')}",
            f"sample_count: {dataset_meta.get('sample_count')}",
            f"primary_label: {dataset_meta.get('primary_label')}",
            f"feature_count: {len(dataset_meta.get('feature_names') or [])}",
            f"best_model: {model_comparison.get('best_model')}",
            "production_enabled: False",
            "",
        ]
    )


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
