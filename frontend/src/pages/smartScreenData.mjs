export function shouldRefreshCurrentTradingPicks({
  calendarContext = {},
  canRefresh = true,
  isRefreshing = false,
} = {}) {
  const hasStaleTradingSnapshot = calendarContext?.mode === 'trading' && Boolean(calendarContext?.snapshot_trade_date)
  return Boolean(canRefresh && !isRefreshing && hasStaleTradingSnapshot)
}

export function getCalendarDisplayContext(calendarContext = {}, tradePlan = {}) {
  const mode = calendarContext?.mode || 'trading'
  const requestedDate = calendarContext?.requested_date || '-'
  const candidateDate = calendarContext?.effective_trade_date || calendarContext?.snapshot_trade_date || '-'
  const signalAge = calendarContext?.signal_age_days
  const isPreparationMode = mode === 'preparation'
  const isHistoricalMode = mode === 'historical'
  const isObservationMode = isPreparationMode || isHistoricalMode
  const planHeadline = tradePlan?.headline || '等待生成交易计划'
  const planSummary = tradePlan?.summary || '系统会先判断市场环境和策略证据，再决定是否输出可执行候选。'

  let kicker = '今日行动'
  let headline = planHeadline
  let alertMessage = calendarContext?.message || ''
  let dateMetricTitle = '交易日'
  let refreshDisabledReason = ''

  if (isPreparationMode) {
    kicker = '备战观察'
    headline = '备战观察'
    dateMetricTitle = '候选池交易日'
    alertMessage = calendarContext?.message || `当前日期 ${requestedDate} 非交易日，正在展示 ${candidateDate} 交易日候选池，仅供观察准备。`
    refreshDisabledReason = `当前日期 ${requestedDate} 非交易日，不生成新的交易计划；${candidateDate} 是展示的候选池交易日。`
  } else if (isHistoricalMode) {
    kicker = '历史快照'
    headline = '历史快照观察'
    dateMetricTitle = '历史候选池日期'
    alertMessage = calendarContext?.message || `展示 ${candidateDate} 历史候选池，仅供复盘观察。`
    refreshDisabledReason = '历史快照只读复盘，不生成新的交易计划。'
  } else if (calendarContext?.snapshot_trade_date) {
    refreshDisabledReason = ''
  }

  return {
    mode,
    isPreparationMode,
    isHistoricalMode,
    isObservationMode,
    kicker,
    headline,
    summary: isObservationMode ? alertMessage : planSummary,
    alertMessage,
    dateMetricTitle,
    dateMetricValue: candidateDate,
    currentDateText: `当前日期：${requestedDate}`,
    candidateDateText: `候选池交易日：${candidateDate}`,
    signalAgeText: signalAge === null || signalAge === undefined ? '-' : `${signalAge} 天`,
    refreshDisabledReason,
  }
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
  const deepAnalysis = funnel.deep_analysis_count === null || funnel.deep_analysis_count === undefined
    ? null
    : Number(funnel.deep_analysis_count || 0)
  const finalOutput = Number(funnel.final_pick_count || 0)
  const rejectionSummary = funnel.rejection_summary && typeof funnel.rejection_summary === 'object'
    ? funnel.rejection_summary
    : {}
  const topRejectionReasons = Object.entries(rejectionSummary)
    .map(([reason, count]) => ({ reason, count: Number(count || 0) }))
    .sort((left, right) => right.count - left.count || left.reason.localeCompare(right.reason))
    .slice(0, 6)
  const policyText = funnel?.filter_policy?.message || ''
  const deepAnalysisText = deepAnalysis === null ? '未记录' : deepAnalysis
  const summaryText = fullMarket
    ? `候选漏斗：${fullMarket} -> ${prefilter} -> ${recall} -> ${deepAnalysisText} -> ${finalOutput}`
    : '候选漏斗暂无数据'

  return {
    fullMarket,
    prefilter,
    recall,
    deepAnalysis,
    finalOutput,
    summaryText,
    policyText,
    topRejectionReasons,
  }
}

export function getRankingEvidenceStatus(evidence = {}) {
  const available = Boolean(evidence?.available)
  const readiness = evidence?.evidence_readiness || {}
  const productionEvidence = Boolean(evidence?.production_evidence)
  const covered = Number(readiness.covered_date_count || 0)
  const required = Number(readiness.required_covered_date_count || 30)
  const blockingReasons = Array.isArray(readiness.blocking_reasons) ? readiness.blocking_reasons : []
  const coverageText = `${covered}/${required}`

  if (!available) {
    return {
      alertType: 'warning',
      tagColor: 'orange',
      title: '排序证据不足',
      description: evidence?.message || '尚未生成真实历史 ranking evaluation 报告，当前排序只能作为研究观察。',
      coverageText,
      blockingReasons,
    }
  }

  if (!productionEvidence) {
    const reasonText = blockingReasons.length ? `阻塞原因：${blockingReasons.join('、')}` : '阻塞原因：覆盖或样本不足'
    return {
      alertType: 'warning',
      tagColor: 'orange',
      title: '排序证据不足',
      description: `历史覆盖 ${coverageText}，${reasonText}。在证据通过前，不应把排序结果解释为高置信交易计划。`,
      coverageText,
      blockingReasons,
    }
  }

  return {
    alertType: 'success',
    tagColor: 'green',
    title: '排序证据已通过基础覆盖门槛',
    description: `历史覆盖 ${coverageText}，当前报告可作为排序质量证据；仍需结合回测和样本外指标审查。`,
    coverageText,
    blockingReasons,
  }
}
