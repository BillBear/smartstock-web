"""Rebuild immutable daily OOF cohort paths without production dependencies."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from app.evaluation.ml_recovery_acceptance import verify_recovery_inputs


HORIZON_SESSIONS = 10
DEFAULT_COMMISSION_PER_SIDE = 0.0003
DEFAULT_SLIPPAGE_PER_SIDE = 0.001
TERMINAL_FACTOR_TOLERANCE = 1e-8

_OOF_COLUMNS = frozenset(
    {
        "fold",
        "quadrant",
        "trade_date",
        "symbol",
        "entry_tradeable",
        "horizon_available_10d",
        "path_ambiguous_10d",
        "net_return_after_cost_10d",
    }
)
_PANEL_COLUMNS = frozenset(
    {
        "trade_date",
        "symbol",
        "next_open_date",
        "adjusted_open",
        "adjusted_close",
        "valid_ohlc",
        "is_suspended",
        "at_up_limit_open",
    }
)
_PATH_COLUMNS = (
    "fold",
    "quadrant",
    "signal_trade_date",
    "entry_trade_date",
    "exit_trade_date",
    "symbol",
    "rank_no",
    "score",
    "portfolio_mark_date",
    "cohort_net_factor",
    "daily_mark_to_market_return",
)


class MLOofDailyPathError(ValueError):
    """Raised when OOF or immutable panel schema cannot support reconstruction."""


def reconstruct_selected_daily_paths(
    *,
    oof_rows: pd.DataFrame,
    panel_rows: pd.DataFrame,
    score_column: str,
    top_k: int = 10,
    commission_per_side: float = DEFAULT_COMMISSION_PER_SIDE,
    slippage_per_side: float = DEFAULT_SLIPPAGE_PER_SIDE,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Reconstruct Top-K daily marks and fail closed on any selected-row defect."""
    if int(top_k) != top_k or top_k <= 0:
        raise MLOofDailyPathError("top_k must be a positive integer")
    if commission_per_side < 0 or slippage_per_side < 0:
        raise MLOofDailyPathError("commission and slippage must be non-negative")
    selected = _select_top_k(oof_rows, score_column=score_column, top_k=int(top_k))
    panel = _normalize_panel(panel_rows)
    panel_index = panel.set_index(["symbol", "trade_date"])
    reconstructed: list[dict[str, object]] = []
    rejection_codes: list[str] = []
    terminal_mismatch_count = 0

    for selected_row in selected.itertuples(index=False):
        path, rejection = _reconstruct_row(
            selected_row=selected_row,
            panel_index=panel_index,
            commission_per_side=float(commission_per_side),
            slippage_per_side=float(slippage_per_side),
        )
        if rejection is not None:
            rejection_codes.append(rejection)
            terminal_mismatch_count += int(rejection == "terminal_factor_mismatch")
            continue
        reconstructed.extend(path)

    rejected_count = len(rejection_codes)
    report: dict[str, object] = {
        "status": "complete" if rejected_count == 0 else "blocked",
        "top_k": int(top_k),
        "horizon_sessions": HORIZON_SESSIONS,
        "commission_per_side": float(commission_per_side),
        "slippage_per_side": float(slippage_per_side),
        "selected_row_count": int(len(selected)),
        "reconstructed_row_count": int(len(selected) - rejected_count),
        "rejected_row_count": int(rejected_count),
        "terminal_mismatch_count": int(terminal_mismatch_count),
        "rejection_codes": sorted(set(rejection_codes)),
        "all_selected_rows_reconstructed": bool(rejected_count == 0),
    }
    if rejected_count:
        return _empty_paths(), report
    paths = pd.DataFrame(reconstructed, columns=_PATH_COLUMNS)
    return paths.sort_values(
        ["fold", "quadrant", "signal_trade_date", "rank_no", "portfolio_mark_date", "symbol"],
        kind="stable",
    ).reset_index(drop=True), report


