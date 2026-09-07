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

export function getPickDataQualityPresentation(pick = {}) {
  const degraded = pick?.analysis_status === 'degraded_timeout'
    || pick?.probability_model?.type === 'snapshot_degraded'
    || pick?.evidence_summary?.strategy_version === 'snapshot-degraded-watch-only'
  return {
    degraded,
    label: degraded ? '分析超时 / 代理估计' : '',
    description: degraded
      ? '深度分析未完成。收益为公式代理估计，综合分为快照预筛映射分，不是成功率；不能作为完整策略分析或收益承诺。'
      : '',
  }
}

function displayNumber(value) {
  if (typeof value !== 'number' && (typeof value !== 'string' || value.trim() === '')) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function getPickEvidencePresentation(pick = {}) {
  const score = displayNumber(pick?.score_breakdown?.total)
  const estimate = displayNumber(pick?.expected_return_pct)
  const sourceLabel = {
    observed_production: '已保存策略快照',
    reconstructed_research: '历史规则重建',
    shadow: '前向旁路观察',
  }[pick?.baseline_kind] || '来源未标记'
  const runId = typeof pick?.run_id === 'string' && pick.run_id.trim() ? pick.run_id : null
  return {
    backendRankText: getRankPresentation(displayNumber(pick?.rank_no)).rankText,
    score,
    scoreText: score === null ? '未记录' : `${score.toFixed(2)} 分`,
    estimateText: estimate === null ? '未记录' : `${estimate.toFixed(2)}%（估计）`,
    sourceLabel,
    runId,
    description: `${sourceLabel}。分数和估计收益不是实证收益或成功率，来源类别也不代表策略已验证。${runId ? `证据运行 ID：${runId}` : '未绑定可核验的证据运行 ID。'}`,
  }
}

export function getRefreshFeedback(response = {}) {
  if (response?.accepted !== true) {
    return { type: 'warning', text: response?.calendar_context?.message || '当前不可刷新候选池' }
  }
  const result = response?.result || {}
  if (result?.snapshot_persistence?.status === 'failed') {
    return { type: 'error', text: '候选已计算，但快照保存失败；当前列表仍可能是旧快照，请检查后端日志后重试。' }
  }
  if ((result.picks || []).some((pick) => getPickDataQualityPresentation(pick).degraded)
    || Number(result?.universe_meta?.analysis_timeout_count || 0) > 0) {
    return { type: 'warning', text: '刷新返回，但深度分析有超时；请查看数据质量提示，不应当作完整分析结果。' }
  }
  return { type: 'success', text: '候选池刷新完成' }
}

export function getSnapshotProvenancePresentation(result = {}) {
  const updatedAt = typeof result?.updated_at === 'string' ? result.updated_at : ''
  const marketSavedAt = result?.universe_meta?.market_snapshot_created_at
  const picks = Array.isArray(result?.picks) ? result.picks : []
  return {
    sourceText: result?.status === 'cached_from_store'
      ? '已保存候选快照（本次读取未重新计算）'
      : '候选来源未标记',
    generatedAtText: /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/.test(updatedAt)
      ? updatedAt : '生成时刻未记录（仅有快照日期）',
    marketSavedAtText: typeof marketSavedAt === 'string' && marketSavedAt.trim()
      ? marketSavedAt : '未记录',
    quoteTimeText: '行情原始时刻未记录；快照保存时间不等于行情时间，不能据此确认实时性。',
    observationOnly: picks.length > 0 && picks.every((pick) => (
      pick?.decision?.grade === 'C' && pick?.decision?.mode === 'watch_only'
    )),
  }
}
