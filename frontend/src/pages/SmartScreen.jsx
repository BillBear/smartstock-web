import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd'
import { InfoCircleOutlined, ReloadOutlined, ThunderboltOutlined, TrophyOutlined } from '@ant-design/icons'
import { coachApi } from '../services/api'
import MarketFactorExplain from '../components/MarketFactorExplain'
import './SmartScreen.css'

const { Option } = Select

const ACTION_LABEL = {
  buy: { text: '可买入', color: 'red' },
  watch: { text: '观察', color: 'blue' },
  pass: { text: '跳过', color: 'default' },
}

const USER_ACTION_LABEL = {
  added_watchlist: { text: '已加观察', color: 'blue' },
  paper_buy: { text: '已模拟买入', color: 'red' },
  ignored: { text: '已忽略', color: 'default' },
  closed: { text: '已关闭', color: 'green' },
}

const STATE_META = {
  offensive: {
    text: '进攻',
    color: 'red',
    desc: '市场偏强，允许提高仓位，但仍需止损纪律。',
  },
  neutral: {
    text: '均衡',
    color: 'gold',
    desc: '市场震荡，建议精选个股、控制节奏。',
  },
  defensive: {
    text: '防守',
    color: 'green',
    desc: '市场承压，优先防回撤，降低仓位和交易频率。',
  },
}

const STRATEGY_NAME_MAP = {
  trend_breakout: '趋势突破',
  pullback_rebound: '回调修复',
}

const NEWS_SOURCE_META = {
  gov: { label: '国务院', color: 'gold' },
  pbc: { label: '人民银行', color: 'blue' },
  csrc: { label: '证监会', color: 'cyan' },
  ndrc: { label: '发改委', color: 'orange' },
  miit: { label: '工信部', color: 'geekblue' },
  fmprc: { label: '外交部', color: 'volcano' },
  sse: { label: '上交所', color: 'purple' },
  szse: { label: '深交所', color: 'magenta' },
  cninfo: { label: '巨潮公告', color: 'green' },
}

const EVENT_LEVEL_META = {
  macro: { label: '宏观', color: 'red' },
  industry: { label: '行业', color: 'gold' },
  stock: { label: '个股', color: 'blue' },
}

const SCORE_META = {
  trend: {
    label: '趋势强度',
    desc: '来自技术趋势信号，越高代表趋势延续概率越高。',
  },
  money_flow: {
    label: '资金流向',
    desc: '结合主力净流入/净流出强弱评估，越高越偏向资金净流入。',
  },
  turnover_liquidity: {
    label: '换手与流动性',
    desc: '结合换手率与成交活跃度，过低流动性不足，过高博弈风险上升。',
  },
  quality: {
    label: '信号质量',
    desc: '多指标共振质量，反映当前形态与历史样本一致性。',
  },
  risk_adjusted: {
    label: '风险调整',
    desc: '按回撤概率折算后的风险得分，越高代表风险可控性更好。',
  },
  news: {
    label: '资讯因子',
    desc: '基于官方政策、央行发布和巨潮公告聚合后的资讯贡献分，越高代表政策与公告环境更友好。',
  },
  total: {
    label: '综合得分',
    desc: '按风险等级权重融合后的总分，用于最终排序。',
  },
}

const SCORE_ORDER = ['trend', 'money_flow', 'turnover_liquidity', 'quality', 'risk_adjusted', 'news', 'total']

const DECISION_META = {
  A: { text: 'A 核心候选', color: 'red' },
  B: { text: 'B 小仓试错', color: 'orange' },
  C: { text: 'C 观察等待', color: 'blue' },
  D: { text: 'D 不建议', color: 'default' },
}

const PLAN_ACTION_META = {
  trade_plan: { label: '今日有交易计划', color: '#22d3ee' },
  light_trade: { label: '防守小仓试错', color: '#fbbf24' },
  paper_only: { label: '只建议模拟验证', color: '#fb7185' },
  watch: { label: '今日只观察', color: '#60a5fa' },
  no_trade: { label: '今日不交易', color: '#94a3b8' },
}

const MONEY_FLOW_QUALITY_META = {
  real: { text: '真实资金流', color: 'green' },
  proxy: { text: '代理资金', color: 'orange' },
  unavailable: { text: '资金缺失', color: 'default' },
}

