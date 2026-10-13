import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { formatOptionalNumber, quoteDescription } from '../src/pages/watchlistPresentation.mjs'

test('unknown amounts remain unknown, actual zero stays zero', () => {
  for (const value of [null, undefined, '', NaN]) assert.equal(formatOptionalNumber(value), '未知')
  assert.equal(formatOptionalNumber(0), '0.00')
  assert.equal(formatOptionalNumber(-3.1), '-3.10')
})

test('quote status never calls missing or stale prices live', () => {
  assert.match(quoteDescription({quote_status: 'latest_session', quote_source: 'Tencent', quote_time: '2026-10-13 16:15:00'}), /Tencent.*2026-10-13/)
  assert.match(quoteDescription({quote_status: 'stale_or_future', quote_time: '2026-10-12 16:15:00'}), /未核验/)
  assert.match(quoteDescription({}), /未核验/)
})

test('page uses one valuation for holdings and review, separates event time', () => {
  const source = readFileSync(new URL('../src/pages/Watchlist.jsx', import.meta.url), 'utf8')
  assert.ok(source.includes('watchlistData?.review'))
  assert.ok(!source.includes('coachApi.getPaperReview('))
  assert.ok(source.includes('建仓 / 加入时间'))
  assert.ok(source.includes('quoteDescription(record)'))
  assert.ok(!source.includes('record.current_price || record.avg_price'))
})
