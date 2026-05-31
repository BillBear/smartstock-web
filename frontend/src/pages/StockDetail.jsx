import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Alert, Card, Row, Col, Statistic, Tabs, Button, Tag, Timeline, Progress, Spin, Empty, Table, Space } from 'antd'
import {
  ArrowLeftOutlined,
  RiseOutlined,
  FallOutlined,
  LineChartOutlined,
  DollarOutlined,
  FundOutlined,
  SafetyOutlined,
  StarOutlined,
  StarFilled
} from '@ant-design/icons'
import ScoreRadar from '../components/ScoreRadar'
import { analysisApi, coachApi } from '../services/api'
import './StockDetail.css'

const clampScore = (value) => Math.max(0, Math.min(100, Math.round(Number(value || 0))))
const clampPercent = (value) => Math.max(0, Math.min(100, Number(Number(value || 0).toFixed(2))))
const normalizedScore = (value) => clampScore((Number(value || 0) + 100) / 2)
const amountToYi = (value) => Number(value || 0) / 100000000
const hasValue = (value) => value !== undefined && value !== null && value !== ''

const STRATEGY_METRIC_META = [
  { key: 'technical', label: '技术趋势', color: '#40A9FF' },
  { key: 'moneyFlow', label: '资金强度', color: '#36CFC9' },
  { key: 'fundamental', label: '策略质量', color: '#FFC53D' },
  { key: 'valuation', label: '风险收益', color: '#B37FEB' },
]

const buildStrategyScores = (breakdown = {}) => ({
  technical: clampScore(breakdown.trend),
  moneyFlow: clampScore(breakdown.money_flow),
  fundamental: clampScore(breakdown.quality),
  valuation: clampScore(breakdown.risk_adjusted),
})

const actionText = {
  buy: '可买入',
  watch: '观察',
  pass: '跳过',
}

const STATE_LABEL = {
  offensive: '进攻',
  neutral: '均衡',
  defensive: '防守',
}

const formatPct = (value, multiplier = 1) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return `${(num * multiplier).toFixed(1)}%`
}

const asPercentValue = (value) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return Math.abs(num) <= 1 ? Number((num * 100).toFixed(1)) : Number(num.toFixed(1))
}

const asNumberOrNull = (value, digits = 2) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return Number(num.toFixed(digits))
}

const formatPrice = (value) => {
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) return '-'
  return `¥${num.toFixed(2)}`
}

const formatPriceRange = (range) => {
  if (!Array.isArray(range) || range.length < 2) return '-'
  const [min, max] = range
  const minText = formatPrice(min)
  const maxText = formatPrice(max)
  if (minText === '-' || maxText === '-') return '-'
  return `${minText} - ${maxText}`
}

const buildOperationPlan = ({ symbolStrategy, aiDecision, riskWarnings, strategyEvidence }) => {
  const hasStrategy = Boolean(symbolStrategy?.available)
  const action = hasStrategy ? (symbolStrategy.action || 'watch') : 'unavailable'
  const strategyCode = symbolStrategy?.strategy_code || symbolStrategy?.evidence_summary?.strategy_code || strategyEvidence?.strategy_code
  const entryRange = hasStrategy ? (symbolStrategy.entry_range || []) : []
  const takeProfit = hasStrategy ? symbolStrategy.take_profit : aiDecision?.position_advice?.stop_profit
  const stopLoss = hasStrategy ? symbolStrategy.stop_loss : aiDecision?.position_advice?.stop_loss
  const positionPct = hasStrategy ? symbolStrategy.position_pct : null
  const horizonDays = hasStrategy ? symbolStrategy.horizon_days : null
  const invalidConditions = hasStrategy
    ? (symbolStrategy.invalid_conditions || [])
    : ['该股当前不在智能选股输出池中', '缺少策略级入场区间和回测证据联动']
  const proxyOnly = Boolean(symbolStrategy?.evidence_summary?.proxy_only || strategyEvidence?.proxy_model)
  const status = action === 'buy' ? 'buy' : action === 'watch' ? 'watch' : action === 'pass' ? 'pass' : 'unavailable'
  const statusMeta = {
    buy: {
      label: '可按纪律试仓',
      color: 'green',
      headline: '可按纪律试仓，不追高，不满仓。',
    },
    watch: {
      label: '观察等待',
      color: 'gold',
      headline: '观察等待，只有触发条件改善后才考虑试仓。',
    },
    pass: {
      label: '暂不操作',
      color: 'red',
      headline: '暂不操作，当前赔率或风险条件不满足。',
    },
    unavailable: {
      label: '证据不足',
      color: 'default',
      headline: '暂无可验证策略计划，不输出交易动作。',
    },
  }[status]
  const entryText = (() => {
    if (!hasStrategy) return '不展示建仓价。当前仅有行情分析参考，缺少智能选股策略计划。'
    if (status === 'buy') {
      return `入场区间 ${formatPriceRange(entryRange)}；首仓不超过 ${Number(positionPct || 0).toFixed(1)}%，只在区间内分批试仓。`
    }
    if (status === 'watch') {
      return `不立刻建仓；可把 ${formatPriceRange(entryRange)} 作为预案区间，只有趋势和资金条件重新改善后再评估。`
    }
    return '不展示建仓价。当前策略未给出可执行入场条件。'
  })()
  const addPositionRule = (() => {
    if (status === 'buy') {
      return '默认不主动加仓；只有首仓盈利、未破止损、价格仍未显著远离入场区间，且趋势/资金继续改善时，才允许小幅加仓。'
    }
    if (status === 'watch') {
      return '观察状态不加仓，也不因回调补仓；先等入场条件重新满足。'
    }
    return '禁止加仓；没有可验证交易计划时，不用加仓摊薄亏损。'
  })()
  const sellRules = hasStrategy
    ? [
        `跌破止损 ${formatPrice(stopLoss)}：执行退出纪律，不做主观补仓。`,
        `到达止盈 ${formatPrice(takeProfit)}：分批兑现，避免盈利回撤。`,
        invalidConditions.length > 0
          ? `策略失效：${invalidConditions.slice(0, 2).join('；')}。`
          : '策略失效：趋势、量能或资金条件转弱时重新评估。',
      ]
    : [
        '未进入智能选股策略池，不输出买卖动作。',
        '若已有持仓，以个人原始止损线和仓位纪律为主。',
        '等待该股重新进入策略池，或在策略回测页补充证据后再评估。',
      ]

  return {
    status,
    statusLabel: statusMeta.label,
    statusColor: statusMeta.color,
    headline: statusMeta.headline,
    source: hasStrategy ? 'smart_screen_strategy' : 'ai_analysis_fallback',
    sourceLabel: hasStrategy ? '智能选股策略计划' : 'AI行情分析低置信度参考',
    strategyCode: strategyCode || null,
    entryRange,
    entryText,
    positionPct,
    horizonDays,
    takeProfit,
    stopLoss,
    addPositionRule,
    sellRules,
    invalidConditions,
    warnings: riskWarnings || [],
    confidenceLevel: symbolStrategy?.confidence_level || null,
    expectedEdgePct: symbolStrategy?.expected_edge_pct,
    profitFactorProxy: symbolStrategy?.profit_factor_proxy,
    proxyOnly,
    evidenceLabel: strategyEvidence?.evidence_source?.label || '策略证据待补充',
  }
}

