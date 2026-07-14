"""Identical-universe controlled evaluation for fixed ranking baselines."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .evaluator import (
    evaluate_ranking,
    simulate_daily_mark_to_market_portfolio,
    validate_identical_comparison_rows,
)
from .research_contract import RankingResearchContract


_KEYS = ["trade_date", "symbol", "fold", "quadrant"]
_SOURCE_COLUMNS = (
    "trade_date",
    "symbol",
    "adjusted_open",
    "adjusted_close",
    "is_suspended",
    "at_up_limit_open",
    "mfe_10d",
    "future_limit_up_count_10d",
    "future_limit_down_count_10d",
    "tp_before_sl_10d",
    "sl_before_tp_10d",
    "total_mv",
)


def run_controlled_evaluation_stage(
    contract: RankingResearchContract,
    run_root: Path,
    asset_root: Path,
) -> dict[str, Any]:
    """Compare every fixed baseline before and after one frozen risk mask."""
    baseline = pd.read_parquet(
        run_root / "artifacts" / "baseline-oof" / "baseline_predictions.parquet"
    )
    risk = pd.read_parquet(
        run_root / "artifacts" / "risk-oof" / "risk_predictions.parquet"
    )
    baseline = _normalise_keys(baseline)
    risk = _normalise_keys(risk)
    _require_identical_oof_rows(baseline, risk)
    risk_columns = risk[_KEYS + ["risk_probability", "risk_eligible"]]
    rows = baseline.merge(risk_columns, on=_KEYS, how="left", validate="one_to_one")
    if rows["risk_eligible"].isna().any():
        raise ValueError("controlled evaluation risk mask is incomplete")

    source = _load_source_panel(contract, asset_root)
    enrichment_columns = [
        column
        for column in _SOURCE_COLUMNS
        if column not in {"adjusted_open", "adjusted_close", "is_suspended", "at_up_limit_open"}
        and column not in rows.columns
    ]
    if enrichment_columns:
        outcomes = source[["trade_date", "symbol", *enrichment_columns]].drop_duplicates(
            ["trade_date", "symbol"], keep="last"
        )
        rows = rows.merge(outcomes, on=["trade_date", "symbol"], how="left", validate="many_to_one")
    rows["market_median_net_return_10d"] = rows.groupby("trade_date", sort=False)[
        "net_return_after_cost_10d"
    ].transform("median")
    rows["industry_median_net_return_10d"] = rows.groupby(
        ["trade_date", "industry_l1"], sort=False, dropna=False
    )["net_return_after_cost_10d"].transform("median")
    rows["label_severe_negative_10d"] = rows["severe_negative_10d"].astype(bool)

    score_columns = {
        name: f"score__{name}" for name in contract.required_baselines
    }
    missing_scores = sorted(set(score_columns.values()) - set(rows.columns))
    if missing_scores:
        raise ValueError("controlled evaluation missing baseline scores: " + ", ".join(missing_scores))
    validate_identical_comparison_rows(
        {
            name: rows[["trade_date", "symbol", "risk_eligible", score]].rename(
                columns={score: "score"}
            )
            for name, score in score_columns.items()
        }
    )

    comparisons: dict[str, dict[str, Any]] = {}
    portfolios: dict[str, dict[str, Any]] = {}
    equity_frames: list[pd.DataFrame] = []
    for quadrant, quadrant_rows in rows.groupby("quadrant", sort=True):
        quadrant_name = str(quadrant)
        comparisons[quadrant_name] = {}
        portfolios[quadrant_name] = {}
        for name, score_col in score_columns.items():
            raw = quadrant_rows
            gated = quadrant_rows.loc[quadrant_rows["risk_eligible"].eq(True)]
            comparisons[quadrant_name][name] = {
                "raw": _ranking_metrics(raw, score_col),
                "same_risk_gated": _ranking_metrics(gated, score_col),
                "raw_row_count": int(len(raw)),
                "same_risk_gated_row_count": int(len(gated)),
            }
            portfolios[quadrant_name][name] = {}
            for gate_name, eligible_col in (("raw", None), ("same_risk_gated", "risk_eligible")):
                signals = raw
                selected_symbols = _selected_symbols(signals, score_col, eligible_col)
                price_panel = source.loc[source["symbol"].isin(selected_symbols), [
                    "trade_date", "symbol", "adjusted_open", "adjusted_close",
                    "is_suspended", "at_up_limit_open",
                ]]
                portfolio = simulate_daily_mark_to_market_portfolio(
                    signals,
                    price_panel,
                    score_col=score_col,
                    eligible_col=eligible_col,
                    top_k=5,
                    hold_sessions=contract.horizon,
                    commission=contract.commission_per_side,
                    slippage=contract.slippage_per_side,
                )
                equity = pd.DataFrame(portfolio.pop("equity_curve"))
                if not equity.empty:
                    equity["quadrant"] = quadrant_name
                    equity["comparator"] = name
                    equity["gate"] = gate_name
                    equity_frames.append(equity)
                portfolios[quadrant_name][name][gate_name] = portfolio

    strongest = _strongest_baseline(comparisons.get("A", {}))
    diagnostic_slices = (
        _diagnostic_slices(rows.loc[rows["quadrant"].eq("A")], score_columns[strongest])
        if strongest
        else {}
    )
    artifact_root = run_root / "artifacts" / "controlled-evaluation"
    artifact_root.mkdir(parents=True, exist_ok=True)
    report_path = artifact_root / "controlled_report.json"
    equity_path = artifact_root / "equity_curves.parquet"
    equity_rows = pd.concat(equity_frames, ignore_index=True) if equity_frames else pd.DataFrame()
    equity_rows.to_parquet(equity_path, compression="zstd", index=False)
    report = {
        "contract_sha256": contract.sha256(),
        "comparison_key_sha256": _key_sha256(rows),
        "row_count": int(len(rows)),
        "risk_keep_rate": float(rows["risk_eligible"].mean()),
        "execution": {
            "signal_timing": contract.signal_timing,
            "horizon": contract.horizon,
            "commission_per_side": contract.commission_per_side,
            "slippage_per_side": contract.slippage_per_side,
            "daily_cohort_fraction": 0.10,
            "per_stock_cap": 0.02,
            "maximum_gross_exposure": 1.0,
        },
        "alpha_model_available": False,
        "alpha_model_unavailable_reason": "nested ablation accepted no alpha feature block",
        "comparisons": comparisons,
        "portfolios": portfolios,
        "strongest_fixed_baseline_by_a_ndcg": strongest,
        "diagnostic_slices_for_strongest_baseline": diagnostic_slices,
    }
    _write_json(report_path, report)
    return {
        "controlled_report": str(report_path),
        "equity_curves": str(equity_path),
        "_status": {"research_design_valid": True, "model_gate_passed": False},
    }


def _normalise_keys(rows: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(_KEYS) - set(rows.columns))
    if missing:
        raise ValueError("OOF predictions missing keys: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    if result.duplicated(_KEYS).any():
        raise ValueError("OOF predictions contain duplicate comparison keys")
    return result


def _require_identical_oof_rows(baseline: pd.DataFrame, risk: pd.DataFrame) -> None:
    left = baseline[_KEYS].sort_values(_KEYS, kind="stable").reset_index(drop=True)
    right = risk[_KEYS].sort_values(_KEYS, kind="stable").reset_index(drop=True)
    if not left.equals(right):
        raise ValueError("baseline and risk predictions must use identical OOF rows")


def _load_source_panel(contract: RankingResearchContract, asset_root: Path) -> pd.DataFrame:
    build_root = asset_root / "datasets" / contract.dataset_id / "artifacts" / "full-build"
    dataset_roots = sorted(path for path in build_root.glob("dataset-*") if path.is_dir())
    if len(dataset_roots) != 1:
        raise FileNotFoundError(
            f"expected exactly one immutable source dataset below {build_root}, found {len(dataset_roots)}"
        )
    frames = []
    for path in sorted(dataset_roots[0].glob("shard=*/data.parquet")):
        schema_names = set(pq.read_schema(path).names)
        missing = sorted(set(_SOURCE_COLUMNS) - schema_names)
        if missing:
            raise ValueError(f"source panel shard missing controlled-evaluation columns: {path}: {', '.join(missing)}")
        frames.append(pq.read_table(path, columns=list(_SOURCE_COLUMNS)).to_pandas())
    if not frames:
        raise FileNotFoundError(f"source panel has no immutable shards: {dataset_roots[0]}")
    source = pd.concat(frames, ignore_index=True)
    source["trade_date"] = pd.to_datetime(source["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    source["symbol"] = source["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    if source.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("source panel contains duplicate trade_date and symbol rows")
    return source


def _ranking_metrics(rows: pd.DataFrame, score_col: str) -> dict[str, Any]:
    return evaluate_ranking(
        rows,
        score_col=score_col,
        grade_col="alpha_relevance_grade_10d",
        strong_col="alpha_top10_10d",
    )


def _selected_symbols(rows: pd.DataFrame, score_col: str, eligible_col: str | None) -> set[str]:
    current = rows if eligible_col is None else rows.loc[rows[eligible_col].eq(True)]
    selected = (
        current.sort_values(["trade_date", score_col, "symbol"], ascending=[True, False, True], kind="stable")
        .groupby("trade_date", sort=False)
        .head(5)
    )
    return set(selected["symbol"].astype(str))


def _strongest_baseline(comparisons: dict[str, Any]) -> str | None:
    if not comparisons:
        return None
    return max(comparisons, key=lambda name: comparisons[name]["raw"]["ndcg_at_10"])


def _diagnostic_slices(rows: pd.DataFrame, score_col: str) -> dict[str, Any]:
    working = rows.copy()
    if "total_mv" in working and working["total_mv"].notna().sum() >= 4:
        working["size_bucket"] = pd.qcut(
            pd.to_numeric(working["total_mv"], errors="coerce"), 4, duplicates="drop"
        ).astype("string")
    if "amount_log" in working and working["amount_log"].notna().sum() >= 4:
        working["liquidity_bucket"] = pd.qcut(
            pd.to_numeric(working["amount_log"], errors="coerce"), 4, duplicates="drop"
        ).astype("string")
    output: dict[str, Any] = {}
    for column in ("fold", "market_state", "industry_l1", "size_bucket", "liquidity_bucket"):
        if column not in working:
            continue
        values = working[column].value_counts(dropna=False).head(20).index
        output[column] = {
            str(value): _ranking_metrics(group, score_col)
            for value in values
            for group in [working.loc[working[column].eq(value)]]
            if group["trade_date"].nunique() >= 2
        }
    return output


def _key_sha256(rows: pd.DataFrame) -> str:
    ordered = rows[_KEYS + ["risk_eligible"]].sort_values(_KEYS, kind="stable")
    payload = ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
