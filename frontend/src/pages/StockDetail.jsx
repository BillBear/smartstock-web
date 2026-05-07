import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Alert, Card, Row, Col, Statistic, Tabs, Button, Tag, Timeline, Progress, Spin, Empty, Table } from 'antd'
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
  backtestPerformance: {
    available: false,
    strategyCode: null,
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
    summary: '暂无策略回测证据',
    notes: [],
    byState: [],
    recentRoundtrips: [],
    recentTrades: [],
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
        const [full, symbolNews, symbolStrategy] = await Promise.all([
          analysisApi.full({
            symbol,
            days: 120,
            money_flow_days: 5,
            holding_period: 'medium',
            risk_level: 'medium',
            target_return: 15,
          }),
          coachApi.getSymbolNews(symbol, { limit: 8 }).catch(() => null),
          coachApi.getSymbolStrategy(symbol, { user_id: 'default', risk_level: 'medium' }).catch(() => null),
        ])
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
        const latestRun = strategyEvidence?.latest_run || {}
        const latestMetrics = latestRun?.metrics || {}
        const latestDiagnostics = latestRun?.diagnostics || {}
        const latestCredibility = latestRun?.credibility || {}
        const evidenceAvailable = Boolean(
          strategyEvidence
          && (
            Number(evidenceOverall.sample_runs || 0) > 0
            || Number(latestDiagnostics.closed_roundtrips || 0) > 0
            || Number(latestMetrics.max_drawdown || 0) > 0
          )
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
          riskWarnings: (symbolStrategy?.risks?.length ? symbolStrategy.risks : null)
            || (aiDecision?.risk_assessment?.warnings?.length
              ? aiDecision.risk_assessment.warnings
              : aiDecision?.risk_assessment?.factors)
            || [
                '资金流和技术信号均可能快速变化，不应单独作为买卖依据',
                '若实时数据源不可用，请以交易软件行情为准',
              ],
          backtestPerformance: {
            available: evidenceAvailable,
            strategyCode,
            winRate: Number(latestMetrics.win_rate ?? evidenceOverall.win_rate ?? 0),
            annualReturn: Number(latestMetrics.annual_return ?? evidenceOverall.annual_return ?? 0),
            maxDrawdown: Number(latestMetrics.max_drawdown ?? evidenceOverall.max_drawdown ?? 0),
            sharpe: Number(latestMetrics.sharpe ?? evidenceOverall.sharpe ?? 0),
            profitLossRatio: Number(latestMetrics.profit_loss_ratio ?? evidenceOverall.profit_loss_ratio ?? 0),
            sampleRuns: Number(evidenceOverall.sample_runs || 0),
            closedRoundtrips: Number(latestDiagnostics.closed_roundtrips || 0),
            validHistorySymbols: Number(latestDiagnostics.valid_history_symbols || 0),
            calendarDays: Number(latestDiagnostics.calendar_days || 0),
            holdingDays: Number(latestRun?.config?.holding_days || 15),
            avgReturn: Number(latestDiagnostics.avg_return_pct || 0),
            credibilityScore: latestCredibility.score,
            credibilityGrade: latestCredibility.grade,
            liveReady: Boolean(latestCredibility.live_ready),
            summary: latestCredibility.summary || (evidenceAvailable ? '已获取最近策略回测证据' : '暂无策略回测证据'),
            notes: strategyEvidence?.notes || [],
            byState: strategyEvidence?.by_state || [],
            recentRoundtrips: latestRun?.recent_roundtrips || [],
            recentTrades: latestRun?.recent_trades || [],
            config: latestRun?.config || {},
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

          <Card className="risk-strip-card">
            <div className="risk-strip-head">
              <div>
                <span className="section-kicker">优先风险</span>
                <strong>先看会亏多少，再看能赚多少</strong>
              </div>
              <Tag color={Number(stockData.strategyContext?.dd_prob || 0) >= 0.35 ? 'red' : 'gold'}>
                回撤概率 {stockData.strategyContext ? formatPct(stockData.strategyContext.dd_prob, 100) : '待策略确认'}
              </Tag>
            </div>
            <div className="risk-chip-grid">
              {stockData.riskWarnings.slice(0, 4).map((warning, i) => (
                <div className="risk-chip" key={`${warning}-${i}`}>
                  <span>{i + 1}</span>
                  <p>{warning}</p>
                </div>
              ))}
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

          {/* 回测表现 */}
          <Card title="📊 历史回测表现" className="backtest-card">
            <p>使用此评分模型，过去1年：</p>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="胜率"
                  value={stockData.backtestPerformance.winRate}
                  suffix="%"
                  valueStyle={{ color: '#52c41a' }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="平均收益"
                  value={stockData.backtestPerformance.avgReturn}
                  suffix="%"
                  valueStyle={{ color: '#cf1322' }}
                  prefix="+"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="持仓周期"
                  value={stockData.backtestPerformance.holdingDays}
                  suffix="天"
                />
              </Col>
            </Row>
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