const SmartScreen = () => {
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [actionLoading, setActionLoading] = useState('')
  const [error, setError] = useState('')
  const [riskLevel, setRiskLevel] = useState('medium')
  const [summary, setSummary] = useState(null)
  const [themeData, setThemeData] = useState(null)
  const [moneyCoverage, setMoneyCoverage] = useState(null)
  const [result, setResult] = useState(null)
  const [loadedAt, setLoadedAt] = useState('')
  const [selectedTheme, setSelectedTheme] = useState(null)
  const [themeDrawerOpen, setThemeDrawerOpen] = useState(false)
  const [themeStocks, setThemeStocks] = useState([])
  const [themeStockMeta, setThemeStockMeta] = useState(null)
  const [themeStocksLoading, setThemeStocksLoading] = useState(false)
  const [themeStockCache, setThemeStockCache] = useState({})
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailData, setDetailData] = useState(null)
  const [diagnosticOpen, setDiagnosticOpen] = useState(false)
  const latestLoadReqRef = useRef(0)
  const mountedRef = useRef(false)

  const loadDashboard = async (targetRisk = null) => {
    const reqId = latestLoadReqRef.current + 1
    latestLoadReqRef.current = reqId
    if (mountedRef.current) {
      setLoading(true)
      setError('')
    }
    try {
      const params = {
        user_id: 'default',
        max_count: 30,
      }
      if (targetRisk) {
        params.risk_level = targetRisk
      }
      const [summaryData, themes, coverage, cachedPicks] = await Promise.all([
        coachApi.getSmartScreenSummary({ user_id: 'default', risk_level: targetRisk || riskLevel }),
        coachApi.getTodayThemes({ limit: 10 }),
        coachApi.getMoneyFlowCoverage?.() || Promise.resolve(null),
        coachApi.getTodayPicks({ ...params, cached_only: true }),
      ])
      if (!mountedRef.current || reqId !== latestLoadReqRef.current) return
      setSummary(summaryData)
      setThemeData(themes)
      setMoneyCoverage(coverage)
      setResult(cachedPicks?.picks?.length ? cachedPicks : null)
      if (!cachedPicks?.picks?.length && !summaryData?.is_refreshing) {
        coachApi.refreshTodayPicks({ user_id: 'default', max_count: 30, risk_level: targetRisk || riskLevel }).catch(() => {})
      }
      const nextRisk = cachedPicks?.risk_profile?.risk_level || summaryData?.risk_profile?.risk_level
      if (nextRisk && ['low', 'medium', 'high'].includes(nextRisk)) {
        setRiskLevel(nextRisk)
      }
      setLoadedAt(new Date().toLocaleString('zh-CN'))
    } catch (err) {
      if (!mountedRef.current || reqId !== latestLoadReqRef.current) return
      console.error('加载智能选股失败', err)
      setError(err?.response?.data?.message || err?.message || '加载失败')
    } finally {
      if (!mountedRef.current || reqId !== latestLoadReqRef.current) return
      setLoading(false)
    }
  }

  const triggerRefresh = async () => {
    setRefreshing(true)
    setError('')
    try {
      await coachApi.refreshTodayPicks({ user_id: 'default', max_count: 30, risk_level: riskLevel })
      message.success('已开始后台刷新，完成后会更新候选池')
      setTimeout(() => loadDashboard(riskLevel), 3000)
      setTimeout(() => loadDashboard(riskLevel), 9000)
    } catch (err) {
      console.error('刷新智能选股失败', err)
      setError(err?.response?.data?.message || err?.message || '刷新失败')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    mountedRef.current = true
    loadDashboard()
    return () => {
      mountedRef.current = false
    }
  }, [])

  const pickList = useMemo(() => result?.picks || summary?.top_picks || [], [result, summary])
  const universeMeta = result?.universe_meta || summary?.data_diagnostics?.universe_meta || {}
  const pipelineCounts = universeMeta.pipeline_counts || {}
  const themeWatchlist = result?.theme_watchlist || []
  const excludedExamples = result?.excluded_examples || []
  const isFallbackUniverse = String(universeMeta.source || '').startsWith('fallback_')
  const marketNews = result?.market_state?.news_context || summary?.market_state?.news_context || {}
  const tradePlan = summary?.trade_plan || result?.trade_plan || {}
  const planMeta = PLAN_ACTION_META[tradePlan.primary_action] || PLAN_ACTION_META.watch
  const corePicks = useMemo(
    () => pickList.filter((item) => ['A', 'B'].includes(item?.decision?.grade)).slice(0, 3),
    [pickList]
  )

  const stateTag = summary?.market_state?.state_tag || result?.market_state?.state_tag
  const stateMeta = STATE_META[stateTag] || STATE_META.neutral

  const handleRiskChange = async (value) => {
    setRiskLevel(value)
    await loadDashboard(value)
  }

  const reportAction = async (pick, actionType) => {
    const currentAction = pick?.user_action?.action_type
    if (currentAction === actionType) {
      message.info('该动作已执行，无需重复提交')
      return
    }

    setActionLoading(`${pick.pick_id}-${actionType}`)
    const payload = {
      action_type: actionType,
      action_price: pick?.entry_range?.[1] || pick?.entry_range?.[0] || null,
      action_qty: actionType === 'paper_buy' ? 100 : null,
      note: 'smart-screen action',
    }

    try {
      await coachApi.recordPickAction(pick.pick_id, payload, 'default')
      message.success('动作已记录并同步')
      await loadDashboard(riskLevel)
      if (detailData?.pick_id === pick.pick_id) {
        await openDetail(pick.pick_id, pick)
      }
    } catch (err) {
      console.error('记录动作失败', err)
      message.error(err?.response?.data?.message || err?.message || '动作记录失败')
    } finally {
      setActionLoading('')
    }
  }

  const openDetail = async (pickId, seedData = null) => {
    setDetailOpen(true)
    setDetailLoading(!seedData)
    setDetailData(seedData ? { trade_date: result?.trade_date, market_state: result?.market_state, ...seedData } : null)
    try {
      const detail = await coachApi.getPickDetail(pickId, {
        user_id: 'default',
        risk_level: riskLevel,
      })
      setDetailData(detail)
    } catch (err) {
      console.error('获取推荐详情失败', err)
      message.error(err?.response?.data?.message || err?.message || '详情加载失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const openThemeDrawer = async (theme) => {
    if (!theme?.theme_id) return
    setSelectedTheme(theme)
    setThemeDrawerOpen(true)
    const cached = themeStockCache[theme.theme_id]
    if (cached) {
      setThemeStocks(cached.stocks || [])
      setThemeStockMeta(cached)
      setThemeStocksLoading(false)
      return
    }
    const leaderRows = (theme.top_symbols || []).map((item) => ({
      symbol: item.symbol || '',
      name: item.name,
      pct_change: item.pct_change,
      amount_yi: item.amount_yi,
      money_flow_quality: 'unavailable',
      selected: false,
      exclusion_reason: '先展示领涨代表股，成分股列表加载中。',
    }))
    setThemeStocks(leaderRows)
    setThemeStockMeta({
      status: leaderRows.length ? 'loading_partial' : 'loading',
      theme,
      message: leaderRows.length ? '先展示领涨代表股，正在加载成分股。' : '正在加载成分股。',
    })
    setThemeStocksLoading(leaderRows.length === 0)
    try {
      const data = await coachApi.getThemeStocks(theme.theme_id, {
        user_id: 'default',
        limit: 80,
      })
      setSelectedTheme(data?.theme || theme)
      setThemeStocks(data?.stocks || [])
      setThemeStockMeta(data || null)
      setThemeStockCache((prev) => ({ ...prev, [theme.theme_id]: data || null }))
    } catch (err) {
      console.error('获取主题成分股失败', err)
      message.error(err?.response?.data?.message || err?.message || '主题成分股加载失败')
    } finally {
      setThemeStocksLoading(false)
    }
  }

  const columns = [
    {
      title: '排名',
      dataIndex: 'rank_no',
      key: 'rank_no',
      width: 72,
      render: (rank) => (
        <div className="rank-cell">
          {rank <= 3 ? <TrophyOutlined style={{ color: '#faad14', fontSize: 18 }} /> : <span>{rank}</span>}
        </div>
      ),
    },
    {
      title: '股票',
      key: 'stock',
      width: 220,
      render: (_, row) => (
        <div className="stock-cell">
          <div className="stock-name">{row.name}</div>
          <div className="stock-code">{row.symbol}</div>
        </div>
      ),
    },
    {
      title: '主题',
      key: 'theme',
      width: 160,
      render: (_, row) => {
        const tags = row?.theme_tags || row?.matched_theme_names || [row?.industry].filter(Boolean)
        return (
          <Space wrap size={[4, 4]}>
            {tags.slice(0, 2).map((tag) => (
              <Tag key={tag} color="cyan">{tag}</Tag>
            ))}
            {tags.length === 0 && <Tag>未匹配</Tag>}
          </Space>
        )
      },
    },
    {
      title: '决策',
      key: 'decision',
      width: 130,
      render: (_, row) => {
        const meta = DECISION_META[row?.decision?.grade] || DECISION_META.C
        return (
          <Tooltip title={row?.decision?.summary || ''}>
            <Tag color={meta.color}>{meta.text}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '资金状态',
      key: 'money_flow_quality',
      width: 130,
      render: (_, row) => {
        const meta = MONEY_FLOW_QUALITY_META[row?.money_flow_quality] || MONEY_FLOW_QUALITY_META.proxy
        return (
          <Tooltip title={`资金置信度 ${(Number(row?.money_flow_confidence || 0) * 100).toFixed(0)}%`}>
            <Tag color={meta.color}>{meta.text}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '上涨概率',
      dataIndex: 'up_prob',
      key: 'up_prob',
      width: 130,
      render: (v, row) => (
        <Tooltip title={row?.probability_model?.message || '当前为规则代理概率，尚未经过历史模型校准'}>
          <span style={{ color: '#ff7875' }}>{(Number(v || 0) * 100).toFixed(1)}%</span>
        </Tooltip>
      ),
    },
    {
      title: '回撤概率',
      dataIndex: 'dd_prob',
      key: 'dd_prob',
      width: 130,
      render: (v) => <span style={{ color: '#95de64' }}>{(Number(v || 0) * 100).toFixed(1)}%</span>,
    },
    {
      title: '综合分',
      key: 'score',
      width: 140,
      render: (_, row) => (
        <Progress
          percent={Number(row?.score_breakdown?.total || 0)}
          size="small"
          strokeColor="#00C076"
        />
      ),
    },
    {
      title: '操作',
      key: 'operation',
      width: 240,
      fixed: 'right',
      render: (_, row) => (
        <Space wrap>
          <Button size="small" onClick={() => openDetail(row.pick_id, row)}>
            详情
          </Button>
          <Button
            size="small"
            type="primary"
            ghost
            loading={actionLoading === `${row.pick_id}-added_watchlist`}
            onClick={() => reportAction(row, 'added_watchlist')}
          >
            加观察
          </Button>
          <Button
            size="small"
            type="primary"
            loading={actionLoading === `${row.pick_id}-paper_buy`}
            disabled={row?.decision?.mode === 'watch_only'}
            onClick={() => reportAction(row, 'paper_buy')}
          >
            模拟买入
          </Button>
          <Button
            size="small"
            danger
            loading={actionLoading === `${row.pick_id}-ignored`}
            onClick={() => reportAction(row, 'ignored')}
          >
            忽略
          </Button>
        </Space>
      ),
    },
  ]

  const themeStockColumns = [
    {
      title: '股票',
      key: 'stock',
      width: 160,
      render: (_, row) => (
        <div className="stock-cell">
          <div className="stock-name">{row.name}</div>
          <div className="stock-code">{row.symbol || '-'}</div>
        </div>
      ),
    },
    {
      title: '涨跌幅',
      dataIndex: 'pct_change',
      key: 'pct_change',
      width: 90,
      render: (v) => <span style={{ color: Number(v || 0) >= 0 ? '#ff7875' : '#95de64' }}>{Number(v || 0).toFixed(2)}%</span>,
    },
    {
      title: '成交额',
      dataIndex: 'amount_yi',
      key: 'amount_yi',
      width: 90,
      render: (v) => `${Number(v || 0).toFixed(2)}亿`,
    },
    {
      title: '资金',
      key: 'money_flow_quality',
      width: 110,
      render: (_, row) => {
        const meta = MONEY_FLOW_QUALITY_META[row?.money_flow_quality] || MONEY_FLOW_QUALITY_META.unavailable
        return <Tag color={meta.color}>{meta.text}</Tag>
      },
    },
    {
      title: '策略状态',
      key: 'selected',
      width: 130,
      render: (_, row) => (
        row.selected ? <Tag color="red">已入选 {row.decision_grade || ''}</Tag> : <Tooltip title={row.exclusion_reason}><Tag>未入选</Tag></Tooltip>
      ),
    },
  ]

  return (
    <div className="smart-screen-container">
      <div className="screen-header">
        <h1 className="page-title">
          <ThunderboltOutlined /> 智能选股
        </h1>
        <p className="page-subtitle">今日交易计划 + 策略证据 + 模拟验证闭环</p>
      </div>

      {error && <Alert style={{ marginBottom: 16 }} type="error" showIcon message={error} />}
      {result?.strategy_health && (
        <Alert
          style={{ marginBottom: 16 }}
          type={result.strategy_health.live_ready ? 'success' : 'warning'}
          showIcon
          message={result.strategy_health.live_ready ? '策略已通过实盘准入检查' : '策略仍处于模拟验证阶段'}
          description={[
            result.strategy_health.summary,
            result.strategy_health.credibility_score !== null && result.strategy_health.credibility_score !== undefined
              ? `可信度 ${Number(result.strategy_health.credibility_score).toFixed(2)} / ${result.strategy_health.credibility_grade || '-'}`
              : null,
            result.strategy_health.metrics?.win_rate !== undefined
              ? `最近回测胜率 ${(Number(result.strategy_health.metrics.win_rate || 0) * 100).toFixed(1)}%，最大回撤 ${(Number(result.strategy_health.metrics.max_drawdown || 0) * 100).toFixed(1)}%，闭环交易 ${result.strategy_health.metrics.closed_roundtrips || 0} 笔`
              : null,
          ].filter(Boolean).join('；')}
        />
      )}

      <Card className="trade-plan-hero" variant="borderless" loading={loading && !result}>
        <div className="plan-hero-main">
          <div>
            <div className="plan-kicker">今日行动</div>
            <h2 style={{ color: planMeta.color }}>{tradePlan.headline || '等待生成交易计划'}</h2>
            <p>{tradePlan.summary || '系统会先判断市场环境和策略证据，再决定是否输出可执行候选。'}</p>
          </div>
          <div className="plan-badge" style={{ borderColor: planMeta.color, color: planMeta.color }}>
            {planMeta.label}
          </div>
        </div>
        <Row gutter={[12, 12]} className="plan-metrics">
          <Col xs={12} md={6}>
            <Statistic title="核心候选" value={tradePlan.core_count || 0} suffix="只" />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="试错候选" value={tradePlan.trial_count || 0} suffix="只" />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="建议实盘仓位" value={tradePlan.suggested_total_exposure_pct || 0} suffix="%" precision={1} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="概率口径" value={tradePlan?.probability_model?.label || '规则代理概率'} />
          </Col>
        </Row>
        <Alert
          className="probability-warning"
          type={tradePlan?.probability_model?.calibrated ? 'success' : 'warning'}
          showIcon
          message={tradePlan?.probability_model?.calibrated ? '概率已完成历史样本校准' : '当前上涨/回撤概率仍是规则代理概率'}
          description={tradePlan?.probability_model?.next_phase || '阶段3会训练真实历史样本概率模型，校准高概率组命中率。'}
        />
      </Card>

      {corePicks.length > 0 && (
        <Row gutter={[16, 16]} className="core-plan-row">
          {corePicks.map((pick) => {
            const meta = DECISION_META[pick?.decision?.grade] || DECISION_META.C
            return (
              <Col xs={24} lg={8} key={pick.pick_id}>
                <Card className="core-pick-card" variant="borderless">
                  <div className="core-pick-head">
                    <div>
                      <strong>{pick.name}</strong>
                      <span>{pick.symbol}</span>
                    </div>
                    <Tag color={meta.color}>{meta.text}</Tag>
                  </div>
                  <div className="core-pick-score">{Number(pick?.score_breakdown?.total || 0).toFixed(2)}</div>
                  <div className="core-pick-grid">
                    <span>入场 {pick.entry_range?.join(' - ') || '-'}</span>
                    <span>止损 {pick.stop_loss || '-'}</span>
                    <span>止盈 {pick.take_profit || '-'}</span>
                    <span>仓位 {Number(pick.position_pct || 0).toFixed(1)}%</span>
                  </div>
                  <p>{pick?.decision?.summary}</p>
                  <Space wrap>
                    <Button size="small" onClick={() => openDetail(pick.pick_id, pick)}>查看计划</Button>
                    <Button
                      size="small"
                      type="primary"
                      disabled={pick?.decision?.mode === 'watch_only'}
                      loading={actionLoading === `${pick.pick_id}-paper_buy`}
                      onClick={() => reportAction(pick, 'paper_buy')}
                    >
                      模拟买入
                    </Button>
                  </Space>
                </Card>
              </Col>
            )
          })}
        </Row>
      )}

      <Row gutter={16} className="stats-row">
        <Col xs={24} sm={6}>
          <Card className="stat-card">
            <Statistic title="交易日" value={summary?.trade_date || result?.trade_date || '-'} />
          </Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card className="stat-card">
            <Statistic title="可投数量" value={pickList.length} suffix="只" />
          </Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card className="stat-card">
            <Statistic
              title={(
                <span>
                  市场状态
                  <Tooltip title={stateMeta.desc}>
                    <InfoCircleOutlined style={{ marginLeft: 6 }} />
                  </Tooltip>
                </span>
              )}
              value={stateMeta.text}
              valueStyle={{ color: '#00C076' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card className="stat-card">
            <Space>
              <Select value={riskLevel} onChange={handleRiskChange} style={{ width: 140 }}>
                <Option value="low">低风险</Option>
                <Option value="medium">中风险</Option>
                <Option value="high">高风险</Option>
              </Select>
              <Button icon={<ReloadOutlined />} loading={refreshing || loading} onClick={triggerRefresh}>
                后台刷新
              </Button>
              <Button size="small" onClick={() => setDiagnosticOpen(true)}>
                数据诊断
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} className="market-layers-row">
        <Col xs={24} xl={15}>
          <Card className="theme-rank-card" variant="borderless">
            <div className="section-title-row">
              <div>
                <h3>市场主线</h3>
                <p>来自概念/行业板块涨跌与资金流。点击主题可穿透查看成分股。</p>
              </div>
              <Tag color={themeData?.data_quality?.is_reliable ? 'green' : 'orange'}>
                {themeData?.data_quality?.is_reliable ? '动态识别' : '数据不足'}
              </Tag>
            </div>
            {themeData?.status === 'insufficient_data' && (
              <Alert
                style={{ marginBottom: 14 }}
                type="warning"
                showIcon
                message="热点数据不足，暂不展示市场主线"
                description={themeData?.message || '真实板块/概念样本不足，避免展示误导性热点。'}
              />
            )}
            {(themeData?.theme_rank || []).length > 0 ? (
              <div className="theme-rank-list">
                {(themeData?.theme_rank || []).slice(0, 6).map((item, index) => (
                  <button
                    type="button"
                    className="theme-rank-item theme-rank-button"
                    key={item.theme_id || item.theme_name}
                    onClick={() => openThemeDrawer(item)}
                  >
                    <div className="theme-rank-index">{index + 1}</div>
                    <div className="theme-rank-body">
                      <div className="theme-rank-name">
                        <strong>{item.theme_name}</strong>
                        <span>{item.category === 'industry' ? '行业' : '概念'} · 涨幅 {Number(item.pct_change || 0).toFixed(2)}%</span>
                      </div>
                      <div className="theme-rank-bars">
                        <Progress percent={Number(item.strength_score || 0)} showInfo={false} strokeColor="#22d3ee" />
                        <Progress percent={Number(item.money_flow_score || 0)} showInfo={false} strokeColor="#fbbf24" />
                      </div>
                      <div className="theme-rank-meta">
                        <span>上涨广度 {(Number(item.breadth || 0) * 100).toFixed(0)}%</span>
                        <span>资金 {item.money_net_inflow_yi === null || item.money_net_inflow_yi === undefined ? '-' : `${Number(item.money_net_inflow_yi).toFixed(2)}亿`}</span>
                        <span>退潮风险 {Number(item.retreat_risk || 0).toFixed(0)}</span>
                      </div>
                      <Space wrap size={[4, 4]}>
                        {(item.top_symbols || []).slice(0, 4).map((stock) => (
                          <Tag key={stock.symbol || stock.name} color="cyan">
                            {stock.name} {Number(stock.pct_change || 0).toFixed(1)}%
                          </Tag>
                        ))}
                      </Space>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可靠市场主线数据" />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={9}>
          <Card className="money-quality-card" variant="borderless">
            <div className="section-title-row compact">
              <div>
                <h3>资金状态</h3>
                <p>资金流是核心因子，但必须先看数据质量。</p>
              </div>
              <Tag color={moneyCoverage?.status === 'available' ? 'green' : 'orange'}>
                {moneyCoverage?.status === 'available' ? '可用' : '降级'}
              </Tag>
            </div>
            <div className="money-quality-grid">
              <div>
                <span>真实资金流</span>
                <strong>{summary?.data_quality?.money_flow_quality?.real ?? result?.data_quality?.money_flow_quality?.real ?? 0}</strong>
              </div>
              <div>
                <span>代理资金</span>
                <strong>{summary?.data_quality?.money_flow_quality?.proxy ?? result?.data_quality?.money_flow_quality?.proxy ?? 0}</strong>
              </div>
              <div>
                <span>暂不可用</span>
                <strong>{summary?.data_quality?.money_flow_quality?.unavailable ?? result?.data_quality?.money_flow_quality?.unavailable ?? 0}</strong>
              </div>
            </div>
            <Alert
              style={{ marginTop: 14 }}
              type={moneyCoverage?.status === 'available' ? 'info' : 'warning'}
              showIcon
              message={moneyCoverage?.coverage_label || '真实资金流优先，代理因子仅作降级展示'}
              description="资金缺失时不显示 0 分，也不把缺失误判为主力流出。"
            />
          </Card>
        </Col>
      </Row>

      <Card className="ranking-card" variant="borderless">
        <div className="ranking-card-title">
          <h3>核心候选</h3>
          <span>只展示通过风险、趋势、流动性和资金质量闸门的股票。</span>
        </div>
        {result?.no_trade ? (
          <Alert
            type="warning"
            showIcon
            message={result?.no_trade_reason || '当前无可执行交易'}
          />
        ) : (
          <Table
            className="ranking-table"
            loading={loading}
            columns={columns}
            dataSource={pickList}
            rowKey="pick_id"
            scroll={{ x: 1180, y: 480 }}
            pagination={{ pageSize: 10, showSizeChanger: false }}
          />
        )}
      </Card>

      <MarketFactorExplain
        drivers={result?.market_state?.drivers}
        loadedAt={loadedAt}
        mode="smart-screen"
      />

      <Card className="info-card" variant="borderless">
        <h3>推荐解释</h3>
        <p style={{ color: 'rgba(255,255,255,0.8)' }}>
          {(result?.market_state?.summary || '暂无市场结论') + '。'}
        </p>
        <Space wrap>
          {(result?.market_state?.reasons || []).map((text) => (
            <Tag key={text} color="blue">
              {text}
            </Tag>
          ))}
        </Space>
      </Card>

      <Card className="info-card" variant="borderless">
        <h3>官方资讯事件</h3>
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={8}>
            <div className="news-panel-summary">
              <div className="news-panel-stat">
                <span>资讯温度</span>
                <strong>{Number(marketNews?.policy_score || 50).toFixed(1)}</strong>
              </div>
              <div className="news-panel-stat">
                <span>风险偏向</span>
                <strong>{marketNews?.risk_bias === 'positive' ? '偏正面' : marketNews?.risk_bias === 'negative' ? '偏负面' : '中性'}</strong>
              </div>
              <div className="news-panel-stat">
                <span>更新时间</span>
                <strong>{marketNews?.updated_at || '-'}</strong>
              </div>
            </div>
            <div className="news-panel-sources">
              {Object.entries(marketNews?.source_counts || {}).map(([source, count]) => {
                const meta = NEWS_SOURCE_META[source] || { label: source?.toUpperCase() || '资讯', color: 'default' }
                return (
                  <Tag key={source} color={meta.color}>
                    {meta.label} {count}
                  </Tag>
                )
              })}
            </div>
          </Col>
          <Col xs={24} xl={16}>
            <div className="news-panel-list">
              {(marketNews?.latest_events || []).slice(0, 8).map((item) => {
                const sourceMeta = NEWS_SOURCE_META[item.source] || { label: item.source?.toUpperCase() || '资讯', color: 'default' }
                const levelMeta = EVENT_LEVEL_META[item.event_level] || { label: item.event_level || '事件', color: 'default' }
                return (
                  <div className="news-panel-item" key={`${item.source}-${item.title}`}>
                    <div className="news-panel-item-tags">
                      <Tag color={sourceMeta.color}>{sourceMeta.label}</Tag>
                      <Tag color={levelMeta.color}>{levelMeta.label}</Tag>
                      <Tag color={item.direction === 'positive' ? 'green' : item.direction === 'negative' ? 'red' : 'blue'}>
                        {item.direction === 'positive' ? '偏利多' : item.direction === 'negative' ? '偏利空' : '中性'}
                      </Tag>
                    </div>
                    <div className="news-panel-item-title">
                      {item.url ? (
                        <a href={item.url} target="_blank" rel="noreferrer">
                          {item.title}
                        </a>
                      ) : item.title}
                    </div>
                    <div className="news-panel-item-time">{item.publish_time || '-'}</div>
                  </div>
                )
              })}
            </div>
          </Col>
        </Row>
      </Card>

      <Drawer
        title={selectedTheme ? `${selectedTheme.theme_name} 成分股` : '主题成分股'}
        open={themeDrawerOpen}
        onClose={() => setThemeDrawerOpen(false)}
        width={760}
      >
        {selectedTheme && (
          <div className="theme-drawer-summary">
            <div>
              <span>主题强度</span>
              <strong>{Number(selectedTheme.strength_score || 0).toFixed(1)}</strong>
            </div>
            <div>
              <span>板块涨幅</span>
              <strong>{Number(selectedTheme.pct_change || 0).toFixed(2)}%</strong>
            </div>
            <div>
              <span>主力净流入</span>
              <strong>{selectedTheme.money_net_inflow_yi === null || selectedTheme.money_net_inflow_yi === undefined ? '-' : `${Number(selectedTheme.money_net_inflow_yi).toFixed(2)}亿`}</strong>
            </div>
            <div>
              <span>退潮风险</span>
              <strong>{Number(selectedTheme.retreat_risk || 0).toFixed(0)}</strong>
            </div>
          </div>
        )}
        <Alert
          style={{ margin: '14px 0' }}
          type={themeStockMeta?.status === 'partial' ? 'warning' : 'info'}
          showIcon
          message="主题强不等于直接买入"
          description={themeStockMeta?.message || '成分股是否进入核心候选，还要通过趋势、资金质量、回撤风险和流动性闸门。'}
        />
        <Table
          className="ranking-table"
          loading={themeStocksLoading}
          columns={themeStockColumns}
          dataSource={themeStocks}
          rowKey={(row) => row.symbol || row.name}
          pagination={{ pageSize: 12, showSizeChanger: false }}
          scroll={{ x: 560 }}
        />
      </Drawer>

      <Drawer
        title="数据诊断"
        open={diagnosticOpen}
        onClose={() => setDiagnosticOpen(false)}
        width={520}
      >
        {isFallbackUniverse && (
          <Alert
            style={{ marginBottom: 16 }}
            type="warning"
            showIcon
            message="候选池处于降级模式"
            description={universeMeta.fallback_reason || '全A快照暂不可用，系统已使用兜底池生成候选。'}
          />
        )}
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="数据状态">{summary?.status || result?.status || '-'}</Descriptions.Item>
          <Descriptions.Item label="刷新状态">{summary?.is_refreshing || result?.is_refreshing ? '刷新中' : '空闲'}</Descriptions.Item>
          <Descriptions.Item label="全A快照">{pipelineCounts.snapshot ?? universeMeta.snapshot_count ?? universeMeta.total_universe_count ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="预筛通过">{pipelineCounts.prefilter ?? universeMeta.after_prefilter_count ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="深度分析">{pipelineCounts.analyzed ?? universeMeta.analyzed_count ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="最终展示">{pipelineCounts.visible_output ?? pickList.length}</Descriptions.Item>
          <Descriptions.Item label="主题识别">{themeData?.source || '-'}</Descriptions.Item>
          <Descriptions.Item label="资金流缓存">{moneyCoverage?.cached_symbol_count ?? 0} 只</Descriptions.Item>
          <Descriptions.Item label="更新时间">{loadedAt || '-'}</Descriptions.Item>
        </Descriptions>
        {excludedExamples.length > 0 && (
          <>
            <Divider />
            <h4>强势但未入选</h4>
            <div className="excluded-list">
              {excludedExamples.slice(0, 8).map((item) => (
                <div className="excluded-item" key={item.symbol}>
                  <span>{item.name} {item.symbol}</span>
                  <em>{item.reason}</em>
                </div>
              ))}
            </div>
          </>
        )}
      </Drawer>

      <Modal
        title="推荐详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={980}
        confirmLoading={detailLoading}
      >
        {detailData ? (
          <>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="股票">{detailData.name} ({detailData.symbol})</Descriptions.Item>
              <Descriptions.Item label="动作">
                <Tag color={(ACTION_LABEL[detailData.action] || ACTION_LABEL.pass).color}>
                  {(ACTION_LABEL[detailData.action] || ACTION_LABEL.pass).text}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="决策等级">
                <Tooltip title={detailData?.decision?.summary || ''}>
                  <Tag color={(DECISION_META[detailData?.decision?.grade] || DECISION_META.C).color}>
                    {(DECISION_META[detailData?.decision?.grade] || DECISION_META.C).text}
                  </Tag>
                </Tooltip>
              </Descriptions.Item>
              <Descriptions.Item label="概率口径">
                <Tag color={detailData?.probability_model?.calibrated ? 'green' : 'orange'}>
                  {detailData?.probability_model?.label || '规则代理概率'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="执行状态">
                {detailData?.user_action ? (
                  <Tag color={(USER_ACTION_LABEL[detailData.user_action.action_type] || { color: 'default' }).color}>
                    {(USER_ACTION_LABEL[detailData.user_action.action_type] || { text: '已执行' }).text}
                  </Tag>
                ) : (
                  <Tag>未执行</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="市场状态">
                <Tooltip title={(STATE_META[detailData?.market_state?.state_tag] || STATE_META.neutral).desc}>
                  <Tag color={(STATE_META[detailData?.market_state?.state_tag] || STATE_META.neutral).color}>
                    {(STATE_META[detailData?.market_state?.state_tag] || STATE_META.neutral).text}
                  </Tag>
                </Tooltip>
              </Descriptions.Item>
              <Descriptions.Item label="入场区间">{detailData.entry_range?.join(' - ')}</Descriptions.Item>
              <Descriptions.Item label="止盈/止损">{detailData.take_profit} / {detailData.stop_loss}</Descriptions.Item>
              <Descriptions.Item label="上涨概率">{(Number(detailData.up_prob || 0) * 100).toFixed(1)}%</Descriptions.Item>
              <Descriptions.Item label="回撤概率">{(Number(detailData.dd_prob || 0) * 100).toFixed(1)}%</Descriptions.Item>
              <Descriptions.Item label="模型版本">{detailData?.model_version_id || '未接入模型'}</Descriptions.Item>
              <Descriptions.Item label="模型最终分">
                {detailData?.model_probability ? Number(detailData.model_probability.final_score || 0).toFixed(2) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="仓位建议">{detailData.position_pct}%</Descriptions.Item>
              <Descriptions.Item label="持有周期">{detailData.horizon_days} 天</Descriptions.Item>
              <Descriptions.Item label="主力净流入(3日)">
                {Number(detailData?.market_metrics?.main_net_inflow_yi || 0).toFixed(2)} 亿
              </Descriptions.Item>
              <Descriptions.Item label="换手率">
                {Number(detailData?.market_metrics?.turnover_rate || 0).toFixed(2)}%
              </Descriptions.Item>
              <Descriptions.Item label="资讯总分">
                {Number(detailData?.news_factor?.total_score || 50).toFixed(1)}
              </Descriptions.Item>
              <Descriptions.Item label="资讯倾向">
                <Tag color={detailData?.news_factor?.sentiment === 'positive' ? 'green' : detailData?.news_factor?.sentiment === 'negative' ? 'red' : 'blue'}>
                  {detailData?.news_factor?.sentiment === 'positive' ? '偏正面' : detailData?.news_factor?.sentiment === 'negative' ? '偏负面' : '中性'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>

            {detailData?.model_probability && (
              <>
                <Divider />
                <h4>机器学习概率与解释</h4>
                <Row gutter={12}>
                  <Col xs={24} sm={8}>
                    <Statistic title="模型上涨概率" value={Number(detailData.model_probability.model_up_prob || 0) * 100} precision={1} suffix="%" />
                  </Col>
                  <Col xs={24} sm={8}>
                    <Statistic title="模型回撤概率" value={Number(detailData.model_probability.model_dd_prob || 0) * 100} precision={1} suffix="%" />
                  </Col>
                  <Col xs={24} sm={8}>
                    <Statistic title="相似样本胜率" value={Number(detailData?.similar_sample_evidence?.win_rate || 0) * 100} precision={1} suffix="%" />
                  </Col>
                </Row>
                <Space wrap style={{ marginTop: 12 }}>
                  {(detailData.factor_contributions || []).slice(0, 8).map((item) => (
                    <Tooltip key={item.feature} title={item.description || item.feature}>
                      <Tag color={item.direction === 'positive' ? 'green' : 'red'}>
                        {item.label}: {Number(item.contribution || 0).toFixed(3)}
                      </Tag>
                    </Tooltip>
                  ))}
                </Space>
                <Alert
                  style={{ marginTop: 12 }}
                  type={detailData?.model_probability?.status === 'live_ready' ? 'success' : 'warning'}
                  showIcon
                  message={detailData?.similar_sample_evidence?.message || '模型解释仅用于提高透明度，不构成收益承诺。'}
                />
              </>
            )}

            <Divider />
            <h4>评分拆解</h4>
            <Row gutter={12}>
              {SCORE_ORDER.map((key) => {
                if (detailData?.score_breakdown?.[key] === undefined) return null
                const meta = SCORE_META[key] || { label: key, desc: '' }
                const value = Number(detailData.score_breakdown[key] || 0)
                return (
                  <Col xs={24} sm={12} key={key} style={{ marginBottom: 8 }}>
                    <div style={{ color: '#9AA0A6', marginBottom: 4 }}>
                      {meta.label}
                      {meta.desc ? (
                        <Tooltip title={meta.desc}>
                          <InfoCircleOutlined style={{ marginLeft: 6 }} />
                        </Tooltip>
                      ) : null}
                    </div>
                    <Progress percent={value} size="small" />
                  </Col>
                )
              })}
            </Row>

            <Divider />
            <h4>理由与风险</h4>
            <Space direction="vertical" style={{ width: '100%' }}>
              {(detailData.reasons || []).map((text) => (
                <Alert key={`r-${text}`} type="success" showIcon message={text} />
              ))}
              {(detailData.risks || []).map((text) => (
                <Alert key={`k-${text}`} type="warning" showIcon message={text} />
              ))}
            </Space>

            <Divider />
            <h4>近期官方事件</h4>
            <Space direction="vertical" style={{ width: '100%' }}>
              {(detailData?.news_factor?.latest_events || []).length > 0 ? (
                (detailData.news_factor.latest_events || []).map((item) => (
                  <Alert
                    key={`${item.source}-${item.title}`}
                    type={item.direction === 'positive' ? 'success' : item.direction === 'negative' ? 'warning' : 'info'}
                    showIcon
                    message={`${item.title}（${item.publish_time || '-'}）`}
                    description={(
                      <span>
                        {(NEWS_SOURCE_META[item.source]?.label || item.source || '资讯')} / {(EVENT_LEVEL_META[item.event_level]?.label || item.event_level || '事件')}
                        {item.url ? (
                          <>
                            {' · '}
                            <a href={item.url} target="_blank" rel="noreferrer">
                              查看原文
                            </a>
                          </>
                        ) : null}
                      </span>
                    )}
                  />
                ))
              ) : (
                <Alert type="info" showIcon message="近期暂无结构化官方事件" />
              )}
            </Space>
          </>
        ) : (
          <Alert type="info" showIcon message={detailLoading ? '加载中...' : '暂无详情数据'} />
        )}
      </Modal>
    </div>
  )
}

export default SmartScreen
