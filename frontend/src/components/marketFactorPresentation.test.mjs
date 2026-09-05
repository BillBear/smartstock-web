import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

test('missing market factors are not rendered as zero scores', async () => {
  const component = readFileSync(new URL('./MarketFactorExplain.jsx', import.meta.url), 'utf8')
  assert.doesNotMatch(component, /Number\(drivers\?\.\[key\] \|\| 0\)/)
  const { getMarketFactorPresentation } = await import('./marketFactorPresentation.mjs')
  for (const value of [null, undefined, '', ' ', 'bad', NaN, Infinity]) {
    const result = getMarketFactorPresentation(value)
    assert.equal(result.available, false)
    assert.equal(result.text, '未记录')
  }
  assert.deepEqual(getMarketFactorPresentation(0), { available: true, value: 0, text: '0.00' })
  assert.deepEqual(getMarketFactorPresentation('65.4'), { available: true, value: 65.4, text: '65.40' })
})
