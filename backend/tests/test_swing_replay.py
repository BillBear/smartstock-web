import copy
from datetime import date, timedelta
import importlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.evaluation.swing_dataset import join_daily_inputs


PROTOCOL = Path(__file__).parent / 'fixtures/swing_quality/protocol.json'
CONFIG = dict(commission=.0003, slippage=.001, holding_days=10, max_position_pct=10.0,
              max_positions=5, risk_level='medium', score_threshold=72.0,
              stop_loss_pct=8.0, stop_profit_pct=15.0, universe_size=300)


def fixture(count=80, bearish=False):
    histories = {}
    for s, symbol in enumerate(('000001', '300750', '600519')):
        rows = []
        for i in range(count):
            day = (date(2026, 3, 1) + timedelta(days=i)).strftime('%Y%m%d')
            price = 15 + s * 4 + (-.03 if bearish else .035) * i + (i % 5) * .01
            daily = dict(ts_code=symbol + ('.SH' if symbol[0] == '6' else '.SZ'),
                         trade_date=day, open=price-.02, close=price, high=price+.2,
                         low=price-.2, pre_close=price-.03, change=.03,
                         pct_chg=-3 if bearish else 2, vol=100000+i*100,
                         amount=1200000+s*110000)
            basic = dict(ts_code=daily['ts_code'], trade_date=day, turnover_rate=4+s,
                         turnover_rate_f=4, volume_ratio=1, circ_mv=900000)
            factor = dict(ts_code=daily['ts_code'], trade_date=day, adj_factor=1)
            rows.append(join_daily_inputs([daily], [basic], [factor], {})['rows'][0])
        histories[symbol] = rows
    return dict(trade_date=day, rows=[x[-1] for x in histories.values()], histories=histories,
                strategy_config=copy.deepcopy(CONFIG),
                identity=dict(user_id='default', strategy_code='trend_breakout', risk_level='medium'))


class SwingExecutionTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('app.evaluation.swing_replay')

    def inputs(self, prices=None):
        prices = prices or [(10,10), (10,8), (7,7.5), (8,8)]
        bars = [dict(symbol='000001', trade_date=f'2026-07-{i+1:02d}', source='tushare',
                     adjustment='raw', open=o, close=c, high=max(o,c)+.1, low=min(o,c)-.1,
                     volume=100000, amount=1000000, adj_factor=1, available_at=None)
                for i,(o,c) in enumerate(prices)]
        signal = dict(symbol='000001', trade_date=bars[0]['trade_date'], rank_no=1,
                      user_id='default', strategy_code='trend_breakout', risk_level='medium',
                      baseline_kind='reconstructed_research', config_sha256=self.module.digest(CONFIG),
                      action='buy', decision_executable=True, position_pct=10, total=80)
        daily = [(r['trade_date'], dict(rows=[r])) for r in bars]
        return [signal], daily

    def run_replay(self, signals, daily, **kwargs):
        self.assertTrue(hasattr(self.module, 'replay_execution'), 'execution ledger missing')
        return self.module.replay_execution(signals, daily, CONFIG, **kwargs)

    def test_entry_day_touch_is_not_exit_and_gap_uses_next_open(self):
        signals, daily = self.inputs()
        r = self.run_replay(signals, daily)
        self.assertEqual([(f['side'],f['trade_date']) for f in r['fills']],
                         [('buy','2026-07-02'),('sell','2026-07-03')])
        self.assertAlmostEqual(r['fills'][1]['price'], 7*.999, places=4)
        self.assertEqual(r['closed_episodes'][0]['exit_reason'], 'stop_loss_close')
        self.assertEqual(r['closed_episodes'][0]['trigger_date'], '2026-07-02')
        self.assertGreater(r['diagnostics']['entry_day_exit_deferred_t1'], 0)
        self.assertEqual(r['policy']['holding_clock'], 'calendar_days')

    def test_intraday_both_touches_are_diagnostic_not_new_exit_policy(self):
        signals, daily = self.inputs([(10,10),(10,10),(10,10)])
        daily[1][1]['rows'][0].update(high=12, low=8)
        r = self.run_replay(signals,daily)
        self.assertEqual(len(r['fills']),1)
        self.assertEqual(len(r['open_positions']),1)
        self.assertEqual(r['diagnostics']['intraday_both_touch_count'],1)
        self.assertIsNone(r['summary']['realized_net_pnl'])

    def test_suspended_exit_defers_until_resume_and_no_terminal_liquidation(self):
        signals,daily = self.inputs()
        daily[2][1]['rows'] = []
        r = self.run_replay(signals,daily)
        self.assertEqual(r['fills'][-1]['trade_date'],'2026-07-04')
        self.assertIn('missing_bar', [x['reason'] for x in r['deferred_orders']])
        truncated = self.run_replay(signals,daily[:3])
        self.assertEqual(len(truncated['fills']),1)
        self.assertTrue(truncated['open_positions'])
        self.assertTrue(truncated['unresolved_exposure'])

    def test_one_price_filters_are_posthoc_uncertainty_not_open_known_signal(self):
        signals,daily = self.inputs([(10,10),(10,10),(10,8),(7,7)])
        daily[1][1]['rows'][0].update(high=10,low=10)
        daily[3][1]['rows'][0].update(high=7,low=7)
        r = self.run_replay(signals,daily)
        self.assertEqual(r['fills'][0]['trade_date'],'2026-07-03')
        self.assertEqual(len(r['fills']),1)
        self.assertEqual(sum(x['reason']=='one_price_uncertain' for x in r['deferred_orders']),2)
        self.assertIn('posthoc',r['policy']['bar_filter'])
        self.assertFalse(r['promotable'])

    def test_cash_lots_caps_and_fees_not_double_counted(self):
        signals,daily = self.inputs()
        r = self.run_replay(signals,daily)
        for fill in r['fills']:
            self.assertEqual(fill['qty']%100,0)
            self.assertAlmostEqual(fill['fee'],sum(fill['fees'].values()),places=6)
        buy,sell = r['fills']
        self.assertLessEqual(buy['amount']+buy['fee'],10000)
        self.assertGreaterEqual(min(x['cash'] for x in r['equity_curve']),0)
        self.assertAlmostEqual(r['ending_cash'],100000-buy['amount']-buy['fee']+sell['amount']-sell['fee'],places=4)
        self.assertEqual(buy['fees']['stamp_tax'],0)
        self.assertAlmostEqual(sell['fees']['stamp_tax'],sell['amount']*.0005,places=4)
        self.assertEqual(buy['fees']['commission'],5)

    def test_score_exit_uses_saved_same_date_not_future_and_calendar_holding(self):
        signals,daily = self.inputs([(10,10)]*4)
        signals.append(dict(signals[0],trade_date='2026-07-03',total=59,action='watch'))
        r = self.run_replay(signals,daily)
        self.assertEqual(r['fills'][-1]['trade_date'],'2026-07-04')
        self.assertEqual(r['closed_episodes'][0]['exit_reason'],'score_below_60')
        self.assertGreater(r['diagnostics']['missing_score_count'],0)
        signals,daily = self.inputs([(10,10)]*3)
        daily[2] = ('2026-07-12',dict(rows=[dict(daily[2][1]['rows'][0],trade_date='2026-07-12')]))
        r = self.run_replay(signals,daily)
        self.assertEqual(r['open_positions'][0]['exit_order']['reason'],'holding_calendar_days')

    def test_factor_change_freezes_exposure_without_fake_share_or_cash_changes(self):
        signals,daily = self.inputs()
        daily[2][1]['rows'][0]['adj_factor'] = 2
        r = self.run_replay(signals,daily)
        self.assertEqual(len(r['fills']),1)
        self.assertEqual(r['open_positions'][0]['qty'],r['fills'][0]['qty'])
        self.assertTrue(r['open_positions'][0]['corporate_action_uncertain'])
        self.assertFalse(r['promotable'])

    def test_saved_gates_identity_config_and_variants_fail_closed(self):
        signals,daily = self.inputs()
        for field,value in [('position_pct',0),('action','watch'),('decision_executable',False),('total',71)]:
            r = self.run_replay([dict(signals[0],**{field:value})],daily)
            self.assertFalse(r['fills'])
        for field,value in [('risk_level','high'),('config_sha256','changed')]:
            with self.assertRaises(ValueError): self.run_replay([dict(signals[0],**{field:value})],daily)
        with self.assertRaises(ValueError):
            self.run_replay(signals+[dict(signals[0],trade_date='2026-07-02',user_id='other')],daily)
        with self.assertRaises(ValueError): self.run_replay(signals,daily,slippage_multiplier=3)
        self.assertEqual(self.run_replay(signals,daily),self.run_replay(signals,copy.deepcopy(daily)))

    def test_late_saved_score_cannot_trigger_a_close_exit(self):
        signals,daily = self.inputs([(10,10)]*4)
        signals.append(dict(signals[0],trade_date='2026-07-03',total=59,action='watch',
                            available_at='2026-07-04T18:00:00+08:00'))
        r = self.run_replay(signals,daily)
        self.assertEqual(len(r['fills']),1)
        self.assertTrue(r['open_positions'])

    def test_nonfinite_saved_gate_cannot_authorize_a_buy(self):
        signals,daily = self.inputs()
        for field in ('total','position_pct'):
            r = self.run_replay([dict(signals[0],**{field:float('nan')})],daily)
            self.assertFalse(r['fills'])

    def test_maximum_positions_and_future_labels_do_not_change_cash_decisions(self):
        signals,daily = self.inputs([(10,10)]*3)
        original = signals[0]
        signals = [dict(original,symbol=f'{i:06d}',rank_no=i) for i in range(1,8)]
        for _,value in daily:
            bar = value['rows'][0]
            value['rows'] = [dict(bar,symbol=r['symbol']) for r in signals]
        first = self.run_replay(signals,daily)
        self.assertEqual(len(first['fills']),5)
        self.assertGreaterEqual(first['ending_cash'],50000)
        changed = [dict(r,future_return_10d=999999,tradable_label='untradable') for r in signals]
        second = self.run_replay(changed,daily)
        self.assertEqual(first['fills'],second['fills'])
        self.assertEqual(first['equity_curve'],second['equity_curve'])

    def test_fixed_labels_are_postrun_diagnostics_only_for_matching_entry_dates(self):
        signals,daily = self.inputs()
        signals[0].update(entry_date='2026-07-02',future_return_5d=3,future_return_10d=6,future_return_20d=9)
        first = self.run_replay(signals,daily)
        self.assertIn('fixed_horizon_comparison',first)
        match = first['fixed_horizon_comparison'][0]
        self.assertTrue(match['same_entry_date'])
        self.assertEqual(match['saved_label_net_returns_pct'],{'5':3,'10':6,'20':9})
        daily[1][1]['rows'] = []
        delayed = self.run_replay(signals,daily)['fixed_horizon_comparison'][0]
        self.assertFalse(delayed['same_entry_date'])
        self.assertTrue(all(v is None for v in delayed['saved_label_net_returns_pct'].values()))

    def test_closed_episode_keeps_same_close_vs_next_open_constraint_delta(self):
        signals,daily = self.inputs()
        r = self.run_replay(signals,daily)
        episode = r['closed_episodes'][0]
        self.assertIn('constraint_delta',episode)
        self.assertEqual(episode['constraint_delta']['legacy_same_close_price_diagnostic'],7.992)
        self.assertEqual(episode['constraint_delta']['execution_price'],6.993)
        self.assertEqual(episode['constraint_delta']['calendar_delay_days'],1)
        self.assertAlmostEqual(episode['constraint_delta']['price_difference'],-.999)

    def test_missing_factor_is_uncertainty_not_confirmed_corporate_action(self):
        signals,daily = self.inputs()
        daily[2][1]['rows'][0]['adj_factor'] = None
        r = self.run_replay(signals,daily)
        self.assertEqual(r['diagnostics'].get('factor_change_or_missing_uncertainty_events'),1)
        self.assertNotIn('corporate_action_events',r['diagnostics'])


class SwingReplayTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.evaluation.swing_replay'),
                             'offline replay adapter is not implemented')
        self.replay = importlib.import_module('app.evaluation.swing_replay')
        self.protocol = json.loads(PROTOCOL.read_text())

    def test_deterministic_complete_decisions_and_separate_ui_rank(self):
        data = fixture()
        first = self.replay.replay_day(data, self.protocol)
        self.assertEqual(first, self.replay.replay_day(copy.deepcopy(data), self.protocol))
        self.assertTrue(first['candidates'])
        self.assertEqual(first['identity']['baseline_kind'], 'reconstructed_research')
        self.assertEqual(first['provenance']['write_attempts'], [])
        self.assertEqual(len(first['frozen_analysis_pool']), first['funnel']['analyzed_count'])
        for item in first['frozen_analysis_pool']:
            self.assertIn('actual_daily_basic', item)
            self.assertEqual(item['quote']['turnover_rate'], 0)
            self.assertIn('pre_score', item['quote'])
        for row in first['candidates']:
            self.assertIsNotNone(row['decision']['executable'])
            self.assertTrue(row['proxy_was_used'])
            self.assertGreater(row['actual_daily_basic']['turnover_rate'], 0)
            self.assertEqual(row['input_quote']['turnover_rate'], 0)
            self.assertEqual(row['input_quote']['circ_mv'], 0)
            self.assertIsNone(row['historical_metadata']['industry'])
            self.assertEqual(row['probability_source'], 'rule_proxy_no_historical_ml')
        ui = sorted(first['candidates'], key=lambda r: (-r['score_breakdown']['total'], r['rank_no']))
        self.assertEqual([r['ui_rank_no'] for r in ui], list(range(1, len(ui)+1)))

    def test_future_bars_and_current_metadata_do_not_change_decisions(self):
        data = fixture()
        before = self.replay.replay_day(data, self.protocol)
        for symbol, history in data['histories'].items():
            future = copy.deepcopy(history[-1])
            future.update(trade_date='20260831', adj_factor=900, close=999999)
            history.append(future)
        for row in data['rows']:
            row.update(name='ST current name', industry='today sector', listing_status='listed')
        after = self.replay.replay_day(data, self.protocol)
        self.assertEqual(before, after)

    def test_known_late_prior_dependency_rejects_day_before_decisions(self):
        data = fixture()
        prior = data['histories']['000001'][-2]
        prior['available_at'] = '2026-12-31T18:00:00+08:00'
        for amount in (prior['amount'], 999999999):
            prior['amount'] = amount
            with self.assertRaisesRegex(ValueError, 'feature_input_available_after_signal'):
                self.replay.prepare_inputs(data, self.protocol)
            with self.assertRaisesRegex(ValueError, 'feature_input_available_after_signal'):
                self.replay.replay_day(data, self.protocol)

    def test_known_same_day_after_cutoff_rejected_and_cutoff_equality_allowed(self):
        data = fixture()
        signal = data['rows'][0]
        signal['available_at'] = '2026-05-19T18:00:01+08:00'
        with self.assertRaisesRegex(ValueError, 'feature_input_available_after_signal'):
            self.replay.replay_day(data, self.protocol)
        signal['available_at'] = '2026-05-19T18:00:00+08:00'
        data['histories']['300750'][-2]['available_at'] = '2026-05-19T09:00:00+00:00'
        prepared = self.replay.prepare_inputs(data, self.protocol)
        self.assertEqual(prepared['sidecars']['300750']['effective_available_at'], signal['available_at'])
        self.assertEqual(prepared['sidecars']['300750']['feature_availability_status'],
                         'assumed_with_unknown_dependencies')
        self.assertTrue(self.replay.replay_day(data,self.protocol)['candidates'])

    def test_insufficient_warmup_and_empty_universe_never_curated_fallback(self):
        short = self.replay.replay_day(fixture(59), self.protocol)
        self.assertEqual(short['candidates'], [])
        self.assertEqual(short['funnel']['insufficient_warmup_count'], 3)
        data = fixture()
        data['rows'] = []
        result = self.replay.replay_day(data, self.protocol)
        self.assertEqual(result['candidates'], [])
        self.assertTrue(result['funnel']['curated_fallback_blocked'])

    def test_bearish_original_market_state_is_retained(self):
        result = self.replay.replay_day(fixture(bearish=True), self.protocol)
        self.assertEqual(result['market_state']['state_tag'], 'defensive')

    def test_duplicate_wrong_date_invalid_ohlc_and_config_drift_block(self):
        variants = []
        data = fixture(); data['rows'].append(copy.deepcopy(data['rows'][0])); variants.append(data)
        data = fixture(); data['histories']['000001'].append(data['histories']['000001'][0]); variants.append(data)
        data = fixture(); data['rows'][0]['trade_date'] = '20260101'; variants.append(data)
        data = fixture(); data['rows'][0]['high'] = -1; variants.append(data)
        data = fixture(); data['strategy_config']['commission'] = .003; variants.append(data)
        data = fixture(); data['identity']['user_id'] = 'other'; variants.append(data)
        for data in variants:
            with self.subTest(data=data['trade_date']), self.assertRaises(ValueError):
                self.replay.replay_day(data, self.protocol)

    def test_missing_same_day_factor_not_replaced_by_prior_bar(self):
        data = fixture()
        data['rows'][0]['adj_factor'] = None
        data['histories']['000001'][-1]['adj_factor'] = None
        result = self.replay.replay_day(data, self.protocol)
        self.assertNotIn('000001', [x['symbol'] for x in result['candidates']])
        self.assertEqual(result['funnel']['missing_signal_factor_count'], 1)

    def test_store_attempt_caught_by_service_still_hard_fails(self):
        from app.services.coach_service import CoachService
        original = CoachService._compute_today_picks
        def malicious(service, *args, **kwargs):
            try:
                service.store.save_market_snapshot([])
            except Exception:
                pass
            return original(service, *args, **kwargs)
        with patch.object(CoachService, '_compute_today_picks', malicious), self.assertRaisesRegex(RuntimeError, 'forbidden'):
            self.replay.replay_day(fixture(), self.protocol)

    def test_asof_adjustment_is_signal_anchored_and_projection_legacy_null(self):
        data = fixture()
        data['histories']['000001'][0]['adj_factor'] = .5
        mapped = self.replay.prepare_inputs(data, self.protocol)
        history = mapped['histories']['000001']
        self.assertEqual(history.iloc[0]['close'], data['histories']['000001'][0]['close']*.5)
        self.assertEqual(history.iloc[-1]['close'], data['rows'][0]['close'])
        projection = self.replay.decision_projection([{'symbol':'000001', 'rank_no':1}])[0]
        self.assertIsNone(projection['decision_executable'])
        self.assertIsNone(projection['raw_total'])

    def test_no_live_store_network_or_model_initialization(self):
        import socket
        from app.services.coach_store import CoachStore
        with patch.object(CoachStore, '__init__', side_effect=AssertionError('DB forbidden')), \
                patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')):
            result = self.replay.replay_day(fixture(), self.protocol)
        self.assertEqual(result['provenance']['write_attempts'], [])
        self.assertFalse(any(r.get('model_probability') for r in result['candidates']))

    def test_ui_rank_projection_does_not_replace_backend_rank(self):
        picks = [dict(symbol='000001',rank_no=1,ui_rank_no=2,total=70),
                 dict(symbol='000002',rank_no=2,ui_rank_no=1,total=80)]
        self.assertEqual([r['rank_no'] for r in self.replay.decision_projection(picks)], [1,2])

    def test_same_input_parity_uses_independently_mapped_original_computation(self):
        from app.services.coach_service import CoachService
        import pandas as pd
        data = fixture()
        result = self.replay.replay_day(data, self.protocol)
        # Independent mapping, no prepare_inputs or replay scheduling in reference path.
        quotes = [{k:r[k] for k in ('symbol','open','high','low','volume','amount','pre_close','pct_change')}
                  | dict(price=r['close'], code=r['symbol'], name=r['symbol'], turnover_rate=0,
                         circ_mv=0, source='tushare') for r in data['rows']]
        class Data:
            def get_realtime_quote(self, symbol):
                return next((r for r in quotes if r['symbol'] == symbol), None)
            def get_stock_industry_map(self): return {}
            def get_history_data(self, symbol, days):
                return pd.DataFrame([dict(date=r['trade_date'], **{k:r[k] for k in
                    ('open','high','low','close','volume','amount')}) for r in data['histories'][symbol]])
        class Store:
            def get_latest_pick_actions(self, **kw): return {}
            def list_backtest_runs(self, **kw): return []
        service = CoachService(Data(), Store(), ml_model_service=None)
        self.addCleanup(service._pick_executor.shutdown, wait=True)
        service.CURATED_FALLBACK_POOL = []
        with self.replay.signal_clock(data['trade_date']):
            now = service._now_ts()
            service._universe_state.update(entries=quotes, entry_map={r['symbol']:r for r in quotes},
                last_full_refresh_ts=now, last_refresh_attempt_ts=now, last_incremental_refresh_ts=now)
            reference, _ = service._compute_today_picks(80, 'default', result['identity']['trade_date'],
                'trend_breakout', None, CONFIG, copy.deepcopy(CoachService.DEFAULT_RISK_PROFILE), 72)
        self.assertEqual(self.replay.decision_projection(reference['picks']),
                         self.replay.decision_projection(result['candidates']))
