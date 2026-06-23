export function shouldRefreshCurrentTradingPicks({
  calendarContext = {},
  canRefresh = true,
  isRefreshing = false,
} = {}) {
  const hasStaleTradingSnapshot = calendarContext?.mode === 'trading' && Boolean(calendarContext?.snapshot_trade_date)
  return Boolean(canRefresh && !isRefreshing && hasStaleTradingSnapshot)
}
