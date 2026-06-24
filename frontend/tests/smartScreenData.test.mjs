import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDisplayedPickList,
  resolveBatchReviewTradeDate,
  shouldRefreshCurrentTradingPicks,
} from '../src/pages/smartScreenData.mjs'

test('batch review date uses effective snapshot date and does not fall back to requested holiday', () => {
  assert.equal(
    resolveBatchReviewTradeDate({
      calendarContext: { effective_trade_date: '2026-06-18' },
      cachedPicks: { trade_date: '2026-06-18' },
      cacheIsFresh: true,
      summaryData: { trade_date: '2026-06-19' },
    }),
    '2026-06-18'
  )

  assert.equal(
    resolveBatchReviewTradeDate({
      calendarContext: {},
      cachedPicks: { trade_date: '2026-06-19', picks: [] },
      cacheIsFresh: false,
      summaryData: { trade_date: '2026-06-19' },
    }),
    undefined
  )
})

test('batch review date uses displayed stale snapshot on trading day before refresh', () => {
  assert.equal(
    resolveBatchReviewTradeDate({
      calendarContext: {
        mode: 'trading',
        effective_trade_date: '2026-06-22',
        snapshot_trade_date: '2026-06-17',
      },
      cachedPicks: {
        trade_date: '2026-06-17',
        picks: [{ pick_id: '2026-06-17-000001', symbol: '000001' }],
      },
      cacheIsFresh: true,
    }),
    '2026-06-17'
  )
})

test('displayed picks fall back to latest batch review items when live picks are empty', () => {
  const fallback = [{ pick_id: '2026-06-18-000001', symbol: '000001', rank_no: 1 }]
  const result = buildDisplayedPickList({
    result: { picks: [] },
    summary: { top_picks: [] },
    batchReview: { available: true, trade_date: '2026-06-18', items: fallback },
  })

  assert.equal(result.usingBatchReviewFallback, true)
  assert.deepEqual(result.pickList, fallback)
})

test('trading day stale snapshot triggers background refresh while non-trading snapshots do not', () => {
  assert.equal(
    shouldRefreshCurrentTradingPicks({
      calendarContext: {
        mode: 'trading',
        effective_trade_date: '2026-06-22',
        snapshot_trade_date: '2026-06-17',
      },
      cacheIsFresh: true,
      canRefresh: true,
      summaryData: { is_refreshing: false },
    }),
    true
  )

  assert.equal(
    shouldRefreshCurrentTradingPicks({
      calendarContext: {
        mode: 'preparation',
        effective_trade_date: '2026-06-18',
      },
      cacheIsFresh: true,
      canRefresh: false,
      summaryData: { is_refreshing: false },
    }),
    false
  )
})
