export function getMarketFactorPresentation(raw) {
  const present = typeof raw === 'number' || (typeof raw === 'string' && raw.trim() !== '')
  const value = present ? Number(raw) : NaN
  if (!Number.isFinite(value)) {
    return { available: false, value: null, text: '未记录' }
  }
  return { available: true, value, text: value.toFixed(2) }
}
