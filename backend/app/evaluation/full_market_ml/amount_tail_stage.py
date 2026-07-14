"""Artifact-producing stage for the registered trading-amount tail audit."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow.parquet as pq

from .amount_tail_audit import (
    REGISTERED_CANDIDATE,
    build_amount_tail_scores,
    build_daily_metric_frame,
    build_quantile_curve,
    evaluate_amount_tail_gate,
    industry_topk_concentration,
    simulate_equal_exposure_lot_portfolio,
)


_KEYS = ["trade_date", "symbol"]
_MATRIX_COLUMNS = [
    "trade_date",
    "symbol",
    "amount_cny",
    "amount_ratio_5d",
    "amount_ratio_20d",
    "turnover_rate",
    "turnover_ratio_20d",
    "total_mv",
    "size_bucket",
    "liquidity_bucket",
]
_SOURCE_COLUMNS = [
    "trade_date",
    "symbol",
    "circ_mv",
    "adjusted_open",
    "adjusted_close",
    "median_amount_20d",
    "is_suspended",
    "at_up_limit_open",
    "entry_tradeable_10d",
    "horizon_available_10d",
    "path_ambiguous_10d",
]
_DIAGNOSTIC_SCORES = (
    "score__amount_raw",
    "score__amount_ratio_5d",
    "score__amount_ratio_20d",
    "score__turnover_rate",
    "score__turnover_ratio_20d",
    "score__amount_to_float_mv",
    "score__industry_amount_rank",
    "score__neutral_amount_tail",
    "score__neutral_amount_tail_diversified",
)
_PORTFOLIO_SCORES = (
    "score__neutral_amount_tail_diversified",
    "score__amount_raw",
    "score__adjusted_return_20d",
    "score__adjusted_return_60d",
    "score__random",
)


def run_amount_tail_signal_audit(
    config_path: str | Path,
    source_run_root: str | Path,
    asset_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Run one immutable development-only amount-tail audit."""
    config_path = Path(config_path).resolve()
    source_run_root = Path(source_run_root).resolve()
    asset_root = Path(asset_root).resolve()
    output_root = Path(output_root).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"amount-tail output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    started_at = _now()
    _write_progress(output_root, "loading", "running", started_at=started_at)
    try:
        source_contract = _load_source_contract(source_run_root)
        _validate_source_identity(config, source_contract)
        baseline_path = source_run_root / "artifacts/baseline-oof/baseline_predictions.parquet"
        baseline = pd.read_parquet(baseline_path)
        baseline = _normalise_unique_keys(baseline, [*_KEYS, "fold", "quadrant"], "baseline predictions")

        matrix, matrix_inputs = _load_feature_matrix(source_run_root)
        signal_source, price_panel, dataset_inputs = _load_source_panel(config, asset_root)
        _write_progress(output_root, "joining", "running", started_at=started_at)
        rows = baseline.merge(matrix, on=_KEYS, how="left", validate="one_to_one")
        rows = rows.merge(signal_source, on=_KEYS, how="left", validate="many_to_one")
        _validate_join(rows, baseline)
        rows = build_amount_tail_scores(
            rows,
            top_k=int(config["comparison"]["top_k"]),
            industry_max_share=float(config["comparison"]["industry_top5_max_share"]),
        )
        _copy_fixed_baselines(rows)

        score_columns = (*_DIAGNOSTIC_SCORES, "score__adjusted_return_20d", "score__adjusted_return_60d", "score__random")
        _write_progress(output_root, "ranking-diagnostics", "running", started_at=started_at)
        quantiles = build_quantile_curve(
            rows,
            _DIAGNOSTIC_SCORES,
            quantile_count=int(config["comparison"]["quantile_count"]),
        )
        daily_metrics = build_daily_metric_frame(rows, score_columns)
        fold_metrics = _aggregate_metrics(daily_metrics, ["quadrant", "fold", "score"])
        state_metrics = _aggregate_metrics(daily_metrics, ["quadrant", "market_state", "score"])
        concentration = industry_topk_concentration(
            rows,
            score_columns,
            top_k=int(config["comparison"]["top_k"]),
        )
        exposure = _selection_exposure(rows, score_columns, top_k=int(config["comparison"]["top_k"]))

        _write_progress(output_root, "equal-exposure-portfolios", "running", started_at=started_at)
        comparable_dates = _common_tradeable_dates(
            rows,
            _PORTFOLIO_SCORES,
            top_k=int(config["comparison"]["top_k"]),
        )
        portfolios, curves = _run_portfolios(
            rows,
            price_panel,
            comparable_dates,
            config,
        )
        decision = evaluate_amount_tail_gate(
            daily_metrics,
            industry_concentration=concentration,
            portfolios=portfolios,
            bootstrap_iterations=int(config["bootstrap"]["iterations"]),
        )

        _write_progress(output_root, "writing", "running", started_at=started_at)
        score_output_columns = [
            "trade_date",
            "symbol",
            "fold",
            "quadrant",
            "industry_l1",
            "market_state",
            "size_bucket",
            "liquidity_bucket",
            "alpha_relevance_grade_10d",
            "alpha_top10_10d",
            "net_return_after_cost_10d",
            "severe_negative_10d",
            "mae_10d",
            *_DIAGNOSTIC_SCORES,
            "score__adjusted_return_20d",
            "score__adjusted_return_60d",
            "score__random",
        ]
        rows[score_output_columns].to_parquet(
            output_root / "score_rows.parquet", compression="zstd", index=False
        )
        quantiles.to_csv(output_root / "quantile_curves.csv", index=False)
        daily_metrics.to_csv(output_root / "daily_metrics.csv", index=False)
        fold_metrics.to_csv(output_root / "fold_metrics.csv", index=False)
        state_metrics.to_csv(output_root / "market_state_metrics.csv", index=False)
        exposure.to_csv(output_root / "selection_exposure.csv", index=False)
        curves.to_parquet(output_root / "equity_curves.parquet", compression="zstd", index=False)
        _write_json(output_root / "industry_concentration.json", concentration)
        _write_json(output_root / "portfolio_metrics.json", portfolios)
        _write_json(
            output_root / "common_comparison_dates.json",
            {quadrant: sorted(dates) for quadrant, dates in comparable_dates.items()},
        )
        _write_json(output_root / "decision.json", decision)
        (output_root / "report.md").write_text(
            _render_report(config, rows, daily_metrics, concentration, portfolios, decision),
            encoding="utf-8",
        )
        result = {
            "run_id": config["run"]["id"],
            "dataset_id": config["run"]["dataset_id"],
            "source_run_id": config["run"]["source_run_id"],
            "row_count": int(len(rows)),
            "date_count": int(rows["trade_date"].nunique()),
            "symbol_count": int(rows["symbol"].nunique()),
            "quadrants": sorted(rows["quadrant"].astype(str).unique()),
            "decision": decision,
        }
        manifest = {
            **result,
            "source_row_count": int(len(baseline)),
            "created_at": _now(),
            "config_sha256": _sha256(config_path),
            "source_inputs": [
                {"path": str(baseline_path), "sha256": _sha256(baseline_path)},
                *matrix_inputs,
                *dataset_inputs,
            ],
            "artifacts": _artifact_manifest(output_root),
            "storage": {
                "large_tables": "parquet-zstd",
                "raw_panel_duplicated": False,
                "local_only": True,
            },
        }
        _write_json(output_root / "run_manifest.json", manifest)
        _write_progress(
            output_root,
            "complete",
            "complete",
            started_at=started_at,
            decision_status=decision["status"],
        )
        return result
    except BaseException as error:
        _write_progress(
            output_root,
            "failed",
            "failed",
            started_at=started_at,
            failure={"type": type(error).__name__, "message": str(error)},
        )
        raise


