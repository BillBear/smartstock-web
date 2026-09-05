"""Frozen offline swing research contract; never imports application services."""
from datetime import date
import hashlib
import json
import math
import re


# Changes here require a new approved protocol, not a CLI tuning parameter.
_FROZEN = {
    "schema_version": "swing-quality-v1",
    "identity": {"user_id": "default", "strategy_code": "trend_breakout", "risk_level": "medium"},
    "primary_horizon": 10, "auxiliary_horizons": [5, 20],
    "primary_k": 5, "auxiliary_ks": [3, 10],
    "dates": {
        "research": ["2024-09-01", "2026-08-31"], "warmup_start": "2024-01-01",
        "max_warmup_bars": 120, "development": ["2024-09-01", "2025-08-31"],
        "validation": ["2025-09-01", "2026-02-28"],
        "walk_forward": ["2026-03-01", "2026-08-31"],
        "walk_forward_frequency": "monthly_prior_information_only",
        "historical_status": "retrospective_not_independent_unseen",
        "tuning_segment": "development_only",
        "purge_embargo": "actual_label_end_overlap_20_valid_bars",
        "calendar_policy": "same_date_daily_bar_no_trade_cal_or_weekday_inference",
    },
    "ranking": {
        "backend_rank_field": "rank_no", "ui_rank_field": "ui_rank_no",
        "ui_order_policy": "record_separately_never_substitute_backend_rank",
        "tie_breakers": ["rank_no", "symbol"],
        "baseline_kinds": ["observed_production", "reconstructed_research", "same_input_parity"],
        "baseline_comparison": "within_kind_only",
    },
    "labels": {
        "entry": "next_valid_bar_open_after_signal_inputs_available",
        "exit": "hth_valid_bar_close_entry_is_bar_1", "immature": None,
        "adjustment": "future_factors_labels_only_entry_scale",
        "uncertain_fills": "flag_not_assumed_tradable",
        "late_input": "exclude_if_available_after_entry",
        "missing_outcomes": "disclose_delays_and_conservative_sensitivity_no_promotion_if_unbounded",
    },
    "missing_labels": {
        "value": None, "refill": False, "count_as_loss": False, "count_as_cash": False,
        "denominator": "min_k_original_daily_candidate_count",
        "report": ["observed", "planned_slots", "evaluable_dates", "coverage"],
        "duplicate_dates": "quarantine_not_silent_deduplication",
    },
    "metrics": {
        "positive_label": "horizon_net_return_gt_zero",
        "ndcg": "v1_2_gain_max_zero_net_return_discount_log2_rank_plus_1_ideal_original_pool",
        "ndcg_k": 10, "zero_ideal_ndcg": 0, "severe_loss_pct": -8.0,
        "daily_aggregation": "equal_weight_dates",
        "lift": "daily_topk_positive_rate_divided_by_daily_pool_positive_rate_then_date_mean",
        "zero_pool_positive_rate_lift": None,
        "comparison": "same_pool_dates_labels_costs_horizon",
        "cash_veto": "preserve_slots_no_refill_report_invested_and_cash_separately",
    },
    "experiments": [
        {"id": "E1", "variable": "same_source_dd_prob_ascending",
         "requires": "homogeneous_probability_provenance", "tie_breakers": ["rank_no", "symbol"]},
        {"id": "E2", "variable": "proxy_turnover_to_same_day_turnover_rate",
         "requires": "proxy_was_used_coverage_and_same_input_parity"},
        {"id": "E3", "variable": "recorded_fused_vs_prefusion_rule_same_input_postprocessing",
         "requires": "complete_prefusion_trace_or_strict_asof_model",
         "missing_trace": "unavailable_never_invert_raw_total"},
    ],
    "qualification": {
        "minimum_signal_dates": 120, "minimum_paired_dates": 60,
        "minimum_required_data_coverage": 0.99, "minimum_optional_field_coverage": 0.95,
        "minimum_market_states": 2,
        "required_improvements": ["top5_10d_median", "ndcg_at_10", "top5_pool_excess"],
        "absolute_net_mean_gt": 0, "severe_loss_must_not_increase": True,
        "source_direction": "all_sources_and_tushare_only_consistent_same_pool",
        "market_state_direction": "no_material_reversal_report_unknown_and_sample_counts",
        "sensitivity": "remove_any_one_date_or_symbol_gain_stays_positive",
        "auxiliary_reversal": "explain_and_do_not_promote",
        "bootstrap": {"unit": "contiguous_valid_trading_date_blocks",
                      "block_bars_by_horizon": {"5": 5, "10": 10, "20": 20},
                      "iterations": 10000, "seed": 20260830, "confidence": 0.95,
                      "ci_lower_bound_gt": 0},
        "multiple_testing": {"p_value": "paired_date_block_permutation", "correction": "holm",
                             "family": ["E1", "E2", "E3"], "alpha": 0.05},
        "execution": "same_capital_positions_exits_is_oos_walk_forward_drawdown_not_worse_return_drawdown_not_lower",
        "slippage_stress_multipliers": [1, 2],
        "block_evidence": "report_block_count_continuity_overlap_and_permutation_assumptions_no_strong_small_sample_claims",
        "max_shadow_candidates": 1,
        "production_gates": "preserve_live_gate_rules_separate_human_approval",
        "automatic_promotion": False,
        "outcomes": ["shadow_candidate", "no_shadow_candidate", "insufficient_evidence", "data_blocked"],
    },
}
_COST_RULES = {
    "provenance": "current_saved_profile_not_proven_historical_asof",
    "ranking_cost_model": "same_frozen_two_sided_commission_and_slippage",
    "execution_cost_model": "separate_date_effective_tax_minimum_commission_same_notional",
    "historical_actual_fees_verified": False,
}
_BASELINE_SHA = "704a5e5429f01395214fcb769c2747d6f637f308"
_KNOWN_EXAMINED = ("2026-06-23", "2026-09-04")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _json_value(value):
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("protocol object keys must be strings")
        for item in value.values():
            _json_value(item)
    elif type(value) is list:
        for item in value:
            _json_value(item)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("protocol must contain JSON values")
    elif type(value) is float and not math.isfinite(value):
        raise ValueError("protocol numbers must be finite")


