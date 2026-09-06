"""Frozen research adapters around CoachService; no live entry or persistence.

The clock patch is process-global: run this offline module in an isolated process,
never in the web server. Only scheduling and unavailable IO are substituted.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from threading import RLock

import pandas as pd

from app.evaluation.swing_dataset import compact_trade_date
from app.evaluation.swing_protocol import validate_protocol
from app.evaluation.ranking_quality_diagnosis import label_snapshot_rows, validate_snapshot_identity
from app.services import coach_service


_CLOCK_LOCK = RLock()
QUOTE_RECIPE = 'jul20_snapshot_schema_zero_turnover_zero_circ_mv_reconstruction_v1'
BAR_FIELDS = ('symbol', 'trade_date', 'source', 'adjustment', 'open', 'high', 'low',
              'close', 'volume', 'amount', 'adj_factor', 'available_at')
LIMITATIONS = [
    'reconstructed_research_not_historical_production_recommendations',
    'snapshot_proxy_recipe_observed_20260720_not_proven_all_past_dates',
    'historical_name_ST_listing_industry_unknown_board_inference_is_research_fallback',
    'historical_input_availability_unknown_end_of_day_assumption_not_verified_fill',
    'historical_news_ML_calibration_actions_and_strategy_health_unavailable',
    'current_saved_config_and_code_default_risk_universe_limits_not_proven_historical_asof',
    'synchronous_no_timeout_replay_does_not_reproduce_live_scheduling',
    'market_state_uses_original_fixed_sample_pool_same_day_quotes_not_historical_full_market',
    'no_full_A_share_recall_or_production_readiness_claim',
]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def iso_day(value):
    value = compact_trade_date(value)
    return f'{value[:4]}-{value[4:6]}-{value[6:]}'


def validate_config(config, identity, protocol):
    if identity != protocol['identity']:
        raise ValueError('identity mismatch')
    if digest(config) != protocol['costs']['config_sha256']:
        raise ValueError('config hash mismatch')
    for key in ('commission', 'slippage'):
        if config.get(key) != protocol['costs'][key]:
            raise ValueError('config cost mismatch')
    if config.get('risk_level') != identity['risk_level']:
        raise ValueError('config risk identity mismatch')


def checked_bars(rows, symbol=None):
    """Reject ambiguity before helpers that would otherwise silently deduplicate."""
    seen = set()
    result = []
    for original in rows:
        row = {key: original.get(key) for key in BAR_FIELDS}
        row['trade_date'] = iso_day(row['trade_date'])
        if row['source'] != 'tushare' or row['adjustment'] != 'raw':
            raise ValueError('unsupported bar source/adjustment')
        if not isinstance(row['symbol'], str) or len(row['symbol']) != 6 or not row['symbol'].isdigit():
            raise ValueError('invalid bar symbol')
        if symbol is not None and row['symbol'] != symbol:
            raise ValueError('bar symbol mismatch')
        key = row['symbol'], row['trade_date']
        if key in seen:
            raise ValueError('duplicate bar symbol/date')
        seen.add(key)
        for field in ('open','high','low','close','volume','amount','adj_factor'):
            value = row[field]
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value)
                                      or value < 0 or (field not in ('volume','amount') and value == 0)):
                raise ValueError('invalid bar numeric field: '+field)
        if row['high'] is not None and row['low'] is not None:
            if row['high'] < row['low'] or any(row[k] is not None and not row['low'] <= row[k] <= row['high']
                                               for k in ('open','close')):
                raise ValueError('invalid bar OHLC')
        if row['available_at'] is not None:
            stamp = datetime.fromisoformat(row['available_at'].replace('Z','+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('available_at requires timezone')
        result.append(row)
    return sorted(result, key=lambda r:(r['trade_date'], r['symbol']))


def _usable(row):
    return all(row.get(k) is not None for k in ('open','high','low','close','volume','amount','adj_factor'))


def _decision_time(day):
    return datetime.fromisoformat(iso_day(day)+'T18:00:00+08:00')


def prepare_inputs(day_inputs, protocol):
    protocol = validate_protocol(protocol)
    config = deepcopy(day_inputs['strategy_config'])
    validate_config(config, day_inputs['identity'], protocol)
    day = iso_day(day_inputs['trade_date'])
    if not protocol['dates']['research'][0] <= day <= protocol['dates']['research'][1]:
        raise ValueError('signal outside protocol range')
    bars = checked_bars(day_inputs['rows'])
    if any(row['trade_date'] != day for row in bars):
        raise ValueError('same-day bar required')
    originals = {r['symbol']:r for r in day_inputs['rows']}
    quotes, histories, sidecars = [], {}, {}
    missing_factor, short, missing_history = [], [], []
    cutoff = _decision_time(day)
    known_availability, unknown_availability = [], False
    for row in bars:
        symbol = row['symbol']; original = originals[symbol]
        # Ignore all current metadata and every future bar before validation/hash.
        prior = checked_bars([r for r in day_inputs.get('histories', {}).get(symbol, [])
            if compact_trade_date(r['trade_date']) <= day.replace('-','')], symbol)
        if not prior or prior[-1]['trade_date'] != day:
            missing_history.append(symbol)
        elif prior[-1] != row:
            raise ValueError('signal/history same-day bar mismatch')
        valid = [r for r in prior if _usable(r)][-protocol['dates']['max_warmup_bars']:]
        # Fail the whole signal day, not one stock: removing a late dependency
        # could change recall, market state and cross-sectional calibration.
        for dependency in [row] + valid:
            stamp = dependency['available_at']
            if stamp is None:
                unknown_availability = True
                continue
            available = datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if available > cutoff:
                raise ValueError('feature_input_available_after_signal: '+symbol+'/'+dependency['trade_date'])
            known_availability.append(available)
        if row['adj_factor'] is None:
            missing_factor.append(symbol)
        if len(valid) < 60:
            short.append(symbol)
        frame = []
        if symbol not in missing_history and row['adj_factor'] is not None and _usable(row) and len(valid) >= 60:
            for r in valid:
                frame.append(dict(date=r['trade_date'], volume=r['volume'], amount=r['amount'],
                    **{k:r[k]*r['adj_factor']/row['adj_factor'] for k in ('open','high','low','close')}))
        histories[symbol] = pd.DataFrame(frame)
        if all(row[k] is not None for k in ('open','high','low','close','volume','amount')):
            quote = {k:row[k] for k in ('symbol','open','high','low','volume','amount')}
            for key in ('pre_close','pct_change'):
                value = original.get(key)
                if value is not None and (type(value) not in (float,int) or not math.isfinite(value)):
                    raise ValueError('invalid quote numeric field: '+key)
                quote[key] = value
            quote.update(code=symbol, name=symbol, price=row['close'], turnover_rate=0,
                         circ_mv=0, source='tushare')
            quotes.append(quote)
        sidecars[symbol] = dict(actual_daily_basic={k:original.get(k) for k in
            ('turnover_rate','turnover_rate_f','volume_ratio','circ_mv')},
            historical_metadata=dict(name=None, industry=None, listing_status=None, st_status=None),
            available_at=row['available_at'], availability_status='unknown' if row['available_at'] is None else 'supplied',
            feature_bar_count=len(frame), missing_feature_bar_count=sum(not _usable(r) for r in prior),
            feature_start_date=frame[0]['date'] if frame else None,
            feature_end_date=frame[-1]['date'] if frame else None)
    effective = max(known_availability).astimezone(cutoff.tzinfo).isoformat() if known_availability else None
    for sidecar in sidecars.values():
        sidecar.update(effective_available_at=effective, decision_time=cutoff.isoformat(),
            feature_availability_status='assumed_with_unknown_dependencies' if unknown_availability else
                                        'known_on_time')
    return dict(day=day, config=config, quotes=quotes, histories=histories, sidecars=sidecars,
                missing_factor=missing_factor, short=short, missing_history=missing_history,
                identity=deepcopy(day_inputs['identity']))


@contextmanager
def signal_clock(day):
    fixed = _decision_time(day)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    with _CLOCK_LOCK:
        old = coach_service.datetime
        coach_service.datetime = FrozenDateTime
        try:
            yield
        finally:
            coach_service.datetime = old


class FrozenStore:
    def __init__(self):
        self.trace = []
        self.forbidden = []

    def get_latest_pick_actions(self, **kwargs):
        self.trace.append('get_latest_pick_actions')
        return {}

    def list_backtest_runs(self, **kwargs):
        self.trace.append('list_backtest_runs')
        return []

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise RuntimeError('forbidden store access: '+name)


class FrozenData:
    def __init__(self, inputs):
        self.quotes = {r['symbol']:r for r in inputs['quotes']}
        self.histories = inputs['histories']
        self.trace = []
        self.forbidden = []

    def get_realtime_quote(self, symbol):
        self.trace.append(['same_day_quote',symbol])
        return deepcopy(self.quotes.get(symbol))

    def get_stock_industry_map(self):
        self.trace.append(['historical_industry_unknown'])
        return {}

    def get_history_data(self, symbol, days=120):
        self.trace.append(['asof_history',symbol,days])
        return self.histories.get(symbol, pd.DataFrame()).tail(days).copy()

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise RuntimeError('forbidden provider access: '+name)


class OfflineCoach(coach_service.CoachService):
    def _curated_fallback_candidates(self, target_size=None):
        self.fallback_blocked = True
        return []

    def _run_pick_analysis(self, rows, risk, market, strategy):
        self.analysis_inputs = deepcopy(rows)
        picks = []
        for row in rows:
            pick = self._build_pick(row['symbol'], risk, market, row, strategy)
            if pick:
                picks.append(pick)
        return picks, [], dict(analysis_completed_count=len(rows), analysis_error_count=0,
            timings=dict(queue_ms=0, compute_ms=0), scheduling='synchronous_frozen_no_timeout')


def decision_projection(picks):
    result = []
    for pick in picks:
        score = pick.get('score_breakdown') or {}; decision = pick.get('decision') or {}
        result.append(dict(symbol=pick.get('symbol'), rank_no=pick.get('rank_no'),
            raw_total=score.get('raw_total',pick.get('raw_total')), total=score.get('total',pick.get('total')),
            up_prob=pick.get('up_prob'), dd_prob=pick.get('dd_prob'), action=pick.get('action'),
            decision_grade=decision.get('grade',pick.get('decision_grade')),
            decision_executable=decision.get('executable',pick.get('decision_executable')),
            position_pct=pick.get('position_pct'), entry_range=pick.get('entry_range'),
            take_profit=pick.get('take_profit'), stop_loss=pick.get('stop_loss')))
    return sorted(result, key=lambda r:(r['rank_no'] if r['rank_no'] is not None else math.inf,r['symbol'] or ''))


def replay_day(day_inputs, protocol):
    prepared = prepare_inputs(day_inputs, protocol)
    data, store = FrozenData(prepared), FrozenStore()
    service = OfflineCoach(data, store, news_service=None, ml_model_service=None)
    service.fallback_blocked = False
    try:
        with signal_clock(prepared['day']):
            now = service._now_ts(); quotes = prepared['quotes']
            service._universe_state.update(entries=deepcopy(quotes),
                entry_map={r['symbol']:deepcopy(r) for r in quotes},
                last_full_refresh_ts=now, last_refresh_attempt_ts=now, last_incremental_refresh_ts=now)
            config = prepared['config']
            risk = deepcopy(service.DEFAULT_RISK_PROFILE)
            risk.update(risk_level=config['risk_level'], max_position_pct=config['max_position_pct'])
            full, _ = service._compute_today_picks(80, prepared['identity']['user_id'], prepared['day'],
                prepared['identity']['strategy_code'], None, config, risk, config['score_threshold'])
    finally:
        service._pick_executor.shutdown(wait=True)
        if store.forbidden or data.forbidden:
            raise RuntimeError('forbidden offline IO attempted: '+','.join(store.forbidden+data.forbidden))
    picks = full['picks']
    ui = sorted(picks, key=lambda r:(-r['score_breakdown']['total'],r['rank_no']))
    ui_rank = {r['symbol']:i for i,r in enumerate(ui,1)}
    quotes = {r['symbol']:r for r in prepared['quotes']}
    for pick in picks:
        symbol = pick['symbol']
        pick.update(trade_date=prepared['day'], **prepared['identity'], ui_rank_no=ui_rank[symbol],
            baseline_kind='reconstructed_research', input_quote=quotes[symbol],
            proxy_was_used=True, turnover_recipe=QUOTE_RECIPE, source='tushare',
            probability_source='rule_proxy_no_historical_ml', market_state=full['market_state'],
            **prepared['sidecars'][symbol])
        pick['name'] = None
    validate_snapshot_identity(picks)
    projection = decision_projection(picks)
    reference = day_inputs.get('reference_projection')
    differences = [] if reference is None else [dict(expected=a,actual=b) for a,b in
        zip(reference,projection) if a != b]
    if reference is not None and len(reference) != len(projection):
        differences.append(dict(expected_count=len(reference),actual_count=len(projection)))
    identity = dict(**prepared['identity'], trade_date=prepared['day'], baseline_kind='reconstructed_research',
        protocol_sha256=validate_protocol(protocol)['protocol_sha256'], config_sha256=digest(config),
        decisions_sha256=digest(projection))
    return dict(identity=identity, provenance=dict(source='tushare', quote_recipe=QUOTE_RECIPE,
        input_sha256=digest(dict(quotes=prepared['quotes'], histories={s:df.to_dict('records') for s,df in
            prepared['histories'].items()})), store_calls=store.trace, provider_calls=data.trace,
        write_attempts=store.forbidden, risk_profile=risk, request_max_count=80,
        historical_config_status='current_saved_profile_not_proven_historical_asof'),
        candidates=picks, frozen_analysis_pool=[dict(quote=row, **prepared['sidecars'][row['symbol']],
            proxy_was_used=True, turnover_recipe=QUOTE_RECIPE) for row in service.analysis_inputs],
        market_state=full['market_state'], funnel=dict(**full['universe_meta'],
            insufficient_warmup_count=len(prepared['short']), missing_signal_factor_count=len(prepared['missing_factor']),
            missing_same_day_history_count=len(prepared['missing_history']), output_count=len(picks),
            curated_fallback_blocked=service.fallback_blocked),
        parity=dict(baseline_kind='same_input_parity', status='not_supplied' if reference is None else
            ('mismatch' if differences else 'matched'), differences=differences,
            scope='independent_frozen_input_reference_only_not_historical_production'),
        unsupported_fields=LIMITATIONS)


def label_candidates(candidates, histories, config):
    """Use the existing V1.2 labels, preserving sidecars and original missing slots."""
    output = []
    execution = dict(commission=config['commission'], slippage=config['slippage'],
                     take_profit_pct=config['stop_profit_pct'], stop_loss_pct=config['stop_loss_pct'])
    for candidate in candidates:
        symbol = candidate['symbol']; day = iso_day(candidate['trade_date'])
        bars = checked_bars(histories.get(symbol, []), symbol)
        same = [r for r in bars if r['trade_date'] == day]
        future = [r for r in bars if r['trade_date'] > day][:20]
        known = [datetime.fromisoformat(candidate[key].replace('Z','+00:00')) for key in
                 ('available_at','effective_available_at') if candidate.get(key)]
        late = bool(known and future and max(known) >
                    datetime.fromisoformat(future[0]['trade_date']+'T09:30:00+08:00'))
        def fetch(_symbol, _start, _end):
            # Entry validity is independent of gaps later in the holding path.
            records = [dict(r, date=r['trade_date']) for r in same+future[:1]]
            return pd.DataFrame(records), 'tushare', None
        labeled, _ = label_snapshot_rows([candidate], fetch, execution_config=execution,
                                         max_calendar_days=10000)
        row = dict(candidate, **labeled[0])
        row['decision_executable'] = decision_projection([candidate])[0]['decision_executable']
        row['name'] = candidate.get('name')
        row['snapshot_has_same_date_bar'] = bool(same)
        row['label_end_dates'] = {str(h):future[h-1]['trade_date'] if len(future)>=h else None for h in (3,5,10,20)}
        row['tradability_status'] = 'unknown_historical_suspension_limits_and_fill'
        row['tradable_label_scope'] = 'entry_bar_proxy_only'
        row['horizon_paths'] = {}
        for h in (3,5,10,20):
            subset = future[:h]
            def horizon_fetch(*_):
                return pd.DataFrame([dict(r,date=r['trade_date']) for r in same+subset]), 'tushare', None
            partial, _ = label_snapshot_rows([candidate], horizon_fetch, execution_config=execution,
                                             max_calendar_days=10000)
            value = partial[0]
            missing_bar = any(not _usable(r) for r in subset)
            reason = ('input_available_after_entry' if late else 'same_day_bar_missing' if not same else
                      value.get('label_missing_reason') or ('missing_future_bar_fields' if missing_bar else
                      'insufficient_future_bars' if len(subset)<h else None))
            row[f'future_return_{h}d'] = None if reason else value.get(f'future_return_{h}d')
            row['horizon_paths'][str(h)] = dict(label_missing_reason=reason,
                mature=len(subset)>=h and not reason,
                mfe=value.get('max_favorable_excursion') if not reason else None,
                mae=value.get('max_adverse_excursion') if not reason else None,
                **{key:value.get(key) if not reason else None for key in
                   ('first_hit_path','first_hit_date','first_hit_take_profit','first_hit_stop_loss')},
                end_date=row['label_end_dates'][str(h)])
        # The legacy scalar path metadata now explicitly describes the primary
        # horizon; per-horizon status is authoritative, never the longest path.
        primary = row['horizon_paths']['10']
        row.update(label_metadata_horizon=10, label_missing_reason=primary['label_missing_reason'],
            incomplete_horizons=[h for h in (3,5,10,20) if not row['horizon_paths'][str(h)]['mature']],
            max_favorable_excursion=primary['mfe'], max_adverse_excursion=primary['mae'],
            **{key:primary[key] for key in ('first_hit_path','first_hit_date',
                                          'first_hit_take_profit','first_hit_stop_loss')})
        if late or not same:
            row['tradable_label'] = 'untradable'
        output.append(row)
    return output


EXECUTION_FEE_SOURCES = {
    'stamp_tax': 'https://shanxi.chinatax.gov.cn/web/detail/sx-11400-545-1780448',
    'commission': 'https://www.chinatax.gov.cn/n810341/n810765/n812203/n813164/c1209808/content.html',
    'transfer_and_current_tax': 'https://one.sse.com.cn/onething/gptz/',
}


def execution_fees(day, side, amount, commission):
    """Narrow research-period fee recipe, not a broker's verified account tariff."""
    if iso_day(day) < '2023-08-28' or side not in ('buy', 'sell'):
        raise ValueError('unsupported execution fee date or side')
    if not all(math.isfinite(v) for v in (amount, commission)) or amount <= 0 or commission < 0:
        raise ValueError('invalid execution fee input')
    return dict(commission=round(max(5.0, amount * commission), 4),
                stamp_tax=round(amount * .0005, 4) if side == 'sell' else 0.0,
                transfer=round(amount * .00001, 4))