def _validate_config(config: dict[str, Any]) -> None:
    if int(config.get("schema_version", 0)) != 1:
        raise ValueError("amount-tail config schema_version must be 1")
    required_run = {"id", "source_run_id", "dataset_id", "production_integration_allowed"}
    missing = sorted(required_run - set(config.get("run", {})))
    if missing:
        raise ValueError("amount-tail config missing run fields: " + ", ".join(missing))
    if config["run"]["production_integration_allowed"] is not False:
        raise PermissionError("amount-tail development audit cannot allow production integration")
    for section in ("comparison", "bootstrap", "execution"):
        if section not in config:
            raise ValueError(f"amount-tail config missing section: {section}")


def _load_source_contract(source_run_root: Path) -> dict[str, Any]:
    path = source_run_root / "artifacts/research_contract.json"
    if not path.is_file():
        raise FileNotFoundError(f"source research contract is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_source_identity(config: dict[str, Any], source: dict[str, Any]) -> None:
    expected_run = str(config["run"]["source_run_id"])
    expected_dataset = str(config["run"]["dataset_id"])
    contract = source.get("contract", source)
    if not isinstance(contract, dict):
        raise ValueError("source research contract payload must be an object")
    actual_run = str(contract.get("run_id") or contract.get("run", {}).get("id") or "")
    actual_dataset = str(
        contract.get("dataset_id") or contract.get("run", {}).get("dataset_id") or ""
    )
    if actual_run != expected_run or actual_dataset != expected_dataset:
        raise ValueError(
            "amount-tail source identity mismatch: "
            f"expected {expected_run}/{expected_dataset}, got {actual_run}/{actual_dataset}"
        )


def _load_feature_matrix(source_run_root: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    root = source_run_root / "artifacts/feature-evidence"
    manifest = json.loads((root / "feature_matrix_manifest.json").read_text(encoding="utf-8"))
    frames = []
    inputs = []
    for item in manifest.get("files", []):
        path = root / "matrix" / str(item["path"])
        digest = _sha256(path)
        if digest != item["sha256"]:
            raise ValueError(f"feature matrix shard hash mismatch: {path}")
        frames.append(pq.read_table(path, columns=_MATRIX_COLUMNS).to_pandas())
        inputs.append({"path": str(path), "sha256": digest})
    if not frames:
        raise FileNotFoundError("source feature matrix contains no shards")
    rows = pd.concat(frames, ignore_index=True)
    rows = _normalise_unique_keys(rows, _KEYS, "feature matrix")
    return rows, inputs


def _load_source_panel(
    config: dict[str, Any], asset_root: Path
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    dataset_root = asset_root / "datasets" / str(config["run"]["dataset_id"])
    full_build = dataset_root / "artifacts/full-build"
    registry_path = full_build / "dataset_registry_v3.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if str(registry.get("dataset_id")) != str(config["run"]["dataset_id"]):
        raise ValueError("dataset registry identity does not match amount-tail config")
    registered = {str(item["path"]): item for item in registry.get("files", [])}
    shard_root = full_build / "dataset-v3"
    frames = []
    inputs = [{"path": str(registry_path), "sha256": _sha256(registry_path)}]
    for path in sorted(shard_root.glob("shard=*/data.parquet")):
        relative = str(path.relative_to(dataset_root))
        item = registered.get(relative)
        if item is None:
            raise ValueError(f"dataset shard is absent from immutable registry: {relative}")
        digest = _sha256(path)
        if digest != item["sha256"]:
            raise ValueError(f"dataset shard hash mismatch: {path}")
        frames.append(pq.read_table(path, columns=_SOURCE_COLUMNS).to_pandas())
        inputs.append({"path": str(path), "sha256": digest})
    if not frames:
        raise FileNotFoundError(f"immutable dataset contains no shards: {shard_root}")
    panel = pd.concat(frames, ignore_index=True)
    panel = _normalise_unique_keys(panel, _KEYS, "immutable source panel")
    signal = panel[
        [
            "trade_date",
            "symbol",
            "circ_mv",
            "adjusted_close",
            "median_amount_20d",
            "entry_tradeable_10d",
            "horizon_available_10d",
            "path_ambiguous_10d",
        ]
    ].copy()
    prices = panel[
        [
            "trade_date",
            "symbol",
            "adjusted_open",
            "adjusted_close",
            "is_suspended",
            "at_up_limit_open",
        ]
    ].copy()
    return signal, prices, inputs


def _validate_join(rows: pd.DataFrame, baseline: pd.DataFrame) -> None:
    if len(rows) != len(baseline):
        raise ValueError("amount-tail join changed OOF row count")
    required = [
        "amount_cny",
        "circ_mv",
        "adjusted_close",
        "median_amount_20d",
        "amount_ratio_5d",
        "amount_ratio_20d",
        "turnover_rate",
        "turnover_ratio_20d",
    ]
    missing = {column: int(rows[column].isna().sum()) for column in required if rows[column].isna().any()}
    if missing:
        raise ValueError(f"amount-tail point-in-time feature join is incomplete: {missing}")


def _copy_fixed_baselines(rows: pd.DataFrame) -> None:
    source_names = {
        "score__adjusted_return_20d": "score__adjusted_return_20d",
        "score__adjusted_return_60d": "score__adjusted_return_60d",
        "score__random": "score__random",
    }
    for output, source in source_names.items():
        if source not in rows:
            raise ValueError(f"source baseline predictions missing score: {source}")
        rows[output] = pd.to_numeric(rows[source], errors="coerce")


def _aggregate_metrics(daily: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    metrics = ["precision_at_5", "ndcg_at_10", "top_5_mean_return", "top_5_median_return"]
    return daily.groupby(groups, sort=True, dropna=False)[metrics].mean().reset_index()


def _selection_exposure(rows: pd.DataFrame, score_columns: Iterable[str], *, top_k: int) -> pd.DataFrame:
    selected = []
    for (quadrant, trade_date), daily in rows.groupby(["quadrant", "trade_date"], sort=True):
        for score_col in score_columns:
            top = daily.sort_values([score_col, "symbol"], ascending=[False, True], kind="stable").head(top_k)
            for column in ("industry_l1", "size_bucket", "liquidity_bucket"):
                counts = top[column].fillna("__UNKNOWN__").value_counts(normalize=True)
                for value, share in counts.items():
                    selected.append(
                        {
                            "quadrant": quadrant,
                            "trade_date": trade_date,
                            "score": score_col.removeprefix("score__"),
                            "dimension": column,
                            "value": value,
                            "share": float(share),
                        }
                    )
    return pd.DataFrame(selected)


def _common_tradeable_dates(
    rows: pd.DataFrame,
    score_columns: Iterable[str],
    *,
    top_k: int,
) -> dict[str, set[str]]:
    required = {"entry_tradeable_10d", "horizon_available_10d", "path_ambiguous_10d"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("amount-tail execution rows missing flags: " + ", ".join(missing))
    output: dict[str, set[str]] = {}
    for quadrant, quadrant_rows in rows.groupby("quadrant", sort=True):
        valid_dates = set(quadrant_rows["trade_date"].unique())
        for score_col in score_columns:
            score_dates = set()
            for trade_date, daily in quadrant_rows.groupby("trade_date", sort=True):
                selected = daily.sort_values(
                    [score_col, "symbol"], ascending=[False, True], kind="stable"
                ).head(top_k)
                valid = (
                    len(selected) == top_k
                    and selected["entry_tradeable_10d"].eq(True).all()
                    and selected["horizon_available_10d"].eq(True).all()
                    and selected["path_ambiguous_10d"].eq(False).all()
                )
                if valid:
                    score_dates.add(str(trade_date))
            valid_dates &= score_dates
        output[str(quadrant)] = valid_dates
    return output


def _run_portfolios(
    rows: pd.DataFrame,
    price_panel: pd.DataFrame,
    comparable_dates: dict[str, set[str]],
    config: dict[str, Any],
) -> tuple[dict[str, dict[str, dict[str, Any]]], pd.DataFrame]:
    portfolios: dict[str, dict[str, dict[str, Any]]] = {}
    curves = []
    execution = config["execution"]
    for quadrant, quadrant_rows in rows.groupby("quadrant", sort=True):
        quadrant_name = str(quadrant)
        signals = quadrant_rows.loc[quadrant_rows["trade_date"].isin(comparable_dates[quadrant_name])]
        portfolios[quadrant_name] = {}
        for score_col in _PORTFOLIO_SCORES:
            selected_symbols = set(
                signals.sort_values(
                    ["trade_date", score_col, "symbol"],
                    ascending=[True, False, True],
                    kind="stable",
                )
                .groupby("trade_date", sort=False)
                .head(int(config["comparison"]["top_k"]))["symbol"]
            )
            prices = price_panel.loc[price_panel["symbol"].isin(selected_symbols)]
            result = simulate_equal_exposure_lot_portfolio(
                signals,
                prices,
                score_col=score_col,
                top_k=int(config["comparison"]["top_k"]),
                hold_sessions=int(execution["horizon_sessions"]),
                commission=float(execution["commission_per_side"]),
                slippage=float(execution["slippage_per_side"]),
                daily_cohort_fraction=float(execution["daily_cohort_fraction"]),
                per_stock_fraction=float(execution["per_stock_fraction"]),
                require_full_cohort=True,
            )
            curve = pd.DataFrame(result.pop("equity_curve"))
            if not curve.empty:
                curve["quadrant"] = quadrant_name
                curve["score"] = score_col.removeprefix("score__")
                curves.append(curve)
            portfolios[quadrant_name][score_col.removeprefix("score__")] = result
    return portfolios, pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()


def _render_report(
    config: dict[str, Any],
    rows: pd.DataFrame,
    daily: pd.DataFrame,
    concentration: dict[str, Any],
    portfolios: dict[str, Any],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# Amount-Tail Signal Audit Result",
        "",
        "## Conclusion",
        "",
        f"Status: `{decision['status']}`.",
        "",
        "This is development-only evidence. Production integration remains prohibited.",
        "",
        "## Scope",
        "",
        f"- Run: `{config['run']['id']}`",
        f"- Source run: `{config['run']['source_run_id']}`",
        f"- Dataset: `{config['run']['dataset_id']}`",
        f"- Rows: {len(rows):,}",
        f"- Dates: {rows['trade_date'].nunique():,}",
        f"- Symbols: {rows['symbol'].nunique():,}",
        "",
        "## Gate Results",
        "",
        "| Gate | Passed |",
        "| --- | --- |",
    ]
    lines.extend(f"| {gate['name']} | {str(bool(gate['passed'])).lower()} |" for gate in decision["gates"])
    lines.extend(["", "## Ranking Summary", "", "| Quadrant | Score | P@5 | NDCG@10 | Top5 return |", "| --- | --- | ---: | ---: | ---: |"]) 
    summary = daily.groupby(["quadrant", "score"])[
        ["precision_at_5", "ndcg_at_10", "top_5_mean_return"]
    ].mean().reset_index()
    keep = summary.loc[summary["score"].isin({REGISTERED_CANDIDATE, "amount_raw", "adjusted_return_20d", "adjusted_return_60d", "random"})]
    for row in keep.itertuples(index=False):
        lines.append(
            f"| {row.quadrant} | {row.score} | {row.precision_at_5:.4f} | "
            f"{row.ndcg_at_10:.4f} | {row.top_5_mean_return:.4%} |"
        )
    lines.extend(["", "## Concentration And Portfolio", ""])
    for quadrant in sorted(concentration):
        share = concentration[quadrant].get(REGISTERED_CANDIDATE)
        portfolio = portfolios.get(quadrant, {}).get(REGISTERED_CANDIDATE, {})
        lines.append(
            f"- {quadrant}: max Top5 industry share {float(share):.1%}; "
            f"equal-exposure return {float(portfolio.get('total_return', 0.0)):.2%}; "
            f"drawdown {float(portfolio.get('maximum_drawdown', 0.0)):.2%}."
        )
    lines.extend(
        [
            "",
            "## Decision Rule",
            "",
            "A failed gate closes this registered candidate. It must not be rescued by changing the label, dates, score formula, or comparator after observing this result.",
            "",
        ]
    )
    return "\n".join(lines)


def _normalise_unique_keys(rows: pd.DataFrame, keys: list[str], label: str) -> pd.DataFrame:
    missing = sorted(set(keys) - set(rows.columns))
    if missing:
        raise ValueError(f"{label} missing keys: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    if result.duplicated(keys).any():
        raise ValueError(f"{label} contains duplicate keys")
    return result


def _artifact_manifest(root: Path) -> list[dict[str, Any]]:
    artifacts = []
    for path in sorted(item for item in root.iterdir() if item.is_file() and item.name not in {"run_manifest.json", "progress.json"}):
        artifacts.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return artifacts


def _write_progress(
    root: Path,
    stage: str,
    status: str,
    *,
    started_at: str,
    decision_status: str | None = None,
    failure: dict[str, str] | None = None,
) -> None:
    _write_json(
        root / "progress.json",
        {
            "stage": stage,
            "status": status,
            "started_at": started_at,
            "heartbeat_at": _now(),
            "decision_status": decision_status,
            "failure": failure,
            "pid": os.getpid(),
        },
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
