from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

import pandas as pd


def audit_label_sample_quality(
    df: pd.DataFrame,
    label_col: str,
    return_col: str,
    horizon_days: int = 10,
    min_daily_count: int = 500,
    min_full_market_daily_count: int = 5000,
    expected_label_rate: float = 0.20,
    label_rate_tolerance: float = 0.08,
) -> Dict[str, Any]:
    if df is None or df.empty:
        return {
            "summary": {"row_count": 0, "symbol_count": 0, "date_count": 0},
            "findings": [_finding("empty_dataset", "critical", "No rows available for label/sample audit.")],
            "safe_for_model_promotion": False,
        }

    local = df.copy()
    local["date"] = pd.to_datetime(local["date"], errors="coerce")
    local = local[local["date"].notna()].copy()
    local["date_text"] = local["date"].dt.date.astype(str)
    local["symbol"] = local["symbol"].astype(str).str.zfill(6)
    local[label_col] = pd.to_numeric(local[label_col], errors="coerce")
    local[return_col] = pd.to_numeric(local[return_col], errors="coerce")

    findings: List[Dict[str, Any]] = []
    if local.duplicated(["date_text", "symbol"]).any():
        duplicate_count = int(local.duplicated(["date_text", "symbol"]).sum())
        findings.append(
            _finding(
                "duplicate_date_symbol_grain",
                "critical",
                f"{duplicate_count} rows duplicate the expected date+symbol grain.",
                {"duplicate_count": duplicate_count},
            )
        )

    daily_count = local.groupby("date_text").size()
    low_daily = daily_count[daily_count < int(min_daily_count)]
    if not low_daily.empty:
        findings.append(
            _finding(
                "daily_cross_section_below_minimum",
                "high",
                f"{len(low_daily)} dates have fewer than {int(min_daily_count)} rows.",
                {
                    "date_count": int(len(low_daily)),
                    "min_observed_daily_count": int(daily_count.min()),
                    "example_dates": low_daily.head(10).to_dict(),
                },
            )
        )

    median_daily_count = float(daily_count.median()) if not daily_count.empty else 0.0
    if median_daily_count < int(min_full_market_daily_count):
        findings.append(
            _finding(
                "not_full_market_cross_section",
                "high",
                f"Median daily rows {median_daily_count:.0f} are below full-market threshold {int(min_full_market_daily_count)}.",
                {
                    "median_daily_count": median_daily_count,
                    "required_daily_count": int(min_full_market_daily_count),
                },
            )
        )

    label_rate = local.groupby("date_text")[label_col].mean().dropna()
    unreliable_label_dates = label_rate[
        (label_rate < float(expected_label_rate) - float(label_rate_tolerance))
        | (label_rate > float(expected_label_rate) + float(label_rate_tolerance))
    ]
    if not unreliable_label_dates.empty:
        findings.append(
            _finding(
                "daily_label_rate_unstable",
                "medium",
                f"{len(unreliable_label_dates)} dates have {label_col} rate outside expected tolerance.",
                {
                    "expected_label_rate": float(expected_label_rate),
                    "tolerance": float(label_rate_tolerance),
                    "min_rate": round(float(label_rate.min()), 6) if not label_rate.empty else None,
                    "median_rate": round(float(label_rate.median()), 6) if not label_rate.empty else None,
                    "max_rate": round(float(label_rate.max()), 6) if not label_rate.empty else None,
                },
            )
        )

    if "name" in local.columns:
        name_text = local["name"].astype(str).str.strip()
        symbol_text = local["symbol"].astype(str).str.zfill(6)
        missing_name_rate = float(((name_text == "") | (name_text == symbol_text)).mean())
        if missing_name_rate > 0.5:
            findings.append(
                _finding(
                    "name_missing_or_symbol_only",
                    "medium",
                    f"{missing_name_rate:.1%} rows have missing names or names equal to symbols.",
                    {"affected_rate": round(missing_name_rate, 6)},
                )
            )

    if local[return_col].isna().any() or local[label_col].isna().any():
        findings.append(
            _finding(
                "missing_labels_or_returns",
                "critical",
                "Some rows have null label or future return values.",
                {
                    "label_null_rate": round(float(local[label_col].isna().mean()), 6),
                    "return_null_rate": round(float(local[return_col].isna().mean()), 6),
                },
            )
        )

    embargo = _embargo_finding(local, horizon_days)
    if embargo:
        findings.append(embargo)

    summary = {
        "row_count": int(len(local)),
        "symbol_count": int(local["symbol"].nunique()),
        "date_count": int(local["date_text"].nunique()),
        "min_daily_count": int(daily_count.min()) if not daily_count.empty else 0,
        "median_daily_count": median_daily_count,
        "max_daily_count": int(daily_count.max()) if not daily_count.empty else 0,
        "label_rate": round(float(local[label_col].mean()), 6),
        "return_mean": round(float(local[return_col].mean()), 6),
    }
    return {
        "audit_type": "ml_label_sample_quality",
        "summary": summary,
        "findings": findings,
        "safe_for_model_promotion": not findings,
    }


def _embargo_finding(local: pd.DataFrame, horizon_days: int) -> Dict[str, Any] | None:
    if "split" not in local.columns:
        return None
    final_dates = local.loc[local["split"].astype(str) == "final_holdout", "date"]
    train_dates = local.loc[local["split"].astype(str) == "train", "date"]
    if final_dates.empty or train_dates.empty:
        return None
    final_start = final_dates.min()
    embargo_start = final_start - timedelta(days=max(1, int(horizon_days or 1)))
    overlap = train_dates[(train_dates >= embargo_start) & (train_dates < final_start)]
    if overlap.empty:
        return None
    return _finding(
        "final_holdout_embargo_overlap",
        "high",
        "Training rows exist inside the label lookahead embargo before final holdout.",
        {
            "final_holdout_start": final_start.date().isoformat(),
            "embargo_start": embargo_start.date().isoformat(),
            "overlap_row_count": int(len(overlap)),
            "overlap_date_count": int(overlap.dt.date.nunique()),
        },
    )


def _finding(code: str, severity: str, message: str, evidence: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "evidence": evidence or {},
    }
