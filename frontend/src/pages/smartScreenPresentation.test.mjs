import assert from 'node:assert/strict'
import test from 'node:test'
import * as qualityPresentation from './smartScreenPresentation.mjs'
import {
  getRankPresentation,
  getPickActionPresentation,
  getPickDecisionActionPresentation,
  getProbabilityModelPresentation,
  RANKING_TABLE_COLUMN_KEYS,
} from './smartScreenPresentation.mjs'

assert.deepEqual(
  RANKING_TABLE_COLUMN_KEYS,
  [
    'rank',
    'stock',
    'decision',
    'user_action',
    'expected_return_pct',
    'position_pct',
    'strategy_score',
    'operation',
  ],
)

assert.equal(RANKING_TABLE_COLUMN_KEYS.includes('up_prob'), false)
assert.equal(RANKING_TABLE_COLUMN_KEYS.includes('dd_prob'), false)
assert.equal(RANKING_TABLE_COLUMN_KEYS.includes('model_probability'), false)
assert.equal(RANKING_TABLE_COLUMN_KEYS.includes('news_score'), false)

assert.deepEqual(
  getPickActionPresentation(
    { decision: { grade: 'B', mode: 'paper_only' } },
    true,
  ),
  {
    canAddWatch: true,
    canShowPaperAction: true,
    paperActionLabel: '模拟验证',
    paperDisabledReason: '',
  },
)

assert.deepEqual(
  getPickActionPresentation(
    { decision: { grade: 'C', mode: 'watch_only' } },
    true,
  ),
  {
    canAddWatch: true,
    canShowPaperAction: false,
    paperActionLabel: '模拟验证',
    paperDisabledReason: '只有 A/B 级候选允许模拟验证',
  },
)

assert.deepEqual(
  getPickActionPresentation(
    { decision: { grade: 'D', mode: 'watch_only' } },
    true,
  ),
  {
    canAddWatch: false,
    canShowPaperAction: false,
    paperActionLabel: '模拟验证',
    paperDisabledReason: '只有 A/B 级候选允许模拟验证',
  },
)

assert.deepEqual(
  getPickActionPresentation(
    { decision: { grade: 'A', mode: 'real_allowed' } },
    false,
  ),
  {
    canAddWatch: true,
    canShowPaperAction: false,
    paperActionLabel: '模拟买入',
    paperDisabledReason: '非交易日不生成交易计划，不能模拟验证',
  },
)

assert.deepEqual(
  getPickDecisionActionPresentation({
    action: 'buy',
    decision: { grade: 'C', mode: 'watch_only', level: '观察等待' },
  }),
  {
    text: '观察等待',
    color: 'blue',
  },
)

assert.deepEqual(
  getPickDecisionActionPresentation({
    action: 'buy',
    decision: { grade: 'B', mode: 'paper_only', level: '小仓试错' },
  }),
  {
    text: '模拟验证',
    color: 'orange',
  },
)

assert.deepEqual(
  getPickDecisionActionPresentation({
    action: 'buy',
    decision: { grade: 'A', mode: 'real_allowed', level: '核心候选' },
  }),
  {
    text: '交易计划',
    color: 'red',
  },
)

assert.deepEqual(
  getProbabilityModelPresentation({
    type: 'ml_explainable_probability',
    label: '弱模型参考',
    calibrated: false,
  }),
  {
    label: '弱模型参考',
    alertType: 'warning',
    message: '当前模型概率未通过样本外校准',
  },
)

assert.deepEqual(
  getProbabilityModelPresentation({
    type: 'historical_score_bucket',
    label: '历史校准概率',
    calibrated: true,
  }),
  {
    label: '历史校准概率',
    alertType: 'success',
    message: '概率已完成历史样本校准',
  },
)

assert.deepEqual(
  getRankPresentation(1),
  {
    isTopRank: true,
    rankText: '1',
  },
)

assert.deepEqual(
  getRankPresentation(4),
  {
    isTopRank: false,
    rankText: '4',
  },
)

assert.deepEqual(
  getRankPresentation(null),
  {
    isTopRank: false,
    rankText: '-',
  },
)
test('degraded estimates are explicitly labeled without changing saved fields', () => {
  assert.equal(typeof qualityPresentation.getPickDataQualityPresentation, 'function')
  const row = { analysis_status: 'degraded_timeout', expected_return_pct: 2.43, score_breakdown: { total: 76 } }
  const before = JSON.stringify(row)
  const display = qualityPresentation.getPickDataQualityPresentation(row)
  assert.equal(display.degraded, true)
  assert.match(display.label, /分析超时/)
  assert.match(display.description, /代理|预筛/)
  assert.equal(JSON.stringify(row), before)
  assert.equal(qualityPresentation.getPickDataQualityPresentation({ probability_model: { calibrated: false } }).degraded, false)
})

test('failed persistence and degraded refresh never use a success toast', () => {
  assert.equal(typeof qualityPresentation.getRefreshFeedback, 'function')
  assert.equal(qualityPresentation.getRefreshFeedback({ accepted: true, result: { snapshot_persistence: { status: 'failed' } } }).type, 'error')
  assert.equal(qualityPresentation.getRefreshFeedback({ accepted: true, result: { picks: [{ analysis_status: 'degraded_timeout' }] } }).type, 'warning')
  assert.equal(qualityPresentation.getRefreshFeedback({ accepted: true, result: { snapshot_persistence: { status: 'saved' }, picks: [] } }).type, 'success')
  assert.equal(qualityPresentation.getRefreshFeedback({ accepted: false }).type, 'warning')
})
