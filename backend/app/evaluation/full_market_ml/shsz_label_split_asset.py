"""Build development-only labels and A/C splits for a certified SH/SZ panel."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows.
    resource = None

from .label_stage import INPUT_COLUMNS as RANKING_LABEL_INPUT_COLUMNS
from .label_stage import OUTPUT_COLUMNS as RANKING_LABEL_OUTPUT_COLUMNS
from .label_stage import build_ranking_label_input
from .labels import HORIZONS, build_forward_labels
from .ranking_labels import audit_label_objective, add_cross_sectional_alpha_labels
from .research_contract import RankingResearchContract
from .splits import build_development_only_split_plan


UNIVERSE_ID = "shsz_a_share_v1"
ALLOWED_EXCHANGES = ("SH", "SZ")
_FORWARD_BASE_COLUMNS = (
    "trade_date",
    "symbol",
    "industry_l1",
    "listing_age_trade_days",
    "valid_ohlc",
    "is_st",
    "is_suspended",
    "median_amount_20d",
    "entry_tradeable",
    "total_mv",
    "amount_cny",
)
_FORWARD_OUTCOME_COLUMNS = tuple(
    column
    for horizon in HORIZONS
    for column in (
        f"horizon_available_{horizon}d",
        f"eligible_for_training_{horizon}d",
        f"entry_tradeable_{horizon}d",
        f"future_return_{horizon}d",
        f"gross_return_{horizon}d",
        f"net_return_after_cost_{horizon}d",
        f"entry_price_{horizon}d",
        f"exit_price_{horizon}d",
        f"exit_trade_date_{horizon}d",
        f"mfe_{horizon}d",
        f"mae_{horizon}d",
        f"future_limit_up_count_{horizon}d",
        f"future_limit_down_count_{horizon}d",
        f"tp_before_sl_{horizon}d",
        f"sl_before_tp_{horizon}d",
        f"path_ambiguous_{horizon}d",
    )
)
_CANONICAL_TEN_DAY_COLUMNS = (
    "eligible_for_training",
    "entry_price",
    "exit_price",
    "exit_trade_date",
    "gross_return",
    "net_return_after_cost",
    "mfe",
    "mae",
)
FORWARD_LABEL_COLUMNS = _FORWARD_BASE_COLUMNS + _FORWARD_OUTCOME_COLUMNS + _CANONICAL_TEN_DAY_COLUMNS
ALPHA_INPUT_COLUMNS = tuple(
    dict.fromkeys(
        (
            *RANKING_LABEL_INPUT_COLUMNS,
            "path_ambiguous_10d",
            *(f"horizon_available_{horizon}d" for horizon in HORIZONS),
            "total_mv",
            "amount_cny",
        )
    )
)
ALPHA_NEW_COLUMNS = tuple(column for column in RANKING_LABEL_OUTPUT_COLUMNS if column not in FORWARD_LABEL_COLUMNS)


def build_shsz_label_split_asset(
    *,
    panel_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
) -> dict[str, object]:
    """Materialize labels without opening a time holdout or training a model."""
    panel_root = Path(panel_root).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    panel_manifest_path = panel_root / "panel_rebuild_manifest.json"
    panel_manifest = _load_panel_manifest(panel_manifest_path)
    shards = sorted((panel_root / "panel" / "stage=full-build").glob("shard=*/data.parquet"))
    if not shards:
        raise FileNotFoundError("certified SH/SZ panel has no shards")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.running"
    if temporary.exists():
        raise FileExistsError(f"label-stage evidence already exists: {temporary}")
    temporary.mkdir(parents=True)
    completed = 0
    current_step = "forward-labels"
    try:
        forward_root = temporary / "forward"
        _write_progress(temporary, current_step, completed, len(shards))
        for completed, source in enumerate(shards, start=1):
            rows = pq.read_table(source).to_pandas()
            forward = build_forward_labels(None, rows)
            _require_columns(forward, FORWARD_LABEL_COLUMNS, source)
            destination = forward_root / source.parent.name / "data.parquet"
            destination.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(forward.loc[:, FORWARD_LABEL_COLUMNS], preserve_index=False), destination, compression="zstd")
            _write_progress(temporary, current_step, completed, len(shards), shard=source.parent.name)

        current_step = "cross-sectional-alpha"
        _write_progress(temporary, current_step, 0, len(shards))
        alpha_frames = []
        for completed, source in enumerate(sorted(forward_root.glob("shard=*/data.parquet")), start=1):
            frame = pq.read_table(source, columns=list(ALPHA_INPUT_COLUMNS)).to_pandas()
            frame["_source_shard"] = source.parent.name
            alpha_frames.append(frame)
            _write_progress(temporary, current_step, completed, len(shards), shard=source.parent.name)
        contract = _label_contract()
        prepared = build_ranking_label_input(pd.concat(alpha_frames, ignore_index=True), contract)
        complete_horizons = prepared[[f"horizon_available_{horizon}d" for horizon in HORIZONS]].eq(True).all(axis=1)
        prepared["eligible_for_training"] = prepared["eligible_for_training"].eq(True) & complete_horizons
        labeled = add_cross_sectional_alpha_labels(prepared)
        eligible = labeled.loc[
            labeled["eligible_for_training"].eq(True) & labeled["alpha_relevance_grade_10d"].notna()
        ].copy()
        if eligible.empty:
            raise ValueError("certified SH/SZ panel has no complete development labels")
        objective_report = audit_label_objective(eligible)
        split = build_development_only_split_plan(eligible)
        label_quality_passed = bool(objective_report.get("passed"))

        current_step = "write-labels"
        labels_root = temporary / "labels"
        _write_progress(temporary, current_step, 0, len(shards))
        alpha_by_shard = {name: rows for name, rows in eligible.groupby("_source_shard", sort=True)}
        label_files = []
        for completed, source in enumerate(sorted(forward_root.glob("shard=*/data.parquet")), start=1):
            shard_name = source.parent.name
            alpha = alpha_by_shard.get(shard_name)
            if alpha is None or alpha.empty:
                _write_progress(temporary, current_step, completed, len(shards), shard=shard_name)
                continue
            forward = pq.read_table(source).to_pandas()
            alpha_columns = ["trade_date", "symbol", *ALPHA_NEW_COLUMNS]
            merged = forward.merge(alpha.loc[:, alpha_columns], on=["trade_date", "symbol"], how="inner", validate="one_to_one")
            destination = labels_root / shard_name / "data.parquet"
            destination.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(merged, preserve_index=False), destination, compression="zstd")
            label_files.append(_file_evidence(destination, temporary))
            _write_progress(temporary, current_step, completed, len(shards), shard=shard_name)

        if not label_files:
            raise ValueError("no labeled SH/SZ shard was written")
        shutil.rmtree(forward_root)
        split_path = temporary / "development_split_plan.json"
        _write_json(split_path, split.to_dict())
        objective_report.update(
            {
                "label_scope": "development_only_complete_3_5_10_20_day_outcomes",
                "eligible_row_count": int(len(eligible)),
                "eligible_trade_date_count": int(eligible["trade_date"].nunique()),
                "future_holdout_status": "awaiting_model_freeze_and_future_labels",
            }
        )
        _write_json(temporary / "label_objective_report.json", objective_report)
        label_schema_sha256 = _sha256_json(
            {
                "forward_columns": FORWARD_LABEL_COLUMNS,
                "alpha_new_columns": ALPHA_NEW_COLUMNS,
                "horizons": HORIZONS,
                "signal_time": "after_close",
                "entry_time": "next_session_open",
            }
        )
        registry_payload = {
            "source_panel_manifest_sha256": _sha256(panel_manifest_path),
            "source_full_build_manifest_sha256": panel_manifest["source"]["full_build_manifest_sha256"],
            "universe_contract_sha256": panel_manifest["source"]["universe_contract_sha256"],
            "label_schema_sha256": label_schema_sha256,
            "split_sha256": split.split_sha256,
            "code_commit": str(code_commit),
        }
        registry = {
            "dataset_id": "shsz_" + _sha256_json(registry_payload)[:20],
            **registry_payload,
            "label_quality_passed": label_quality_passed,
            "label_quality_failed_gates": list(objective_report.get("failed_gates", ())),
            "production_integration_allowed": False,
            "future_holdout_status": "awaiting_model_freeze_and_future_labels",
            "label_file_count": len(label_files),
            "label_files": label_files,
        }
        _write_json(temporary / "dataset_registry.json", registry)
        report = {
            "schema_version": 1,
            "status": (
                "complete_development_labels_ready"
                if label_quality_passed
                else "complete_development_labels_quality_failed"
            ),
            "research_ready": label_quality_passed,
            "production_integration_allowed": False,
            "universe_id": UNIVERSE_ID,
            "allowed_exchanges": list(ALLOWED_EXCHANGES),
            "code_commit": str(code_commit),
            "source": {
                "panel_root": str(panel_root),
                "panel_rebuild_manifest_sha256": _sha256(panel_manifest_path),
                "full_build_manifest_sha256": panel_manifest["source"]["full_build_manifest_sha256"],
                "universe_contract_sha256": panel_manifest["source"]["universe_contract_sha256"],
            },
            "output": {
                "dataset_id": registry["dataset_id"],
                "label_row_count": int(len(eligible)),
                "label_trade_date_count": int(eligible["trade_date"].nunique()),
                "shard_count": len(label_files),
                "label_schema_sha256": label_schema_sha256,
                "split_sha256": split.split_sha256,
            },
            "future_holdout": split.to_dict()["future_holdout"],
            "interpretation": (
                "This asset contains development-only labels and A/C split membership. Formal future time holdout, "
                "model selection, final fitting, and production integration remain forbidden."
            ),
        }
        _write_json(temporary / "label_split_manifest.json", report)
        _write_progress(temporary, "complete", len(shards), len(shards))
        os.replace(temporary, output)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            completed,
            len(shards),
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _load_panel_manifest(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"panel rebuild manifest is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("panel rebuild manifest must be a JSON object")
    if value.get("status") != "complete_shsz_panel_rebuilt" or value.get("research_ready") is not True:
        raise ValueError("panel rebuild is not certified for development label construction")
    if value.get("universe_id") != UNIVERSE_ID or tuple(value.get("allowed_exchanges", ())) != ALLOWED_EXCHANGES:
        raise ValueError("panel rebuild does not define the SH/SZ research universe")
    source = value.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("panel rebuild manifest source is missing")
    for key in ("full_build_manifest_sha256", "universe_contract_sha256"):
        text = str(source.get(key, ""))
        if len(text) != 64 or any(character not in "0123456789abcdef" for character in text.lower()):
            raise ValueError(f"panel rebuild manifest has invalid {key}")
    return value


def _label_contract() -> RankingResearchContract:
    return RankingResearchContract(
        dataset_id="development-label-staging",
        run_id="shsz-label-split",
        feature_blocks=(("label_staging", ("not_used_for_training",)),),
    )


def _require_columns(rows: pd.DataFrame, columns: tuple[str, ...], source: Path) -> None:
    missing = sorted(set(columns) - set(rows.columns))
    if missing:
        raise ValueError(f"forward labels missing columns in {source}: {', '.join(missing)}")


def _write_progress(
    root: Path,
    step: str,
    completed: int,
    total: int,
    *,
    shard: str | None = None,
    failure_type: str | None = None,
    failure_message: str | None = None,
) -> None:
    _write_json(
        root / "progress.json",
        {
            "stage": "shsz_development_label_split",
            "step": step,
            "completed_shards": int(completed),
            "total_shards": int(total),
            "last_shard": shard,
            "failure_type": failure_type,
            "failure_message": failure_message,
            "pid": os.getpid(),
            "peak_rss_bytes": _peak_rss_bytes(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _file_evidence(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(root)),
        "row_count": int(pq.ParquetFile(path).metadata.num_rows),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}-", suffix=".tmp", delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024
