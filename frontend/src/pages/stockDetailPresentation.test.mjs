import assert from 'node:assert/strict'
import {
  getStockStrategyActionPresentation,
  getStockStrategyMetricItems,
} from './stockDetailPresentation.mjs'

assert.deepEqual(
  getStockStrategyActionPresentation(null),
  {
    text: '未入候选池',
    color: 'default',
  },
)

assert.deepEqual(
  getStockStrategyActionPresentation({
    action: 'buy',
    decision: { grade: 'C', mode: 'watch_only', level: '观察等待' },
  }),
  {
    text: '观察等待',
    color: 'blue',
  },
)

const metricItems = getStockStrategyMetricItems({
  up_prob: 0.7,
  dd_prob: 0.2,
  expected_return_pct: 6.8,
  decision: { grade: 'B', mode: 'paper_only', level: '小仓试错' },
})

assert.deepEqual(
  metricItems.map((item) => item.title),
  ['决策等级', '执行模式', '预期收益'],
)
assert.equal(metricItems.some((item) => item.title.includes('上涨概率')), false)
assert.equal(metricItems.some((item) => item.title.includes('回撤概率')), false)

assert.deepEqual(
  getStockStrategyActionPresentation({
    action: 'buy',
    decision: { grade: 'B', mode: 'paper_only', level: '小仓试错' },
  }),
  {
    text: '模拟验证',
    color: 'orange',
  },
)

assert.deepEqual(
  getStockStrategyActionPresentation({
    action: 'buy',
    decision: { grade: 'A', mode: 'real_allowed', level: '核心候选' },
  }),
  {
    text: '交易计划',
    color: 'red',
  },
)
