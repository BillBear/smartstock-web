"""Pre-feature certification for an immutable full-market training sample.

This module deliberately has no dependency on model selection, feature audits, or
candidate manifests.  Those are downstream research outputs and cannot certify
their own input sample.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_EMBARGO_SESSIONS = 20
DEFAULT_OUTER_FOLDS = 5
DEFAULT_STOCK_HOLDOUT_RATIO = 0.20
DEFAULT_SEALED_TEMPORAL_AUDIT_DATES = 60
MINIMUM_FIT_DATES = 120
MINIMUM_VALIDATION_DATES = 40
MINIMUM_TEST_DATES = 40
CERTIFICATION_COLUMNS = (
    "trade_date",
    "symbol",
    "industry_l1",
    "total_mv",
    "amount_cny",
    "eligible_for_training",
    "entry_tradeable",
    "alpha_relevance_grade_10d",
    "alpha_top10_10d",
    "alpha_target_10d",
    "market_median_net_return_10d",
    "net_return_after_cost_10d",
    "severe_negative_10d",
    "sl_before_tp_10d",
    "future_limit_down_count_10d",
)


def build_certified_split_plan(
    rows: pd.DataFrame,
    *,
    outer_folds: int = DEFAULT_OUTER_FOLDS,
    embargo_sessions: int = DEFAULT_EMBARGO_SESSIONS,
    stock_holdout_ratio: float = DEFAULT_STOCK_HOLDOUT_RATIO,
    seed: int = 20260718,
    sealed_temporal_audit_dates: int = DEFAULT_SEALED_TEMPORAL_AUDIT_DATES,
) -> dict[str, Any]:
    """Build reproducible nested development splits without opening future data.

    The latest labelable dates are sealed as a *development-time* temporal audit.
    They are not a formal future holdout and are never used for feature/model
    selection.  Each outer fold has chronological fit, validation, and test
    roles separated by the execution-label embargo.
    """
    frame = _normalise_rows(rows)
    dates = tuple(sorted(frame["trade_date"].unique()))
    if outer_folds != 5:
        raise ValueError("certified split plan requires exactly five outer folds")
    if embargo_sessions < 20:
        raise ValueError("certified split plan requires an embargo of at least 20 sessions")
    if not 0.0 < stock_holdout_ratio < 0.5:
        raise ValueError("stock_holdout_ratio must be in (0, 0.5)")
    if sealed_temporal_audit_dates < 60:
        raise ValueError("at least 60 sealed temporal audit dates are required")
    if len(dates) <= sealed_temporal_audit_dates:
        raise ValueError("no development dates remain after sealing temporal audit dates")

    development_dates = dates[:-sealed_temporal_audit_dates]
    temporal_audit_dates = dates[-sealed_temporal_audit_dates:]
    minimum_development_dates = (
        MINIMUM_FIT_DATES
        + MINIMUM_VALIDATION_DATES
        + MINIMUM_TEST_DATES
        + embargo_sessions * 2
    )
    if len(development_dates) < minimum_development_dates:
        raise ValueError(
            "insufficient development dates for one 120/40/40 outer fold with embargo: "
            f"need={minimum_development_dates} actual={len(development_dates)}"
        )

    development = frame.loc[frame["trade_date"].isin(development_dates)].copy()
    training_symbols, holdout_symbols, strata = _stratified_symbol_holdout(
        development,
        ratio=stock_holdout_ratio,
        seed=seed,
    )
    folds = _outer_folds(
        development_dates,
        training_symbols=training_symbols,
        outer_folds=outer_folds,
        embargo_sessions=embargo_sessions,
    )
    payload: dict[str, Any] = {
        "split_plan_version": "full_market_certified_v2",
        "signal_time": "after_close",
        "entry_time": "next_session_open",
        "label_horizon_sessions": 10,
        "outer_folds": folds,
        "embargo_sessions": int(embargo_sessions),
        "development_dates": list(development_dates),
        "sealed_temporal_audit_dates": list(temporal_audit_dates),
        "training_symbols": list(training_symbols),
        "stock_holdout_symbols": list(holdout_symbols),
        "stock_holdout_ratio_requested": float(stock_holdout_ratio),
        "stock_holdout_ratio_actual": len(holdout_symbols) / (len(training_symbols) + len(holdout_symbols)),
        "stock_holdout_strata": strata,
        "outer_test_windows_overlap": _outer_test_windows_overlap(folds),
        "outer_test_aggregation_policy": "fold_local_metrics_only",
        "outer_test_overlap_note": (
            "Two-year data can require overlapping outer test windows. "
            "Each fold remains temporally disjoint internally; aggregate OOF metrics "
            "must not pool duplicate trade_date + symbol predictions across folds."
        ),
        "evaluation_quadrants": {
            "A_development_seen": {"dates": list(development_dates), "symbols": list(training_symbols)},
            "C_development_unseen": {"dates": list(development_dates), "symbols": list(holdout_symbols)},
            "B_future_seen": {"status": "not_collected"},
            "D_future_unseen": {"status": "not_collected"},
        },
        "formal_future_holdout_status": "not_collected",
        "production_integration_allowed": False,
    }
    payload["sha256"] = _sha256_payload(payload)
    return payload


def certify_full_market_run(
    *,
    run_root: str | Path,
    asset_root: str | Path,
    code_commit: str,
) -> dict[str, Any]:
    """Register one full-build run as a pre-feature, research-only dataset.

    Certification intentionally refuses to inspect any feature-audit, model, OOF,
    or candidate output.  The dataset must be valid before those artifacts exist.
    The large parquet file is hard-linked into the immutable asset tree when
    possible, so preserving the certified data does not double local storage.
    """
    source = Path(run_root).expanduser().resolve()
    assets = Path(asset_root).expanduser().resolve()
    commit = _normalise_commit(code_commit)
    dataset_source = source / "artifacts" / "full-build" / "dataset.parquet"
    quality_source = source / "artifacts" / "full-build" / "quality_report.json"
    raw_manifest_source = source / "manifests" / "full-build.json"
    feature_source = source / "panel" / "stage=full-build" / "feature_contract.json"
    for path in (dataset_source, quality_source, raw_manifest_source, feature_source):
        if not path.is_file():
            raise FileNotFoundError(f"required full-build certification input is missing: {path}")

    quality = _load_json(quality_source)
    if quality.get("ready") is not True:
        raise ValueError("full-build quality report is not ready")
    rows = load_certification_dataset(dataset_source)
    _validate_dataset_rows(rows, quality)
    feature_contract = _load_json(feature_source)
    feature_schema = _validate_pre_feature_schema(feature_contract)
    label_report = _build_label_report(rows)
    split_plan = build_certified_split_plan(rows)
    raw_manifest_sha = _sha256_file(raw_manifest_source)
    dataset_sha = _sha256_file(dataset_source)
    quality_sha = _sha256_file(quality_source)
    feature_schema_sha = _sha256_payload(feature_schema)
    label_schema = _label_schema()
    label_schema_sha = _sha256_payload(label_schema)
    split_sha = str(split_plan["sha256"])
    dataset_id = "fm2_" + _sha256_payload(
        {
            "raw_manifest_sha256": raw_manifest_sha,
            "dataset_sha256": dataset_sha,
            "quality_sha256": quality_sha,
            "feature_schema_sha256": feature_schema_sha,
            "label_schema_sha256": label_schema_sha,
            "split_sha256": split_sha,
            "code_commit": commit,
        }
    )[:20]
    destination = assets / "datasets" / dataset_id
    registry_path = destination / "dataset_registry_v2.json"
    if registry_path.is_file():
        existing = _load_json(registry_path)
        if existing.get("dataset_id") != dataset_id or existing.get("source_hashes", {}).get("dataset") != dataset_sha:
            raise ValueError(f"existing certified dataset does not match source: {destination}")
        return _result_from_existing(existing, destination)
    if destination.exists():
        raise FileExistsError(f"dataset destination already exists without registry: {destination}")

    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"incomplete certification destination exists: {temporary}")
    try:
        dataset_destination = temporary / "artifacts" / "full-build" / "dataset.parquet"
        dataset_destination.parent.mkdir(parents=True, exist_ok=False)
        _link_or_copy(dataset_source, dataset_destination)
        _copy_verified(quality_source, temporary / "artifacts" / "full-build" / "quality_report.json")
        _copy_verified(raw_manifest_source, temporary / "manifests" / "full-build.json")
        _copy_verified(feature_source, temporary / "panel" / "stage=full-build" / "feature_contract.json")
        _write_json(temporary / "artifacts" / "full-build" / "label_report_v2.json", label_report)
        _write_json(temporary / "artifacts" / "full-build" / "split_plan_v2.json", split_plan)
        _write_json(temporary / "artifacts" / "full-build" / "label_schema_v2.json", label_schema)
        source_hashes = {
            "dataset": dataset_sha,
            "quality_report": quality_sha,
            "raw_manifest": raw_manifest_sha,
            "feature_contract": _sha256_file(feature_source),
            "label_schema": label_schema_sha,
            "split_plan": split_sha,
        }
        registry: dict[str, Any] = {
            "dataset_registry_version": "full_market_v2",
            "dataset_id": dataset_id,
            "certification_status": "certified_research_sample",
            "production_integration_allowed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "code_commit": commit,
            "source_run_id": source.name,
            "required_inputs": ["raw_manifest", "dataset", "quality_report", "feature_contract", "label_schema", "split_plan"],
            "source_hashes": source_hashes,
            "row_count": int(len(rows)),
            "symbol_count": int(rows["symbol"].nunique()),
            "trade_date_count": int(rows["trade_date"].nunique()),
            "feature_schema_sha256": feature_schema_sha,
            "label_schema_sha256": label_schema_sha,
            "split_sha256": split_sha,
            "formal_future_holdout_status": "not_collected",
            "model_status": "research_only",
        }
        registry["sha256"] = _sha256_payload(registry)
        _write_json(temporary / "dataset_registry_v2.json", registry)
        sample_contract = {
            "sample_contract_version": "full_market_pre_feature_v2",
            "dataset_id": dataset_id,
            "dataset_registry_sha256": registry["sha256"],
            "label_definition": label_schema,
            "split_plan_sha256": split_sha,
            "security_and_tradability": {
                "signal_time": "after_close",
                "entry_time": "next_session_open",
                "entry_tradeable_required": True,
                "limit_up_entry_rejected": True,
                "suspension_rejected": True,
            },
            "production_integration_allowed": False,
        }
        sample_contract["sha256"] = _sha256_payload(sample_contract)
        _write_json(temporary / "sample_contract_v2.json", sample_contract)
        os.replace(temporary, destination)
    except Exception:
        # Leave incomplete data intact for forensic inspection; never replace a
        # completed immutable dataset after a failed certification attempt.
        raise
    return {
        "dataset_id": dataset_id,
        "status": "certified_research_sample",
        "production_integration_allowed": False,
        "dataset_path": str(destination / "artifacts" / "full-build" / "dataset.parquet"),
        "registry_path": str(registry_path),
        "sample_contract_path": str(destination / "sample_contract_v2.json"),
        "split_plan": split_plan,
    }


def _normalise_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    required = {"trade_date", "symbol", "industry_l1", "total_mv", "amount_cny", "eligible_for_training"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("rows missing required certification columns: " + ", ".join(missing))
    frame = rows.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["symbol"] = frame["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    frame["industry_l1"] = frame["industry_l1"].astype("string").fillna("UNKNOWN")
    frame["total_mv"] = pd.to_numeric(frame["total_mv"], errors="coerce")
    frame["amount_cny"] = pd.to_numeric(frame["amount_cny"], errors="coerce")
    frame = frame.loc[frame["eligible_for_training"].eq(True)].copy()
    frame = frame.dropna(subset=["trade_date", "total_mv", "amount_cny"])
    frame = frame.loc[frame["symbol"].ne("") & frame["total_mv"].ge(0) & frame["amount_cny"].ge(0)]
    duplicate_count = int(frame.duplicated(["trade_date", "symbol"]).sum())
    if duplicate_count:
        raise ValueError(f"eligible sample has duplicate trade_date + symbol rows: {duplicate_count}")
    if frame.empty:
        raise ValueError("eligible sample is empty")
    return frame.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def load_certification_dataset(path: str | Path) -> pd.DataFrame:
    """Load only immutable sample, label, and split columns from the feature matrix."""
    return pd.read_parquet(Path(path), columns=list(CERTIFICATION_COLUMNS))


def _stratified_symbol_holdout(
    development: pd.DataFrame,
    *,
    ratio: float,
    seed: int,
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, dict[str, int]]]:
    summary = development.groupby("symbol", sort=True).agg(
        industry_l1=("industry_l1", "first"),
        median_total_mv=("total_mv", "median"),
        median_amount_cny=("amount_cny", "median"),
    )
    if len(summary) < 5:
        raise ValueError("at least five symbols are required for stock holdout")
    summary["board"] = summary.index.to_series().map(_board)
    summary["size_bucket"] = _tertiles(summary["median_total_mv"])
    summary["liquidity_bucket"] = _tertiles(summary["median_amount_cny"])
    summary["stratum"] = summary.apply(
        lambda row: f"{row['board']}|{row['industry_l1']}|size={row['size_bucket']}|liquidity={row['liquidity_bucket']}",
        axis=1,
    )
    counts = summary["stratum"].value_counts().to_dict()
    summary["selected_stratum"] = summary.apply(
        lambda row: row["stratum"]
        if counts[row["stratum"]] >= 5
        else f"{row['board']}|size={row['size_bucket']}|liquidity={row['liquidity_bucket']}",
        axis=1,
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for symbol, row in summary.iterrows():
        grouped[str(row["selected_stratum"])].append(str(symbol))
    for symbols in grouped.values():
        symbols.sort()
    target = min(len(summary) - 1, max(1, round(len(summary) * ratio)))
    quotas = {stratum: int(len(symbols) * ratio) for stratum, symbols in grouped.items()}
    remaining = target - sum(quotas.values())
    remainders = sorted(
        ((len(symbols) * ratio - quotas[stratum], stratum) for stratum, symbols in grouped.items()),
        key=lambda value: (-value[0], value[1]),
    )
    for _, stratum in remainders[:remaining]:
        quotas[stratum] += 1
    generator = random.Random(seed)
    holdout = []
    for stratum, symbols in sorted(grouped.items()):
        holdout.extend(generator.sample(symbols, quotas[stratum]))
    holdout_symbols = tuple(sorted(holdout))
    holdout_set = set(holdout_symbols)
    training_symbols = tuple(symbol for symbol in sorted(summary.index.astype(str)) if symbol not in holdout_set)
    evidence = {
        stratum: {"population": len(grouped[stratum]), "holdout": quotas[stratum]}
        for stratum in sorted(grouped)
    }
    return training_symbols, holdout_symbols, evidence


def _outer_folds(
    development_dates: Sequence[str],
    *,
    training_symbols: Sequence[str],
    outer_folds: int,
    embargo_sessions: int,
) -> list[dict[str, Any]]:
    test_block = MINIMUM_TEST_DATES
    earliest_test_start = (
        MINIMUM_FIT_DATES + MINIMUM_VALIDATION_DATES + embargo_sessions * 2
    )
    latest_test_start = len(development_dates) - test_block
    if latest_test_start < earliest_test_start:
        raise ValueError("insufficient development dates for registered outer roles")
    starts = _outer_test_starts(earliest_test_start, latest_test_start, outer_folds)
    folds: list[dict[str, Any]] = []
    for fold_index, test_start in enumerate(starts):
        test_end = test_start + test_block
        validation_end = test_start - embargo_sessions
        validation_start = validation_end - MINIMUM_VALIDATION_DATES
        fit_end = validation_start - embargo_sessions
        if fit_end < MINIMUM_FIT_DATES:
            raise ValueError("insufficient development dates for registered outer roles")
        fit_dates = tuple(development_dates[:fit_end])
        validation_dates = tuple(development_dates[validation_start:validation_end])
        test_dates = tuple(development_dates[test_start:test_end])
        if len(validation_dates) != MINIMUM_VALIDATION_DATES or len(test_dates) != MINIMUM_TEST_DATES:
            raise ValueError("outer fold date roles do not meet registered minimums")
        folds.append(
            {
                "fold": fold_index + 1,
                "fit_dates": list(fit_dates),
                "validation_dates": list(validation_dates),
                "test_dates": list(test_dates),
                "training_symbols": list(training_symbols),
                "fit_to_validation_embargo_sessions": int(embargo_sessions),
                "validation_to_test_embargo_sessions": int(embargo_sessions),
                "fit_start": fit_dates[0],
                "fit_end": fit_dates[-1],
                "validation_start": validation_dates[0],
                "validation_end": validation_dates[-1],
                "test_start": test_dates[0],
                "test_end": test_dates[-1],
            }
        )
    return folds


def _outer_test_starts(first: int, last: int, fold_count: int) -> tuple[int, ...]:
    if fold_count == 1:
        return (last,)
    span = last - first
    return tuple(first + round(index * span / (fold_count - 1)) for index in range(fold_count))


def _outer_test_windows_overlap(folds: Sequence[dict[str, Any]]) -> bool:
    seen: set[str] = set()
    for fold in folds:
        dates = {str(value) for value in fold["test_dates"]}
        if seen & dates:
            return True
        seen.update(dates)
    return False


def _tertiles(values: pd.Series) -> pd.Series:
    ranked = sorted((float(value), str(symbol)) for symbol, value in values.items())
    count = len(ranked)
    buckets = {symbol: min(2, index * 3 // count) for index, (_, symbol) in enumerate(ranked)}
    return pd.Series(buckets).reindex(values.index).astype("int64")


def _board(symbol: str) -> str:
    if symbol.startswith(("300", "301")):
        return "CHINEXT"
    if symbol.startswith(("688", "689")):
        return "STAR"
    return "MAIN"


def _sha256_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_dataset_rows(rows: pd.DataFrame, quality: dict[str, Any]) -> None:
    required = {
        "trade_date",
        "symbol",
        "eligible_for_training",
        "entry_tradeable",
        "alpha_relevance_grade_10d",
        "alpha_top10_10d",
        "alpha_target_10d",
        "market_median_net_return_10d",
        "net_return_after_cost_10d",
        "severe_negative_10d",
        "sl_before_tp_10d",
        "future_limit_down_count_10d",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("full-build dataset missing required label/sample columns: " + ", ".join(missing))
    if int(quality.get("row_count", -1)) != len(rows):
        raise ValueError("quality report row_count does not match dataset")
    duplicate_count = int(rows.duplicated(["trade_date", "symbol"]).sum())
    if duplicate_count or int(quality.get("duplicate_key_count", 0) or 0):
        raise ValueError("full-build dataset has duplicate trade_date + symbol rows")
    eligible = rows.loc[rows["eligible_for_training"].eq(True)]
    if eligible.empty:
        raise ValueError("full-build dataset has no eligible training rows")
    if eligible["entry_tradeable"].ne(True).any():
        raise ValueError("eligible training rows include next-session non-tradeable entries")


def _validate_pre_feature_schema(feature_contract: dict[str, Any]) -> dict[str, Any]:
    columns = feature_contract.get("allowed_feature_columns")
    if not isinstance(columns, list) or not columns or not all(isinstance(item, str) and item for item in columns):
        raise ValueError("feature contract has no allowed_feature_columns")
    prohibited = [
        column
        for column in columns
        if any(token in column.lower() for token in ("future_", "label_", "alpha_target", "tp_before", "sl_before", "mfe_", "mae_"))
    ]
    if prohibited:
        raise ValueError("future or outcome fields are declared as features: " + ", ".join(sorted(prohibited)))
    return {"allowed_feature_columns": sorted(set(columns))}


def _build_label_report(rows: pd.DataFrame) -> dict[str, Any]:
    frame = rows.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    eligible = frame.loc[frame["eligible_for_training"].eq(True)].copy()
    daily = []
    for trade_date, group in eligible.groupby("trade_date", sort=True):
        top10_rate = float(group["alpha_top10_10d"].eq(True).mean())
        market = pd.to_numeric(group["market_median_net_return_10d"], errors="coerce").dropna()
        daily.append(
            {
                "trade_date": str(trade_date),
                "eligible_count": int(len(group)),
                "alpha_top10_prevalence": top10_rate,
                "market_median_net_return_10d": float(market.iloc[0]) if not market.empty else None,
                "severe_negative_rate": float(group["severe_negative_10d"].eq(True).mean()),
            }
        )
    if len(daily) < 60:
        raise ValueError("fewer than 60 labelable trade dates are available")
    report = pd.DataFrame(daily)
    failures = []
    low_coverage = report.loc[report["eligible_count"].lt(1000), "trade_date"].tolist()
    if low_coverage:
        failures.append("eligible_cross_section_below_1000")
    unstable = report.loc[
        ~report["alpha_top10_prevalence"].between(0.08, 0.105, inclusive="both"), "trade_date"
    ].tolist()
    if unstable:
        failures.append("alpha_top10_prevalence_outside_8_to_10_5pct")
    prevalence_std = float(report["alpha_top10_prevalence"].std(ddof=0))
    market_std = float(report["market_median_net_return_10d"].std(ddof=0))
    if prevalence_std <= 1e-12:
        correlation_value = 0.0
    elif market_std <= 1e-12:
        correlation_value = 0.0
    else:
        correlation_value = float(report["alpha_top10_prevalence"].corr(report["market_median_net_return_10d"]))
    if prevalence_std > 0.01:
        failures.append("alpha_top10_prevalence_std_exceeds_0_01")
    if pd.isna(correlation_value) or abs(correlation_value) >= 0.10:
        failures.append("alpha_top10_market_return_correlation_at_least_0_10")
    if failures:
        raise ValueError("label certification failed: " + ", ".join(sorted(set(failures))) )
    return {
        "label_report_version": "alpha_risk_10d_v2",
        "labelable_trade_date_count": len(daily),
        "eligible_row_count": int(len(eligible)),
        "alpha_top10_prevalence_std": prevalence_std,
        "alpha_top10_market_return_correlation": correlation_value,
        "daily": daily,
    }


def _label_schema() -> dict[str, Any]:
    return {
        "primary_ranking_target": "alpha_relevance_grade_10d",
        "primary_positive": "alpha_top10_10d",
        "continuous_target": "alpha_target_10d",
        "target_reference": "all eligible full-market rows on the same signal date; industry reference falls back to market below peer minimum",
        "risk_targets": ["severe_negative_10d", "sl_before_tp_10d", "future_limit_down_count_10d"],
        "execution": {"signal_time": "after_close", "entry_time": "next_session_open", "horizon_sessions": 10, "commission_per_side": 0.0003, "slippage_per_side": 0.001},
        "alpha_and_path_risk_are_separate": True,
    }


def _normalise_commit(value: str) -> str:
    commit = str(value).strip().lower()
    if len(commit) < 7 or len(commit) > 64 or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("code_commit must be a git SHA")
    return commit


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _copy_verified(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if _sha256_file(source) != _sha256_file(destination):
        raise ValueError(f"copied certification input failed checksum validation: {source}")


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        _copy_verified(source, destination)
        return
    if _sha256_file(source) != _sha256_file(destination):
        raise ValueError("hard-linked certification dataset failed checksum validation")


def _result_from_existing(registry: dict[str, Any], destination: Path) -> dict[str, Any]:
    split_path = destination / "artifacts" / "full-build" / "split_plan_v2.json"
    return {
        "dataset_id": str(registry["dataset_id"]),
        "status": str(registry["certification_status"]),
        "production_integration_allowed": bool(registry["production_integration_allowed"]),
        "dataset_path": str(destination / "artifacts" / "full-build" / "dataset.parquet"),
        "registry_path": str(destination / "dataset_registry_v2.json"),
        "sample_contract_path": str(destination / "sample_contract_v2.json"),
        "split_plan": _load_json(split_path),
    }