const createInitialStockData = (routeSymbol) => ({
  symbol: routeSymbol || '',
  name: routeSymbol || '加载中',
  price: 0,
  change: 0,
  changeAmount: 0,
  open: 0,
  high: 0,
  low: 0,
  volume: 0,
  turnover: 0,
  totalScore: 0,
  scoreLabel: '行情分析分',
  scoreSource: 'analysis',
  scores: {
    technical: 0,
    moneyFlow: 0,
    fundamental: 0,
    valuation: 0
  },
  technicalAnalysis: {
    trend: '待分析',
    signals: [
      '等待实时行情加载后生成技术面分析',
    ]
  },
  moneyFlowAnalysis: {
    mainNetInflow: 0,
    controlRatio: 0,
    trend: '待分析',
    strength: '待确认',
    signals: [
      '等待资金流数据加载后生成资金面分析',
    ]
  },
  fundamentalAnalysis: {
    pe: null,
    pb: null,
    roe: null,
    revenueGrowth: null,
    netProfitGrowth: null,
    grossMargin: null,
    debtRatio: null,
    reportDate: null,
    source: null,
    isAvailable: false,
    strategyQualityScore: null,
    strategyRiskScore: null,
    signals: [
      '等待基本面数据接入后生成分析',
    ]
  },
  riskWarnings: [
    '数据加载完成前，不应依据默认展示做投资判断',
  ],
  operationPlan: {
    status: 'unavailable',
    statusLabel: '证据不足',
    statusColor: 'default',
    headline: '暂无可验证策略计划，不输出交易动作。',
    source: 'loading',
    sourceLabel: '等待数据加载',
    strategyCode: null,
    entryRange: [],
    entryText: '等待实时行情和策略计划加载。',
    positionPct: null,
    horizonDays: null,
    takeProfit: null,
    stopLoss: null,
    addPositionRule: '等待策略计划加载后再评估。',
    sellRules: ['数据加载完成前，不应依据默认展示做投资判断。'],
    invalidConditions: [],
    warnings: ['数据加载完成前，不应依据默认展示做投资判断'],
    confidenceLevel: null,
    expectedEdgePct: null,
    profitFactorProxy: null,
    proxyOnly: false,
    evidenceLabel: '策略证据待补充',
  },
  backtestPerformance: {
    available: false,
    strategyCode: null,
    evidenceSource: null,
    winRate: null,
    annualReturn: null,
    maxDrawdown: null,
    sharpe: null,
    profitLossRatio: null,
    sampleRuns: 0,
    closedRoundtrips: 0,
    validHistorySymbols: 0,
    calendarDays: 0,
    holdingDays: null,
    avgReturn: null,
    credibilityScore: null,
    credibilityGrade: null,
    liveReady: false,
    runId: null,
    latestRunId: null,
    evidenceHash: null,
    verificationPath: null,
    displayScope: 'unavailable',
    proxyOnly: false,
    summary: '暂无策略回测证据',
    notes: [],
    byState: [],
    recentRoundtrips: [],
    recentTrades: [],
    gateChecks: [],
    executionAssumptions: {},
    sampleSummary: {},
    config: {},
  },
  news: {
    totalScore: 50,
    sentiment: 'neutral',
    latestEvents: [],
  },
  strategyContext: null,
  isWatchlist: false
})