def _execution_signal_groups(signals, config):
    validate_snapshot_identity(signals)
    identities, kinds, groups = set(), set(), {}
    for row in signals:
        identity = tuple(row.get(k) for k in ('user_id', 'strategy_code', 'risk_level'))
        if any(v is None for v in identity) or identity[-1] != config['risk_level']:
            raise ValueError('execution signal identity mismatch')
        if row.get('config_sha256') != digest(config):
            raise ValueError('execution signal config hash mismatch')
        identities.add(identity); kinds.add(row.get('baseline_kind'))
        groups.setdefault(iso_day(row['trade_date']), []).append(row)
    if len(identities) > 1 or len(kinds) > 1 or (kinds and kinds != {'reconstructed_research'}):
        raise ValueError('execution mixed identity or unsupported baseline kind')
    return {day: sorted(items, key=lambda r:(r.get('_execution_order', r['rank_no']), r['symbol']))
            for day, items in groups.items()}


def _execution_bar_reason(bar):
    # These full-day observations define a posthoc conservative fill filter,
    # not information a live order algorithm could know at the opening auction.
    if bar is None:
        return 'missing_bar'
    if not _usable(bar) or any(bar[k] <= 0 for k in ('open','high','low','close','volume','amount')):
        return 'unusable_or_suspended_bar'
    if bar['high'] == bar['low']:
        return 'one_price_uncertain'
    return None


