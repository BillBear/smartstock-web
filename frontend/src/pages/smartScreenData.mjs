export function shouldRefreshCurrentTradingPicks({
  calendarContext = {},
  canRefresh = true,
  isRefreshing = false,
} = {}) {
  const hasStaleTradingSnapshot = calendarContext?.mode === 'trading' && Boolean(calendarContext?.snapshot_trade_date)
  return Boolean(canRefresh && !isRefreshing && hasStaleTradingSnapshot)
}

export function getSmartScreenDiagnostic(result = {}) {
  const universeMeta = result?.universe_meta || {}
  const tradePlan = result?.trade_plan || {}
  const picks = Array.isArray(result?.picks) ? result.picks : []
  const totalUniverse = Number(universeMeta.total_universe_count || 0)
  const prefilterCount = Number(universeMeta.after_prefilter_count || 0)
  const candidateCount = Number(universeMeta.candidate_count || 0)
  const analyzedCount = Number(universeMeta.analyzed_count || 0)
  const analysisCompletedCount = Number(universeMeta.analysis_completed_count || 0)
  const analysisTimeoutCount = Number(universeMeta.analysis_timeout_count || 0)
  const analysisDegradedCount = Number(universeMeta.analysis_degraded_count || 0)
  const analysisStatus = universeMeta.analysis_status || ''
  const coverageStatus = universeMeta.data_coverage_status || ''
  let coverageLevel = 'info'
  let coverageText = ''

  if (analysisTimeoutCount > 0 || ['degraded_timeout', 'partial_timeout'].includes(analysisStatus)) {
    coverageLevel = 'warning'
    coverageText = `全量池正常：全A ${totalUniverse || '-'} 只，预筛 ${prefilterCount || '-'} 只，策略目标 ${candidateCount || '-'} 只；深度分析超时 ${analysisTimeoutCount || '-'} 只，已降级展示 ${analysisDegradedCount || picks.length || '-'} 只今日快照观察候选。`
  } else if (coverageStatus === 'full_snapshot_available' && totalUniverse > 0) {
    coverageLevel = 'success'
    const candidateLabel = universeMeta.source === 'pick_snapshots' ? '快照候选' : '策略目标'
    const completedText = analysisCompletedCount || analyzedCount || '-'
    coverageText = `全量池正常：全A ${totalUniverse} 只，预筛 ${prefilterCount || '-'} 只，${candidateLabel} ${candidateCount || '-'} 只，评分完成 ${completedText} 只。`
  } else if (coverageStatus === 'sparse_market_snapshot') {
    coverageLevel = 'warning'
    coverageText = `同日全量快照偏少：当前仅 ${totalUniverse || '-'} 只，请先刷新或检查数据源。`
  } else if (coverageStatus === 'market_snapshot_missing') {
    coverageLevel = 'warning'
    coverageText = `缺少同日全量快照；最近可用快照为 ${universeMeta.latest_market_snapshot_trade_date || '-'}，建议刷新后再判断候选池质量。`
  } else if (coverageStatus === 'market_snapshot_unavailable') {
    coverageLevel = 'warning'
    coverageText = '暂未取得市场快照诊断，无法确认本次候选池是否基于同日全量池。'
  }

  const coreCount = Number(tradePlan.core_count || 0)
  const trialCount = Number(tradePlan.trial_count || 0)
  const watchCount = Number(tradePlan.watch_count || 0)
  let decisionText = ''
  if (picks.length > 0 && coreCount + trialCount === 0 && watchCount > 0) {
    decisionText = '当前有候选但 A/B 级为 0，说明买入候选被策略准入、回撤概率或回测证据门槛拦截，不代表股票池缺失。'
  }

  return {
    coverageStatus: coverageLevel === 'success' ? 'ok' : 'warning',
    coverageLevel,
    coverageText,
    decisionText,
  }
}

export function getUniverseFunnelSummary(funnel = {}) {
  const fullMarket = Number(funnel.universe_count || 0)
  const prefilter = Number(funnel.prefilter_count || 0)
  const recall = Number(funnel.recall_count || 0)
  const deepAnalysis = Number(funnel.deep_analysis_count || 0)
  const finalOutput = Number(funnel.final_pick_count || 0)
  const summaryText = fullMarket
    ? `候选漏斗：${fullMarket} -> ${prefilter} -> ${recall} -> ${deepAnalysis} -> ${finalOutput}`
    : '候选漏斗暂无数据'

  return {
    fullMarket,
    prefilter,
    recall,
    deepAnalysis,
    finalOutput,
    summaryText,
  }
}
