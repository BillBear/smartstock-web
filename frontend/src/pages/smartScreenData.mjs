export function resolveBatchReviewTradeDate({
  calendarContext = {},
  cachedPicks = null,
  cacheIsFresh = false,
} = {}) {
  const hasCachedPicks = (cachedPicks?.picks || []).filter(Boolean).length > 0
  return calendarContext?.snapshot_trade_date
    || calendarContext?.effective_trade_date
    || (cacheIsFresh && hasCachedPicks ? cachedPicks?.trade_date : null)
    || (hasCachedPicks ? cachedPicks?.trade_date : null)
    || undefined
}

export function shouldRefreshCurrentTradingPicks({
  calendarContext = {},
  cacheIsFresh = false,
  summaryData = null,
  canRefresh = true,
} = {}) {
  const hasStaleTradingSnapshot = calendarContext?.mode === 'trading' && Boolean(calendarContext?.snapshot_trade_date)
  return Boolean(canRefresh && !summaryData?.is_refreshing && (!cacheIsFresh || hasStaleTradingSnapshot))
}

export function buildDisplayedPickList({
  result = null,
  summary = null,
  batchReview = null,
} = {}) {
  const directPicks = (result?.picks || summary?.top_picks || []).filter(Boolean)
  if (directPicks.length > 0) {
    return {
      pickList: directPicks,
      usingBatchReviewFallback: false,
    }
  }

  const reviewPicks = batchReview?.available ? (batchReview?.items || []).filter(Boolean) : []
  return {
    pickList: reviewPicks,
    usingBatchReviewFallback: reviewPicks.length > 0,
  }
}
