import test from 'node:test'
import assert from 'node:assert/strict'

import { shouldRefreshCurrentTradingPicks } from '../src/pages/smartScreenData.mjs'

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
