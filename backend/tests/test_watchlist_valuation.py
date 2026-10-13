import copy
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from app.services.coach_service import CoachService
from app.services.pick_freshness import FreshnessError


class WatchlistValuationTests(unittest.TestCase):
    def setUp(self):
        clock = patch('app.services.coach_service.beijing_now', return_value=datetime(2026, 10, 13, 22, 30))
        clock.start()
        self.addCleanup(clock.stop)
        self.store, self.dsm, self.calendar = Mock(), Mock(), Mock()
        self.calendar.resolve.return_value = {'latest_trade_date': '2026-10-13'}
        self.row = dict(id=1, symbol='000333', name='美的集团', qty=100, avg_price=80.64,
                        cost_amount=8064, market_value=8246, opened_at='2026-07-06 23:13:04',
                        updated_at='2026-10-13 22:25:08')
        self.store.list_open_positions.return_value = [self.row]
        self.store.list_pick_actions.return_value = []
        self.store.get_latest_pick_actions.return_value = {}
        self.store.list_paper_trades.return_value = []
        self.store.get_latest_pick_snapshot_by_symbol.return_value = {}
        self.dsm._get_cache.return_value = []
        self.dsm.get_realtime_quotes_batch.return_value = {'000333': {
            'price': 83, 'name': '美的集团', 'update_time': '2026-10-13 16:15:00', 'source': 'Tencent'}}
        self.service = CoachService(self.dsm, self.store, trading_calendar=self.calendar)
        self.service.get_active_strategy_config = Mock(return_value={'config': {}})

    def test_watchlist_fetches_quotes_and_uses_opened_at_not_mark_time(self):
        result = self.service.get_watchlist()
        item = result['items'][0]
        self.dsm.get_realtime_quotes_batch.assert_called_once_with(['000333'])
        self.assertEqual(item['created_at'], '2026-07-06 23:13:04')
        self.assertEqual(item['current_price'], 83)
        self.assertEqual(item['unrealized_pnl'], 236)
        self.assertEqual(item['quote_time'], '2026-10-13 16:15:00')
        self.assertEqual(item['quote_source'], 'Tencent')
        self.assertEqual(item['quote_status'], 'latest_session')
        self.assertEqual(result['review']['items'][0]['unrealized_pnl'], 236)
        self.assertEqual(self.row['opened_at'], '2026-07-06 23:13:04')

    def test_latest_symbol_action_wins_regardless_of_map_order(self):
        self.store.get_latest_pick_actions.return_value = {
            'new': dict(symbol='601988', action_type='ignored', created_at='2026-10-13 12:00:00'),
            'old': dict(symbol='601988', action_type='added_watchlist', created_at='2026-10-12 12:00:00'),
        }
        self.assertNotIn('601988', [r['symbol'] for r in self.service.get_watchlist()['items']])

    def test_opened_at_wins_over_later_watch_action(self):
        self.store.get_latest_pick_actions.return_value = {
            'p': dict(symbol='000333', action_type='added_watchlist', created_at='2026-10-12 12:00:00')}
        self.store.get_pick_snapshot.return_value = {}
        self.assertEqual(self.service.get_watchlist()['items'][0]['created_at'], self.row['opened_at'])

    def test_unavailable_stale_unknown_future_and_invalid_quotes_do_not_fake_flat_pnl(self):
        for quote in (None, {'price': 83}, {'price': 83, 'update_time': '2026-10-12 16:15:00'},
                      {'price': 83, 'update_time': '2026-10-14 16:15:00'},
                      {'price': 0, 'update_time': '2026-10-13 16:15:00'},
                      {'price': float('nan'), 'update_time': '2026-10-13 16:15:00'}):
            with self.subTest(quote=quote):
                self.store.update_position_mark.reset_mock()
                self.dsm.get_realtime_quotes_batch.return_value = {'000333': quote}
                result = self.service.get_paper_portfolio()
                pos = result['positions'][0]
                self.assertIsNone(pos['current_price'])
                self.assertIsNone(pos['unrealized_pnl'])
                self.assertEqual(pos['risk_status'], 'unknown')
                self.assertEqual(pos['last_known_price'], 82.46)
                self.assertIsNone(result['summary']['total_unrealized_pnl'])
                self.assertEqual(result['summary']['unpriced_position_count'], 1)
                self.store.update_position_mark.assert_not_called()
                self.dsm.get_realtime_quote.assert_not_called()

    def test_cached_read_does_not_update_mark_or_timestamp(self):
        result = self.service.get_paper_portfolio(refresh_quotes=False)
        self.dsm.get_realtime_quotes_batch.assert_not_called()
        self.store.update_position_mark.assert_not_called()
        self.assertEqual(result['positions'][0]['updated_at'], self.row['updated_at'])
        self.assertIsNone(result['positions'][0]['quote_time'])

    def test_batch_quotes_keep_actual_source_and_timestamp(self):
        from app.services.data_source_manager import DataSourceManager
        provider = Mock()
        provider.get_realtime_quotes_batch.return_value = {'000333': {
            'price': 83, 'update_time': '2026-10-13 16:15:00'}}
        manager = DataSourceManager(tencent_service=provider)
        quote = manager.get_realtime_quotes_batch(['000333'])['000333']
        self.assertEqual(quote['source'], 'Tencent')
        self.assertEqual(quote['update_time'], '2026-10-13 16:15:00')

    def test_provider_or_calendar_failure_preserves_positions(self):
        self.dsm.get_realtime_quotes_batch.side_effect = RuntimeError('offline')
        result = self.service.get_paper_portfolio()
        self.assertEqual(len(result['positions']), 1)
        self.assertIsNone(result['positions'][0]['unrealized_pnl'])
        self.dsm.get_realtime_quotes_batch.side_effect = None
        self.calendar.resolve.side_effect = FreshnessError('calendar unavailable')
        result = self.service.get_paper_portfolio()
        self.assertEqual(result['positions'][0]['quote_status'], 'calendar_unavailable')
        self.store.update_position_mark.assert_not_called()

    def test_partial_coverage_totals_and_review_are_not_complete_or_zero(self):
        second = copy.deepcopy(self.row)
        second.update(id=2, symbol='601988')
        self.store.list_open_positions.return_value.append(second)
        watchlist = self.service.get_watchlist()
        summary = watchlist['portfolio_summary']
        self.assertIsNone(summary['total_market_value'])
        self.assertEqual(summary['known_market_value'], 8300)
        self.assertEqual(summary['priced_position_count'], 1)
        review = self.service.get_paper_review(watchlist=watchlist)
        self.assertEqual(review['metrics']['reviewed_position_count'], 1)
        unknown = next(r for r in review['items'] if r['symbol'] == '601988')
        self.assertEqual(unknown['verdict'], '行情待更新')
        self.assertIsNone(unknown['unrealized_pnl_pct'])
        self.dsm.get_realtime_quotes_batch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