def _keys(value, expected, field):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f"{field}: missing or unknown fields")


def _intervals(values, examined):
    if type(values) is not list:
        raise ValueError("intervals must be lists")
    for item in values:
        fields = {"start", "end", "status", "basis", "source"} if examined else {"start", "end"}
        _keys(item, fields, "interval")
        for key in ("start", "end"):
            value = item[key]
            if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("interval dates must be YYYY-MM-DD")
            date.fromisoformat(value)
        if item["start"] > item["end"]:
            raise ValueError("interval start exceeds end")
        if examined and (item["status"] != "previously_examined" or any(
                type(item[key]) is not str or not item[key].strip() for key in ("basis", "source"))):
            raise ValueError("examined interval requires status and provenance")
    return values


def validate_protocol(config: dict) -> dict:
    """Validate frozen policy, not dataset compliance or promotion eligibility.

    Only top-level generated_at is runtime metadata. All source/cost provenance
    remains hashed. Unseen interval declarations still require first-capture
    evidence from the forward observer; this function cannot prove that evidence.
    """
    if type(config) is not dict:
        raise ValueError("protocol must be a dict")
    _json_value(config)
    try:
        protocol = json.loads(_canonical(config))
    except (TypeError, ValueError) as exc:
        raise ValueError("protocol must contain finite JSON values") from exc
    if "generated_at" in protocol and type(protocol["generated_at"]) is not str:
        raise ValueError("generated_at must be a string")
    protocol.pop("generated_at", None)
    supplied_hash = protocol.pop("protocol_sha256", None)
    _keys(protocol, {*_FROZEN, "sources", "costs", "previously_examined_intervals",
                     "claimed_unseen_intervals"}, "protocol")
    for field, expected in _FROZEN.items():
        if _canonical(protocol[field]) != _canonical(expected):
            raise ValueError(f"{field}: differs from frozen swing-quality-v1 policy")

    sources = protocol["sources"]
    _keys(sources, {"production_baseline_sha", "application_head_sha", "research_head_sha",
                    "model_version", "model_policy"}, "sources")
    for key in ("production_baseline_sha", "application_head_sha", "research_head_sha"):
        if type(sources[key]) is not str or not re.fullmatch(r"[0-9a-f]{40}", sources[key]):
            raise ValueError(f"sources.{key}: full lowercase commit SHA required")
    if sources["production_baseline_sha"] != _BASELINE_SHA:
        raise ValueError("production baseline cannot move")
    if sources["model_policy"] != "existing_only_no_retraining_or_promotion":
        raise ValueError("model policy cannot change")
    if sources["model_version"] is not None and (
            type(sources["model_version"]) is not str or not sources["model_version"].strip()):
        raise ValueError("model_version must be a recorded version or null when unknown")

    costs = protocol["costs"]
    _keys(costs, {*_COST_RULES, "commission", "slippage", "source", "config_sha256"}, "costs")
    for field, expected in _COST_RULES.items():
        if _canonical(costs[field]) != _canonical(expected):
            raise ValueError(f"costs.{field}: frozen cost provenance policy required")
    for field in ("commission", "slippage"):
        if type(costs[field]) not in (int, float) or not 0 <= costs[field] < 0.5:
            raise ValueError(f"costs.{field}: finite rate in [0, 0.5) required")
    if type(costs["source"]) is not str or not costs["source"].strip():
        raise ValueError("costs.source required")
    if type(costs["config_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", costs["config_sha256"]):
        raise ValueError("costs.config_sha256 required")

    examined = _intervals(protocol["previously_examined_intervals"], examined=True)
    unseen = _intervals(protocol["claimed_unseen_intervals"], examined=False)
    # Conservatively protect the whole legacy response envelope, not only signal dates.
    if not any(item["start"] <= _KNOWN_EXAMINED[0] and item["end"] >= _KNOWN_EXAMINED[1]
               for item in examined):
        raise ValueError("known V1.2 examined label window must remain disclosed")
    for item in unseen:
        if item["start"] <= _FROZEN["dates"]["research"][1]:
            raise ValueError("retrospective research cannot be independent unseen evidence")
        if any(item["start"] <= prior["end"] and prior["start"] <= item["end"] for prior in examined):
            raise ValueError("claimed unseen interval overlaps examined inputs or labels")

    digest = hashlib.sha256(_canonical(protocol).encode("utf-8")).hexdigest()
    if "protocol_sha256" in config and supplied_hash != digest:
        raise ValueError("protocol_sha256 mismatch")
    protocol["protocol_sha256"] = digest
    return protocol
