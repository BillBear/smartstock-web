export const RANKING_TABLE_COLUMN_KEYS = [
  'rank',
  'stock',
  'decision',
  'user_action',
  'expected_return_pct',
  'position_pct',
  'strategy_score',
  'operation',
]

export function getPickActionPresentation(pick, canPaperBuy) {
  const grade = pick?.decision?.grade || 'C'
  const mode = pick?.decision?.mode || 'watch_only'
  const isTradePlanGrade = ['A', 'B'].includes(grade)
  const isRealAllowed = mode === 'real_allowed'
  const canShowPaperAction = Boolean(canPaperBuy && isTradePlanGrade && mode !== 'watch_only')

  let paperDisabledReason = ''
  if (!canPaperBuy) {
    paperDisabledReason = '非交易日不生成交易计划，不能模拟验证'
  } else if (!isTradePlanGrade) {
    paperDisabledReason = '只有 A/B 级候选允许模拟验证'
  } else if (mode === 'watch_only') {
    paperDisabledReason = '观察候选不进入模拟验证'
  }

  return {
    canAddWatch: grade !== 'D',
    canShowPaperAction,
    paperActionLabel: isRealAllowed ? '模拟买入' : '模拟验证',
    paperDisabledReason,
  }
}

export function getRankPresentation(rank) {
  const numericRank = Number(rank)
  const hasRank = Number.isFinite(numericRank) && numericRank > 0
  return {
    isTopRank: hasRank && numericRank <= 3,
    rankText: hasRank ? String(numericRank) : '-',
  }
}
