import assert from 'node:assert/strict'
import test from 'node:test'

import { sortPicksByStrategyScore } from './smartScreenData.mjs'

test('sortPicksByStrategyScore orders candidates by strategy score descending', () => {
  const rows = [
    { symbol: '000001', rank_no: 1, score_breakdown: { total: 70 } },
    { symbol: '000002', rank_no: 2, score_breakdown: { total: 86.5 } },
    { symbol: '000003', rank_no: 3, score_breakdown: { total: 82 } },
    { symbol: '000004', rank_no: 4, score_breakdown: { total: 86.5 } },
  ]

  const sorted = sortPicksByStrategyScore(rows)

  assert.deepEqual(sorted.map((row) => row.symbol), ['000002', '000004', '000003', '000001'])
  assert.deepEqual(rows.map((row) => row.symbol), ['000001', '000002', '000003', '000004'])
})
