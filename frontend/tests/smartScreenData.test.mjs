import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getRankingEvidenceStatus,
  getSmartScreenDiagnostic,
  getUniverseFunnelSummary,
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

test('diagnostic warns when deep analysis times out and snapshot fallback is used', () => {
  const diagnostic = getSmartScreenDiagnostic({
    universe_meta: {
      data_coverage_status: 'full_snapshot_available',
      total_universe_count: 5030,
      after_prefilter_count: 957,
      candidate_count: 220,
      analyzed_count: 72,
      analysis_completed_count: 0,
      analysis_timeout_count: 72,
      analysis_status: 'degraded_timeout',
      analysis_degraded_count: 30,
    },
    trade_plan: {
      core_count: 0,
      trial_count: 0,
      watch_count: 30,
    },
    picks: Array.from({ length: 30 }, (_, index) => ({ symbol: String(index + 1).padStart(6, '0') })),
  })

  assert.equal(diagnostic.coverageStatus, 'warning')
  assert.match(diagnostic.coverageText, /深度分析超时/)
  assert.match(diagnostic.coverageText, /72/)
  assert.match(diagnostic.coverageText, /30/)
})

test('funnel summary reports compression from full market to final output', () => {
  const summary = getUniverseFunnelSummary({
    universe_count: 5210,
    prefilter_count: 1975,
    recall_count: 220,
    deep_analysis_count: 72,
    final_pick_count: 17,
  })

  assert.equal(summary.fullMarket, 5210)
  assert.equal(summary.prefilter, 1975)
  assert.equal(summary.recall, 220)
  assert.equal(summary.deepAnalysis, 72)
  assert.equal(summary.finalOutput, 17)
  assert.match(summary.summaryText, /5210 -> 1975 -> 220 -> 72 -> 17/)
})

test('ranking evidence status warns when latest report is insufficient', () => {
  const status = getRankingEvidenceStatus({
    available: true,
    production_evidence: false,
    evidence_type: 'real_insufficient',
    evidence_readiness: {
      status: 'insufficient',
      blocking_reasons: ['coverage_status_partial', 'covered_dates_below_30'],
      covered_date_count: 8,
      required_covered_date_count: 30,
    },
  })

  assert.equal(status.alertType, 'warning')
  assert.equal(status.tagColor, 'orange')
  assert.match(status.title, /排序证据不足/)
  assert.match(status.description, /8\/30/)
  assert.match(status.description, /coverage_status_partial/)
})

test('ranking evidence status marks ready reports as usable evidence', () => {
  const status = getRankingEvidenceStatus({
    available: true,
    production_evidence: true,
    evidence_type: 'real',
    evidence_readiness: {
      status: 'ready',
      covered_date_count: 32,
      required_covered_date_count: 30,
    },
  })

  assert.equal(status.alertType, 'success')
  assert.equal(status.tagColor, 'green')
  assert.match(status.title, /排序证据已通过/)
  assert.match(status.description, /32\/30/)
})
