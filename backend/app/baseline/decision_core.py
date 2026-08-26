"""Canonical projection of persisted decision fields without business logic."""

import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping, Sequence


_FLOAT_QUANTUM = Decimal("0.000001")
_CORE_FIELDS = (
    "symbol",
    "rank_no",
    "action",
    "executable",
    "up_prob",
    "dd_prob",
    "expected_return_pct",
    "position_pct",
    "entry_range",
    "take_profit",
    "stop_loss",
)


def project_decision_core(pick: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only persisted decision fields, representing absent legacy fields as null."""
    if not isinstance(pick, Mapping):
        raise TypeError("decision core pick must be a mapping")

    decision = pick.get("decision")
    score_breakdown = pick.get("score_breakdown")
    projected = {field: _normalize_value(pick.get(field)) for field in _CORE_FIELDS}
    projected["decision"] = {
        "grade": _normalize_value(decision.get("grade"))
        if isinstance(decision, Mapping)
        else None
    }
    projected["score_breakdown"] = {
        "raw_total": _normalize_value(score_breakdown.get("raw_total"))
        if isinstance(score_breakdown, Mapping)
        else None,
        "total": _normalize_value(score_breakdown.get("total"))
        if isinstance(score_breakdown, Mapping)
        else None,
    }
    return projected


def canonical_json_bytes(candidates: Sequence[Mapping[str, Any]]) -> bytes:
    """Serialize decision-core candidates in a stable, UTF-8 JSON representation."""
    projected = [project_decision_core(candidate) for candidate in candidates]
    projected.sort(key=_candidate_sort_key)
    return json.dumps(
        projected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def decision_core_sha256(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Return the SHA-256 of the canonical, projected decision core."""
    return hashlib.sha256(canonical_json_bytes(candidates)).hexdigest()


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[int, int, Any, str]:
    rank_no = candidate["rank_no"]
    if rank_no is None:
        return (1, 1, "", str(candidate["symbol"] or ""))
    if isinstance(rank_no, (int, float)) and not isinstance(rank_no, bool):
        return (0, 0, rank_no, str(candidate["symbol"] or ""))
    return (0, 1, str(rank_no), str(candidate["symbol"] or ""))


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("decision core does not accept NaN or infinity")
        quantized = Decimal(str(value)).quantize(_FLOAT_QUANTUM, rounding=ROUND_HALF_EVEN)
        return 0.0 if quantized == 0 else float(quantized)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decision core does not accept NaN or infinity")
        quantized = value.quantize(_FLOAT_QUANTUM, rounding=ROUND_HALF_EVEN)
        return 0.0 if quantized == 0 else float(quantized)
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value
