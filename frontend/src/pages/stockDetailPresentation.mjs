export function getStockStrategyActionPresentation(strategyContext) {
  if (!strategyContext) {
    return { text: '未入候选池', color: 'default' }
  }
  const grade = strategyContext?.decision?.grade || 'C'
  const mode = strategyContext?.decision?.mode || 'watch_only'
  const level = strategyContext?.decision?.level || ''
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
  return { text: '观察', color: 'blue' }
}

export function getStockStrategyMetricItems(strategyContext) {
  if (!strategyContext) return []
  const actionPresentation = getStockStrategyActionPresentation(strategyContext)
  const grade = strategyContext?.decision?.grade || '-'
  return [
    { title: '决策等级', value: grade, suffix: '' },
    { title: '执行模式', value: actionPresentation.text, suffix: '' },
    {
      title: '预期收益',
      value: Number(strategyContext?.expected_return_pct || 0),
      precision: 2,
      suffix: '%',
    },
  ]
}
