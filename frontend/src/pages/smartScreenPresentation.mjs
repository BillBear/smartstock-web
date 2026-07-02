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

export function getPickDecisionActionPresentation(pick) {
  const grade = pick?.decision?.grade || 'C'
  const mode = pick?.decision?.mode || 'watch_only'
  const level = pick?.decision?.level || ''
  if (grade === 'A' && mode === 'real_allowed') {
    return { text: '交易计划', color: 'red' }
  }
  if (['A', 'B'].includes(grade) && mode !== 'watch_only') {
    return { text: '模拟验证', color: 'orange' }
  }
  if (grade === 'C') {
    return { text: level || '观察等待', color: 'blue' }
  }
  if (grade === 'D') {
    return { text: '不建议', color: 'default' }
  }
  if (pick?.action === 'pass') {
    return { text: '跳过', color: 'default' }
  }
  return { text: '观察', color: 'blue' }
}

export function getProbabilityModelPresentation(probabilityModel = {}) {
  const label = probabilityModel?.label || '规则代理概率'
  const calibrated = Boolean(probabilityModel?.calibrated)
  const isWeakMl = probabilityModel?.type === 'ml_explainable_probability' && !calibrated
  return {
    label,
    alertType: calibrated ? 'success' : 'warning',
    message: calibrated
      ? '概率已完成历史样本校准'
      : (isWeakMl ? '当前模型概率未通过样本外校准' : '当前上涨/回撤概率仍是规则代理概率'),
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
