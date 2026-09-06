"""Research-only turnover substitution with a shared preanalysis denominator."""
from collections import Counter
import math

from app.evaluation.ranking_quality_diagnosis import _flatten_snapshot, validate_snapshot_identity
from app.evaluation.ranking_quality_experiments import (
    HORIZONS, _by_date, _candidate_pool_metrics, _daily_metrics, _evaluate_variant,
    _paired_top5_comparison, swing_block_inference)
from app.evaluation.swing_replay import digest, decision_projection


LABEL_FIELDS = (
    'entry_date', 'entry_price', 'history_source', 'label_end_dates', 'horizon_paths',
    'tradable_label', 'label_missing_reason', 'snapshot_has_same_date_bar',
) + tuple(f'future_return_{h}d' for h in (3, 5, 10, 20))
IDENTITY_FIELDS = ('user_id', 'strategy_code', 'risk_level', 'baseline_kind')


def attach_labels(picks, labeled_pool):
    """Join by day/symbol, never by the displaced stock's rank slot."""
    index = {(r['trade_date'], r['symbol']): r for r in labeled_pool}
    if len(index) != len(labeled_pool):
        raise ValueError('duplicate label identity')
    output = []
    for pick in picks:
        if any(key in pick for key in LABEL_FIELDS):
            raise ValueError('signal already contains future label fields')
        key = (pick['trade_date'], pick['symbol'])
        if key not in index:
            raise ValueError('output outside frozen preanalysis pool')
        output.append(dict(index[key], **dict(pick, **_flatten_snapshot(pick))))
    return output


def replay_turnover_day(prepared, saved):
    from scripts.run_swing_benchmark import _fixed_pool_compute
    input_hash = digest(dict(quotes=prepared['quotes'], histories={s:df.to_dict('records')
                         for s,df in prepared['histories'].items()}))
    if input_hash != saved['provenance']['input_sha256']:
        raise ValueError('frozen input hash mismatch')
    pool = saved['frozen_analysis_pool']
    for item in pool:
        symbol = item['quote']['symbol']
        value = item['actual_daily_basic']['turnover_rate']
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('unavailable actual turnover: '+symbol)
        if item['actual_daily_basic'] != prepared['sidecars'][symbol]['actual_daily_basic']:
            raise ValueError('actual turnover differs from frozen dataset')
        if item.get('proxy_was_used') is not True:
            raise ValueError('reference proxy not established')
    before = digest(pool)
    reference = _fixed_pool_compute(prepared, saved)
    reference_sha = digest(decision_projection(reference['picks']))
    if reference_sha != saved['identity']['decisions_sha256']:
        raise ValueError('reference decision parity mismatch')
    actual = _fixed_pool_compute(prepared, saved, actual=True)
    if digest(pool) != before:
        raise ValueError('frozen pool mutated')
    if reference['market_state'] != actual['market_state']:
        raise ValueError('non-variable market state changed')
    membership = {r['quote']['symbol'] for r in pool}
    quote_map = {r['quote']['symbol']: r['quote'] for r in pool}
    for pick in actual['picks']:
        symbol = pick['symbol']
        if symbol not in membership:
            raise ValueError('trial escaped frozen preanalysis pool')
        pick.update(trade_date=prepared['day'], **prepared['identity'],
            baseline_kind='reconstructed_research', config_sha256=digest(prepared['config']),
            source='tushare', probability_source='rule_proxy_no_historical_ml',
            market_state=actual['market_state'], **prepared['sidecars'][symbol],
            proxy_was_used=False, turnover_recipe='actual_daily_basic_same_day',
            input_quote=dict(quote_map[symbol], turnover_rate=prepared['sidecars'][symbol]['actual_daily_basic']['turnover_rate']))
        pick['name'] = None
    validate_snapshot_identity(actual['picks'])
    old = {r['symbol']:r for r in decision_projection(reference['picks'])}
    new = {r['symbol']:r for r in decision_projection(actual['picks'])}
    changes = {s:{k:dict(old=old[s][k],new=new[s][k]) for k in old[s] if old[s][k]!=new[s][k]}
               for s in sorted(set(old)&set(new)) if old[s]!=new[s]}
    return actual['picks'], dict(trade_date=prepared['day'], baseline_parity=True,
        input_sha256=input_hash, preanalysis_sha256=before, changed_input_fields=['quote.turnover_rate'],
        reference_decisions_sha256=reference_sha, trial_decisions_sha256=digest(decision_projection(actual['picks'])),
        reference_count=len(old), trial_count=len(new),
        added=sorted(set(new)-set(old)), removed=sorted(set(old)-set(new)), changes=changes,
        reference_actions=dict(Counter(r.get('action') for r in reference['picks'])),
        trial_actions=dict(Counter(r.get('action') for r in actual['picks'])))