def run_oof_daily_path_reconstruction(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    panel_root: str | Path,
    candidate_run_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
) -> dict[str, object]:
    """Atomically publish a research-only reconstruction audit for an OOF run."""
    destination = Path(output_dir).expanduser().resolve()
    candidate_root = Path(candidate_run_root).expanduser().resolve()
    if "prospective-lockbox" in destination.parts or "prospective-lockbox" in candidate_root.parts:
        raise MLOofDailyPathError("path reconstruction must not read or write inside prospective-lockbox")
    if destination.exists():
        raise FileExistsError(f"path reconstruction output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete path reconstruction requires inspection: {temporary}")
    temporary.mkdir()
    try:
        _write_progress(temporary, stage="data-verify", status="running")
        inputs = verify_recovery_inputs(label_root, feature_asset_root, panel_root)
        screen_path = candidate_root / "candidate_screen.json"
        oof_path = candidate_root / "oof_predictions.parquet"
        candidate_screen = _read_json(screen_path, "candidate screen")
        if not oof_path.is_file():
            raise FileNotFoundError(f"candidate OOF predictions are missing: {oof_path}")
        oof_rows = pd.read_parquet(oof_path)
        model_selected = _select_top_k(oof_rows, score_column="model_score", top_k=10)
        baseline_selected = _select_top_k(oof_rows, score_column="baseline_score", top_k=10)
        symbols = sorted(set(model_selected["symbol"]) | set(baseline_selected["symbol"]))
        _write_progress(
            temporary,
            stage="load-panel",
            status="running",
            selected_symbol_count=len(symbols),
            model_selected_row_count=len(model_selected),
            baseline_selected_row_count=len(baseline_selected),
        )
        panel_rows = _read_selected_panel_rows(Path(inputs["panel_root"]), symbols)
        _write_progress(temporary, stage="reconstruct", status="running", panel_row_count=len(panel_rows))
        model_paths, model_report = reconstruct_selected_daily_paths(
            oof_rows=oof_rows,
            panel_rows=panel_rows,
            score_column="model_score",
            top_k=10,
        )
        baseline_paths, baseline_report = reconstruct_selected_daily_paths(
            oof_rows=oof_rows,
            panel_rows=panel_rows,
            score_column="baseline_score",
            top_k=10,
        )
        reconstruction_complete = model_report["status"] == "complete" and baseline_report["status"] == "complete"
        report: dict[str, object] = {
            "status": "complete" if reconstruction_complete else "blocked",
            "research_only": True,
            "production_integration_allowed": False,
            "code_commit": str(code_commit),
            "candidate_screen_status": str(candidate_screen.get("status", "missing")),
            "candidate_freeze_allowed": bool(candidate_screen.get("candidate_freeze_allowed", False)),
            "candidate_screen_sha256": _sha256_file(screen_path),
            "oof_predictions_sha256": _sha256_file(oof_path),
            "input_manifest": {**dict(inputs["input_manifest"]), "code_commit": str(code_commit)},
            "prospective_lockbox_read": False,
            "market_regime_reporting_available": False,
            "market_regime_reason": "No separate frozen signal-time regime contract is bound to this OOF artifact.",
            "model": model_report,
            "baseline": baseline_report,
            "portfolio_metrics_available": bool(reconstruction_complete),
            "limitations": [
                "This run reconstructs existing development OOF paths only and never fits or selects a model.",
                "A reconstructed rejected candidate remains rejected and cannot enter final holdout or production.",
                "No prospective lockbox files or outcome labels were read.",
            ],
        }
        if reconstruction_complete:
            _write_progress(temporary, stage="portfolio-metrics", status="running")
            model_paths.to_parquet(temporary / "model_daily_cohorts.parquet", index=False)
            baseline_paths.to_parquet(temporary / "baseline_daily_cohorts.parquet", index=False)
            model_portfolio, model_metrics = _aggregate_portfolio_paths(model_paths)
            baseline_portfolio, baseline_metrics = _aggregate_portfolio_paths(baseline_paths)
            model_portfolio.to_parquet(temporary / "model_portfolio_daily.parquet", index=False)
            baseline_portfolio.to_parquet(temporary / "baseline_portfolio_daily.parquet", index=False)
            report["portfolio_metrics"] = {"model": model_metrics, "baseline": baseline_metrics}
            _write_json(temporary / "portfolio_metrics.json", report["portfolio_metrics"])
        _write_json(temporary / "path_reconstruction_report.json", report)
        _write_progress(temporary, stage="complete", status=str(report["status"]))
        os.replace(temporary, destination)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            stage="failed",
            status="failed",
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _select_top_k(oof_rows: pd.DataFrame, *, score_column: str, top_k: int) -> pd.DataFrame:
    if not isinstance(oof_rows, pd.DataFrame):
        raise TypeError("oof_rows must be a pandas DataFrame")
    missing = sorted((_OOF_COLUMNS | {str(score_column)}) - set(oof_rows.columns))
    if missing:
        raise MLOofDailyPathError("OOF rows miss required columns: " + ", ".join(missing))
    rows = oof_rows.copy()
    rows["trade_date"] = _normalize_dates(rows["trade_date"], "OOF trade_date")
    rows["symbol"] = _normalize_symbols(rows["symbol"], "OOF symbol")
    rows["selected_score"] = pd.to_numeric(rows[score_column], errors="coerce")
    eligible = (
        rows["entry_tradeable"].eq(True).fillna(False)
        & rows["horizon_available_10d"].eq(True).fillna(False)
        & rows["path_ambiguous_10d"].eq(False).fillna(False)
        & np.isfinite(rows["selected_score"])
        & pd.to_numeric(rows["net_return_after_cost_10d"], errors="coerce").notna()
    )
    rows = rows.loc[eligible].copy()
    if rows.empty:
        raise MLOofDailyPathError("OOF rows have no execution-eligible scored candidates")
    if rows.duplicated(["fold", "quadrant", "trade_date", "symbol"]).any():
        raise MLOofDailyPathError("OOF rows have duplicate fold/quadrant/trade_date/symbol keys")
    rows = rows.sort_values(
        ["fold", "quadrant", "trade_date", "selected_score", "symbol"],
        ascending=[True, True, True, False, True],
        kind="stable",
    )
    selected = rows.groupby(["fold", "quadrant", "trade_date"], sort=False, group_keys=False).head(top_k).copy()
    selected["rank_no"] = selected.groupby(["fold", "quadrant", "trade_date"], sort=False).cumcount() + 1
    selected["selected_score"] = pd.to_numeric(selected["selected_score"], errors="raise")
    return selected.reset_index(drop=True)


