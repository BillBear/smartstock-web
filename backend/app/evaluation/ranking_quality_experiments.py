"""Read-only single-variable ranking experiments over labeled snapshots."""
from __future__ import annotations

from collections import defaultdict
import math
import random
from statistics import mean, median
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


HORIZONS = (5, 10, 20)
PRIMARY_HORIZON = 10
TOP_KS = (3, 5, 10)
SEVERE_LOSS_PCT = -8.0


def validate_swing_pair(baseline, trial):
    """Reject changed identities, labels or original denominators before sorting."""
    from app.evaluation.ranking_quality_diagnosis import validate_snapshot_identity
    for rows in (baseline, trial):
        validate_snapshot_identity(rows)
    fields = ('baseline_kind', 'user_id', 'strategy_code', 'risk_level',
              'label_end_dates', 'horizon_paths', 'entry_date', 'entry_price',
              'history_source', 'probability_source') + tuple(f'future_return_{h}d' for h in HORIZONS)
    def projection(rows):
        return {(r['trade_date'], r['symbol']): {k:r.get(k) for k in fields} for r in rows}
    if projection(baseline) != projection(trial):
        raise ValueError('changed frozen pool, label, source or baseline identity')


def swing_holm(p_values):
    family = ('E1', 'E2', 'E3')
    values = {key:1.0 if p_values.get(key) is None else p_values[key] for key in family}
    adjusted, previous = {}, 0.0
    for i, key in enumerate(sorted(family, key=lambda k:(values[k], k))):
        previous = max(previous, min(1.0, (len(family)-i)*values[key]))
        adjusted[key] = dict(p_value=values[key], adjusted_p=previous, reject=previous <= .05,
                             family=list(family), unavailable_or_insufficient=p_values.get(key) is None)
    return adjusted


def swing_block_inference(deltas, trading_dates, horizon):
    """Paired cluster bootstrap and independent block sign randomization under H0."""
    index = {day:i for i,day in enumerate(trading_dates)}
    if len(index) != len(trading_dates) or list(trading_dates) != sorted(trading_dates):
        raise ValueError('actual trading-date index must be unique and sorted')
    runs = []
    for day in sorted(deltas):
        if day not in index:
            raise ValueError('evaluation date absent from dataset actual-date index')
        if not runs or index[day] != index[runs[-1][-1]]+1:
            runs.append([])
        runs[-1].append(day)
    blocks = [run[i:i+horizon] for run in runs for i in range(0,len(run),horizon)]
    count = sum(len(block) == horizon for block in blocks)
    result = dict(status='insufficient_blocks', p_value=None, ci=dict(lower=None,upper=None),
        run_lengths=list(map(len,runs)), block_count=count, blocks=blocks, block_length=horizon,
        residual_block_count=sum(len(b)<horizon for b in blocks), iterations=10000, seed=20260830,
        method='nonoverlapping_contiguous_observed_date_cluster_bootstrap',
        null_method='paired_block_sign_randomization_one_sided_improvement',
        assumptions='exchangeable symmetric block effects under null; dependence within holding blocks; '
                    'adjacent block dependence may remain; at least three full blocks required',
        overlap='forward labels overlap within blocks; stock rows never resampled independently')
    if count < 3:
        return result
    generator = random.Random(20260830)
    summaries = [(sum(deltas[d] for d in b),len(b)) for b in blocks]
    observed = sum(deltas.values())/len(deltas)
    samples, extreme = [], 0
    for _ in range(10000):
        selected = [summaries[generator.randrange(len(summaries))] for _ in summaries]
        samples.append(sum(x for x,n in selected)/sum(n for x,n in selected))
    # A separate RNG stream and a null-centered sign test, not a bootstrap tail.
    null_rng = random.Random(20260830)
    for _ in range(10000):
        null = sum(x*(1 if null_rng.getrandbits(1) else -1) for x,n in summaries)/len(deltas)
        extreme += null >= observed-1e-12
    samples.sort()
    result.update(status='evaluated', p_value=(extreme+1)/10001,
                  ci=dict(lower=samples[249],upper=samples[9749]))
    return result


def _swing_pair_metrics(rows, trial, trading_dates, infer=True):
    validate_swing_pair(rows, trial)
    current = _evaluate_variant(rows, 'backend_rank', lambda r:(r['rank_no'],r['symbol']))
    variant = _evaluate_variant(trial, 'trial', lambda r:(r.get('_trial_order',r['rank_no']),r['symbol']), rows)
    dates = sorted(day for day in current['_daily_primary_metrics']
                   if _daily_primary_complete(current['_daily_primary_metrics'][day]) and
                   _daily_primary_complete(variant['_daily_primary_metrics'][day]))
    narrowed = [{**v, '_daily_top5_returns':{d:v['_daily_top5_returns'][d] for d in dates}}
                for v in (current,variant)]
    paired = _paired_top5_comparison(*narrowed, 0, 20260830)
    paired.pop('bootstrap_95pct_ci',None); paired.pop('qualification',None)
    paired['lost_dates'] = sorted(set(_by_date(rows))-set(dates))
    paired['statistics_by_horizon'] = {}
    paired['auxiliary_same_date_metrics'] = {}
    pools = _by_date(rows)
    for horizon in HORIZONS:
        daily, distributions = [], []
        for source in (rows, trial):
            ordered = {d:sorted(items,key=lambda r:(r.get('_trial_order',r['rank_no']),r['symbol']))
                       for d,items in _by_date(source).items()}
            daily.append(_daily_top_k(ordered,horizon,5))
            distributions.append({d:_daily_metrics(items,f'future_return_{horizon}d',pools[d]) for d,items in ordered.items()})
        paired['auxiliary_same_date_metrics'][str(horizon)] = {}
        for k in TOP_KS:
            accepted=[d for d in dates if all(v[d]['pool_complete'] and v[d]['top_k'][str(k)]['complete'] for v in distributions)]
            summaries=[_aggregate_top_k([v[d] for d in accepted],k) for v in distributions]
            paired['auxiliary_same_date_metrics'][str(horizon)][str(k)]=dict(dates=accepted,
                baseline=summaries[0],experiment=summaries[1],
                no_reversal=bool(accepted) and _not_greater(summaries[0]['avg_return'],summaries[1]['avg_return']) and
                    _not_greater(summaries[1]['severe_loss_rate'],summaries[0]['severe_loss_rate']))
        eligible = [d for d in dates if all(v[d]['avg_return'] is not None for v in daily)]
        deltas = {d:daily[1][d]['avg_return']-daily[0][d]['avg_return'] for d in eligible}
        paired['statistics_by_horizon'][str(horizon)] = (swing_block_inference(deltas,trading_dates,horizon)
            if infer else dict(status='descriptive_only',p_value=None,ci=dict(lower=None,upper=None)))
        paired['statistics_by_horizon'][str(horizon)]['daily_deltas'] = deltas
    return dict(baseline=current, metrics=variant, paired=paired,
                sensitivity=paired['leave_one_contributor_out'])