def compare_outputs(reference, trial, pool, trading_dates, infer=True):
    for rows in (reference, trial, pool):
        validate_snapshot_identity(rows)
    index = {(r['trade_date'], r['symbol']):r for r in pool}
    for row in reference+trial:
        original = index.get((row['trade_date'], row['symbol']))
        if original is None or any(row.get(k)!=original.get(k) for k in LABEL_FIELDS+IDENTITY_FIELDS):
            raise ValueError('changed labels, identity or membership outside preanalysis pool')
    by_pool = _by_date(pool)
    by_variants = [_by_date(rows) for rows in (reference, trial)]
    result = dict(by_horizon={}, coverage=dict(pool_rows=len(pool),reference_rows=len(reference),
        trial_rows=len(trial),pool_dates=len(by_pool)), denominator='identical_frozen_preanalysis_pool')
    for horizon in HORIZONS:
        key = f'future_return_{horizon}d'; dates = []; excluded = {}
        for day, items in sorted(by_pool.items()):
            reasons = []
            if any(type(r.get(key)) not in (int,float) or not math.isfinite(r[key]) for r in items):
                reasons.append('incomplete_preanalysis_labels')
            if any(len(variant.get(day,[])) < 10 for variant in by_variants):
                reasons.append('fewer_than_10_outputs')
            if reasons: excluded[day] = reasons
            else: dates.append(day)
        accepted = set(dates)
        shared = [r for r in pool if r['trade_date'] in accepted]
        metrics = [_evaluate_variant([r for r in rows if r['trade_date'] in accepted],name,
                   lambda r:(r['rank_no'],r['symbol']),shared)
                   for rows,name in ((reference,'reference'),(trial,'actual_turnover'))]
        # Reuse tested Top5 contribution accounting, replacing only the horizon.
        for metric, grouped in zip(metrics, by_variants):
            ordered = {d:sorted(grouped[d],key=lambda r:(r['rank_no'],r['symbol'])) for d in dates}
            from app.evaluation.ranking_quality_experiments import _daily_top_k
            daily = _daily_top_k(ordered,horizon,5)
            metric['_daily_top5_returns'] = {d:daily[d]['avg_return'] for d in dates}
            metric['_daily_top5_contributions'] = {d:daily[d]['contributions'] for d in dates}
            metric['_daily_primary_metrics'] = {d:_daily_metrics(ordered[d],key,by_pool[d]) for d in dates}
        paired = _paired_top5_comparison(*metrics,0,20260830)
        paired.pop('bootstrap_95pct_ci',None); paired.pop('qualification',None)
        deltas = paired['daily_top5_return_deltas']
        inference = (swing_block_inference(deltas,trading_dates,horizon) if infer else dict(status='descriptive_only'))
        if infer:
            p = inference.get('p_value')
            inference['four_explorations_bonferroni_p'] = None if p is None else min(1,4*p)
        result['by_horizon'][str(horizon)] = dict(dates=dates,excluded=excluded,
            pool=_candidate_pool_metrics(shared)[str(horizon)],
            baseline=metrics[0]['metrics'][str(horizon)],trial=metrics[1]['metrics'][str(horizon)],
            paired=paired,inference=inference)
    return result