def _normalize_panel(panel_rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel_rows, pd.DataFrame):
        raise TypeError("panel_rows must be a pandas DataFrame")
    missing = sorted(_PANEL_COLUMNS - set(panel_rows.columns))
    if missing:
        raise MLOofDailyPathError("panel rows miss required columns: " + ", ".join(missing))
    panel = panel_rows.loc[:, list(_PANEL_COLUMNS)].copy()
    panel["trade_date"] = _normalize_dates(panel["trade_date"], "panel trade_date")
    panel["next_open_date"] = _normalize_optional_dates(panel["next_open_date"], "panel next_open_date")
    panel["symbol"] = _normalize_symbols(panel["symbol"], "panel symbol")
    if panel.duplicated(["symbol", "trade_date"]).any():
        raise MLOofDailyPathError("panel rows have duplicate symbol/trade_date keys")
    for column in ("adjusted_open", "adjusted_close"):
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    for column in ("valid_ohlc", "is_suspended", "at_up_limit_open"):
        panel[column] = panel[column].eq(True).fillna(False)
    return panel


def _reconstruct_row(
    *,
    selected_row: Any,
    panel_index: pd.DataFrame,
    commission_per_side: float,
    slippage_per_side: float,
) -> tuple[list[dict[str, object]], str | None]:
    symbol = str(selected_row.symbol)
    signal_date = str(selected_row.trade_date)
    signal = _panel_record(panel_index, symbol, signal_date)
    expected_date = _date_value(None if signal is None else signal.next_open_date)
    if signal is None or expected_date is None:
        return [], "missing_entry_session"

    entry_date = expected_date
    previous_close: float | None = None
    factor = 1.0
    path: list[dict[str, object]] = []
    for session_offset in range(HORIZON_SESSIONS):
        current = _panel_record(panel_index, symbol, expected_date)
        if current is None:
            return [], "missing_future_session"
        opening = _positive_float(current.adjusted_open)
        closing = _positive_float(current.adjusted_close)
        if opening is None or closing is None:
            return [], "invalid_adjusted_price"
        if session_offset == 0 and (
            not bool(current.valid_ohlc) or bool(current.is_suspended) or bool(current.at_up_limit_open)
        ):
            return [], "entry_tradeability_contradiction"
        previous_factor = factor
        if session_offset == 0:
            factor = closing / (opening * (1.0 + slippage_per_side)) * (1.0 - commission_per_side)
        else:
            if previous_close is None or previous_close <= 0:
                return [], "invalid_adjusted_price"
            factor *= closing / previous_close
        if session_offset == HORIZON_SESSIONS - 1:
            factor *= (1.0 - slippage_per_side) * (1.0 - commission_per_side)
        path.append(
            {
                "fold": int(selected_row.fold),
                "quadrant": str(selected_row.quadrant),
                "signal_trade_date": signal_date,
                "entry_trade_date": entry_date,
                "exit_trade_date": None,
                "symbol": symbol,
                "rank_no": int(selected_row.rank_no),
                "score": float(selected_row.selected_score),
                "portfolio_mark_date": expected_date,
                "cohort_net_factor": float(factor),
                "daily_mark_to_market_return": float(factor / previous_factor - 1.0),
            }
        )
        previous_close = closing
        if session_offset < HORIZON_SESSIONS - 1:
            expected_date = _date_value(current.next_open_date)
            if expected_date is None:
                return [], "nonconsecutive_future_session"

    expected_factor = float(pd.to_numeric(pd.Series([selected_row.net_return_after_cost_10d]), errors="coerce").iloc[0]) + 1.0
    if not np.isfinite(expected_factor) or not np.isclose(factor, expected_factor, rtol=0.0, atol=TERMINAL_FACTOR_TOLERANCE):
        return [], "terminal_factor_mismatch"
    for point in path:
        point["exit_trade_date"] = str(path[-1]["portfolio_mark_date"])
    return path, None


