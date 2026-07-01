import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getSmartScreenDiagnostic,
  shouldRefreshCurrentTradingPicks,
} from '../src/pages/smartScreenData.mjs'

test('trading day stale snapshot triggers background refresh', () => {
  assert.equal(
    shouldRefreshCurrentTradingPicks({
      calendarContext: {
        mode: 'trading',
        effective_trade_date: '2026-06-22',
        snapshot_trade_date: '2026-06-17',
      },
      canRefresh: true,
      isRefreshing: false,
    }),
    true
  )
})

test('non-trading and already refreshing states do not trigger background refresh', () => {
  assert.equal(
    shouldRefreshCurrentTradingPicks({
      calendarContext: {
        mode: 'preparation',
        effective_trade_date: '2026-06-18',
      },
      canRefresh: false,
      isRefreshing: false,
    }),
    false
  )

  assert.equal(
    shouldRefreshCurrentTradingPicks({
      calendarContext: {
        mode: 'trading',
        effective_trade_date: '2026-06-22',
        snapshot_trade_date: '2026-06-17',
      },
      canRefresh: true,
      isRefreshing: true,
    }),
    false
  )
})

test('diagnostic separates full universe coverage from risk-gated no-buy state', () => {
  const diagnostic = getSmartScreenDiagnostic({
    universe_meta: {
      data_coverage_status: 'full_snapshot_available',
      total_universe_count: 5209,
      after_prefilter_count: 1746,
      candidate_count: 220,
      analyzed_count: 72,
    },
    trade_plan: {
      core_count: 0,
      trial_count: 0,
      watch_count: 22,
    },
    picks: Array.from({ length: 22 }, (_, index) => ({ symbol: String(index).padStart(6, '0') })),
  })

  assert.equal(diagnostic.coverageStatus, 'ok')
  assert.match(diagnostic.coverageText, /全量池正常/)
  assert.match(diagnostic.decisionText, /策略准入/)
})

test('diagnostic calls out missing same-day market snapshot', () => {
  const diagnostic = getSmartScreenDiagnostic({
    universe_meta: {
      data_coverage_status: 'market_snapshot_missing',
      latest_market_snapshot_trade_date: '2026-06-29',
    },
    trade_plan: {
      core_count: 0,
      trial_count: 0,
      watch_count: 2,
    },
    picks: [{ symbol: '000001' }, { symbol: '000333' }],
  })

  assert.equal(diagnostic.coverageStatus, 'warning')
  assert.match(diagnostic.coverageText, /缺少同日全量快照/)
  assert.match(diagnostic.coverageText, /2026-06-29/)
})
