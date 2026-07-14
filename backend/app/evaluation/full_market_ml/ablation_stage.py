"""Contract-bound full-data nested feature-block ablation stage."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .ablation import run_nested_block_ablation
from .baseline_model import RegisteredBaselineTrainer
from .research_contract import RankingResearchContract
from .splits import SplitPlan, WalkForwardFold


def run_nested_ablation_stage(
    contract: RankingResearchContract,
    run_root: Path,
) -> dict[str, Any]:
    feature_root = run_root / "artifacts" / "feature-evidence"
    manifest_path = feature_root / "feature_matrix_manifest.json"
    split_path = feature_root / "development_split.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract_sha256") != contract.sha256():
        raise ValueError("feature matrix contract hash changed before ablation")
    split = _load_split(split_path)
    if manifest.get("split_sha256") != split.split_sha256:
        raise ValueError("feature matrix split hash changed before ablation")
    columns = {
        "trade_date",
        "symbol",
        "alpha_target_10d",
        "alpha_relevance_grade_10d",
        "net_return_after_cost_10d",
        "severe_negative_10d",
        *(feature for _, schema in contract.feature_blocks for feature in schema),
    }
    frames = []
    matrix_root = feature_root / "matrix"
    for item in manifest.get("files", []):
        path = matrix_root / str(item["path"])
        if _sha256(path) != item.get("sha256"):
            raise ValueError(f"feature matrix shard changed: {path}")
        frames.append(pq.read_table(path, columns=sorted(columns)).to_pandas())
    rows = pd.concat(frames, ignore_index=True)
    rows["alpha_top10_10d"] = pd.to_numeric(
        rows["alpha_relevance_grade_10d"], errors="coerce"
    ).ge(3)
    decisions = run_nested_block_ablation(
        rows,
        split,
        ("adjusted_return_60d",),
        {name: schema for name, schema in contract.feature_blocks},
        RegisteredBaselineTrainer(),
    )
    artifact_root = run_root / "artifacts" / "nested-ablation"
    result_path = artifact_root / "block_decisions.json"
    payload = {
        "contract_sha256": contract.sha256(),
        "split_sha256": split.split_sha256,
        "base_features": ["adjusted_return_60d"],
        "decisions": [
            {
                "name": decision.name,
                "status": decision.status,
                "coverage": decision.coverage,
                "inner_selected_folds": list(decision.inner_selected_folds),
                "outer_fold_uplifts": list(decision.outer_fold_uplifts),
                "aggregate_oof_uplift": decision.oof_uplift,
                "precision_bootstrap_ci": list(decision.precision_bootstrap_ci),
                "reasons": list(decision.reasons),
            }
            for decision in decisions
        ],
    }
    _write_json(result_path, payload)
    accepted = [decision.name for decision in decisions if decision.status == "accepted_alpha"]
    return {
        "ablation_decisions": str(result_path),
        "_status": {"research_design_valid": True, "model_gate_passed": bool(accepted)},
    }


def _load_split(path: Path) -> SplitPlan:
    value = json.loads(path.read_text(encoding="utf-8"))
    quadrants = value["quadrants"]
    folds = tuple(
        WalkForwardFold(
            fold=int(item["fold"]),
            training_dates=tuple(item["training_dates"]),
            validation_dates=tuple(item["validation_dates"]),
            training_symbols=tuple(item["training_symbols"]),
            train_start=str(item["train_start"]),
            train_end=str(item["train_end"]),
            validation_start=str(item["validation_start"]),
            validation_end=str(item["validation_end"]),
        )
        for item in value["walk_forward"]
    )
    return SplitPlan(
        development_dates=tuple(value["development_dates"]),
        final_dates=tuple(value["final_dates"]),
        stock_holdout_symbols=tuple(value["stock_holdout_symbols"]),
        A_dev_train_symbols=tuple(quadrants["A_dev_train_symbols"]),
        B_final_train_symbols=tuple(quadrants["B_final_train_symbols"]),
        C_dev_unseen_symbols=tuple(quadrants["C_dev_unseen_symbols"]),
        D_final_unseen_symbols=tuple(quadrants["D_final_unseen_symbols"]),
        walk_forward=folds,
        stratum_counts_before=dict(value.get("stratum_counts_before", {})),
        stratum_counts_after=dict(value.get("stratum_counts_after", {})),
        split_sha256=str(value["split_sha256"]),
        final_holdout_frozen_model_sha=value.get("final_holdout_frozen_model_sha"),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
