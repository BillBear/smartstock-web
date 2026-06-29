import assert from 'node:assert/strict'
import {
  getPickActionPresentation,
  RANKING_TABLE_COLUMN_KEYS,
} from './smartScreenPresentation.mjs'

assert.deepEqual(
  RANKING_TABLE_COLUMN_KEYS,
  [
    'rank',
    'stock',
    'decision',
    'user_action',
    'up_prob',
    'dd_prob',
    'expected_return_pct',
    'position_pct',
    'strategy_score',
    'operation',
  ],
)

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