def _panel_record(panel_index: pd.DataFrame, symbol: str, trade_date: str) -> Any | None:
    try:
        return panel_index.loc[(symbol, trade_date)]
    except KeyError:
        return None


def _normalize_dates(values: pd.Series, source: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce")
    if dates.isna().any():
        raise MLOofDailyPathError(f"{source} contains an invalid date")
    return dates.dt.strftime("%Y-%m-%d")


def _normalize_optional_dates(values: pd.Series, source: str) -> pd.Series:
    raw = values.astype("string")
    present = raw.notna() & raw.str.strip().ne("")
    normalized = pd.Series(pd.NA, index=values.index, dtype="string")
    if present.any():
        normalized.loc[present] = _normalize_dates(raw.loc[present], source).astype("string")
    return normalized


def _normalize_symbols(values: pd.Series, source: str) -> pd.Series:
    raw = values.astype("string").str.strip().str.split(".", regex=False).str[0]
    if raw.isna().any() or raw.str.fullmatch(r"\d{1,6}").eq(False).any():
        raise MLOofDailyPathError(f"{source} contains an invalid symbol")
    return raw.str.zfill(6)


def _positive_float(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) and np.isfinite(parsed) and float(parsed) > 0 else None


def _date_value(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def _empty_paths() -> pd.DataFrame:
    return pd.DataFrame(columns=_PATH_COLUMNS)


def _read_selected_panel_rows(panel_root: Path, symbols: list[str]) -> pd.DataFrame:
    if not symbols:
        raise MLOofDailyPathError("no selected symbols available for panel reconstruction")
    intermediate = panel_root / "intermediate"
    if not intermediate.is_dir():
        raise FileNotFoundError(f"certified panel intermediate directory is missing: {intermediate}")
    dataset = ds.dataset(intermediate, format="parquet", partitioning="hive")
    table = dataset.to_table(columns=sorted(_PANEL_COLUMNS), filter=ds.field("symbol").isin(symbols))
    rows = table.to_pandas()
    if rows.empty:
        raise MLOofDailyPathError("certified panel has no rows for selected OOF symbols")
    return rows


def _aggregate_portfolio_paths(paths: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    if paths.empty:
        raise MLOofDailyPathError("cannot aggregate an empty reconstructed path")
    cohort = (
        paths.groupby(
            ["fold", "quadrant", "signal_trade_date", "entry_trade_date", "exit_trade_date", "portfolio_mark_date"],
            sort=True,
        )["cohort_net_factor"]
        .mean()
        .reset_index()
    )
    daily_rows: list[dict[str, object]] = []
    metrics: dict[str, object] = {}
    for (fold, quadrant), current in cohort.groupby(["fold", "quadrant"], sort=True):
        marks, summary = _aggregate_single_portfolio(current)
        for mark in marks:
            mark["fold"] = int(fold)
            mark["quadrant"] = str(quadrant)
        daily_rows.extend(marks)
        metrics[f"fold_{int(fold)}_{str(quadrant)}"] = summary
    return pd.DataFrame(daily_rows).sort_values(["fold", "quadrant", "portfolio_mark_date"], kind="stable"), metrics


def _aggregate_single_portfolio(cohorts: pd.DataFrame) -> tuple[list[dict[str, object]], dict[str, float | int]]:
    by_entry = {date: rows.copy() for date, rows in cohorts.groupby("entry_trade_date", sort=True)}
    by_mark = {date: rows.copy() for date, rows in cohorts.groupby("portfolio_mark_date", sort=True)}
    active: dict[str, dict[str, float | str]] = {}
    cash = 1.0
    marks: list[dict[str, object]] = []
    for mark_date in sorted(by_mark):
        for entry in by_entry.get(mark_date, pd.DataFrame()).itertuples(index=False):
            cohort_id = str(entry.signal_trade_date)
            allocation = cash / HORIZON_SESSIONS
            cash -= allocation
            active[cohort_id] = {"value": allocation, "factor": 1.0, "exit_trade_date": str(entry.exit_trade_date)}
        for row in by_mark[mark_date].itertuples(index=False):
            cohort_id = str(row.signal_trade_date)
            position = active.get(cohort_id)
            if position is None:
                raise MLOofDailyPathError(f"portfolio cohort is missing active allocation: {cohort_id}/{mark_date}")
            factor = float(row.cohort_net_factor)
            previous_factor = float(position["factor"])
            position["value"] = float(position["value"]) * factor / previous_factor
            position["factor"] = factor
        for cohort_id, position in list(active.items()):
            if str(position["exit_trade_date"]) == mark_date:
                cash += float(position["value"])
                active.pop(cohort_id)
        equity = cash + sum(float(position["value"]) for position in active.values())
        rolling_high = max([1.0, *(float(mark["equity_factor"]) for mark in marks), equity])
        marks.append(
            {
                "portfolio_mark_date": mark_date,
                "equity_factor": float(equity),
                "drawdown": float(equity / rolling_high - 1.0),
                "cash_weight": float(cash / equity) if equity > 0 else 0.0,
                "active_cohort_count": int(len(active)),
            }
        )
    final_equity = float(marks[-1]["equity_factor"])
    max_drawdown = float(min(mark["drawdown"] for mark in marks))
    net_return = final_equity - 1.0
    return_drawdown = net_return / abs(max_drawdown) if max_drawdown < 0 else None
    return marks, {
        "date_count": len(marks),
        "net_portfolio_return": float(net_return),
        "maximum_drawdown": max_drawdown,
        "return_drawdown": return_drawdown,
    }


def _read_json(path: Path, source: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{source} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MLOofDailyPathError(f"{source} is invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise MLOofDailyPathError(f"{source} must contain a JSON object: {path}")
    return value


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_progress(directory: Path, *, stage: str, status: str, **details: object) -> None:
    _write_json(
        directory / "progress.json",
        {
            "stage": stage,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
