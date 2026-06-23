import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
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
import { shouldRefreshCurrentTradingPicks } from './smartScreenData.mjs'
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

const SmartScreen = () => {
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState('')
  const [error, setError] = useState('')
  const [riskLevel, setRiskLevel] = useState('medium')
  const [result, setResult] = useState(null)
  const [loadedAt, setLoadedAt] = useState('')
  const [selectedSnapshotDate, setSelectedSnapshotDate] = useState(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailData, setDetailData] = useState(null)
  const latestLoadReqRef = useRef(0)
  const mountedRef = useRef(false)
  const refreshAttemptedForDateRef = useRef('')

  const loadPicks = async (targetRisk = null, targetSnapshotDate = selectedSnapshotDate) => {
    const reqId = latestLoadReqRef.current + 1
    latestLoadReqRef.current = reqId
    if (mountedRef.current) {
      setLoading(true)
      setError('')
    }
    try {
      const effectiveRisk = targetRisk || riskLevel
      const params = {
        user_id: 'default',
        max_count: 30,
        risk_level: effectiveRisk,
        cached_only: true,
      }
      const summaryParams = {
        user_id: 'default',
        risk_level: effectiveRisk,
      }
      if (targetSnapshotDate) {
        params.trade_date = targetSnapshotDate
        summaryParams.trade_date = targetSnapshotDate
      }
      const [summary, data] = await Promise.all([
        coachApi.getSmartScreenSummary(summaryParams),
        coachApi.getTodayPicks(params),
      ])
      if (!mountedRef.current || reqId !== latestLoadReqRef.current) return
      const combinedResult = {
        ...(summary || {}),
        ...(data || {}),
        calendar_context: data?.calendar_context || summary?.calendar_context,
        snapshot_dates: data?.snapshot_dates || summary?.snapshot_dates || [],
        trade_plan: data?.trade_plan || summary?.trade_plan || {},
      }
      setResult(combinedResult)
      const calendarContext = combinedResult.calendar_context || {}
      const refreshKey = calendarContext.requested_date || calendarContext.effective_trade_date || ''
      const canRefreshCurrent = (calendarContext.actions || {}).can_refresh !== false
      if (
        refreshKey
        && refreshAttemptedForDateRef.current !== refreshKey
        && shouldRefreshCurrentTradingPicks({
          calendarContext,
          canRefresh: canRefreshCurrent,
          isRefreshing: Boolean(combinedResult.is_refreshing),
        })
      ) {
        refreshAttemptedForDateRef.current = refreshKey
        coachApi.refreshTodayPicks({
          user_id: 'default',
          max_count: 30,
          risk_level: effectiveRisk,
        }).then(() => {
          if (mountedRef.current && reqId === latestLoadReqRef.current) {
            loadPicks(effectiveRisk, null)
          }
        }).catch((refreshErr) => {
          console.warn('自动刷新当前交易日候选池失败', refreshErr)
        })
      }
      const nextRisk = data?.risk_profile?.risk_level
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

  useEffect(() => {
    mountedRef.current = true
    loadPicks()
    return () => {
      mountedRef.current = false
    }
  }, [])

  const pickList = useMemo(() => result?.picks || [], [result])
  const marketNews = result?.market_state?.news_context || {}
  const tradePlan = result?.trade_plan || {}
  const planMeta = PLAN_ACTION_META[tradePlan.primary_action] || PLAN_ACTION_META.watch
  const corePicks = useMemo(
    () => pickList.filter((item) => ['A', 'B'].includes(item?.decision?.grade)).slice(0, 3),
    [pickList]
  )

  const stateTag = result?.market_state?.state_tag
  const stateMeta = STATE_META[stateTag] || STATE_META.neutral
  const calendarContext = result?.calendar_context || {}
  const calendarActions = calendarContext?.actions || {}
  const calendarMode = calendarContext?.mode || 'trading'
  const isPreparationMode = calendarMode === 'preparation'
  const isHistoricalMode = calendarMode === 'historical'
  const isObservationMode = isPreparationMode || isHistoricalMode
  const snapshotDates = result?.snapshot_dates || []
  const canRefresh = calendarActions.can_refresh !== false && calendarMode === 'trading'
  const canPaperBuy = calendarActions.can_paper_buy !== false
  const candidateDate = calendarContext?.effective_trade_date || result?.trade_date || '-'
  const signalAge = calendarContext?.signal_age_days
  const signalAgeText = signalAge === null || signalAge === undefined ? '-' : `${signalAge} 天`
  const heroKicker = isPreparationMode ? '备战观察' : (isHistoricalMode ? '历史快照' : '今日行动')
  const heroHeadline = isPreparationMode
    ? '备战观察'
    : (isHistoricalMode ? '历史快照观察' : (tradePlan.headline || '等待生成交易计划'))
  const heroSummary = isObservationMode
    ? (calendarContext?.message || '当前只读取已保存候选池快照，不重新运行策略。')
    : (tradePlan.summary || '系统会先判断市场环境和策略证据，再决定是否输出可执行候选。')
  const heroBadge = isPreparationMode
    ? { label: '观察准备', color: '#60a5fa' }
    : (isHistoricalMode ? { label: '复盘观察', color: '#a78bfa' } : planMeta)

  const handleRiskChange = async (value) => {
    setRiskLevel(value)
    await loadPicks(value, selectedSnapshotDate)
  }

  const handleSnapshotDateChange = async (value) => {
    const nextDate = value === 'latest' ? null : value
    setSelectedSnapshotDate(nextDate)
    await loadPicks(riskLevel, nextDate)
  }

  const triggerRefresh = async () => {
    if (!canRefresh) {
      message.warning('非交易日不生成交易计划')
      return
    }
    setLoading(true)
    try {
      const response = await coachApi.refreshTodayPicks({
        user_id: 'default',
        max_count: 30,
        risk_level: riskLevel,
      })
      if (response?.accepted === false) {
        message.warning(response?.calendar_context?.message || '非交易日不生成交易计划')
        setResult((prev) => ({
          ...(prev || {}),
          calendar_context: response?.calendar_context || prev?.calendar_context,
          snapshot_dates: response?.snapshot_dates || prev?.snapshot_dates || [],
        }))
        return
      }
      message.success('后台刷新完成')
      setSelectedSnapshotDate(null)
      await loadPicks(riskLevel, null)
    } catch (err) {
      console.error('刷新智能选股失败', err)
      message.error(err?.response?.data?.message || err?.message || '刷新失败')
    } finally {
      setLoading(false)
    }
  }

  const reportAction = async (pick, actionType) => {
    if (actionType === 'paper_buy' && !canPaperBuy) {
      message.warning('非交易日不生成交易计划，不能模拟买入')
      return
    }
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
      await loadPicks(riskLevel)
      if (detailData?.pick_id === pick.pick_id) {
        await openDetail(pick.pick_id)
      }
    } catch (err) {
      console.error('记录动作失败', err)
      message.error(err?.response?.data?.message || err?.message || '动作记录失败')
    } finally {
      setActionLoading('')
    }
  }

  const openDetail = async (pickId) => {
    setDetailOpen(true)
    setDetailLoading(true)
    setDetailData(null)
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
      title: '决策等级',
      key: 'decision',
      width: 140,
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
      title: '执行状态',
      key: 'user_action',
      width: 120,
      render: (_, row) => {
        const meta = USER_ACTION_LABEL[row?.user_action?.action_type]
        if (!meta) return <Tag>未执行</Tag>
        return <Tag color={meta.color}>{meta.text}</Tag>
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
      title: '模型概率',
      key: 'model_probability',
      width: 150,
      render: (_, row) => {
        const model = row?.model_probability
        if (!model) return <Tag color="orange">规则代理</Tag>
        return (
          <Tooltip title={`模型 ${row?.model_version_id || '-'}，最终分 ${Number(model.final_score || 0).toFixed(1)}`}>
            <Tag color={model.status === 'live_ready' ? 'green' : 'cyan'}>
              ML {(Number(model.model_up_prob || 0) * 100).toFixed(1)}%
            </Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '预期收益',
      dataIndex: 'expected_return_pct',
      key: 'expected_return_pct',
      width: 120,
      render: (v) => `${Number(v || 0).toFixed(2)}%`,
    },
    {
      title: '仓位',
      dataIndex: 'position_pct',
      key: 'position_pct',
      width: 120,
      render: (v) => `${Number(v || 0).toFixed(1)}%`,
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
      title: '资讯分',
      key: 'news_score',
      width: 110,
      render: (_, row) => Number(row?.news_factor?.total_score || 50).toFixed(1),
    },
    {
      title: '操作',
      key: 'operation',
      width: 280,
      fixed: 'right',
      render: (_, row) => (
        <Space wrap>
          <Button size="small" onClick={() => openDetail(row.pick_id)}>
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
            disabled={!canPaperBuy || row?.decision?.mode === 'watch_only'}
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

  return (
    <div className="smart-screen-container">
      <div className="screen-header">
        <h1 className="page-title">
          <ThunderboltOutlined /> 智能选股
        </h1>
        <p className="page-subtitle">今日交易计划 + 策略证据 + 模拟验证闭环</p>
      </div>

      {error && <Alert style={{ marginBottom: 16 }} type="error" showIcon message={error} />}
      {isObservationMode && (
        <Alert
          style={{ marginBottom: 16 }}
          type={isPreparationMode ? 'info' : 'success'}
          showIcon
          message={calendarContext?.message || `以下为 ${candidateDate} 候选池，仅供观察准备。`}
        />
      )}
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
            <div className="plan-kicker">{heroKicker}</div>
            <h2 style={{ color: heroBadge.color }}>{heroHeadline}</h2>
            <p>{heroSummary}</p>
          </div>
          <div className="plan-badge" style={{ borderColor: heroBadge.color, color: heroBadge.color }}>
            {heroBadge.label}
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
                    <Button size="small" onClick={() => openDetail(pick.pick_id)}>查看计划</Button>
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      loading={actionLoading === `${pick.pick_id}-added_watchlist`}
                      onClick={() => reportAction(pick, 'added_watchlist')}
                    >
                      加入观察
                    </Button>
                    <Tooltip title={!canPaperBuy ? '非交易日不生成交易计划，不能模拟买入' : ''}>
                      <Button
                        size="small"
                        type="primary"
                        disabled={!canPaperBuy || pick?.decision?.mode === 'watch_only'}
                        loading={actionLoading === `${pick.pick_id}-paper_buy`}
                        onClick={() => reportAction(pick, 'paper_buy')}
                      >
                        模拟买入
                      </Button>
                    </Tooltip>
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
            <Statistic title={isObservationMode ? '候选池日期' : '交易日'} value={candidateDate} />
            <div className="stat-extra">信号年龄：{signalAgeText}</div>
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
            <Space className="snapshot-controls" wrap>
              <Select value={riskLevel} onChange={handleRiskChange} style={{ width: 140 }}>
                <Option value="low">低风险</Option>
                <Option value="medium">中风险</Option>
                <Option value="high">高风险</Option>
              </Select>
              <Select value={selectedSnapshotDate || 'latest'} onChange={handleSnapshotDateChange} style={{ width: 148 }}>
                <Option value="latest">最近快照</Option>
                {snapshotDates.map((dateText) => (
                  <Option value={dateText} key={dateText}>{dateText}</Option>
                ))}
              </Select>
              <Tooltip title={!canRefresh ? '非交易日不生成交易计划' : '刷新当前交易日候选池'}>
                <Button icon={<ReloadOutlined />} loading={loading} disabled={!canRefresh} onClick={triggerRefresh}>
                  后台刷新
                </Button>
              </Tooltip>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card className="info-card" variant="borderless" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Tooltip title={STATE_META.offensive.desc}>
            <Tag color={STATE_META.offensive.color}>进攻：可提高仓位</Tag>
          </Tooltip>
          <Tooltip title={STATE_META.neutral.desc}>
            <Tag color={STATE_META.neutral.color}>均衡：精选个股</Tag>
          </Tooltip>
          <Tooltip title={STATE_META.defensive.desc}>
            <Tag color={STATE_META.defensive.color}>防守：优先控回撤</Tag>
          </Tooltip>
          <Tag color="volcano">
            当前策略：{STRATEGY_NAME_MAP[result?.strategy_context?.strategy_code] || result?.strategy_context?.strategy_code || '趋势突破'}
          </Tag>
          <Tag color="purple">
            配置模板：{result?.strategy_context?.profile_key || '默认'}
          </Tag>
          <Tag color="cyan">
            阈值：{result?.strategy_context?.config?.score_threshold ?? '-'}
          </Tag>
          <Tag color="blue">
            生效阈值：{result?.strategy_context?.config?.effective_score_threshold ?? result?.strategy_context?.config?.score_threshold ?? '-'}
          </Tag>
          <Tag color="geekblue">
            全A原始池：{result?.universe_meta?.total_universe_count ?? '-'}
          </Tag>
          <Tag color="cyan">
            预筛通过：{result?.universe_meta?.after_prefilter_count ?? '-'}
          </Tag>
          <Tag color="green">
            分析候选：{result?.universe_meta?.candidate_count ?? '-'}
          </Tag>
          <Tag color="lime">
            评分完成：{result?.universe_meta?.analyzed_count ?? '-'}
          </Tag>
          <Tag color="gold">
            策略目标池：{result?.universe_meta?.rules?.strategy_target_size ?? '-'}
          </Tag>
          <Tag color="gold">
            推荐输出：{Array.isArray(result?.picks) ? result.picks.length : '-'}
          </Tag>
          <Tag color="purple">
            行业覆盖：{result?.universe_meta?.industry_count ?? '-'}
          </Tag>
          {result?.universe_meta?.full_refresh_at && (
            <Tag color="orange">全量刷新：{result.universe_meta.full_refresh_at}</Tag>
          )}
          {result?.universe_meta?.incremental_refresh_at && (
            <Tag color="magenta">增量刷新：{result.universe_meta.incremental_refresh_at}</Tag>
          )}
          <Tag color="blue">当前数据时间：{loadedAt || '-'}</Tag>
          <Tag color={result?.market_state?.news_context?.risk_bias === 'positive' ? 'green' : result?.market_state?.news_context?.risk_bias === 'negative' ? 'red' : 'blue'}>
            资讯温度：{Number(result?.market_state?.news_context?.policy_score || 50).toFixed(1)}
          </Tag>
          {result?.market_state?.news_context?.updated_at && (
            <Tag color="lime">资讯更新：{result.market_state.news_context.updated_at}</Tag>
          )}
        </Space>
      </Card>

      <Card className="ranking-card" variant="borderless">
        <div className="ranking-card-title">
          <h3>完整候选池</h3>
          <span>只有 A/B 级才进入交易计划，C 级用于观察学习。</span>
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
            scroll={{ x: 1850, y: 480 }}
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