const StockDetail = () => {
  const { symbol } = useParams()
  const navigate = useNavigate()

  const [stockData, setStockData] = useState(() => createInitialStockData(symbol))
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')

  const toggleWatchlist = () => {
    setStockData(prev => ({ ...prev, isWatchlist: !prev.isWatchlist }))
  }

  useEffect(() => {
    setStockData(createInitialStockData(symbol))
    setLoadError('')
    const loadDetail = async () => {
      if (!symbol) return
      setLoading(true)
      try {
        const optionalFullAnalysis = Promise.race([
          analysisApi.full({
            symbol,
            days: 120,
            money_flow_days: 5,
            holding_period: 'medium',
            risk_level: 'medium',
            target_return: 15,
          }).catch((err) => ({ __error: err })),
          new Promise((resolve) => setTimeout(() => {
            resolve({ __error: new Error('行情分析加载超时，已先展示策略计划') })
          }, 6000)),
        ])
        const [fullResult, symbolNews, symbolStrategy] = await Promise.all([
          optionalFullAnalysis,
          coachApi.getSymbolNews(symbol, { limit: 8 }).catch(() => null),
          coachApi.getSymbolStrategy(symbol, { user_id: 'default', risk_level: 'medium' }).catch(() => null),
        ])
        const fullLoadError = fullResult?.__error
        const full = fullLoadError ? {} : fullResult
        if (fullLoadError) {
          setLoadError(fullLoadError?.response?.data?.message || fullLoadError?.message || '行情分析加载失败，已保留策略计划展示')
        } else {
          setLoadError('')
        }
        const strategyCode = symbolStrategy?.strategy_code || symbolStrategy?.evidence_summary?.strategy_code || 'trend_breakout'
        const strategyEvidence = await coachApi.getStrategyEvidence(strategyCode, { state_tag: 'neutral' }).catch(() => null)
        const realtime = full?.realtime || {}
        const signal = full?.signal_analysis || {}
        const moneyFlow = full?.money_flow?.money_flow || {}
        const aiDecision = full?.ai_decision || {}
        const fundamental = full?.fundamental?.data || {}
        const fundamentalText = full?.fundamental?.analysis || {}
        const rawNews = full?.news || symbolNews || {}
        const news = {
          ...rawNews,
          latest_events: (rawNews?.latest_events || []).filter((item) => ['stock', 'industry'].includes(item?.event_level)),
        }
        const technicalScore = normalizedScore(signal?.score)
        const moneyScore = normalizedScore(aiDecision?.scores?.money_flow)
        const strategyBreakdown = symbolStrategy?.available ? (symbolStrategy?.score_breakdown || {}) : {}
        const strategyScore = Number(strategyBreakdown?.total)
        const hasStrategyScore = symbolStrategy?.available && Number.isFinite(strategyScore) && strategyScore > 0
        const roeScore = hasValue(fundamental?.roe) ? clampScore(50 + Number(fundamental.roe)) : 50
        const growthScore = hasValue(fundamental?.net_profit_growth) ? clampScore(50 + Number(fundamental.net_profit_growth) * 0.7) : 50
        const fundamentalScore = fundamental?.is_available ? clampScore(roeScore * 0.55 + growthScore * 0.45) : 50
        const peValue = hasValue(realtime?.pe) ? Number(realtime.pe) : (hasValue(fundamental?.pe) ? Number(fundamental.pe) : null)
        const pbValue = hasValue(realtime?.pb) ? Number(realtime.pb) : (hasValue(fundamental?.pb) ? Number(fundamental.pb) : null)
        const valuationScore = peValue ? clampScore(80 - Math.max(0, peValue - 15)) : 50
        const analysisScore = clampPercent(
          technicalScore * 0.35
          + moneyScore * 0.25
          + fundamentalScore * 0.15
          + valuationScore * 0.10
          + Number(news?.total_score || 50) * 0.15
        )
        const totalScore = hasStrategyScore ? clampPercent(strategyScore) : analysisScore
        const mainNetYi = amountToYi(moneyFlow?.main_net_inflow)
        const evidenceOverall = strategyEvidence?.overall || {}
        const displayRun = strategyEvidence?.display_run || null
        const latestRun = strategyEvidence?.latest_run || {}
        const evidenceSource = strategyEvidence?.evidence_source || {}
        const verificationTarget = strategyEvidence?.verification_target || {}
        const sampleSummary = strategyEvidence?.sample_summary || {}
        const credibilitySummary = strategyEvidence?.credibility_summary || {}
        const latestMetrics = latestRun?.metrics || {}
        const latestDiagnostics = latestRun?.diagnostics || {}
        const latestCredibility = latestRun?.credibility || credibilitySummary || {}
        const latestClosedRoundtrips = Number(latestRun?.sample_summary?.closed_roundtrips || latestDiagnostics.closed_roundtrips || 0)
        const latestHasClosedTrades = latestClosedRoundtrips > 0
        const displayMetrics = displayRun?.metrics || (latestHasClosedTrades ? latestMetrics : evidenceOverall)
        const displayDiagnostics = displayRun?.diagnostics || (latestHasClosedTrades
          ? latestDiagnostics
          : {
              ...latestDiagnostics,
              closed_roundtrips: evidenceOverall.closed_roundtrips,
              avg_return_pct: evidenceOverall.avg_return_pct,
            })
        const displaySampleSummary = displayRun?.sample_summary || sampleSummary || {}
        const evidenceScope = evidenceSource?.display_scope || (displayRun ? 'display_run' : 'overall')
        const evidenceAvailable = Boolean(
          strategyEvidence
          && (
            Number(evidenceOverall.sample_runs || 0) > 0
            || Number(sampleSummary.closed_roundtrips || 0) > 0
            || latestClosedRoundtrips > 0
            || Number(latestMetrics.max_drawdown || 0) > 0
          )
        )
        const proxyOnlyEvidence = Boolean(
          symbolStrategy?.evidence_summary?.proxy_only
          || symbolStrategy?.evidence_summary?.source === 'proxy_model'
          || strategyEvidence?.proxy_model
        )
        const fundamentalSignals = []
        if (fundamental?.is_available) {
          fundamentalSignals.push(`财报期 ${fundamental.report_date || '-'}，来源：同花顺财务摘要`)
          if (hasValue(fundamental.roe)) fundamentalSignals.push(`ROE ${Number(fundamental.roe).toFixed(2)}%`)
          if (hasValue(fundamental.net_profit_growth)) fundamentalSignals.push(`净利润同比 ${Number(fundamental.net_profit_growth).toFixed(2)}%`)
          if (hasValue(fundamental.revenue_growth)) fundamentalSignals.push(`营收同比 ${Number(fundamental.revenue_growth).toFixed(2)}%`)
          if (fundamentalText?.summary) fundamentalSignals.push(fundamentalText.summary)
        } else {
          fundamentalSignals.push(fundamental?.reason || '暂未获取到可靠财务摘要数据')
        }
        if (hasStrategyScore) {
          fundamentalSignals.push(`智能选股“策略质量”分 ${clampScore(strategyBreakdown.quality)}，该分数来自趋势结构、量能、资金闸门，不等同于财报基本面`)
          fundamentalSignals.push(`智能选股“风险收益”分 ${clampScore(strategyBreakdown.risk_adjusted)}，用于衡量赔率/回撤后的可执行性`)
        }
        const riskWarnings = (symbolStrategy?.risks?.length ? symbolStrategy.risks : null)
          || (aiDecision?.risk_assessment?.warnings?.length
            ? aiDecision.risk_assessment.warnings
            : aiDecision?.risk_assessment?.factors)
          || [
              '资金流和技术信号均可能快速变化，不应单独作为买卖依据',
              '若实时数据源不可用，请以交易软件行情为准',
            ]
        const operationPlan = buildOperationPlan({
          symbolStrategy,
          aiDecision,
          riskWarnings,
          strategyEvidence,
        })
        setStockData({
          symbol: realtime?.code || full?.symbol || symbol,
          name: full?.name || realtime?.name || symbol,
          price: Number(realtime?.price || 0),
          change: Number(realtime?.pct_change || 0),
          changeAmount: Number(realtime?.change || 0),
          open: Number(realtime?.open || 0),
          high: Number(realtime?.high || 0),
          low: Number(realtime?.low || 0),
          volume: Number(realtime?.volume || 0) / 10000,
          turnover: Number(realtime?.amount || 0) / 100000000,
          totalScore,
          scoreLabel: hasStrategyScore ? '智能选股策略评分' : '行情分析分',
          scoreSource: hasStrategyScore ? 'strategy' : 'analysis',
          scores: hasStrategyScore ? buildStrategyScores(strategyBreakdown) : {
            technical: technicalScore,
            moneyFlow: moneyScore,
            fundamental: fundamentalScore,
            valuation: valuationScore,
          },
          technicalAnalysis: {
            trend: signal?.trend || signal?.overall_signal || '待分析',
            signals: signal?.signals?.length ? signal.signals : ['暂无技术信号'],
          },
          moneyFlowAnalysis: {
            mainNetInflow: Number(mainNetYi.toFixed(2)),
            controlRatio: Number(moneyFlow?.control_ratio || 0),
            trend: moneyFlow?.trend || '待分析',
            strength: moneyFlow?.strength || '待确认',
            signals: full?.money_flow?.signal?.signals?.length
              ? full.money_flow.signal.signals
              : ['暂无资金流向信号'],
          },
          fundamentalAnalysis: {
            pe: peValue,
            pb: pbValue,
            roe: hasValue(fundamental?.roe) ? Number(fundamental.roe) : null,
            revenueGrowth: hasValue(fundamental?.revenue_growth) ? Number(fundamental.revenue_growth) : null,
            netProfitGrowth: hasValue(fundamental?.net_profit_growth) ? Number(fundamental.net_profit_growth) : null,
            grossMargin: hasValue(fundamental?.gross_margin) ? Number(fundamental.gross_margin) : null,
            debtRatio: hasValue(fundamental?.debt_ratio) ? Number(fundamental.debt_ratio) : null,
            reportDate: fundamental?.report_date || null,
            source: fundamental?.source || null,
            isAvailable: Boolean(fundamental?.is_available),
            strategyQualityScore: hasStrategyScore ? clampScore(strategyBreakdown.quality) : null,
            strategyRiskScore: hasStrategyScore ? clampScore(strategyBreakdown.risk_adjusted) : null,
            signals: fundamentalSignals,
          },
          riskWarnings,
          operationPlan,
          backtestPerformance: {
            available: evidenceAvailable,
            strategyCode,
            evidenceSource,
            evidenceScope,
            latestHasClosedTrades,
            winRate: asPercentValue(displayMetrics.win_rate),
            annualReturn: asPercentValue(displayMetrics.annual_return),
            maxDrawdown: asPercentValue(displayMetrics.max_drawdown),
            sharpe: asNumberOrNull(displayMetrics.sharpe, 2),
            profitLossRatio: asNumberOrNull(displayMetrics.profit_loss_ratio, 2),
            sampleRuns: Number(evidenceOverall.sample_runs || 0),
            closedRoundtrips: Number(displaySampleSummary.closed_roundtrips || displayDiagnostics.closed_roundtrips || evidenceOverall.closed_roundtrips || 0),
            validHistorySymbols: Number(displaySampleSummary.valid_history_symbols || latestDiagnostics.valid_history_symbols || 0),
            calendarDays: Number(displaySampleSummary.calendar_days || latestDiagnostics.calendar_days || 0),
            holdingDays: Number(displayRun?.config?.holding_days || latestRun?.config?.holding_days || 15),
            avgReturn: asNumberOrNull(displayDiagnostics.avg_return_pct, 1),
            credibilityScore: credibilitySummary.score ?? latestCredibility.score,
            credibilityGrade: credibilitySummary.grade ?? latestCredibility.grade,
            liveReady: Boolean(credibilitySummary.live_ready ?? latestCredibility.live_ready),
            runId: displayRun?.run_id || verificationTarget?.run_id || null,
            latestRunId: latestRun?.run_id || null,
            evidenceHash: displayRun?.evidence_hash || null,
            verificationPath: verificationTarget?.path || `/backtest?strategy_code=${strategyCode}`,
            displayScope: evidenceScope,
            proxyOnly: proxyOnlyEvidence,
            summary: credibilitySummary.summary || latestCredibility.summary || (evidenceAvailable ? '已获取策略回测证据' : '暂无策略回测证据'),
            notes: strategyEvidence?.notes || [],
            byState: strategyEvidence?.by_state || [],
            recentRoundtrips: displayRun?.recent_roundtrips || latestRun?.recent_roundtrips || [],
            recentTrades: displayRun?.recent_trades || latestRun?.recent_trades || [],
            gateChecks: credibilitySummary.gate_checks || displayRun?.credibility?.gate_checks || [],
            executionAssumptions: strategyEvidence?.execution_assumptions || {},
            sampleSummary,
            config: displayRun?.config || latestRun?.config || {},
          },
          news: {
            totalScore: Number(news?.total_score || 50),
            sentiment: news?.sentiment || 'neutral',
            latestEvents: news?.latest_events || [],
          },
          strategyContext: symbolStrategy?.available ? symbolStrategy : null,
          isWatchlist: false,
        })
      } catch (e) {
        console.error('加载股票详情数据失败', e)
        setLoadError(e?.response?.data?.message || e?.message || '加载失败')
        setStockData(prev => ({
          ...prev,
          symbol,
          name: symbol || '加载失败',
          riskWarnings: [
            '实时行情加载失败，请稍后重试',
            '当前页面不会再使用贵州茅台等默认样例数据兜底',
          ],
        }))
      } finally {
        setLoading(false)
      }
    }
    loadDetail()
  }, [symbol])

  const roundtripColumns = [
    {
      title: '股票',
      key: 'stock',
      render: (_, row) => `${row.name || row.symbol || '-'} (${row.symbol || '-'})`,
    },
    {
      title: '买入/卖出',
      key: 'dates',
      render: (_, row) => `${row.entry_date || '-'} → ${row.exit_date || '-'}`,
    },
    {
      title: '收益',
      dataIndex: 'return_pct',
      key: 'return_pct',
      render: (value) => (
        <span className={Number(value || 0) >= 0 ? 'positive-text' : 'negative-text'}>
          {formatPct(value, 1)}
        </span>
      ),
    },
    {
      title: '持有',
      dataIndex: 'holding_days',
      key: 'holding_days',
      render: (value) => `${Number(value || 0).toFixed(0)}天`,
    },
  ]

  const tabItems = [
    {
      key: 'overview',
      label: <span><LineChartOutlined /> 综合分析</span>,
      children: (
        <div className="overview-content">
          <div className="analysis-grid">
            <Card title={stockData.scoreLabel} className="score-card">
              <ScoreRadar
                data={stockData.scores}
                metricMeta={stockData.scoreSource === 'strategy' ? STRATEGY_METRIC_META : undefined}
              />
            </Card>
            <Card title="策略结论" className="analysis-card decision-card">
              {stockData.strategyContext ? (
                <>
                  <div className="decision-score-line">
                    <span>{actionText[stockData.strategyContext.action] || '策略观察'}</span>
                    <strong>{Number(stockData.totalScore || 0).toFixed(2)}分</strong>
                  </div>
                  <Row gutter={[12, 12]} className="decision-metrics">
                    <Col span={8}>
                      <Statistic title="上涨概率" value={Number(stockData.strategyContext.up_prob || 0) * 100} precision={1} suffix="%" />
                    </Col>
                    <Col span={8}>
                      <Statistic title="回撤概率" value={Number(stockData.strategyContext.dd_prob || 0) * 100} precision={1} suffix="%" />
                    </Col>
                    <Col span={8}>
                      <Statistic title="预期收益" value={Number(stockData.strategyContext.expected_return_pct || 0)} precision={2} suffix="%" />
                    </Col>
                  </Row>
                  <div className="decision-list">
                    {(stockData.strategyContext.reasons || []).slice(0, 4).map((item) => (
                      <div key={item}>✓ {item}</div>
                    ))}
                  </div>
                </>
              ) : (
                <Alert
                  type="info"
                  showIcon
                  message="该股当前不在智能选股输出池中"
                  description="因此本页展示的是个股行情分析分，不与智能选股排序分混用。"
                />
              )}
            </Card>
          </div>

          <Card className="operation-plan-card">
            <div className="operation-plan-head">
              <div>
                <span className="section-kicker">操作纪律</span>
                <strong>先定纪律，再谈交易</strong>
              </div>
              <Space wrap>
                <Tag color={stockData.operationPlan.statusColor}>{stockData.operationPlan.statusLabel}</Tag>
                <Tag color={Number(stockData.strategyContext?.dd_prob || 0) >= 0.35 ? 'red' : 'gold'}>
                  回撤概率 {stockData.strategyContext ? formatPct(stockData.strategyContext.dd_prob, 100) : '待策略确认'}
                </Tag>
              </Space>
            </div>
            <div className="operation-hero">
              <div>
                <span>{stockData.operationPlan.sourceLabel}</span>
                <strong>{stockData.operationPlan.headline}</strong>
              </div>
              <div className="operation-hero-metrics">
                {hasValue(stockData.operationPlan.expectedEdgePct) && (
                  <span>赔率边际 {Number(stockData.operationPlan.expectedEdgePct || 0).toFixed(2)}%</span>
                )}
                {hasValue(stockData.operationPlan.profitFactorProxy) && (
                  <span>盈亏比代理 {Number(stockData.operationPlan.profitFactorProxy || 0).toFixed(2)}</span>
                )}
                {stockData.operationPlan.confidenceLevel && <span>置信度 {stockData.operationPlan.confidenceLevel}</span>}
              </div>
            </div>
            <div className="operation-grid">
              <div className="operation-cell primary">
                <span>当前动作</span>
                <strong>{stockData.operationPlan.statusLabel}</strong>
                <p>{stockData.operationPlan.headline}</p>
              </div>
              <div className="operation-cell">
                <span>建仓纪律</span>
                <strong>{stockData.operationPlan.positionPct ? `首仓 ≤ ${Number(stockData.operationPlan.positionPct).toFixed(1)}%` : '不输出建仓动作'}</strong>
                <p>{stockData.operationPlan.entryText}</p>
                {stockData.operationPlan.horizonDays && <em>计划周期：{stockData.operationPlan.horizonDays} 天</em>}
              </div>
              <div className="operation-cell">
                <span>加仓纪律</span>
                <strong>默认保守</strong>
                <p>{stockData.operationPlan.addPositionRule}</p>
              </div>
              <div className="operation-cell sell-rules">
                <span>卖出纪律</span>
                <strong>
                  {hasValue(stockData.operationPlan.stopLoss) || hasValue(stockData.operationPlan.takeProfit)
                    ? `止损 ${formatPrice(stockData.operationPlan.stopLoss)} / 止盈 ${formatPrice(stockData.operationPlan.takeProfit)}`
                    : '无策略止盈/止损线'}
                </strong>
                {(stockData.operationPlan.sellRules || []).map((rule) => (
                  <p key={rule}>{rule}</p>
                ))}
              </div>
            </div>
            <div className="operation-risk-grid">
              {(stockData.operationPlan.invalidConditions?.length > 0
                ? stockData.operationPlan.invalidConditions
                : stockData.operationPlan.warnings
              ).slice(0, 4).map((warning, i) => (
                <div className="operation-risk-chip" key={`${warning}-${i}`}>
                  <span>{i + 1}</span>
                  <p>{warning}</p>
                </div>
              ))}
            </div>
            <div className="operation-evidence-note">
              <SafetyOutlined />
              <span>
                证据来源：{stockData.operationPlan.strategyCode || '无策略代码'} / {stockData.operationPlan.evidenceLabel}
                {stockData.operationPlan.proxyOnly ? '。当前含代理模型估计，不能视为确定胜率。' : '。价格计划是条件化纪律，不是收益承诺。'}
              </span>
            </div>
          </Card>

          {/* 技术面分析 */}
          <Card title="📈 技术面分析" className="analysis-card">
            <div className="analysis-header">
              <Tag color="blue">趋势: {stockData.technicalAnalysis.trend}</Tag>
              <Progress
                percent={stockData.scores.technical}
                strokeColor="#1890ff"
                style={{ width: 200 }}
              />
            </div>
            <Timeline style={{ marginTop: 16 }}>
              {stockData.technicalAnalysis.signals.map((signal, i) => (
                <Timeline.Item
                  key={i}
                  color={signal.startsWith('✓') ? 'green' : 'orange'}
                >
                  {signal}
                </Timeline.Item>
              ))}
            </Timeline>
          </Card>

          {/* 资金面分析 */}
          <Card title="💰 资金流向分析" className="analysis-card">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="主力净流入"
                  value={stockData.moneyFlowAnalysis.mainNetInflow}
                  suffix="亿"
                  valueStyle={{ color: '#cf1322' }}
                  prefix={<RiseOutlined />}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="主力控盘度"
                  value={stockData.moneyFlowAnalysis.controlRatio}
                  suffix="%"
                  valueStyle={{ color: '#1890ff' }}
                />
              </Col>
              <Col span={8}>
                <Tag color="red" style={{ fontSize: 16, padding: '8px 16px' }}>
                  {stockData.moneyFlowAnalysis.trend} ({stockData.moneyFlowAnalysis.strength})
                </Tag>
              </Col>
            </Row>
            <Timeline style={{ marginTop: 16 }}>
              {stockData.moneyFlowAnalysis.signals.map((signal, i) => (
                <Timeline.Item key={i} color="green">
                  {signal}
                </Timeline.Item>
              ))}
            </Timeline>
          </Card>

          {/* 基本面分析 */}
          <Card title="💎 基本面分析" className="analysis-card">
            <div className="fundamental-source-line">
              <Tag color={stockData.fundamentalAnalysis.isAvailable ? 'green' : 'orange'}>
                {stockData.fundamentalAnalysis.isAvailable ? '财报摘要已接入' : '财报摘要暂缺'}
              </Tag>
              {stockData.fundamentalAnalysis.reportDate && <span>报告期：{stockData.fundamentalAnalysis.reportDate}</span>}
              {stockData.scoreSource === 'strategy' && <span>上方雷达图的“策略质量”不是 PE/PB/ROE 财报基本面。</span>}
            </div>
            <Row gutter={[16, 16]}>
              <Col span={6}>
                <Statistic
                  title="PE"
                  value={hasValue(stockData.fundamentalAnalysis.pe) ? Number(stockData.fundamentalAnalysis.pe) : '-'}
                  precision={hasValue(stockData.fundamentalAnalysis.pe) ? 2 : 0}
                  suffix={hasValue(stockData.fundamentalAnalysis.pe) ? '倍' : ''}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="PB"
                  value={hasValue(stockData.fundamentalAnalysis.pb) ? Number(stockData.fundamentalAnalysis.pb) : '-'}
                  precision={hasValue(stockData.fundamentalAnalysis.pb) ? 2 : 0}
                  suffix={hasValue(stockData.fundamentalAnalysis.pb) ? '倍' : ''}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="ROE"
                  value={hasValue(stockData.fundamentalAnalysis.roe) ? Number(stockData.fundamentalAnalysis.roe) : '-'}
                  precision={hasValue(stockData.fundamentalAnalysis.roe) ? 2 : 0}
                  suffix={hasValue(stockData.fundamentalAnalysis.roe) ? '%' : ''}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="净利润增长"
                  value={hasValue(stockData.fundamentalAnalysis.netProfitGrowth) ? Number(stockData.fundamentalAnalysis.netProfitGrowth) : '-'}
                  precision={hasValue(stockData.fundamentalAnalysis.netProfitGrowth) ? 2 : 0}
                  suffix={hasValue(stockData.fundamentalAnalysis.netProfitGrowth) ? '%' : ''}
                  valueStyle={{ color: '#cf1322' }}
                  prefix={hasValue(stockData.fundamentalAnalysis.netProfitGrowth) ? <RiseOutlined /> : null}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="营收增长"
                  value={hasValue(stockData.fundamentalAnalysis.revenueGrowth) ? Number(stockData.fundamentalAnalysis.revenueGrowth) : '-'}
                  precision={hasValue(stockData.fundamentalAnalysis.revenueGrowth) ? 2 : 0}
                  suffix={hasValue(stockData.fundamentalAnalysis.revenueGrowth) ? '%' : ''}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="毛利率"
                  value={hasValue(stockData.fundamentalAnalysis.grossMargin) ? Number(stockData.fundamentalAnalysis.grossMargin) : '-'}
                  precision={hasValue(stockData.fundamentalAnalysis.grossMargin) ? 2 : 0}
                  suffix={hasValue(stockData.fundamentalAnalysis.grossMargin) ? '%' : ''}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="资产负债率"
                  value={hasValue(stockData.fundamentalAnalysis.debtRatio) ? Number(stockData.fundamentalAnalysis.debtRatio) : '-'}
                  precision={hasValue(stockData.fundamentalAnalysis.debtRatio) ? 2 : 0}
                  suffix={hasValue(stockData.fundamentalAnalysis.debtRatio) ? '%' : ''}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="策略质量分"
                  value={hasValue(stockData.fundamentalAnalysis.strategyQualityScore) ? stockData.fundamentalAnalysis.strategyQualityScore : '-'}
                  suffix={hasValue(stockData.fundamentalAnalysis.strategyQualityScore) ? '分' : ''}
                />
              </Col>
            </Row>
            <Timeline style={{ marginTop: 16 }}>
              {stockData.fundamentalAnalysis.signals.map((signal, i) => (
                <Timeline.Item
                  key={i}
                  color={signal.startsWith('✓') ? 'green' : 'orange'}
                >
                  {signal}
                </Timeline.Item>
              ))}
            </Timeline>
          </Card>

          <Card title="📰 关联资讯" className="analysis-card">
            <div className="stock-news-head">
              <Tag color={stockData.news.sentiment === 'positive' ? 'green' : stockData.news.sentiment === 'negative' ? 'red' : 'blue'}>
                {stockData.news.sentiment === 'positive' ? '偏正面' : stockData.news.sentiment === 'negative' ? '偏负面' : '中性'}
              </Tag>
              <span>资讯分 {Number(stockData.news.totalScore || 50).toFixed(1)}</span>
            </div>
            <div className="stock-news-list">
              {stockData.news.latestEvents.length > 0 ? (
                stockData.news.latestEvents.map((item, index) => (
                  <div className="stock-news-item" key={`${item.source}-${item.title}-${index}`}>
                    <div className="stock-news-title">
                      {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : item.title}
                    </div>
                    <div className="stock-news-meta">
                      <Tag color="cyan">{item.source || '资讯'}</Tag>
                      <Tag color={item.direction === 'positive' ? 'green' : item.direction === 'negative' ? 'red' : 'blue'}>
                        {item.direction === 'positive' ? '利多' : item.direction === 'negative' ? '利空' : '中性'}
                      </Tag>
                      <span>{item.publish_time || '-'}</span>
                    </div>
                  </div>
                ))
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无该股直接关联公告或明确行业资讯" />
              )}
            </div>
          </Card>

          {/* 风险提示 */}
          <Card title="⚠️ 风险提示" className="risk-card">
            <ul className="risk-list">
              {stockData.riskWarnings.map((warning, i) => (
                <li key={i}>{warning}</li>
              ))}
            </ul>
          </Card>

          {/* 策略证据 */}
          <Card title="📊 策略证据" className="backtest-card">
            <div className="backtest-summary-head">
              <div>
                <p>
                  {stockData.backtestPerformance.evidenceSource?.label
                    || (stockData.backtestPerformance.evidenceScope === 'overall'
                      ? `使用最近 ${stockData.backtestPerformance.sampleRuns || 0} 次历史回放的总体聚合证据`
                      : '使用最近一次有闭环交易的历史回放')}
                </p>
                {stockData.backtestPerformance.latestRunId && (
                  <span className="backtest-muted">
                    最新回测 {stockData.backtestPerformance.latestRunId}
                    {stockData.backtestPerformance.runId && stockData.backtestPerformance.runId !== stockData.backtestPerformance.latestRunId
                      ? `；当前展示可验证回测 ${stockData.backtestPerformance.runId}`
                      : ''}
                  </span>
                )}
                {!stockData.backtestPerformance.latestHasClosedTrades && stockData.backtestPerformance.available && stockData.backtestPerformance.displayScope !== 'display_run' && (
                  <span className="backtest-muted">最新一次回测没有闭环成交，当前展示总体聚合证据，避免把无成交结果误读为策略表现。</span>
                )}
                {stockData.backtestPerformance.proxyOnly && (
                  <span className="backtest-muted warning">当前智能选股上下文含代理模型估计，不能替代下方历史回放证据。</span>
                )}
              </div>
              <Space wrap>
                <Tag color={stockData.backtestPerformance.liveReady ? 'green' : 'orange'}>
                  {stockData.backtestPerformance.credibilityGrade ? `可信度 ${stockData.backtestPerformance.credibilityGrade}` : '证据待积累'}
                </Tag>
                <Button
                  size="small"
                  type="primary"
                  disabled={!stockData.backtestPerformance.verificationPath}
                  onClick={() => navigate(stockData.backtestPerformance.verificationPath || '/backtest')}
                >
                  查看完整证据
                </Button>
              </Space>
            </div>
            {!stockData.backtestPerformance.available && (
              <Alert
                showIcon
                type="warning"
                style={{ marginBottom: 16 }}
                message="暂无可验证历史回放证据"
                description="当前不能只看 0 值统计。请先在策略回测页运行回测，或放宽阈值、扩大样本池后重新验证。"
              />
            )}
            <Row gutter={[16, 16]}>
              <Col xs={12} md={6}>
                <Statistic
                  title="胜率"
                  value={stockData.backtestPerformance.winRate ?? '-'}
                  precision={stockData.backtestPerformance.winRate === null ? undefined : 1}
                  suffix="%"
                  valueStyle={{ color: '#52c41a' }}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="年化收益"
                  value={stockData.backtestPerformance.annualReturn ?? '-'}
                  precision={stockData.backtestPerformance.annualReturn === null ? undefined : 1}
                  suffix="%"
                  valueStyle={{ color: '#cf1322' }}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="最大回撤"
                  value={stockData.backtestPerformance.maxDrawdown ?? '-'}
                  precision={stockData.backtestPerformance.maxDrawdown === null ? undefined : 1}
                  suffix="%"
                  valueStyle={{ color: '#faad14' }}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="夏普比率"
                  value={stockData.backtestPerformance.sharpe ?? '-'}
                  precision={stockData.backtestPerformance.sharpe === null ? undefined : 2}
                  valueStyle={{ color: '#22d3ee' }}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="平均单笔收益"
                  value={stockData.backtestPerformance.avgReturn ?? '-'}
                  precision={stockData.backtestPerformance.avgReturn === null ? undefined : 1}
                  suffix="%"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="持仓周期"
                  value={stockData.backtestPerformance.holdingDays ?? '-'}
                  suffix="天"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="闭环交易"
                  value={stockData.backtestPerformance.closedRoundtrips}
                  suffix="笔"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="回放次数"
                  value={stockData.backtestPerformance.sampleRuns}
                  suffix="次"
                />
              </Col>
            </Row>
            <div className="evidence-proof-grid">
              <div className="evidence-proof-item">
                <span>证据类型</span>
                <strong>{stockData.backtestPerformance.displayScope === 'overall' ? '总体聚合样本' : '单次历史回放'}</strong>
              </div>
              <div className="evidence-proof-item">
                <span>可验证ID</span>
                <strong>{stockData.backtestPerformance.runId || '需重新回测'}</strong>
              </div>
              <div className="evidence-proof-item">
                <span>样本标的</span>
                <strong>{stockData.backtestPerformance.validHistorySymbols || 0} / {stockData.backtestPerformance.sampleSummary?.universe_size || stockData.backtestPerformance.config?.universe_size || 0}</strong>
              </div>
              <div className="evidence-proof-item">
                <span>回测区间</span>
                <strong>{stockData.backtestPerformance.config?.test_start || '-'} → {stockData.backtestPerformance.config?.test_end || '-'}</strong>
              </div>
              <div className="evidence-proof-item">
                <span>交易成本</span>
                <strong>佣金 {stockData.backtestPerformance.config?.commission ?? '-'} / 滑点 {stockData.backtestPerformance.config?.slippage ?? '-'}</strong>
              </div>
              <div className="evidence-proof-item">
                <span>证据指纹</span>
                <strong>{stockData.backtestPerformance.evidenceHash || '聚合证据'}</strong>
              </div>
            </div>
            {stockData.backtestPerformance.summary && (
              <div className="backtest-summary-note">{stockData.backtestPerformance.summary}</div>
            )}
            {Object.keys(stockData.backtestPerformance.executionAssumptions || {}).length > 0 && (
              <div className="evidence-assumption-box">
                <strong>执行假设</strong>
                <div>
                  <span>{stockData.backtestPerformance.executionAssumptions.buy_execution}</span>
                  <span>{stockData.backtestPerformance.executionAssumptions.sell_execution}</span>
                  <span>{stockData.backtestPerformance.executionAssumptions.cost_model}</span>
                  <span>{stockData.backtestPerformance.executionAssumptions.money_flow_caveat}</span>
                </div>
              </div>
            )}
            {stockData.backtestPerformance.gateChecks?.length > 0 && (
              <div className="evidence-gate-grid">
                {stockData.backtestPerformance.gateChecks.slice(0, 6).map((item) => (
                  <div className="evidence-gate-item" key={item.key || item.label}>
                    <span>{item.label}</span>
                    <Tag color={item.passed ? 'green' : 'red'}>{item.passed ? '通过' : '未通过'}</Tag>
                  </div>
                ))}
              </div>
            )}
            {stockData.backtestPerformance.byState?.length > 0 && (
              <div className="backtest-state-grid">
                {stockData.backtestPerformance.byState.map((item) => (
                  <div className="backtest-state-item" key={item.state_tag}>
                    <span>{STATE_LABEL[item.state_tag] || item.state_tag}</span>
                    <strong>{formatPct(item.win_rate, 100)}</strong>
                    <em>回撤 {formatPct(item.max_drawdown, 100)} / 样本 {item.sample_count || 0}</em>
                  </div>
                ))}
              </div>
            )}
            {stockData.backtestPerformance.recentRoundtrips?.length > 0 && (
              <div className="evidence-sample-table">
                <div className="evidence-sample-title">最近闭环交易样本</div>
                <Table
                  rowKey={(row) => `${row.symbol}-${row.entry_date}-${row.exit_date}-${row.return_pct}-${row.holding_days}`}
                  columns={roundtripColumns}
                  dataSource={stockData.backtestPerformance.recentRoundtrips.slice(-5).reverse()}
                  pagination={false}
                  size="small"
                />
              </div>
            )}
            {stockData.backtestPerformance.notes?.length > 0 && (
              <div className="evidence-notes">
                {stockData.backtestPerformance.notes.slice(0, 3).map((note) => (
                  <span key={note}>{note}</span>
                ))}
              </div>
            )}
          </Card>
        </div>
      )
    }
  ]

  return (
    <div className="stock-detail-container">
      {loadError && <Alert type="error" showIcon message={loadError} style={{ marginBottom: 16 }} />}
      {/* 页面头部 */}
      <div className="detail-header stock-hero">
        <div className="hero-left">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} className="back-btn">
            返回
          </Button>
          <div className="stock-title">
            <h1>{stockData.name}</h1>
            <span className="stock-code">{stockData.symbol}</span>
            <Button
              type="text"
              size="large"
              icon={stockData.isWatchlist ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
              onClick={toggleWatchlist}
            />
          </div>
          <div className="price-info-large">
            <div className="current-price">¥{stockData.price.toFixed(2)}</div>
            <div className={`price-change-large ${stockData.change >= 0 ? 'up' : 'down'}`}>
              {stockData.change >= 0 ? <RiseOutlined /> : <FallOutlined />}
              {stockData.change >= 0 ? '+' : ''}{Number(stockData.change || 0).toFixed(2)}%
              <span className="change-amount">
                {stockData.changeAmount >= 0 ? '+' : ''}{stockData.changeAmount.toFixed(2)}
              </span>
            </div>
          </div>
        </div>

        <div className="hero-score-card">
          <div className="score-label">{stockData.scoreLabel}</div>
          <Progress
            type="dashboard"
            percent={stockData.totalScore}
            width={132}
            strokeColor={stockData.scoreSource === 'strategy' ? '#22d3ee' : '#faad14'}
            trailColor="rgba(148, 163, 184, 0.16)"
            format={(percent) => <span className="score-number">{Number(percent || 0).toFixed(1)}</span>}
          />
          <div className="score-footnote">
            {stockData.scoreSource === 'strategy' ? '与智能选股同源' : '非智能选股排序分'}
          </div>
        </div>
      </div>

      {/* 基础数据 */}
      <Card className="basic-info-card quote-strip">
        <Row gutter={[12, 12]}>
          <Col xs={12} md={4}>
            <Statistic title="开盘" value={stockData.open.toFixed(2)} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="最高" value={stockData.high.toFixed(2)} valueStyle={{ color: '#cf1322' }} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="最低" value={stockData.low.toFixed(2)} valueStyle={{ color: '#52c41a' }} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="成交量" value={stockData.volume} suffix="万手" />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="成交额" value={stockData.turnover} suffix="亿" />
          </Col>
          <Col xs={24} md={4}>
            <Button type="primary" block size="large">
              查看K线图
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 详细分析标签页 */}
      <Spin spinning={loading}>
        <Tabs items={tabItems} size="large" />
      </Spin>

      {/* 免责声明 */}
      <div className="disclaimer-footer">
        💡 以上数据和分析仅供参考，不构成投资建议。投资有风险，决策需谨慎。
      </div>
    </div>
  )
}

export default StockDetail
