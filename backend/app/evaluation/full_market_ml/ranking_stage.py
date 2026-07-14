"""Contract-bound fixed-baseline and nested-ranker OOF stages."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .ablation_stage import _load_split, _sha256
from .evaluator import evaluate_ranking
from .ranking_model import RankingModelSpec, build_fixed_baseline_predictions, run_nested_ranking_oof
from .research_contract import RankingResearchContract


LABEL_COLUMNS = (
    "alpha_target_10d",
    "alpha_relevance_grade_10d",
    "net_return_after_cost_10d",
    "severe_negative_10d",
    "mae_10d",
)


def run_baseline_oof_stage(contract: RankingResearchContract, run_root: Path) -> dict[str, Any]:
    feature_columns = sorted({_definition_source(source) for _, source in contract.baseline_definitions if _definition_source(source)})
    rows, split = _load_matrix(run_root, feature_columns)
    outer = _outer_rows(rows, split)
    predictions = build_fixed_baseline_predictions(outer, contract.baseline_definitions)
    artifact_root = run_root / "artifacts" / "baseline-oof"
    prediction_path = artifact_root / "baseline_predictions.parquet"
    report_path = artifact_root / "baseline_report.json"
    artifact_root.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(prediction_path, compression="zstd", index=False)
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for quadrant, quadrant_rows in predictions.groupby("quadrant", sort=True):
        metrics[str(quadrant)] = {}
        for name, _ in contract.baseline_definitions:
            metrics[str(quadrant)][name] = evaluate_ranking(
                quadrant_rows,
                score_col=f"score__{name}",
                grade_col="alpha_relevance_grade_10d",
                strong_col="alpha_top10_10d",
            )
    report = {
        "contract_sha256": contract.sha256(),
        "split_sha256": split.split_sha256,
        "row_count": int(len(predictions)),
        "definitions": dict(contract.baseline_definitions),
        "metrics": metrics,
        "coach_service_score": {
            "available": False,
            "reason": "historical CoachService score is not stored point-in-time for the full-market panel",
        },
    }
    _write_json(report_path, report)
    return {
        "baseline_predictions": str(prediction_path),
        "baseline_report": str(report_path),
        "_status": {"research_design_valid": True, "model_gate_passed": False},
    }


def run_ranker_oof_stage(contract: RankingResearchContract, run_root: Path) -> dict[str, Any]:
    ablation_path = run_root / "artifacts" / "nested-ablation" / "block_decisions.json"
    ablation = json.loads(ablation_path.read_text(encoding="utf-8"))
    accepted_names = {
        item["name"] for item in ablation.get("decisions", []) if item.get("status") == "accepted_alpha"
    }
    if not accepted_names:
        raise RuntimeError("ranker-oof blocked: nested ablation accepted no alpha feature block")
    accepted_features = tuple(
        feature
        for name, schema in contract.feature_blocks
        if name in accepted_names
        for feature in schema
    )
    if not accepted_features:
        raise RuntimeError("ranker-oof blocked: accepted feature schema is empty")
    rows, split = _load_matrix(run_root, list(accepted_features))
    rows["alpha_top10_10d"] = pd.to_numeric(rows["alpha_relevance_grade_10d"], errors="coerce").ge(3)
    specs = (
        RankingModelSpec("linear_scorecard", "linear_scorecard", accepted_features, seed=contract.seeds[0]),
        RankingModelSpec(
            "bounded_lambdarank",
            "lightgbm_lambdarank",
            accepted_features,
            parameters=(("n_estimators", 200), ("num_leaves", 15), ("max_depth", 5)),
            seed=contract.seeds[0],
        ),
    )
    artifact_root = run_root / "artifacts" / "ranker-oof"
    result = run_nested_ranking_oof(
        rows,
        split,
        specs,
        checkpoint_dir=artifact_root / "checkpoints",
        resume=True,
    )
    prediction_path = artifact_root / "ranker_predictions.parquet"
    report_path = artifact_root / "ranker_report.json"
    artifact_root.mkdir(parents=True, exist_ok=True)
    predictions = result.pop("predictions")
    predictions.to_parquet(prediction_path, compression="zstd", index=False)
    metrics = {
        str(quadrant): evaluate_ranking(
            quadrant_rows,
            score_col="score",
            grade_col="alpha_relevance_grade_10d",
            strong_col="alpha_top10_10d",
        )
        for quadrant, quadrant_rows in predictions.groupby("quadrant", sort=True)
    }
    report = {
        "contract_sha256": contract.sha256(),
        "split_sha256": split.split_sha256,
        **result,
        "metrics": metrics,
    }
    _write_json(report_path, report)
    return {
        "ranker_predictions": str(prediction_path),
        "ranker_report": str(report_path),
        "_status": {"research_design_valid": True, "model_gate_passed": True},
    }


def _load_matrix(run_root: Path, feature_columns: list[str]) -> tuple[pd.DataFrame, Any]:
    root = run_root / "artifacts" / "feature-evidence"
    manifest = json.loads((root / "feature_matrix_manifest.json").read_text(encoding="utf-8"))
    split = _load_split(root / "development_split.json")
    columns = sorted({"trade_date", "symbol", "industry_l1", "market_state", *LABEL_COLUMNS, *feature_columns})
    frames = []
    for item in manifest["files"]:
        path = root / "matrix" / str(item["path"])
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"feature matrix shard changed: {path}")
        frames.append(pq.read_table(path, columns=columns).to_pandas())
    return pd.concat(frames, ignore_index=True), split


def _outer_rows(rows: pd.DataFrame, split) -> pd.DataFrame:
    frames = []
    c_symbols = set(split.C_dev_unseen_symbols)
    for fold in split.walk_forward:
        symbols = set(fold.training_symbols) | c_symbols
        current = rows.loc[
            rows["trade_date"].isin(fold.validation_dates) & rows["symbol"].isin(symbols)
        ].copy()
        current["fold"] = fold.fold
        current["quadrant"] = current["symbol"].map(lambda value: "C" if value in c_symbols else "A")
        frames.append(current)
    output = pd.concat(frames, ignore_index=True)
    output["alpha_top10_10d"] = pd.to_numeric(output["alpha_relevance_grade_10d"], errors="coerce").ge(3)
    return output


def _definition_source(definition: str) -> str:
    kind, _, source = str(definition).partition(":")
    return source if kind in {"column", "column_descending"} else ""


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
