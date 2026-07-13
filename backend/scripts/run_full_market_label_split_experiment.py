"""Run the immutable V3 return-label experiment without opening final holdout data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pyarrow.dataset as arrow_dataset

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.evaluator import evaluate_ranking, simulate_daily_topk_portfolio
from app.evaluation.full_market_ml.label_split import add_return_only_labels
from app.evaluation.full_market_ml.label_split_experiment import (
    RETURN_RANKING_LABEL,
    RETURN_STRONG_LABEL,
    _validate_source_contract,
    run_label_split_experiment,
)
from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold


_REQUIRED_DATA_COLUMNS = {
    "trade_date",
    "symbol",
    "eligible_for_training",
    "future_return_10d",
    "net_return_after_cost_10d",
    "relevance_grade_10d",
    "label_strong_path_10d",
    "label_severe_negative_10d",
}
_OPTIONAL_SAFETY_COLUMNS = {
    "entry_price",
    "entry_price_10d",
    "exit_price",
    "exit_price_10d",
    "exit_trade_date",
    "exit_trade_date_10d",
    "mfe_10d",
    "mae_10d",
    "tp_before_sl_10d",
    "sl_before_tp_10d",
    "future_limit_up_count_10d",
    "future_limit_down_count_10d",
    "market_median_net_return_10d",
    "industry_median_net_return_10d",
}


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    dataset_path = _existing_path(arguments.dataset, "dataset")
    split_path = _existing_file(arguments.split_plan, "split-plan")
    candidate_path = _existing_file(arguments.candidate_manifest, "candidate-manifest")
    output = Path(arguments.output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output-dir must not already exist: {output}")

    split_plan = _load_split_plan(split_path)
    candidate = _load_json(candidate_path)
    features = tuple(str(value) for value in candidate.get("selected_features", ()))
    contract_sha256 = _validate_source_contract(candidate, split_plan, features)
    input_evidence = {
        "dataset": _path_evidence(dataset_path),
        "split_plan": _path_evidence(split_path),
        "candidate_manifest": _path_evidence(candidate_path),
    }
    development = _read_development_rows(dataset_path, split_plan, features)
    if development.empty:
        raise ValueError("dataset contains no development rows for the frozen split")

    checkpoint_dir = Path(arguments.checkpoint_dir).expanduser().resolve() if arguments.checkpoint_dir else output / "checkpoints"
    checkpoint_source = _checkpoint_source_evidence(
        checkpoint_dir,
        external_reuse=arguments.checkpoint_dir is not None,
    )
    output.mkdir(parents=True, exist_ok=False)
    _write_json_atomic(
        output / "input_manifest.json",
        {
            "schema_version": 1,
            "state": "validated_inputs",
            "source_inputs": input_evidence,
            "checkpoint_source": checkpoint_source,
            "source_contract_sha256": contract_sha256,
            "split_sha256": split_plan.split_sha256,
            "selected_features": list(features),
            "final_holdout_used": False,
        },
    )

    report = run_label_split_experiment(
        development,
        split_plan,
        features,
        checkpoint_dir=checkpoint_dir,
        source_contract=candidate,
    )
    predictions = report.predictions
    by_quadrant = {name: rows.copy() for name, rows in predictions.groupby("quadrant", sort=True)}
    missing_quadrants = {"A_time_oof", "C_dev_unseen"} - set(by_quadrant)
    if missing_quadrants:
        raise ValueError("experiment did not produce required development quadrants: " + ", ".join(sorted(missing_quadrants)))
    _write_parquet_atomic(by_quadrant["A_time_oof"], output / "a_time_oof_predictions.parquet")
    _write_parquet_atomic(by_quadrant["C_dev_unseen"], output / "c_dev_unseen_predictions.parquet")

    labels = add_return_only_labels(development)
    _write_label_reports(labels, output)
    daily_metrics = _daily_metrics(by_quadrant)
    pd.DataFrame(daily_metrics).to_csv(output / "daily_metrics.csv", index=False)
    fold_metrics = _fold_metrics(by_quadrant)
    pd.DataFrame(fold_metrics).to_csv(output / "fold_metrics.csv", index=False)
    baseline_rows = _baseline_rows(report.baseline_metrics)
    pd.DataFrame(baseline_rows).to_csv(output / "baseline_comparison.csv", index=False)
    safety_metrics, portfolio_metrics = _safety_and_portfolios(by_quadrant, report.portfolios)
    gate = _research_gate(report.quadrant_metrics, report.baseline_metrics, report.bootstrap, fold_metrics, portfolio_metrics)
    metrics = {
        "model_status": gate["model_status"],
        "gate_results": gate,
        "quadrants": report.quadrant_metrics,
        "baseline_metrics": report.baseline_metrics,
        "portfolio_metrics": portfolio_metrics,
        "final_holdout_used": False,
    }
    _write_json_atomic(output / "metrics.json", metrics)
    _write_json_atomic(output / "bootstrap.json", report.bootstrap)
    _write_json_atomic(output / "safety_metrics.json", safety_metrics)
    manifest = {
        "schema_version": 1,
        "source_inputs": input_evidence,
        "source_commit": _git_commit(),
        "source_contract_sha256": report.source_contract_sha256,
        "checkpoint_contract": report.checkpoint_contract,
        "checkpoint_source": checkpoint_source,
        "split_sha256": split_plan.split_sha256,
        "label_contract": {
            "ranking_label": report.ranking_label,
            "strong_label": report.strong_label,
            "outcome": "net_return_after_cost_10d",
            "path_risk_used_as_training_target": False,
        },
        "selected_features": list(features),
        "selected_ranker_params": candidate["selected_ranker_params"],
        "seeds": candidate["seeds"],
        "development_date_count": int(development["trade_date"].nunique()),
        "development_row_count": int(len(development)),
        "final_holdout_used": False,
        "model_status": gate["model_status"],
        "artifacts": {
            "metrics": "metrics.json",
            "bootstrap": "bootstrap.json",
            "safety": "safety_metrics.json",
            "daily_metrics": "daily_metrics.csv",
            "fold_metrics": "fold_metrics.csv",
            "baselines": "baseline_comparison.csv",
            "a_predictions": "a_time_oof_predictions.parquet",
            "c_predictions": "c_dev_unseen_predictions.parquet",
        },
    }
    _write_json_atomic(output / "experiment_manifest.json", manifest)
    _write_runtime_review(output / "experiment_review.md", metrics, manifest)
    return {"output_dir": str(output), "model_status": gate["model_status"], "failed_gates": gate["failed_gates"]}


def _load_split_plan(path: Path) -> SplitPlan:
    raw = _load_json(path)
    try:
        quadrants = raw["quadrants"]
        folds = tuple(
            WalkForwardFold(
                **{
                    key: tuple(value) if key in {"training_dates", "validation_dates", "training_symbols"} else value
                    for key, value in fold.items()
                }
            )
            for fold in raw["walk_forward"]
        )
        return SplitPlan(
            development_dates=tuple(raw["development_dates"]),
            final_dates=tuple(raw["final_dates"]),
            stock_holdout_symbols=tuple(raw["stock_holdout_symbols"]),
            A_dev_train_symbols=tuple(quadrants["A_dev_train_symbols"]),
            B_final_train_symbols=tuple(quadrants["B_final_train_symbols"]),
            C_dev_unseen_symbols=tuple(quadrants["C_dev_unseen_symbols"]),
            D_final_unseen_symbols=tuple(quadrants["D_final_unseen_symbols"]),
            walk_forward=folds,
            stratum_counts_before=dict(raw["stratum_counts_before"]),
            stratum_counts_after=dict(raw["stratum_counts_after"]),
            split_sha256=str(raw["split_sha256"]),
            final_holdout_frozen_model_sha=raw.get("final_holdout_frozen_model_sha"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid split-plan JSON: {path}") from error


def _read_development_rows(dataset_path: Path, split_plan: SplitPlan, features: tuple[str, ...]) -> pd.DataFrame:
    source = arrow_dataset.dataset(str(dataset_path), format="parquet")
    available = set(source.schema.names)
    missing = sorted((_REQUIRED_DATA_COLUMNS | set(features)) - available)
    if missing:
        raise ValueError("dataset missing required V3 columns: " + ", ".join(missing))
    columns = sorted((_REQUIRED_DATA_COLUMNS | set(features) | _OPTIONAL_SAFETY_COLUMNS) & available)
    table = source.to_table(
        columns=columns,
        filter=arrow_dataset.field("trade_date").isin(list(split_plan.development_dates)),
    )
    rows = table.to_pandas()
    if rows["trade_date"].isin(split_plan.final_dates).any():
        raise RuntimeError("development parquet scan returned final-holdout rows")
    return rows


def _write_label_reports(rows: pd.DataFrame, output: Path) -> None:
    eligible = rows.loc[rows[RETURN_RANKING_LABEL].notna()].copy()
    distribution = (
        eligible.groupby(RETURN_RANKING_LABEL, dropna=False)
        .size()
        .rename("count")
        .reset_index()
        .sort_values(RETURN_RANKING_LABEL, kind="stable")
    )
    distribution.to_csv(output / "label_distribution.csv", index=False)
    confusion = pd.crosstab(
        eligible["relevance_grade_10d"],
        eligible[RETURN_RANKING_LABEL],
        dropna=False,
    )
    confusion.index.name = "composite_relevance_grade_10d"
    confusion.reset_index().to_csv(output / "label_confusion_with_composite.csv", index=False)


def _daily_metrics(by_quadrant: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for quadrant, predictions in by_quadrant.items():
        for trade_date, daily in predictions.groupby("trade_date", sort=True):
            rows.append(
                {
                    "quadrant": quadrant,
                    "trade_date": str(trade_date),
                    **evaluate_ranking(
                        daily,
                        grade_col=RETURN_RANKING_LABEL,
                        strong_col=RETURN_STRONG_LABEL,
                    ),
                }
            )
    return rows


def _fold_metrics(by_quadrant: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for quadrant, predictions in by_quadrant.items():
        for fold, fold_rows in predictions.groupby("fold", sort=True):
            model_metrics = evaluate_ranking(
                fold_rows,
                grade_col=RETURN_RANKING_LABEL,
                strong_col=RETURN_STRONG_LABEL,
            )
            amount_metrics = None
            if "amount_log" in fold_rows and pd.to_numeric(fold_rows["amount_log"], errors="coerce").notna().all():
                amount_metrics = evaluate_ranking(
                    fold_rows.assign(score=fold_rows["amount_log"]),
                    grade_col=RETURN_RANKING_LABEL,
                    strong_col=RETURN_STRONG_LABEL,
                )
            rows.append(
                {
                    "quadrant": quadrant,
                    "fold": int(fold),
                    **model_metrics,
                    "amount_log_ndcg_at_10": None if amount_metrics is None else amount_metrics["ndcg_at_10"],
                    "ndcg_at_10_not_below_amount_log": False if amount_metrics is None else model_metrics["ndcg_at_10"] >= amount_metrics["ndcg_at_10"],
                }
            )
    return rows


def _baseline_rows(baselines: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for quadrant, reports in baselines.items():
        for baseline, report in reports.items():
            for metric, value in report.items():
                rows.append(
                    {
                        "quadrant": quadrant,
                        "baseline": baseline,
                        "metric": metric,
                        "value": json.dumps(value, ensure_ascii=True, sort_keys=True) if isinstance(value, (dict, list)) else value,
                    }
                )
    return rows


def _safety_and_portfolios(
    by_quadrant: Mapping[str, pd.DataFrame], model_portfolios: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    safety: dict[str, Any] = {}
    portfolios: dict[str, Any] = {}
    for quadrant, rows in by_quadrant.items():
        selected = (
            rows.sort_values(["trade_date", "score", "symbol"], ascending=[True, False, True], kind="stable")
            .groupby("trade_date", sort=True)
            .head(5)
        )
        safety[quadrant] = {
            "top_5_rows": int(len(selected)),
            "label_strong_path_rate": _mean_flag(selected, "label_strong_path_10d"),
            "label_severe_negative_rate": _mean_flag(selected, "label_severe_negative_10d"),
            "tp_before_sl_rate": _mean_flag(selected, "tp_before_sl_10d"),
            "sl_before_tp_rate": _mean_flag(selected, "sl_before_tp_10d"),
            "future_limit_up_rate": _mean_positive(selected, "future_limit_up_count_10d"),
            "future_limit_down_rate": _mean_positive(selected, "future_limit_down_count_10d"),
            "mfe_mean": _mean_numeric(selected, "mfe_10d"),
            "mae_mean": _mean_numeric(selected, "mae_10d"),
            "top_5_median_net_return": _mean_by_date(selected, "net_return_after_cost_10d", median=True),
        }
        portfolios[quadrant] = {"model": dict(model_portfolios[quadrant])}
        if "amount_log" in rows and pd.to_numeric(rows["amount_log"], errors="coerce").notna().all():
            try:
                portfolios[quadrant]["amount_log"] = simulate_daily_topk_portfolio(rows.assign(score=rows["amount_log"]))
            except ValueError as error:
                portfolios[quadrant]["amount_log"] = {"status": "unavailable", "reason": str(error)}
    return safety, portfolios


def _research_gate(
    metrics: Mapping[str, Mapping[str, Any]],
    baselines: Mapping[str, Mapping[str, Mapping[str, Any]]],
    bootstrap: Mapping[str, Mapping[str, Any]],
    fold_metrics: list[dict[str, Any]],
    portfolios: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    failures = []
    a_metrics = metrics.get("A_time_oof", {})
    c_metrics = metrics.get("C_dev_unseen", {})
    a_amount = baselines.get("A_time_oof", {}).get("amount_log", {})
    c_amount = baselines.get("C_dev_unseen", {}).get("amount_log", {})
    if a_amount.get("status") != "available":
        failures.append("A_time_oof:amount_log_unavailable")
    else:
        if a_metrics.get("precision_at_5", 0.0) <= a_amount.get("precision_at_5", 0.0):
            failures.append("A_time_oof:precision_at_5_not_above_amount_log")
        if a_metrics.get("ndcg_at_10", 0.0) <= a_amount.get("ndcg_at_10", 0.0):
            failures.append("A_time_oof:ndcg_at_10_not_above_amount_log")
    if bootstrap.get("A_time_oof", {}).get("precision_at_5_uplift_ci_low", 0.0) <= 0.0:
        failures.append("A_time_oof:bootstrap_precision_at_5_lower_bound_not_positive")
    if c_amount.get("status") != "available":
        failures.append("C_dev_unseen:amount_log_unavailable")
    elif (
        c_metrics.get("precision_at_5", 0.0) < c_amount.get("precision_at_5", 0.0)
        and c_metrics.get("ndcg_at_10", 0.0) < c_amount.get("ndcg_at_10", 0.0)
    ):
        failures.append("C_dev_unseen:both_precision_at_5_and_ndcg_at_10_below_amount_log")
    if a_metrics.get("top_5_median_return", 0.0) <= 0.0:
        failures.append("A_time_oof:top_5_median_return_not_positive")
    model_portfolio = portfolios.get("A_time_oof", {}).get("model", {})
    amount_portfolio = portfolios.get("A_time_oof", {}).get("amount_log", {})
    if "maximum_drawdown" not in model_portfolio or "maximum_drawdown" not in amount_portfolio:
        failures.append("A_time_oof:portfolio_drawdown_unavailable")
    elif model_portfolio["maximum_drawdown"] < amount_portfolio["maximum_drawdown"]:
        failures.append("A_time_oof:maximum_drawdown_worse_than_amount_log")
    a_folds = [row for row in fold_metrics if row["quadrant"] == "A_time_oof"]
    # Fold baseline metrics must be recomputed from matching fold rows; the aggregate baseline is not reused here.
    if len(a_folds) < 5:
        failures.append("A_time_oof:insufficient_outer_fold_metrics")
    # The matching per-fold amount comparison is populated after the OOF run below.
    fold_wins = sum(bool(row.get("ndcg_at_10_not_below_amount_log")) for row in a_folds)
    if a_folds and fold_wins < 4:
        failures.append("A_time_oof:fewer_than_four_folds_not_below_amount_log_ndcg")
    return {
        "model_status": "research_only_failed_gate" if failures else "research_only",
        "failed_gates": failures,
        "production_integration_allowed": False,
    }


def _mean_flag(rows: pd.DataFrame, column: str) -> float | None:
    if column not in rows:
        return None
    return float(rows[column].fillna(False).astype(bool).mean())


def _mean_positive(rows: pd.DataFrame, column: str) -> float | None:
    if column not in rows:
        return None
    return float(pd.to_numeric(rows[column], errors="coerce").fillna(0.0).gt(0.0).mean())


def _mean_numeric(rows: pd.DataFrame, column: str) -> float | None:
    if column not in rows:
        return None
    values = pd.to_numeric(rows[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _mean_by_date(rows: pd.DataFrame, column: str, *, median: bool = False) -> float | None:
    if column not in rows:
        return None
    values = pd.to_numeric(rows[column], errors="coerce")
    grouped = values.groupby(rows["trade_date"], sort=True)
    result = grouped.median() if median else grouped.mean()
    return float(result.mean()) if not result.empty else None


def _write_runtime_review(path: Path, metrics: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    lines = [
        "# Return-Label Split Experiment",
        "",
        f"- Status: `{metrics['model_status']}`",
        "- Scope: development A/time OOF and C/unseen-stock OOF only.",
        "- Final holdout used: `false`.",
        "- Production integration: prohibited.",
        f"- Source contract SHA256: `{manifest['source_contract_sha256']}`",
        "",
        "## Failed Gates",
        "",
    ]
    failures = metrics["gate_results"]["failed_gates"]
    lines.extend([f"- `{item}`" for item in failures] or ["- None"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _path_evidence(path: Path) -> dict[str, Any]:
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise FileNotFoundError(f"input path contains no files: {path}")
    digest = hashlib.sha256()
    total_bytes = 0
    for item in files:
        relative = item.name if path.is_file() else str(item.relative_to(path))
        file_digest = _file_sha256(item)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
        total_bytes += item.stat().st_size
    return {
        "path": str(path),
        "sha256": digest.hexdigest() if path.is_dir() else _file_sha256(path),
        "file_count": len(files),
        "total_bytes": total_bytes,
    }


def _checkpoint_source_evidence(path: Path, *, external_reuse: bool) -> dict[str, Any]:
    if external_reuse:
        if not path.is_dir():
            raise ValueError(f"checkpoint-dir must be an existing directory when reusing checkpoints: {path}")
        return {"mode": "external_reuse", "evidence": _path_evidence(path)}
    return {"mode": "generated_in_output", "path": str(path)}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _existing_path(value: str, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{name} path does not exist: {path}")
    return path


def _existing_file(value: str, name: str) -> Path:
    path = _existing_path(value, name)
    if not path.is_file():
        raise ValueError(f"{name} must be a file: {path}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON file: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return value


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as temporary:
        temporary.write(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, default=str) + "\n")
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _write_parquet_atomic(rows: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{path.name}.", dir=path.parent) as temporary:
        temporary_path = Path(temporary) / path.name
        rows.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, path)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a research-only V3 return-label split experiment.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--split-plan", required=True)
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--checkpoint-dir")
    arguments = parser.parse_args(argv)
    try:
        result = run(arguments)
    except (FileNotFoundError, FileExistsError, RuntimeError, TypeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