def _execution_number(value):
    return type(value) in (int,float) and math.isfinite(value)


def _execution_signal_on_time(signal, day):
    known = [datetime.fromisoformat(signal[k].replace('Z','+00:00')) for k in
             ('available_at','effective_available_at') if signal.get(k)]
    if any(stamp.tzinfo is None for stamp in known):
        raise ValueError('execution signal availability requires timezone')
    return not known or max(known) <= _decision_time(day)


def _execution_exit_reason(position, bar, score, day, config):
    if bar['close'] <= position['stop_loss_price']:
        return 'stop_loss_close'
    if bar['close'] >= position['take_profit_price']:
        return 'take_profit_close'
    if (datetime.fromisoformat(day) - datetime.fromisoformat(position['entry_date'])).days >= config['holding_days']:
        return 'holding_calendar_days'
    if score is not None and score < max(45, config['score_threshold'] - 12):
        return f'score_below_{max(45, config["score_threshold"] - 12):g}'
    return None


def _execution_fill(day, side, symbol, qty, price, config):
    amount = round(qty * price, 4)
    fees = execution_fees(day, side, amount, config['commission'])
    return dict(trade_date=day, side=side, symbol=symbol, qty=qty, price=price,
                amount=amount, fees=fees, fee=round(sum(fees.values()), 4),
                fill_status='research_open_proxy_not_verified_market_fill')