def swing_segments(rows, protocol):
    intervals = {name:protocol['dates'][name] for name in ('development','validation','walk_forward')}
    import calendar
    for month in range(3,9):
        intervals[f'walk_forward_2026-{month:02d}'] = [f'2026-{month:02d}-01',
            f'2026-{month:02d}-{calendar.monthrange(2026,month)[1]}']
    result = {}
    for name,(start,end) in intervals.items():
        items = [r for r in rows if start <= r['trade_date'] <= end]
        excluded = {r['trade_date'] for r in items if not (r.get('label_end_dates') or {}).get('20') or
                    r['label_end_dates']['20'] > end}
        result[name] = dict(dates=sorted({r['trade_date'] for r in items}-excluded),
            excluded_dates=sorted(excluded), purge='whole_date_actual_20bar_end_no_refill')
    return result


def build_e3_rule_trial(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Replay the existing medium-risk rank path with only saved rule-side values.

    A date is eligible only when every persisted candidate has a complete trace
    and the saved fused trace reproduces the stored rank.  This is deliberately
    stricter than dropping individual rows: the counterfactual must retain the
    exact same daily candidate pool and labels as the observed ranking.
    """
    trial_rows: List[Dict[str, Any]] = []
    included_dates: List[str] = []
    excluded_dates: List[Dict[str, Any]] = []
    for trade_date, items in _by_date(rows).items():
        records, errors = [], []
        for row in items:
            record, reason = _e3_trace_record(row)
            if reason:
                errors.append(reason)
            else:
                records.append(record)
        if errors:
            excluded_dates.append(
                {
                    "trade_date": trade_date,
                    "reason": "incomplete_ml_fusion_trace",
                    "reason_counts": {reason: errors.count(reason) for reason in sorted(set(errors))},
                    "candidate_count": len(items),
                }
            )
            continue

        fused = _e3_rank_records(records, "fused")
        stored_symbols = [record["symbol"] for record in sorted(records, key=lambda record: (record["rank_no"], record["symbol"]))]
        fused_symbols = [record["symbol"] for record in fused]
        score_mismatch = any(
            abs(record["display_total"] - record["ranking_total"]) > 0.01
            for record in fused
        )
        if score_mismatch or fused_symbols != stored_symbols:
            excluded_dates.append(
                {
                    "trade_date": trade_date,
                    "reason": "fused_ranking_replay_mismatch",
                    "candidate_count": len(items),
                    "stored_symbols": stored_symbols,
                    "replayed_symbols": fused_symbols,
                }
            )
            continue

        rule = _e3_rank_records(records, "rule")
        for index, record in enumerate(rule, start=1):
            trial_rows.append(dict(record["row"], _trial_order=index))
        included_dates.append(trade_date)

    diagnostics = {
        "schema_version": "ml_fusion_trace_v2",
        "input_row_count": len(rows),
        "input_date_count": len(_by_date(rows)),
        "included_dates": included_dates,
        "excluded_dates": excluded_dates,
        "included_row_count": len(trial_rows),
        "whole_date_policy": "require_complete_trace_and_fused_rank_replay_no_row_drop_or_refill",
    }
    return {
        "rows": trial_rows,
        "unavailable_reasons": [] if trial_rows else ["no_complete_ml_fusion_trace_dates"],
        "trace_diagnostics": diagnostics,
    }


def _e3_trace_record(row: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    trace = row.get("ml_fusion_trace")
    if not isinstance(trace, dict):
        return None, "trace_missing"
    if trace.get("schema_version") != "ml_fusion_trace_v2":
        return None, "unsupported_trace_schema"
    if trace.get("status") != "applied":
        return None, f"trace_status_{trace.get('status') or 'unknown'}"
    rule = trace.get("rule") or {}
    fused = trace.get("fused") or {}
    ranking = trace.get("ranking") or {}
    inputs = trace.get("ranking_inputs") or {}
    if not all(isinstance(value, dict) for value in (rule, fused, ranking, inputs)):
        return None, "trace_section_invalid"
    if str(inputs.get("risk_level") or "") != "medium":
        return None, "risk_level_not_medium"
    for name, values in (("rule", rule), ("fused", fused)):
        for field in ("up_prob", "dd_prob", "total_score"):
            if _as_float(values.get(field)) is None:
                return None, f"{name}_{field}_missing"
    for field in ("raw_total", "total"):
        if _as_float(ranking.get(field)) is None:
            return None, f"ranking_{field}_missing"
    for field in ("expected_edge_pct", "profit_factor_proxy", "risk_adjusted_score", "main_net_inflow_yi"):
        if _as_float(inputs.get(field)) is None:
            return None, f"ranking_input_{field}_missing"
    if str(inputs.get("selection_action") or "") not in {"buy", "watch"}:
        return None, "ranking_input_selection_action_invalid"
    if str(inputs.get("confidence_level") or "") not in {"high", "medium", "low"}:
        return None, "ranking_input_confidence_invalid"
    if str(inputs.get("market_state_tag") or "") not in {"neutral", "defensive", "offensive"}:
        return None, "ranking_input_market_state_invalid"
    rank_no = _as_float(row.get("rank_no"))
    if rank_no is None or rank_no <= 0:
        return None, "stored_rank_no_invalid"

    comparisons = (
        (row.get("up_prob"), fused.get("up_prob")),
        (row.get("dd_prob"), fused.get("dd_prob")),
        (row.get("raw_total"), ranking.get("raw_total")),
        (row.get("total"), ranking.get("total")),
    )
    if any(not _e3_numbers_match(left, right) for left, right in comparisons):
        return None, "stored_trace_value_mismatch"
    return {
        "row": row,
        "symbol": str(row.get("symbol") or ""),
        "rank_no": int(rank_no),
        "rule": {field: float(rule[field]) for field in ("up_prob", "dd_prob", "total_score")},
        "fused": {field: float(fused[field]) for field in ("up_prob", "dd_prob", "total_score")},
        "ranking_total": float(ranking["total"]),
        "inputs": {
            "selection_action": str(inputs["selection_action"]),
            "confidence_level": str(inputs["confidence_level"]),
            "expected_edge_pct": float(inputs["expected_edge_pct"]),
            "profit_factor_proxy": float(inputs["profit_factor_proxy"]),
            "risk_adjusted_score": float(inputs["risk_adjusted_score"]),
            "main_net_inflow_yi": float(inputs["main_net_inflow_yi"]),
            "market_state_tag": str(inputs["market_state_tag"]),
        },
    }, None


def _e3_rank_records(records: Sequence[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    raw_values = sorted(record[source]["total_score"] for record in records)
    count = len(raw_values)
    ranked = []
    for record in records:
        raw_total = record[source]["total_score"]
        less = sum(value < raw_total for value in raw_values)
        equal = sum(value == raw_total for value in raw_values)
        relative_score = 48.0 + ((less + 0.5 * equal) / count if count > 1 else 0.5) * 24.0
        inputs = record["inputs"]
        up_prob = record[source]["up_prob"]
        dd_prob = record[source]["dd_prob"]
        edge_score = _e3_clamp(48.0 + inputs["expected_edge_pct"] * 6.5, 0.0, 100.0)
        pf_score = _e3_clamp(45.0 + (inputs["profit_factor_proxy"] - 1.0) * 22.0, 0.0, 100.0)
        quality_score = (
            up_prob * 100.0 * 0.22
            + (1.0 - dd_prob) * 100.0 * 0.20
            + inputs["risk_adjusted_score"] * 0.20
            + edge_score * 0.24
            + pf_score * 0.14
        )
        bonus = _e3_calibration_bonus(inputs, dd_prob)
        state_adjust = -2.0 if inputs["market_state_tag"] == "defensive" else (1.0 if inputs["market_state_tag"] == "offensive" else 0.0)
        display_total = _e3_clamp(raw_total * 0.34 + quality_score * 0.46 + relative_score * 0.20 + bonus + state_adjust, 0.0, 100.0)
        rank_edge = _e3_clamp(50.0 + inputs["expected_edge_pct"] * 6.0, 0.0, 100.0)
        rank_pf = _e3_clamp(45.0 + (inputs["profit_factor_proxy"] - 1.0) * 22.0, 0.0, 100.0)
        rank_score = (
            up_prob * 100.0 * 0.20
            + (1.0 - dd_prob) * 100.0 * 0.20
            + rank_edge * 0.28
            + rank_pf * 0.14
            + display_total * 0.18
        )
        ranked.append(dict(record, display_total=round(display_total, 2), rank_score=rank_score))
    return sorted(ranked, key=lambda record: (-record["rank_score"], record["rank_no"], record["symbol"]))


def _e3_calibration_bonus(inputs: Dict[str, Any], dd_prob: float) -> float:
    bonus = 2.0 if inputs["selection_action"] == "buy" else 0.0
    if inputs["confidence_level"] == "high":
        bonus += 4.0
    elif inputs["confidence_level"] == "medium":
        bonus += 2.0
    flow_yi = inputs["main_net_inflow_yi"]
    if flow_yi > 2.0:
        bonus += 2.0
    elif flow_yi < -1.0:
        bonus -= 4.0
    if dd_prob <= 0.20:
        bonus += 1.0
    edge_pct = inputs["expected_edge_pct"]
    if edge_pct < 0.6:
        bonus -= 8.0
    elif edge_pct < 1.5:
        bonus -= 3.0
    profit_factor = inputs["profit_factor_proxy"]
    if profit_factor < 1.15:
        bonus -= 6.0
    elif profit_factor < 1.30:
        bonus -= 2.0
    return bonus


def _e3_numbers_match(left: Any, right: Any) -> bool:
    first, second = _as_float(left), _as_float(right)
    return first is not None and second is not None and abs(first - second) <= 0.0001


def _e3_clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _qualification_group_evidence(groups, primary_dates):
    """Descriptive subsets cannot reintroduce dates missing from primary evidence."""
    result = {}
    primary_dates = set(primary_dates)
    for dimension in ('source', 'market_state'):
        result[dimension] = {}
        for name, group in groups[dimension].items():
            dates = sorted(primary_dates.intersection(group['paired']['matched_dates']))
            deltas = {day: group['metrics']['_daily_top5_returns'][day] -
                      group['baseline']['_daily_top5_returns'][day] for day in dates}
            result[dimension][name] = dict(dates=dates, paired_date_count=len(dates),
                mean_delta=mean(deltas.values()) if deltas else None,
                status='available' if dates else 'unavailable')
    return result


def evaluate_swing_experiments(rows, protocol, trading_dates, e2_rows=None, e2_evidence=None,
                               required_coverage=None):
    """Only the three frozen hypotheses; no strategy registration or promotion."""
    from app.evaluation.swing_protocol import validate_protocol
    protocol = validate_protocol(protocol)
    kinds = {r.get('baseline_kind') for r in rows}
    if len(kinds)>1:
        raise ValueError('observed and reconstructed baselines must not mix')
    experiments = {}
    provenance = {r.get('probability_source') for r in rows}
    e1_reasons = []
    if not rows: e1_reasons.append('empty_reference_pool')
    if len(provenance)!=1 or None in provenance or any('unknown' in str(x) for x in provenance):
        e1_reasons.append('homogeneous_known_probability_provenance_required')
    if any(_as_float(r.get('dd_prob')) is None for r in rows):
        e1_reasons.append('missing_dd_prob')
    e1 = []
    for items in _by_date(rows).values():
        e1.extend(dict(r,_trial_order=i) for i,r in enumerate(sorted(items,
            key=lambda r:(_number_or_inf(r.get('dd_prob')),r['rank_no'],r['symbol'])),1))
    e2_evidence = e2_evidence or {}
    e3_trial = build_e3_rule_trial(rows)
    e3_dates = set(e3_trial['trace_diagnostics']['included_dates'])
    e3_baseline = [row for row in rows if row.get('trade_date') in e3_dates]
    variants = {
        'E1': (rows, e1, e1_reasons, None),
        'E2': (rows, e2_rows, e2_evidence.get('unavailable_reasons',
            [] if e2_rows is not None else ['fixed_pool_turnover_replay_not_supplied']), None),
        'E3': (e3_baseline, e3_trial['rows'], e3_trial['unavailable_reasons'], e3_trial['trace_diagnostics']),
    }
    evaluation_rows_by_experiment = {}
    for name,(baseline_rows, trial, reasons, trace_diagnostics) in variants.items():
        if reasons or trial is None:
            experiments[name] = dict(status='unavailable',unavailable_reasons=reasons,metrics=None,
                paired=None,sensitivity=None,decision='insufficient_evidence',trace_diagnostics=trace_diagnostics)
            continue
        evaluation_rows_by_experiment[name] = baseline_rows
        result = _swing_pair_metrics(baseline_rows,trial,trading_dates)
        result.update(status='available',unavailable_reasons=[],segments={},groups={})
        if trace_diagnostics is not None:
            result['trace_diagnostics'] = trace_diagnostics
        for segment, meta in swing_segments(baseline_rows,protocol).items():
            accepted = set(meta['dates'])
            result['segments'][segment] = dict(**meta, **_swing_pair_metrics(
                [r for r in baseline_rows if r['trade_date'] in accepted],
                [r for r in trial if r['trade_date'] in accepted],trading_dates,False))
        dimensions = {'action':lambda r:r.get('action') or 'unknown',
            'analysis':lambda r:'full' if r.get('feature_bar_count',0)>=60 and r.get('analysis_status')!='degraded' else 'proxy_or_unknown',
            'probability_source':lambda r:r.get('probability_source') or 'unknown',
            'market_state':lambda r:r.get('market_state_tag') or 'unknown',
            'source':lambda r:'tushare_only' if str(r.get('history_source')).lower()=='tushare' else 'other'}
        for dimension,key in dimensions.items():
            # Group by baseline attributes, never trial gate outcomes: same pool.
            names = set(map(key,baseline_rows)) | ({'buy','watch'} if dimension=='action' else set())
            result['groups'][dimension] = {}
            for group in sorted(names):
                base = [r for r in baseline_rows if key(r)==group]
                ids = {(r['trade_date'],r['symbol']) for r in base}
                result['groups'][dimension][group] = _swing_pair_metrics(base,
                    [r for r in trial if (r['trade_date'],r['symbol']) in ids],trading_dates,False)
        experiments[name] = result
    holm = swing_holm({name:(r['paired']['statistics_by_horizon']['10']['p_value']
        if r['status']=='available' else None) for name,r in experiments.items()})
    for name,result in experiments.items():
        result['holm'] = holm[name]
        if result['status']!='available': continue
        paired = result['paired']; primary = paired['paired_primary_metrics']
        base,trial = primary['baseline'],primary['experiment']
        evaluation_rows = evaluation_rows_by_experiment[name]
        ci = paired['statistics_by_horizon']['10']['ci']
        q = protocol['qualification']; sensitivity = result['sensitivity']
        group_evidence = _qualification_group_evidence(result['groups'], paired['matched_dates'])
        known_states = {key:value for key,value in group_evidence['market_state'].items()
                        if key!='unknown' and value['paired_date_count'] > 0}
        state_counts = {key:value['paired_date_count'] for key,value in known_states.items()}
        adequate_states = sorted(key for key, count in state_counts.items() if count >= q['minimum_paired_dates'])
        sparse_states = {key:count for key,count in state_counts.items() if count < q['minimum_paired_dates']}
        # No state-specific sample minimum was frozen; never invent a passing one.
        checks = dict(signal_dates=len(set(r['trade_date'] for r in evaluation_rows))>=q['minimum_signal_dates'],
            paired_dates=paired['matched_date_count']>=q['minimum_paired_dates'],
            required_coverage=required_coverage is not None and required_coverage>=q['minimum_required_data_coverage'],
            optional_coverage=name!='E2' or e2_evidence.get('field_coverage',0)>=q['minimum_optional_field_coverage'],
            median=_greater(trial['top5_median'],base['top5_median']),
            ndcg=_greater(trial['ndcg_at_10'],base['ndcg_at_10']),
            excess=_greater(trial['top5_excess'],base['top5_excess']),
            severe_loss=_not_greater(trial['top5_severe_loss'],base['top5_severe_loss']),
            absolute_positive=bool(paired['matched_dates']) and mean(result['metrics']['_daily_top5_returns'][d]
                for d in paired['matched_dates'])>0,
            ci_positive=ci['lower'] is not None and ci['lower']>0, holm=holm[name]['reject'],
            leave_date=sensitivity['positive_after_every_day_removal'],
            leave_symbol=sensitivity['positive_after_every_symbol_removal'])
        source = group_evidence['source'].get('tushare_only')
        checks['source_direction'] = bool(source) and _greater(
            source['mean_delta'],0) and _greater(paired['mean_daily_top5_return_difference'],0)
        checks['market_state_coverage'] = len(adequate_states)>=q['minimum_market_states']
        checks['market_state_direction'] = bool(known_states) and all(_not_greater(0,
            v['mean_delta']) for v in known_states.values())
        checks['auxiliary_no_reversal'] = all(paired['auxiliary_same_date_metrics'][str(h)][str(k)]['no_reversal']
            for h in HORIZONS for k in TOP_KS if (h,k)!=(10,5))
        availability = dict(
            primary_inference=paired['statistics_by_horizon']['10']['status']=='evaluated' and
                paired['statistics_by_horizon']['10']['p_value'] is not None and
                all(ci[key] is not None for key in ('lower', 'upper')),
            source=bool(source) and source['status']=='available',
            market_states=bool(known_states) and all(v['status']=='available' for v in known_states.values()),
            auxiliary=all(bool(paired['auxiliary_same_date_metrics'][str(h)][str(k)]['dates'])
                for h in HORIZONS for k in TOP_KS if (h,k)!=(10,5)))
        result['qualification'] = dict(checks=checks,market_state_paired_counts=state_counts,
            evidence_available=availability, group_evidence=group_evidence,
            adequate_market_states=adequate_states, sparse_market_states=sparse_states,
            sparse_state_policy='disclosed_not_counted_as_adequate_adverse_direction_still_blocks',
            adequate_state_basis='conservative_use_existing_minimum_paired_dates_per_state_not_new_tuning',
            execution='pending_task_7', historical_production_parity='unavailable',
            source_independence='all_sources_and_tushare_only_are_not_independent_when_identical')
        result['provisional_ranking_candidate'] = all(checks.values()) and all(availability.values())
        enough = all(availability.values()) and all(checks[k] for k in ('signal_dates','paired_dates','required_coverage','optional_coverage','market_state_coverage'))
        result['decision'] = 'insufficient_evidence' if not enough or all(checks.values()) else 'no_shadow_candidate'
    available = [r for r in experiments.values() if r['status']=='available']
    return dict(experiments=experiments, candidate_pool=_candidate_pool_metrics(rows),
        decision='no_shadow_candidate' if available and all(r['decision']=='no_shadow_candidate' for r in available) else 'insufficient_evidence',
        formal_shadow_candidate=None, execution_run=False, frozen_protocol_sha256=protocol['protocol_sha256'],
        previously_examined_intervals=protocol['previously_examined_intervals'],
        historical_status='retrospective_not_independent_unseen', e2_evidence=e2_evidence,
        ui_order=_evaluate_variant(rows,'ui_order',lambda r:(r['ui_rank_no'],r['symbol']))
            if rows and all(r.get('ui_rank_no') is not None for r in rows) else dict(status='unavailable'),
        e3_future_collection='New snapshots record the trace required for E3. Existing snapshots without a complete '
            'trace remain unavailable; no historical rule scores or model outputs are reconstructed.')


def compare_current_and_a(rows: Sequence[Dict[str, Any]], bootstrap_iterations: int = 10000) -> Dict[str, Any]:
    """Forward observation only: reuse fixed-pool metrics, never select/deploy a model."""
    masked = []
    for item in rows:
        row = dict(item)
        if row.get("tradable_label") != "tradable" or row.get("history_source") != "TuShare":
            for horizon in HORIZONS:
                row[f"future_return_{horizon}d"] = None
        masked.append(row)
    baseline = _evaluate_variant(masked, "baseline_current_rank", lambda row: (float(row["rank_no"]), str(row["symbol"])))
    trial = _evaluate_feature_variant(masked, "A_dd_prob_ascending", "dd_prob", descending=False)
    paired = _paired_top5_comparison(baseline, trial, bootstrap_iterations, 20260830) if trial["status"] == "available" else {}
    return {"status": "observing_not_promoted", "candidate_pool": _candidate_pool_metrics(masked),
            "experiments": {"baseline_current_rank": baseline, "A_dd_prob_ascending": trial},
            "paired_comparison": paired, "source_policy": "TuShare_only_no_refill", "automatic_promotion": False}


def run_ranking_experiments(
    rows: Sequence[Dict[str, Any]],
    dd_prob_veto_threshold: Optional[float],
    threshold_source: Optional[str],
    bootstrap_iterations: int = 10_000,
    bootstrap_seed: int = 20260830,
) -> Dict[str, Any]:
    """Compare fixed offline ranking variants without changing production logic."""
    # Availability is an observation mask, never a candidate-selection rule.
    segments = {}
    for source in ("all_sources", "tushare_only"):
        masked = []
        for item in rows:
            row = dict(item)
            if row.get("tradable_label") != "tradable" or (source == "tushare_only" and str(row.get("history_source") or "").lower() != "tushare"):
                for horizon in HORIZONS:
                    row[f"future_return_{horizon}d"] = None
            masked.append(row)
        segments[source] = masked
    output = {
        "methodology": {
            "primary_horizon_days": PRIMARY_HORIZON,
            "daily_aggregation": "macro_equal_weight",
            "relevance_definition": "future net return is greater than zero after persisted execution costs",
            "severe_loss_definition": f"future net return <= {SEVERE_LOSS_PCT:.1f}%",
            "bootstrap": {"unit": "moving_block_of_ordered_observed_dates", "block_length_dates": PRIMARY_HORIZON, "minimum_nonoverlapping_blocks": 3, "iterations": bootstrap_iterations, "seed": bootstrap_seed},
            "missing_labels": "Never refill or treat unknown returns as cash; each K reports complete dates independently. Pool-relative metrics and NDCG require the complete original daily pool.",
            "source_sensitivity": "TuShare-only masks non-TuShare labels in the same original pool and ranking; it does not rerank a source-filtered pool. Complete source-only days require every original candidate label from TuShare.",
            "top_k_denominator": "min(K, original daily candidate count), including explicit veto cash slots",
            "experiment_c": {
                "dd_prob_veto_threshold": dd_prob_veto_threshold,
                "threshold_source": threshold_source,
                "rule": "retain original rank slots, replace known dd_prob above the existing threshold with zero-return cash, and never refill; unknown dd_prob is incomplete, not cash",
            },
        },
        "segments": {},
    }
    for source_name, source_rows in segments.items():
        output["segments"][source_name] = {
            "all_candidates": _evaluate_segment(source_rows, dd_prob_veto_threshold, threshold_source, bootstrap_iterations, bootstrap_seed),
            "action_buy": _evaluate_segment(_filter_action(source_rows, "buy"), dd_prob_veto_threshold, threshold_source, bootstrap_iterations, bootstrap_seed),
            "action_watch": _evaluate_segment(_filter_action(source_rows, "watch"), dd_prob_veto_threshold, threshold_source, bootstrap_iterations, bootstrap_seed),
        }
    output["shadow_selection"] = _shadow_selection(output["segments"])
    return output


def _evaluate_segment(
    rows: Sequence[Dict[str, Any]],
    dd_prob_veto_threshold: Optional[float],
    threshold_source: Optional[str],
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> Dict[str, Any]:
    candidate_pool = _candidate_pool_metrics(rows)
    baseline = _evaluate_variant(rows, "baseline_current_rank", lambda row: (float(row.get("rank_no") or 999999), str(row.get("symbol") or "")))
    experiments = {
        "baseline_current_rank": baseline,
        "A_dd_prob_ascending": _evaluate_feature_variant(
            rows,
            "A_dd_prob_ascending",
            "dd_prob",
            descending=False,
        ),
        "B_risk_adjusted_descending": _evaluate_feature_variant(
            rows,
            "B_risk_adjusted_descending",
            "risk_adjusted",
            descending=True,
        ),
        "C_dd_prob_veto": _evaluate_veto_variant(rows, dd_prob_veto_threshold, threshold_source),
    }
    for name, experiment in experiments.items():
        if experiment["status"] != "available":
            continue
        experiment["candidate_pool"] = candidate_pool
        experiment["paired_comparison"] = _paired_top5_comparison(
            baseline,
            experiment,
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed + sum(ord(char) for char in name),
        )
    return {
        "status": "available" if rows else "unavailable",
        "row_count": len(rows),
        "date_count": len(_by_date(rows)),
        "candidate_pool": candidate_pool,
        "experiments": experiments,
    }


def _evaluate_feature_variant(rows: Sequence[Dict[str, Any]], name: str, feature: str, descending: bool) -> Dict[str, Any]:
    missing = sum(_as_float(row.get(feature)) is None for row in rows)
    if missing:
        return {
            "status": "unavailable",
            "name": name,
            "reason": f"{missing} candidates have unavailable {feature}; no ranking feature or substitute order was invented.",
            "coverage": {"input_row_count": len(rows), "accepted_row_count": 0, "coverage": 0.0, "missing_feature_count": missing},
            "metrics": {},
            "selection_by_date": {},
        }
    direction = -1 if descending else 1
    return _evaluate_variant(rows, name, lambda row: (direction * float(row[feature]), str(row.get("symbol") or "")))


def _evaluate_veto_variant(rows: Sequence[Dict[str, Any]], threshold: Optional[float], source: Optional[str]) -> Dict[str, Any]:
    if threshold is None or not source:
        return {
            "status": "unavailable",
            "reason": "A single existing dd_prob veto threshold is unavailable; no threshold was invented.",
            "coverage": {"input_row_count": len(rows), "accepted_row_count": 0, "coverage": 0.0},
            "metrics": {},
            "selection_by_date": {},
        }
    slots = []
    for item in rows:
        row = dict(item)
        probability = _as_float(row.get("dd_prob"))
        row["_cash_slot"] = probability is not None and probability > threshold
        row["_selection_unknown"] = probability is None
        slots.append(row)
    result = _evaluate_variant(
        slots,
        "C_dd_prob_veto",
        lambda row: (float(row.get("rank_no") or 999999), str(row.get("symbol") or "")),
        pool_rows=rows,
    )
    result["threshold"] = threshold
    result["threshold_source"] = source
    result["no_refill"] = True
    return result


def _evaluate_variant(
    rows: Sequence[Dict[str, Any]],
    name: str,
    sort_key: Callable[[Dict[str, Any]], Tuple[float, str]],
    pool_rows: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    ordered_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for trade_date, items in _by_date(rows).items():
        ordered = sorted((dict(row) for row in items), key=sort_key)
        for index, row in enumerate(ordered, start=1):
            row["evaluated_rank_no"] = index
        ordered_by_date[trade_date] = ordered
    pools = _by_date(rows if pool_rows is None else pool_rows)
    accepted_count = sum(not row.get("_cash_slot") and not row.get("_selection_unknown") for items in ordered_by_date.values() for row in items)
    original_count = len(rows)
    result = {
        "status": "available",
        "name": name,
        "coverage": {
            "input_row_count": original_count,
            "accepted_row_count": accepted_count,
            "coverage": _ratio(accepted_count, original_count),
            "input_date_count": len(ordered_by_date),
            "accepted_date_count": sum(any(not row.get("_cash_slot") and not row.get("_selection_unknown") for row in items) for items in ordered_by_date.values()),
            "cash_slot_count": sum(bool(row.get("_cash_slot")) for items in ordered_by_date.values() for row in items),
            "unknown_selection_count": sum(bool(row.get("_selection_unknown")) for items in ordered_by_date.values() for row in items),
        },
        "selection_by_date": {trade_date: [str(row.get("symbol") or "") for row in items if not row.get("_cash_slot") and not row.get("_selection_unknown")] for trade_date, items in ordered_by_date.items()},
        "slot_selection_by_date": {trade_date: [None if row.get("_cash_slot") else str(row.get("symbol") or "") for row in items] for trade_date, items in ordered_by_date.items()},
        "metrics": {str(horizon): _horizon_metrics(ordered_by_date, horizon, pools) for horizon in HORIZONS},
        "_daily_top5_returns": {},
        "_daily_top5_symbols": {},
    }
    primary_daily = _daily_top_k(ordered_by_date, PRIMARY_HORIZON, 5)
    result["_daily_top5_returns"] = {trade_date: value["avg_return"] for trade_date, value in primary_daily.items() if value["avg_return"] is not None}
    result["_daily_top5_symbols"] = {trade_date: value["symbols"] for trade_date, value in primary_daily.items() if value["avg_return"] is not None}
    result["_daily_top5_contributions"] = {trade_date: value["contributions"] for trade_date, value in primary_daily.items() if value["avg_return"] is not None}
    result["_daily_primary_metrics"] = {trade_date: _daily_metrics(items, f"future_return_{PRIMARY_HORIZON}d", pools[trade_date]) for trade_date, items in ordered_by_date.items()}
    return result


def _candidate_pool_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(horizon): _pool_horizon_metrics(_by_date(rows), horizon) for horizon in HORIZONS}


def _horizon_metrics(ordered_by_date: Dict[str, List[Dict[str, Any]]], horizon: int, pools: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    return_key = f"future_return_{horizon}d"
    eligible_by_date = {
        trade_date: [row for row in rows if _slot_return(row, return_key) is not None and not row.get("_cash_slot")]
        for trade_date, rows in ordered_by_date.items()
    }
    eligible_by_date = {trade_date: rows for trade_date, rows in eligible_by_date.items() if rows}
    daily: Dict[str, Dict[str, Any]] = {}
    for trade_date, rows in ordered_by_date.items():
        daily[trade_date] = _daily_metrics(rows, return_key, pools[trade_date])
    daily_groups = [_rank_groups({day:items},return_key) for day,items in eligible_by_date.items()]
    equal_groups = []
    for i,label in enumerate(('1-5','6-10','11-20','21+')):
        values = [groups[i] for groups in daily_groups if groups[i]['candidate_count']]
        equal_groups.append(dict(rank_group=label,evaluable_dates=len(values),candidate_count=sum(v['candidate_count'] for v in values),
            **{key:_mean_or_none([v[key] for v in values]) for key in
               ('avg_return','median_return','positive_return_rate','severe_loss_rate')}))
    return {
        "horizon_days": horizon,
        "evaluated_date_count": sum(item["pool_complete"] for item in daily.values()),
        "input_date_count": len(daily),
        "complete_pool_date_count": sum(item["pool_complete"] for item in daily.values()),
        "incomplete_pool_date_count": sum(not item["pool_complete"] for item in daily.values()),
        "labeled_row_count": sum(len(rows) for rows in eligible_by_date.values()),
        "precision_at": {str(k): _mean_or_none([item["top_k"][str(k)]["positive_return_rate"] for item in daily.values()]) for k in TOP_KS},
        "ndcg_at_10": _mean_or_none([item["ndcg_at_10"] for item in daily.values()]),
        "mrr": _mean_or_none([item["mrr"] for item in daily.values()]),
        "top_k": {str(k): _aggregate_top_k(daily.values(), k) for k in TOP_KS},
        "rank_groups": _rank_groups(eligible_by_date, return_key),
        "legacy_rank_aggregation": "row_pooled_descriptive_not_protocol_date_weighted",
        "daily_equal_weight_rank_groups": equal_groups,
        "daily_equal_weight_monotonicity": _monotonic_rank_groups(equal_groups),
        "daily_equal_weight_spearman": _mean_or_none([_spearman(
            [float(r['evaluated_rank_no']) for r in items],[float(r[return_key]) for r in items])
            for items in eligible_by_date.values()]),
        "spearman_rank_vs_future_return": _spearman(
            [float(row["evaluated_rank_no"]) for rows in eligible_by_date.values() for row in rows],
            [float(row[return_key]) for rows in eligible_by_date.values() for row in rows],
        ),
        "monotonic_rank_groups": _monotonic_rank_groups(_rank_groups(eligible_by_date, return_key)),
    }


def _pool_horizon_metrics(by_date: Dict[str, List[Dict[str, Any]]], horizon: int) -> Dict[str, Any]:
    key = f"future_return_{horizon}d"
    per_day = []
    for rows in by_date.values():
        values = [float(row[key]) for row in rows if _as_float(row.get(key)) is not None]
        if values and len(values) == len(rows):
            per_day.append(_return_distribution(values))
    return {
        "horizon_days": horizon,
        "evaluated_date_count": len(per_day),
        "input_date_count": len(by_date),
        "incomplete_date_count": len(by_date) - len(per_day),
        "avg_return": _mean_or_none([item["avg_return"] for item in per_day]),
        "median_return": _mean_or_none([item["median_return"] for item in per_day]),
        "positive_return_rate": _mean_or_none([item["positive_return_rate"] for item in per_day]),
        "severe_loss_rate": _mean_or_none([item["severe_loss_rate"] for item in per_day]),
        "mean_daily_candidate_count": _mean_or_none([item["candidate_count"] for item in per_day]),
    }


def _daily_metrics(rows: Sequence[Dict[str, Any]], return_key: str, pool_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    pool_values = [_as_float(row.get(return_key)) for row in pool_rows]
    pool_complete = bool(pool_values) and all(value is not None for value in pool_values)
    values = [_slot_return(row, return_key) for row in rows]
    complete = bool(values) and all(value is not None for value in values)
    result = {
        "candidate_pool": _return_distribution(pool_values if pool_complete else []),
        "pool_complete": pool_complete,
        "top_k": {},
        "ndcg_at_10": _ndcg(rows, return_key, 10, pool_rows) if pool_complete and all(value is not None for value in values[:10]) else None,
        "mrr": next((round(1.0 / index, 6) for index, value in enumerate(values, start=1) if value > 0), 0.0) if complete else None,
    }
    for k in TOP_KS:
        top = list(rows[:k])
        result["top_k"][str(k)] = _top_k_distribution(top, return_key, result["candidate_pool"])
    return result


def _daily_top_k(ordered_by_date: Dict[str, List[Dict[str, Any]]], horizon: int, k: int) -> Dict[str, Dict[str, Any]]:
    key = f"future_return_{horizon}d"
    output = {}
    for trade_date, rows in ordered_by_date.items():
        top = rows[:k]
        values = [_slot_return(row, key) for row in top]
        complete = bool(values) and all(value is not None for value in values)
        contributions = defaultdict(float)
        if complete:
            for row, value in zip(top, values):
                if not row.get("_cash_slot"):
                    contributions[str(row.get("symbol") or "")] += value / len(top)
        output[trade_date] = {"avg_return": _mean_or_none(values) if complete else None, "symbols": [str(row.get("symbol") or "") for row in top if not row.get("_cash_slot")], "contributions": dict(contributions)}
    return output


def _slot_return(row: Dict[str, Any], key: str) -> Optional[float]:
    if row.get("_selection_unknown"):
        return None
    if row.get("_cash_slot"):
        return 0.0
    return _as_float(row.get(key))


def _top_k_distribution(rows: Sequence[Dict[str, Any]], return_key: str, pool: Dict[str, Any]) -> Dict[str, Any]:
    values = [_slot_return(row, return_key) for row in rows]
    complete = bool(values) and all(value is not None for value in values)
    distribution = _return_distribution(values if complete else [])
    if not complete:
        distribution.update({"positive_return_rate": None, "severe_loss_rate": None})
    distribution.update({
        "candidate_count": sum(not row.get("_cash_slot") and not row.get("_selection_unknown") for row in rows),
        "slot_count": len(rows),
        "cash_slot_count": sum(bool(row.get("_cash_slot")) for row in rows),
        "unknown_slot_count": sum(value is None for value in values),
        "complete": complete,
    })
    pool_avg = pool.get("avg_return")
    pool_positive = pool.get("positive_return_rate")
    distribution["relative_candidate_pool_excess_return"] = round(distribution["avg_return"] - pool_avg, 6) if distribution["avg_return"] is not None and pool_avg is not None else None
    distribution["lift_at_k"] = round(distribution["positive_return_rate"] / pool_positive, 6) if pool_positive and distribution["positive_return_rate"] is not None else None
    return distribution


def _aggregate_top_k(daily: Iterable[Dict[str, Any]], k: int) -> Dict[str, Any]:
    values = [item["top_k"][str(k)] for item in daily]
    keys = (
        "candidate_count",
        "avg_return",
        "median_return",
        "positive_return_rate",
        "severe_loss_rate",
        "relative_candidate_pool_excess_return",
        "lift_at_k",
        "slot_count",
        "cash_slot_count",
        "unknown_slot_count",
    )
    output = {key: _mean_or_none([item.get(key) for item in values]) for key in keys}
    output["mean_daily_candidate_count"] = output["candidate_count"]
    output["complete_date_count"] = sum(item["complete"] for item in values)
    output["incomplete_date_count"] = sum(not item["complete"] for item in values)
    output["input_date_count"] = len(values)
    output["completeness"] = _ratio(output["complete_date_count"], len(values))
    output['planned_slots'] = sum(item['slot_count'] for item in values)
    output['observed_slots'] = sum(item['slot_count']-item['unknown_slot_count'] for item in values)
    output['slot_coverage'] = _ratio(output['observed_slots'],output['planned_slots'])
    return output


def _return_distribution(values: Sequence[float]) -> Dict[str, Any]:
    return {
        "candidate_count": len(values),
        "avg_return": _mean_or_none(values),
        "median_return": _median_or_none(values),
        "positive_return_rate": _ratio(sum(value > 0 for value in values), len(values)),
        "severe_loss_rate": _ratio(sum(value <= SEVERE_LOSS_PCT for value in values), len(values)),
    }


def _rank_groups(by_date: Dict[str, List[Dict[str, Any]]], return_key: str) -> List[Dict[str, Any]]:
    bands = (("1-5", 1, 5), ("6-10", 6, 10), ("11-20", 11, 20), ("21+", 21, None))
    result = []
    for label, lower, upper in bands:
        values = [
            float(row[return_key])
            for rows in by_date.values()
            for row in rows
            if lower <= int(row["evaluated_rank_no"]) and (upper is None or int(row["evaluated_rank_no"]) <= upper)
        ]
        output = _return_distribution(values)
        output["rank_group"] = label
        result.append(output)
    return result


def _monotonic_rank_groups(groups: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    populated = [item["avg_return"] for item in groups if item.get("candidate_count") and item.get("avg_return") is not None]
    if len(populated) < 2:
        return {"status": "insufficient_groups", "is_monotonic": None}
    return {"status": "evaluated", "is_monotonic": all(left >= right for left, right in zip(populated, populated[1:]))}


def _paired_top5_comparison(
    baseline: Dict[str, Any],
    experiment: Dict[str, Any],
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> Dict[str, Any]:
    base_daily = baseline.get("_daily_top5_returns") or {}
    trial_daily = experiment.get("_daily_top5_returns") or {}
    dates = sorted(set(base_daily) & set(trial_daily))
    deltas = [float(trial_daily[trade_date]) - float(base_daily[trade_date]) for trade_date in dates]
    base_contributions = baseline.get("_daily_top5_contributions") or {}
    trial_contributions = experiment.get("_daily_top5_contributions") or {}
    contributions_available = bool(dates) and all(date in base_contributions and date in trial_contributions for date in dates)
    symbol_deltas = defaultdict(float)
    if contributions_available:
        for date in dates:
            for symbol in set(base_contributions[date]) | set(trial_contributions[date]):
                symbol_deltas[symbol] += trial_contributions[date].get(symbol, 0.0) - base_contributions[date].get(symbol, 0.0)
    # Zero the contributor's effect; keep date/slot weights and do not refill.
    day_removed = {date: round((sum(deltas) - delta) / len(dates), 6) for date, delta in zip(dates, deltas)}
    symbol_removed = {symbol: round((sum(deltas) - delta) / len(dates), 6) for symbol, delta in sorted(symbol_deltas.items())}
    base_metrics = baseline.get("_daily_primary_metrics") or {}
    trial_metrics = experiment.get("_daily_primary_metrics") or {}
    metric_dates = [date for date in dates if date in base_metrics and date in trial_metrics and _daily_primary_complete(base_metrics[date]) and _daily_primary_complete(trial_metrics[date])]
    result = {
        "matched_date_count": len(dates),
        "matched_dates": dates,
        "daily_top5_return_deltas": dict(zip(dates, deltas)),
        "baseline_only_date_count": len(set(base_daily) - set(trial_daily)),
        "experiment_only_date_count": len(set(trial_daily) - set(base_daily)),
        "mean_daily_top5_return_difference": _mean_or_none(deltas),
        "win_date_count": sum(delta > 0 for delta in deltas),
        "loss_date_count": sum(delta < 0 for delta in deltas),
        "tie_date_count": sum(delta == 0 for delta in deltas),
        "bootstrap_95pct_ci": _bootstrap_ci(deltas, bootstrap_iterations, bootstrap_seed),
        "improvement_unique_symbol_count": sum(delta > 0 for delta in symbol_deltas.values()),
        "improvement_dates": [trade_date for trade_date, delta in zip(dates, deltas) if delta > 0],
        "leave_one_contributor_out": {
            "status": "evaluated" if contributions_available else "insufficient_evidence",
            "method": "zero one day or one symbol's paired contribution; fixed date/slot denominators, no refill",
            "day_removed_mean_deltas": day_removed,
            "symbol_removed_mean_deltas": symbol_removed,
            "positive_after_every_day_removal": bool(day_removed) and all(value > 0 for value in day_removed.values()),
            "positive_after_every_symbol_removal": bool(symbol_removed) and all(value > 0 for value in symbol_removed.values()),
        },
        "paired_primary_metrics": {
            "matched_date_count": len(metric_dates),
            "matched_dates": metric_dates,
            "baseline": _aggregate_primary_days([base_metrics[date] for date in metric_dates]),
            "experiment": _aggregate_primary_days([trial_metrics[date] for date in metric_dates]),
        },
    }
    if metric_dates == dates:
        result["qualification"] = {key: result[key] for key in ("matched_dates", "bootstrap_95pct_ci", "leave_one_contributor_out")}
    else:
        # One narrowing step makes robustness and qualification use identical dates.
        narrowed = []
        for variant in (baseline, experiment):
            narrowed.append({**variant, "_daily_top5_returns": {
                date: variant["_daily_top5_returns"][date] for date in metric_dates}})
        result["qualification"] = _paired_top5_comparison(*narrowed, bootstrap_iterations, bootstrap_seed)["qualification"]
    return result


def _daily_primary_complete(day: Dict[str, Any]) -> bool:
    top5 = day["top_k"]["5"]
    return day["pool_complete"] and top5["complete"] and day["ndcg_at_10"] is not None


def _aggregate_primary_days(days: Sequence[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    return {
        "top5_median": _mean_or_none([day["top_k"]["5"]["median_return"] for day in days]),
        "top5_severe_loss": _mean_or_none([day["top_k"]["5"]["severe_loss_rate"] for day in days]),
        "top5_excess": _mean_or_none([day["top_k"]["5"]["relative_candidate_pool_excess_return"] for day in days]),
        "ndcg_at_10": _mean_or_none([day["ndcg_at_10"] for day in days]),
    }


def _bootstrap_ci(values: Sequence[float], iterations: int, seed: int) -> Dict[str, Any]:
    block_length = PRIMARY_HORIZON
    block_count = len(values) // block_length
    output = {"lower": None, "upper": None, "block_length_dates": block_length, "nonoverlapping_block_count": block_count,
              "method": "moving_blocks_of_ordered_observed_dates", "status": "insufficient_blocks",
              "inferential_claim": False}
    if block_count < 3 or iterations <= 0:
        output["reason"] = "At least three horizon-10 blocks and positive bootstrap iterations are required; descriptive deltas are not inferential evidence."
        return output
    generator = random.Random(seed)
    count = len(values)
    samples = []
    for _ in range(iterations):
        sampled = []
        while len(sampled) < count:
            start = generator.randrange(count - block_length + 1)
            sampled.extend(values[start:start + block_length])
        samples.append(mean(sampled[:count]))
    samples.sort()
    output.update({"status": "evaluated", "inferential_claim": True,
                   "lower": round(samples[int((len(samples) - 1) * 0.025)], 6), "upper": round(samples[int((len(samples) - 1) * 0.975)], 6)})
    return output


def _shadow_selection(segments: Dict[str, Any]) -> Dict[str, Any]:
    all_source = ((segments.get("all_sources") or {}).get("all_candidates") or {}).get("experiments") or {}
    tushare = ((segments.get("tushare_only") or {}).get("all_candidates") or {}).get("experiments") or {}
    candidates = {}
    for name in ("A_dd_prob_ascending", "B_risk_adjusted_descending", "C_dd_prob_veto"):
        experiment = all_source.get(name) or {}
        tushare_experiment = tushare.get(name) or {}
        if experiment.get("status") != "available" or tushare_experiment.get("status") != "available":
            candidates[name] = {"status": "unavailable", "reason": "Required all-sources or TuShare-only comparison is unavailable."}
            continue
        paired = experiment.get("paired_comparison") or {}
        source_paired = tushare_experiment.get("paired_comparison") or {}
        metrics = paired.get("paired_primary_metrics") or {}
        source_metrics = source_paired.get("paired_primary_metrics") or {}
        base_metrics, trial_metrics = metrics.get("baseline") or {}, metrics.get("experiment") or {}
        base_tushare, trial_tushare = source_metrics.get("baseline") or {}, source_metrics.get("experiment") or {}
        qualification = paired.get("qualification") or paired
        source_qualification = source_paired.get("qualification") or source_paired
        sensitivity = qualification.get("leave_one_contributor_out") or {}
        source_criteria = _direction_criteria(base_tushare, trial_tushare)
        criteria = _direction_criteria(base_metrics, trial_metrics)
        criteria.update({
            "tushare_only_direction_consistent": all(source_criteria.values()),
            "not_single_stock_or_date": sensitivity.get("positive_after_every_day_removal") is True and sensitivity.get("positive_after_every_symbol_removal") is True,
        })
        enough = (metrics.get("matched_date_count", 0) >= PRIMARY_HORIZON * 3
                  and source_metrics.get("matched_date_count", 0) >= PRIMARY_HORIZON * 3
                  and (qualification.get("bootstrap_95pct_ci") or {}).get("status") == "evaluated"
                  and (source_qualification.get("bootstrap_95pct_ci") or {}).get("status") == "evaluated"
                  and sensitivity.get("status") == "evaluated")
        status = "qualified" if all(criteria.values()) else "rejected"
        if not enough:
            status = "insufficient_evidence"
        candidates[name] = {"status": status, "criteria": criteria, "tushare_only_criteria": source_criteria, "all_sources": trial_metrics, "tushare_only": trial_tushare,
                            "paired_date_count": metrics.get("matched_date_count", 0), "tushare_paired_date_count": source_metrics.get("matched_date_count", 0)}
    # Predeclared experiment order breaks ties, never optimize selection on holdout returns.
    qualified = [name for name, value in candidates.items() if value["status"] == "qualified"]
    selected = qualified[:1]
    for name in qualified:
        candidates[name]["status"] = "shadow_candidate" if name in selected else "qualified_not_selected"
    status = "shadow_candidate" if selected else ("insufficient_evidence" if any(value["status"] == "insufficient_evidence" for value in candidates.values()) else "no_shadow_candidate")
    return {"status": status, "selected": selected, "selection_rule": "maximum one; fixed priority A, B, C among qualified experiments", "candidates": candidates}


def _direction_criteria(baseline: Dict[str, Any], trial: Dict[str, Any]) -> Dict[str, bool]:
    return {
        "top5_median_10d_improved": _greater(trial.get("top5_median"), baseline.get("top5_median")),
        "top5_severe_loss_not_higher": _not_greater(trial.get("top5_severe_loss"), baseline.get("top5_severe_loss")),
        "ndcg_at_10_improved": _greater(trial.get("ndcg_at_10"), baseline.get("ndcg_at_10")),
        "top5_excess_return_improved": _greater(trial.get("top5_excess"), baseline.get("top5_excess")),
    }


def _primary_metrics(experiment: Dict[str, Any]) -> Dict[str, Optional[float]]:
    metrics = (experiment.get("metrics") or {}).get(str(PRIMARY_HORIZON)) or {}
    top5 = (metrics.get("top_k") or {}).get("5") or {}
    return {
        "top5_median": top5.get("median_return"),
        "top5_severe_loss": top5.get("severe_loss_rate"),
        "top5_excess": top5.get("relative_candidate_pool_excess_return"),
        "ndcg_at_10": metrics.get("ndcg_at_10"),
    }


def _filter_action(rows: Sequence[Dict[str, Any]], action: str) -> List[Dict[str, Any]]:
    return [row for row in rows if str(row.get("action") or "").lower() == action]


def _by_date(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("trade_date") or "unknown")].append(row)
    return dict(sorted(grouped.items()))


def _ndcg(rows: Sequence[Dict[str, Any]], return_key: str, k: int, pool_rows: Sequence[Dict[str, Any]]) -> float:
    gains = [max(0.0, _slot_return(row, return_key)) for row in rows[:k]]
    ideal = sorted((max(0.0, float(row[return_key])) for row in pool_rows), reverse=True)[:k]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    return round(dcg / idcg, 6) if idcg else 0.0


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return round(_pearson(_ranks(xs), _ranks(ys)), 6)


def _ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    result = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[start][0]:
            end += 1
        rank = (start + end + 2) / 2.0
        for _, index in ordered[start : end + 1]:
            result[index] = rank
        start = end + 1
    return result


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    x_mean, y_mean = mean(xs), mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def _as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number_or_inf(value: Any) -> float:
    number = _as_float(value)
    return number if number is not None else float("inf")


def _number_or_neg_inf(value: Any) -> float:
    number = _as_float(value)
    return number if number is not None else float("-inf")


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _mean_or_none(values: Sequence[Optional[float]]) -> Optional[float]:
    available = [float(value) for value in values if value is not None]
    return round(mean(available), 6) if available else None


def _median_or_none(values: Sequence[float]) -> Optional[float]:
    return round(median(values), 6) if values else None


def _greater(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and float(left) > float(right)


def _not_greater(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and float(left) <= float(right)
