"""Immutable SH/SZ-only panel rebuild from a certified raw source run."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Mapping

from . import panel as panel_module
from .manifests import CollectionManifest


UNIVERSE_ID = "shsz_a_share_v1"
ALLOWED_EXCHANGES = ("SH", "SZ")


def rebuild_shsz_research_panel(
    *,
    source_run_root: str | Path,
    universe_contract_path: str | Path,
    output_dir: str | Path,
    code_commit: str,
) -> dict[str, object]:
    """Rebuild a new SH/SZ-only panel without mutating or reusing old features.

    The source is an immutable raw run.  Every stock-code-bearing frame is
    exchange-filtered before the panel builder converts ``ts_code`` to a
    six-digit symbol.  The output contains only a derived panel and provenance,
    never a copied or modified raw source run.
    """
    source = Path(source_run_root).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    manifest_path = source / "manifests" / "full-build.json"
    contract_path = Path(universe_contract_path).expanduser().resolve()
    contract = _load_contract(contract_path, source, manifest_path)
    manifest = _load_source_manifest(manifest_path)
    trade_dates = _daily_trade_dates(manifest)
    if not trade_dates:
        raise ValueError("source full-build manifest has no usable daily partitions")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.running"
    if temporary.exists():
        raise FileExistsError(f"rebuild evidence already exists: {temporary}")
    temporary.mkdir(parents=True)
    try:
        static = panel_module._load_static_frames(source, manifest)
        calendar_lookup = panel_module._build_calendar_lookup(static["trade_cal"])
        raw_daily_rows = 0
        selected_daily_rows = 0
        emitted_symbols: set[str] = set()
        intermediate = temporary / "intermediate"
        _write_progress(temporary, "running", 0, len(trade_dates))
        for completed, trade_date in enumerate(trade_dates, start=1):
            frames = dict(static)
            frames.update(panel_module._load_daily_frames(source, manifest, trade_date))
            raw_daily_rows += len(frames.get("daily", ()))
            filtered = panel_module.filter_frames_to_exchanges(frames, ALLOWED_EXCHANGES)
            selected_daily_rows += len(filtered.get("daily", ()))
            base = panel_module._build_base_panel(
                filtered,
                industry_relative_enabled=manifest.industry_relative_enabled,
                calendar_lookup=calendar_lookup,
            )
            if not base.empty:
                emitted_symbols.update(base["symbol"].astype(str))
                panel_module._write_intermediate_shards(base, intermediate, trade_date)
            _write_progress(temporary, "running", completed, len(trade_dates), trade_date=trade_date)

        panel_output = temporary / "panel" / "stage=full-build"
        shard_paths, row_count, feature_contract_path = panel_module._finalize_shards(
            intermediate,
            panel_output,
            manifest.industry_relative_enabled,
        )
        report = {
            "schema_version": 1,
            "status": "complete_shsz_panel_rebuilt",
            "research_ready": True,
            "production_integration_allowed": False,
            "universe_id": UNIVERSE_ID,
            "allowed_exchanges": list(ALLOWED_EXCHANGES),
            "code_commit": str(code_commit),
            "source": {
                "run_root": str(source),
                "full_build_manifest_path": str(manifest_path),
                "full_build_manifest_sha256": _sha256(manifest_path),
                "universe_contract_path": str(contract_path),
                "universe_contract_sha256": _sha256(contract_path),
            },
            "input": {
                "trade_date_count": len(trade_dates),
                "raw_daily_row_count": raw_daily_rows,
                "shsz_daily_row_count_before_historical_master_join": selected_daily_rows,
                "unresolved_daily_master_symbols_excluded": list(contract.get("unresolved_daily_master_symbols", ())),
            },
            "output": {
                "panel_row_count": row_count,
                "panel_symbol_count": len(emitted_symbols),
                "panel_stage": "full-build",
                "feature_contract_sha256": _sha256(feature_contract_path),
                "shard_count": len(shard_paths),
            },
            "interpretation": (
                "This is a new SH/SZ research panel derived from certified raw partitions. "
                "It does not reuse old feature or training parquet assets and does not authorize model training or production integration."
            ),
        }
        _write_json(temporary / "panel_rebuild_manifest.json", report)
        _write_progress(temporary, "complete", len(trade_dates), len(trade_dates), trade_date=trade_dates[-1])
        os.replace(temporary, output)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            completed if "completed" in locals() else 0,
            len(trade_dates),
            trade_date=trade_date if "trade_date" in locals() else None,
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _load_contract(path: Path, source: Path, manifest_path: Path) -> Mapping[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"universe contract is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("universe contract must be a JSON object")
    if value.get("status") != "complete_research_universe_certified" or value.get("research_ready") is not True:
        raise ValueError("universe contract is not certified for research rebuild")
    if value.get("universe_id") != UNIVERSE_ID or tuple(value.get("allowed_exchanges", ())) != ALLOWED_EXCHANGES:
        raise ValueError("universe contract does not define the SH/SZ research universe")
    contract_source = value.get("source")
    if not isinstance(contract_source, Mapping):
        raise ValueError("universe contract source is missing")
    if Path(str(contract_source.get("run_root", ""))).expanduser().resolve() != source:
        raise ValueError("universe contract source run does not match")
    if str(contract_source.get("full_build_manifest_sha256", "")) != _sha256(manifest_path):
        raise ValueError("universe contract source manifest hash does not match")
    return value


def _load_source_manifest(path: Path) -> CollectionManifest:
    if not path.is_file():
        raise FileNotFoundError(f"source full-build manifest is missing: {path}")
    manifest = CollectionManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if not manifest.ready:
        raise ValueError("source full-build manifest is not ready")
    return manifest


def _daily_trade_dates(manifest: CollectionManifest) -> tuple[str, ...]:
    dates = []
    for record in manifest.partitions:
        if record.endpoint != "daily" or record.status == "failed":
            continue
        value = str(record.key).strip()
        if len(value) != 8 or not value.isdigit():
            raise ValueError(f"daily partition has invalid trade date key: {record.key}")
        dates.append(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    if len(set(dates)) != len(dates):
        raise ValueError("source full-build manifest has duplicate daily trade-date keys")
    return tuple(sorted(dates))


def _write_progress(
    root: Path,
    status: str,
    completed: int,
    total: int,
    *,
    trade_date: str | None = None,
    failure_type: str | None = None,
    failure_message: str | None = None,
) -> None:
    _write_json(
        root / "progress.json",
        {
            "stage": "shsz_panel_rebuild",
            "status": status,
            "completed_trade_dates": completed,
            "total_trade_dates": total,
            "last_trade_date": trade_date,
            "failure_type": failure_type,
            "failure_message": failure_message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _write_json(path: Path, value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}-", suffix=".tmp", delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