def _execution_label_comparison(signals, fills, episodes):
    saved = {(iso_day(r['trade_date']),r['symbol']):r for r in signals}
    closed = {(r['entry_date'],r['symbol']):r for r in episodes}
    output = []
    for fill in fills:
        if fill['side'] != 'buy':
            continue
        row = saved[fill['signal_date'],fill['symbol']]
        same_entry = row.get('entry_date') == fill['trade_date']
        episode = closed.get((fill['trade_date'],fill['symbol']))
        output.append(dict(symbol=fill['symbol'],signal_date=fill['signal_date'],
            execution_entry_date=fill['trade_date'],saved_label_entry_date=row.get('entry_date'),same_entry_date=same_entry,
            saved_label_net_returns_pct={str(h):row.get(f'future_return_{h}d') if same_entry and
                _execution_number(row.get(f'future_return_{h}d')) else None for h in (5,10,20)},
            existing_policy_net_return_pct=episode['net_pnl']/episode['entry_cost']*100 if episode else None,
            scope='postrun_only_saved_label_costs_vs_ledger_fees_no_direct_portfolio_equivalence',
            missing_reason=None if same_entry else 'entry_delayed_or_saved_entry_unknown_no_relabeling'))
    return output


def replay_execution(signals, daily, config, *, slippage_multiplier=1):
    """One chronological cash ledger; saved signals only, no service calls.

    Existing close-trigger policy is retained but executed at a later valid open.
    Corporate actions freeze uncertain exposure; raw marks are diagnostic only.
    """
    if slippage_multiplier not in (1, 2):
        raise ValueError('only original and 2x slippage scenarios are frozen')
    keys = ('commission','slippage','holding_days','max_positions','max_position_pct',
            'score_threshold','stop_profit_pct','stop_loss_pct')
    if any(type(config.get(k)) not in (int,float) or not math.isfinite(config[k]) for k in keys):
        raise ValueError('invalid execution config')
    if (not 0 <= config['commission'] <= .01 or not 0 <= config['slippage'] <= .01 or
        not 1 <= config['max_positions'] <= 20 or int(config['max_positions']) != config['max_positions'] or
        not 2 <= config['max_position_pct'] <= 30 or not 3 <= config['holding_days'] <= 90 or
        not 50 <= config['score_threshold'] <= 95 or not 2 <= config['stop_loss_pct'] <= 25 or
        not 5 <= config['stop_profit_pct'] <= 40):
        raise ValueError('execution config outside existing policy bounds')
    groups = _execution_signal_groups(signals, config)
    initial = max(10000.0, float(config.get('initial_capital', 100000)))
    if not math.isfinite(initial):
        raise ValueError('invalid initial capital')
    cash, peak, max_drawdown = initial, initial, 0.0
    positions, pending = {}, {}
    fills, episodes, deferred, rejected, curve = [], [], [], [], []
    diagnostics = dict(entry_day_exit_deferred_t1=0, intraday_both_touch_count=0,
                       missing_score_count=0, factor_change_or_missing_uncertainty_events=0, stale_valuation_days=0)
    previous = None; seen_dates = set()
    for raw_day, value in daily:
        day = iso_day(raw_day)
        if previous is not None and day <= previous:
            raise ValueError('execution daily dates must be unique and ascending')
        previous = day; seen_dates.add(day)
        bars = checked_bars(value['rows'])
        if any(b['trade_date'] != day for b in bars):
            raise ValueError('execution wrong-date bar')
        today = {b['symbol']:b for b in bars}
        if groups and day < min(groups):
            continue
        for symbol, pos in list(positions.items()):
            bar = today.get(symbol)
            if bar and bar.get('adj_factor') != pos['entry_factor'] and not pos['corporate_action_uncertain']:
                pos['corporate_action_uncertain'] = True
                diagnostics['factor_change_or_missing_uncertainty_events'] += 1
            order = pos['exit_order']
            if order is None or day <= order['trigger_date']:
                continue
            reason = ('corporate_action_uncertain' if pos['corporate_action_uncertain'] else
                      't_plus_one' if day <= pos['entry_date'] else _execution_bar_reason(bar))
            if reason:
                deferred.append(dict(trade_date=day, symbol=symbol, side='sell', reason=reason))
                continue
            fill = _execution_fill(day,'sell',symbol,pos['qty'],round(bar['open']*(1-config['slippage']*slippage_multiplier),4),config)
            cash = round(cash + fill['amount'] - fill['fee'], 4); fills.append(fill)
            episodes.append(dict(symbol=symbol, entry_date=pos['entry_date'], exit_date=day,
                trigger_date=order['trigger_date'], exit_reason=order['reason'], qty=pos['qty'],
                entry_cost=pos['entry_cost'], proceeds_net=fill['amount']-fill['fee'],
                net_pnl=round(fill['amount']-fill['fee']-pos['entry_cost'],4),
                constraint_delta=dict(legacy_same_close_price_diagnostic=order['legacy_same_close_price_diagnostic'],
                    execution_price=fill['price'],price_difference=round(fill['price']-order['legacy_same_close_price_diagnostic'],4),
                    calendar_delay_days=(datetime.fromisoformat(day)-datetime.fromisoformat(order['trigger_date'])).days,
                    scope='price_timing_diagnostic_not_a_separate_legacy_portfolio_return'),
                holding_calendar_days=(datetime.fromisoformat(day)-datetime.fromisoformat(pos['entry_date'])).days,
                holding_observed_bars=pos['observed_bars']))
            del positions[symbol]
        for symbol, signal in list(pending.items()):
            if day <= iso_day(signal['trade_date']):
                continue
            bar = today.get(symbol); reason = _execution_bar_reason(bar)
            if reason:
                deferred.append(dict(trade_date=day, symbol=symbol, side='buy', reason=reason)); continue
            if len(positions) >= config['max_positions']:
                rejected.append(dict(trade_date=day,symbol=symbol,reason='position_limit')); del pending[symbol]; continue
            price = round(bar['open']*(1+config['slippage']*slippage_multiplier),4)
            cap = initial * min(config['max_position_pct'], signal['position_pct'])/100
            budget = min(cap, cash / max(1, config['max_positions']-len(positions)))
            qty = int(budget / price / 100)*100
            while qty >= 100:
                fill = _execution_fill(day,'buy',symbol,qty,price,config)
                if fill['amount'] + fill['fee'] <= budget:
                    break
                qty -= 100
            del pending[symbol]
            if qty < 100:
                rejected.append(dict(trade_date=day,symbol=symbol,reason='cash_cap_or_minimum_lot')); continue
            fill['signal_date'] = iso_day(signal['trade_date'])
            cash = round(cash-fill['amount']-fill['fee'],4); fills.append(fill)
            positions[symbol] = dict(symbol=symbol,qty=qty,entry_price=price,entry_date=day,
                entry_score=signal['total'],entry_cost=fill['amount']+fill['fee'],entry_factor=bar['adj_factor'],
                last_price=price,last_mark_date=day,observed_bars=0,corporate_action_uncertain=False,
                take_profit_price=round(price*(1+config['stop_profit_pct']/100),4),
                stop_loss_price=round(price*(1-config['stop_loss_pct']/100),4),exit_order=None)
        saved = {s['symbol']:s for s in groups.get(day,[]) if _execution_signal_on_time(s,day)}
        for symbol,pos in positions.items():
            bar = today.get(symbol)
            if bar is None or not _usable(bar):
                diagnostics['stale_valuation_days'] += 1; continue
            pos['last_price'] = bar['close']; pos['last_mark_date'] = day; pos['observed_bars'] += 1
            if pos['corporate_action_uncertain']:
                continue
            if bar['high'] >= pos['take_profit_price'] and bar['low'] <= pos['stop_loss_price']:
                diagnostics['intraday_both_touch_count'] += 1
            score = (saved.get(symbol) or {}).get('total')
            if not _execution_number(score):
                diagnostics['missing_score_count'] += 1
                score = pos['entry_score']
            reason = _execution_exit_reason(pos,bar,score,day,config)
            if reason and pos['exit_order'] is None:
                pos['exit_order'] = dict(trigger_date=day,reason=reason,
                    legacy_same_close_price_diagnostic=round(bar['close']*(1-config['slippage']*slippage_multiplier),4))
                if day == pos['entry_date']:
                    diagnostics['entry_day_exit_deferred_t1'] += 1
        for signal in groups.get(day,[]):
            symbol = signal['symbol']
            reason = ('late_signal_input' if not _execution_signal_on_time(signal,day) else
                'saved_entry_gate' if signal.get('action') != 'buy' or signal.get('decision_executable') is not True or
                    not _execution_number(signal.get('total')) or signal['total'] < config['score_threshold'] or
                    not _execution_number(signal.get('position_pct')) or signal['position_pct'] <= 0 else None)
            if reason:
                rejected.append(dict(trade_date=day,symbol=symbol,reason=reason)); continue
            if symbol in positions or symbol in pending:
                continue
            if len(positions)+len(pending) >= config['max_positions']:
                rejected.append(dict(trade_date=day,symbol=symbol,reason='position_limit')); continue
            pending[symbol] = signal
        market_value = sum(pos['qty']*pos['last_price'] for pos in positions.values())
        equity = cash + market_value; peak = max(peak,equity)
        drawdown = (peak-equity)/peak*100; max_drawdown = max(max_drawdown,drawdown)
        if cash < -.0001 or len(positions) > config['max_positions']:
            raise RuntimeError('execution cash/position invariant failed')
        curve.append(dict(trade_date=day,cash=cash,raw_mark_market_value=round(market_value,4),
            raw_mark_equity=round(equity,4),raw_mark_drawdown_pct=round(drawdown,6),
            open_positions=len(positions),valuation_uncertain=any(p['corporate_action_uncertain'] or
                p['last_mark_date'] != day for p in positions.values())))
    if set(groups)-seen_dates:
        raise ValueError('execution signal date absent from daily index')
    ending = curve[-1]['raw_mark_equity'] if curve else initial
    net_return = (ending/initial-1)*100
    return dict(initial_capital=initial,ending_cash=cash,equity_curve=curve,fills=fills,closed_episodes=episodes,
        fixed_horizon_comparison=_execution_label_comparison(signals,fills,episodes),
        open_positions=[positions[k] for k in sorted(positions)],
        pending_entries=[dict(symbol=k,signal_date=pending[k]['trade_date']) for k in sorted(pending)],
        deferred_orders=deferred,rejected_orders=rejected,diagnostics=diagnostics,
        unresolved_exposure=bool(positions),promotable=False,
        summary=dict(raw_mark_return_pct=round(net_return,6),raw_mark_max_drawdown_pct=round(max_drawdown,6),
            raw_mark_return_drawdown_ratio=round(net_return/max_drawdown,6) if max_drawdown else None,
            realized_net_pnl=round(sum(p['net_pnl'] for p in episodes),4) if episodes else None,
            closed_episode_count=len(episodes),fill_count=len(fills),
            win_rate=sum(p['net_pnl']>0 for p in episodes)/len(episodes) if episodes else None,
            turnover=sum(f['amount'] for f in fills)/initial,
            mean_holding_calendar_days=sum(p['holding_calendar_days'] for p in episodes)/len(episodes) if episodes else None,
            terminal_zero_recovery_bound_pct=(cash/initial-1)*100 if positions else None),
        policy=dict(notional_source='current_backtest_default_100000_floor10000_not_account_balance',
            holding_clock='calendar_days',holding_days=config['holding_days'],score_exit_threshold=max(45,config['score_threshold']-12),
            trigger_order=['stop_loss_close','take_profit_close','holding_calendar_days','saved_score_deterioration'],
            execution='signal_after_close_then_first_later_valid_open_proxy_sells_before_buys_T1',
            bar_filter='posthoc_conservative_OHLCV_and_one_price_filter_not_open_known_strategy',
            missing_score='legacy_entry_score_fallback_no_new_score_or_signal',
            intraday_touch='diagnostic_only_both_touch_has_no_primary_execution_effect',
            corporate_action='freeze_uncertain_exposure_no_synthetic_shares_dividends_or_cash',
            slippage_multiplier=slippage_multiplier,fees_sources=EXECUTION_FEE_SOURCES,
            fee_scope='sell_stamp_0.0005_since20230828_transfer_both_0.00001_mincommission5_no_duplicate_regulatory_fees',
            transfer_effective_date='2022_change_original_notice_not_verified_current_SSE_rate_research_assumption'),
        limitations=['historical_risk_status_limits_board_lot_exceptions_and_auction_liquidity_unknown',
            'daily_bar_proxy_not_verified_executable_market_fill_no_live_authorization',
            'no_forced_terminal_liquidation_raw_marks_not_recoverable_cash',
            'corporate_action_or_terminal_missing_exposure_blocks_promotion',
            'saved_score_coverage_not_full_historical_universe_scoring',
            'fixed_horizon_labels_are_separate_not_this_cash_ledger'])
