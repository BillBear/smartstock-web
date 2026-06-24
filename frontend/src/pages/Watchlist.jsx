import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Collapse, Progress, Row, Space, Table, Tabs, Tag, Tooltip, message } from 'antd'
import {
  AuditOutlined,
  DeleteOutlined,
  LineChartOutlined,
  MinusCircleOutlined,
  ReloadOutlined,
  StarFilled,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Line } from '@ant-design/plots'
import { useNavigate } from 'react-router-dom'
import { coachApi } from '../services/api'
import './Watchlist.css'

const ACTION_META = {
  added_watchlist: { text: '观察', color: 'blue' },
  paper_buy: { text: '模拟持仓', color: 'red' },
}

const RISK_META = {
  normal: { text: '正常', color: 'green' },
  warning: { text: '浮亏警戒', color: 'orange' },
  stop_loss: { text: '跌破止损', color: 'red' },
  take_profit: { text: '达到止盈', color: 'gold' },
  profit_watch: { text: '浮盈跟踪', color: 'cyan' },
}

const MONITOR_META = {
  continue_hold: { text: '继续持有', color: 'green' },
  risk_review: { text: '风险复核', color: 'orange' },
  suggest_exit: { text: '建议退出', color: 'red' },
  missed_opportunity: { text: '错过机会', color: 'gold' },
  validation_failed: { text: '验证失败', color: 'volcano' },
  waiting_trigger: { text: '等待触发', color: 'blue' },
}

const MONEY_FLOW_META = {
  real: { text: '真实资金流', color: 'green' },
  proxy: { text: '代理资金', color: 'gold' },
  unavailable: { text: '资金不可用', color: 'default' },
}

const MODEL_ROLE_META = {
  model_ready_correction: { text: '模型可用修正', color: 'green' },
  ml_paper_only_correction: { text: '模型纸面修正', color: 'gold' },
  ml_correction: { text: '模型修正', color: 'blue' },
  rule_proxy_or_legacy: { text: '规则/旧策略', color: 'default' },
}

const pctColor = (value) => (Number(value || 0) >= 0 ? '#ff5a5f' : '#22c55e')
const formatMaybePct = (value) => (value === null || value === undefined ? '-' : `${Number(value || 0).toFixed(2)}%`)
const daysSince = (value) => {
  const dt = value ? new Date(String(value).replace(' ', 'T')) : null
  if (!dt || Number.isNaN(dt.getTime())) return null
  return Math.max(0, Math.floor((Date.now() - dt.getTime()) / 86400000))
}

const Watchlist = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [actionLoading, setActionLoading] = useState('')
  const [rows, setRows] = useState([])
  const [portfolio, setPortfolio] = useState(null)
  const [trades, setTrades] = useState([])
  const [review, setReview] = useState(null)
  const [monitorOverview, setMonitorOverview] = useState(null)
  const [monitorPositions, setMonitorPositions] = useState([])
  const [monitorFeedback, setMonitorFeedback] = useState(null)
  const [paperPerformance, setPaperPerformance] = useState(null)
  const [paperAttribution, setPaperAttribution] = useState(null)
  const [reviewRunning, setReviewRunning] = useState(false)
  const [monitorTab, setMonitorTab] = useState('all')

  const loadWatchlist = async () => {
    setLoading(true)
    setError('')
    try {
      const [watchlistData, tradeData, reviewData, overviewData, positionsData, feedbackData, performanceData, attributionData] = await Promise.all([
        coachApi.getWatchlist({ user_id: 'default' }),
        coachApi.getPaperTrades({ user_id: 'default', limit: 50 }),
        coachApi.getPaperReview({ user_id: 'default' }),
        coachApi.getMonitorOverview({ user_id: 'default' }),
        coachApi.getMonitorPositions({ user_id: 'default' }),
        coachApi.getMonitorFeedback({ user_id: 'default' }),
        coachApi.getPaperPerformance({ user_id: 'default' }),
        coachApi.getPaperAttribution({ user_id: 'default' }),
      ])
      setRows(watchlistData?.items || [])
      setPortfolio({ summary: watchlistData?.portfolio_summary || {} })
      setTrades(tradeData?.items || [])
      setReview(reviewData || null)
      setMonitorOverview(overviewData || null)
      setMonitorPositions(positionsData?.items || [])
      setMonitorFeedback(feedbackData || null)
      setPaperPerformance(performanceData || null)
      setPaperAttribution(attributionData || null)
    } catch (err) {
      console.error('加载自选池失败', err)
      setError(err?.response?.data?.message || err?.message || '加载失败')
      setRows([])
      setPortfolio(null)
      setTrades([])
      setReview(null)
      setMonitorOverview(null)
      setMonitorPositions([])
      setMonitorFeedback(null)
      setPaperPerformance(null)
      setPaperAttribution(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadWatchlist()
  }, [])

  const runDailyReview = async () => {
    setReviewRunning(true)
    try {
      const data = await coachApi.runDailyMonitorReview({ user_id: 'default' })
      setMonitorFeedback(data || null)
      setMonitorPositions(data?.positions || monitorPositions)
      message.success('已生成今日监控复盘')
      await loadWatchlist()
    } catch (err) {
      console.error('生成监控复盘失败', err)
      message.error(err?.response?.data?.message || err?.message || '生成复盘失败')
    } finally {
      setReviewRunning(false)
    }
  }

  const handleRemove = async (record, isClosePosition = false) => {
    setActionLoading(`${record.pick_id}-${isClosePosition ? 'closed' : 'ignored'}`)
    try {
      if (isClosePosition) {
        await coachApi.recordPickAction(
          record.pick_id,
          {
            action_type: 'closed',
            action_price: record.current_price || record.avg_price || record.action_price,
            action_qty: record.position_qty || record.action_qty,
            note: 'close paper position',
          },
          'default'
        )
        message.success('模拟持仓已平仓')
      } else {
        await coachApi.recordPickAction(
          record.pick_id,
          {
            action_type: 'ignored',
            note: 'removed from watchlist',
          },
          'default'
        )
        message.success('已从观察池移除')
      }
      await loadWatchlist()
    } catch (err) {
      console.error('移除失败', err)
      message.error(err?.response?.data?.message || err?.message || '移除失败')
    } finally {
      setActionLoading('')
    }
  }

  const portfolioTotalCost = Number(portfolio?.summary?.total_cost || 0)

  const columns = useMemo(() => ([
    {
      title: '股票',
      key: 'stock',
      width: 220,
      render: (_, record) => (
        <div className="watchlist-stock">
          <div className="stock-name">{record.name}</div>
          <div className="stock-code">{record.symbol}</div>
        </div>
      ),
    },
    {
      title: '类型',
      dataIndex: 'action_type',
      key: 'action_type',
      render: (v) => <Tag color={(ACTION_META[v] || { color: 'default' }).color}>{(ACTION_META[v] || { text: '-' }).text}</Tag>,
    },
    {
      title: '策略/信号',
      key: 'strategy',
      width: 190,
      render: (_, record) => {
        const modelMeta = MODEL_ROLE_META[
          record.model_status === 'paper_only' ? 'ml_paper_only_correction' : record.model_version_id ? 'ml_correction' : 'rule_proxy_or_legacy'
        ] || MODEL_ROLE_META.rule_proxy_or_legacy
        return (
          <div className="strategy-signal-cell">
            <span>{record.strategy_version || '旧策略/缺快照'}</span>
            <Space size={4} wrap>
              <Tag color={record.snapshot_quality === 'complete' ? 'green' : 'default'}>
                {record.signal_date || '无信号日'}
              </Tag>
              <Tag color={modelMeta.color}>{modelMeta.text}</Tag>
            </Space>
          </div>
        )
      },
    },
    {
      title: '触发价',
      dataIndex: 'action_price',
      key: 'action_price',
      render: (v) => v ? `¥${Number(v).toFixed(2)}` : '-',
    },
    {
      title: '上涨概率',
      dataIndex: 'up_prob',
      key: 'up_prob',
      render: (v) => v !== undefined && v !== null ? `${(Number(v) * 100).toFixed(1)}%` : '-',
    },
    {
      title: '回撤概率',
      dataIndex: 'dd_prob',
      key: 'dd_prob',
      render: (v) => v !== undefined && v !== null ? `${(Number(v) * 100).toFixed(1)}%` : '-',
    },
    {
      title: '综合分',
      dataIndex: 'score',
      key: 'score',
      render: (v) => (v !== undefined && v !== null ? `${Number(v).toFixed(1)}分` : '-'),
    },
    {
      title: '持仓',
      key: 'position_qty',
      render: (_, record) => (record.position_qty ? `${Number(record.position_qty).toFixed(0)} 股` : '-'),
    },
    {
      title: '仓位贡献',
      key: 'capital_weight',
      width: 120,
      render: (_, record) => {
        if (!record.position_qty || !record.avg_price || !portfolioTotalCost) return '-'
        const cost = Number(record.position_qty || 0) * Number(record.avg_price || 0)
        const weight = cost / portfolioTotalCost * 100
        return (
          <Tooltip title={`成本约 ¥${cost.toFixed(2)}`}>
            <Tag color={weight >= 25 ? 'red' : weight >= 12 ? 'gold' : 'blue'}>{weight.toFixed(1)}%</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '现价',
      key: 'current_price',
      render: (_, record) => (record.current_price ? `¥${Number(record.current_price).toFixed(2)}` : '-'),
    },
    {
      title: '浮盈亏',
      key: 'unrealized_pnl',
      render: (_, record) => {
        if (record.unrealized_pnl === undefined || record.unrealized_pnl === null) return '-'
        const color = Number(record.unrealized_pnl) >= 0 ? 'var(--bull-color)' : 'var(--bear-color)'
        return <span style={{ color }}>{Number(record.unrealized_pnl).toFixed(2)}</span>
      },
    },
    {
      title: '风控位',
      key: 'risk_levels',
      width: 150,
      render: (_, record) => {
        if (!record.stop_loss && !record.take_profit) return '-'
        return (
          <div>
            <div>止损 ¥{Number(record.stop_loss || 0).toFixed(2)}</div>
            <div>止盈 ¥{Number(record.take_profit || 0).toFixed(2)}</div>
          </div>
        )
      },
    },
    {
      title: '风控状态',
      key: 'risk_status',
      width: 120,
      render: (_, record) => {
        if (!record.risk_status) return '-'
        const meta = RISK_META[record.risk_status] || RISK_META.normal
        return (
          <Tooltip title={record.risk_message || ''}>
            <Tag color={meta.color}>{meta.text}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '记录时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v) => {
        const days = daysSince(v)
        return (
          <div className="time-stack">
            <span>{v || '-'}</span>
            {days !== null && <Tag color={days > 20 ? 'orange' : 'default'}>{days}天</Tag>}
          </div>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Space>
          <Button
            type="primary"
            size="small"
            ghost
            icon={<LineChartOutlined />}
            onClick={() => navigate(`/stock/${record.symbol}`)}
          >
            分析
          </Button>
          <Button
            danger
            size="small"
            icon={record.action_type === 'paper_buy' ? <MinusCircleOutlined /> : <DeleteOutlined />}
            loading={actionLoading === `${record.pick_id}-${record.action_type === 'paper_buy' ? 'closed' : 'ignored'}`}
            onClick={() => handleRemove(record, record.action_type === 'paper_buy')}
          >
            {record.action_type === 'paper_buy' ? '模拟平仓' : '移除'}
          </Button>
        </Space>
      ),
    },
  ]), [actionLoading, navigate, portfolioTotalCost])

  const tradeColumns = useMemo(() => ([
    { title: '时间', dataIndex: 'trade_date', key: 'trade_date', width: 180 },
    { title: '股票', key: 'stock', render: (_, row) => `${row.name || row.symbol} (${row.symbol})` },
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      width: 80,
      render: (side) => <Tag color={side === 'buy' ? 'red' : 'green'}>{side === 'buy' ? '买入' : '卖出'}</Tag>,
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 90,
      render: (v) => `¥${Number(v || 0).toFixed(2)}`,
    },
    {
      title: '数量',
      dataIndex: 'qty',
      key: 'qty',
      width: 100,
      render: (v) => `${Number(v || 0).toFixed(0)}股`,
    },
    {
      title: '金额',
      dataIndex: 'amount',
      key: 'amount',
      width: 110,
      render: (v) => `¥${Number(v || 0).toFixed(2)}`,
    },
    { title: '原因', dataIndex: 'reason', key: 'reason' },
  ]), [])

  const reviewColumns = useMemo(() => ([
    {
      title: '股票',
      key: 'stock',
      width: 150,
      render: (_, record) => (
        <div className="watchlist-stock compact">
          <div className="stock-name">{record.name}</div>
          <div className="stock-code">{record.symbol}</div>
        </div>
      ),
    },
    {
      title: '推荐质量',
      key: 'score',
      width: 150,
      render: (_, record) => (
        <Space size={6}>
          <Tag color="cyan">{record.decision_grade || '-'}</Tag>
          <span>{record.score !== undefined && record.score !== null ? `${Number(record.score).toFixed(1)}分` : '-'}</span>
        </Space>
      ),
    },
    {
      title: '当前反馈',
      key: 'pnl',
      width: 150,
      render: (_, record) => {
        const pnl = Number(record.unrealized_pnl_pct || 0)
        return (
          <span style={{ color: pnl >= 0 ? 'var(--bull-color)' : 'var(--bear-color)' }}>
            {record.unrealized_pnl_pct !== undefined && record.unrealized_pnl_pct !== null ? `${pnl.toFixed(2)}%` : '-'}
          </span>
        )
      },
    },
    {
      title: '复盘结论',
      dataIndex: 'verdict',
      key: 'verdict',
      width: 120,
      render: (v) => <Tag color={v === '必须复核' ? 'red' : v === '风险复核' ? 'orange' : 'green'}>{v}</Tag>,
    },
    { title: '建议动作', dataIndex: 'suggestion', key: 'suggestion' },
  ]), [])

  const attributionColumns = useMemo(() => ([
    {
      title: '归因',
      key: 'reason',
      render: (_, record) => (
        <div className="attribution-reason">
          <strong>{record.label || record.code}</strong>
          <span>{record.code}</span>
        </div>
      ),
    },
    {
      title: '样本',
      dataIndex: 'sample_count',
      key: 'sample_count',
      width: 90,
      render: (v) => `${Number(v || 0)} 笔`,
    },
    {
      title: '亏损率',
      dataIndex: 'loss_rate',
      key: 'loss_rate',
      width: 100,
      render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
    },
    {
      title: '平均收益',
      dataIndex: 'avg_return_pct',
      key: 'avg_return_pct',
      width: 110,
      render: (v) => {
        const value = Number(v || 0)
        return <strong style={{ color: pctColor(value) }}>{value.toFixed(2)}%</strong>
      },
    },
    {
      title: '跑赢指数',
      dataIndex: 'avg_relative_index_return_pct',
      key: 'avg_relative_index_return_pct',
      width: 110,
      render: (v) => (
        <strong style={{ color: v === null || v === undefined ? undefined : pctColor(v) }}>
          {formatMaybePct(v)}
        </strong>
      ),
    },
  ]), [])

  const calibrationColumns = useMemo(() => ([
    { title: '概率分桶', dataIndex: 'label', key: 'label' },
    {
      title: '样本',
      dataIndex: 'sample_count',
      key: 'sample_count',
      width: 90,
      render: (v) => `${Number(v || 0)} 笔`,
    },
    {
      title: '观察胜率',
      dataIndex: 'observed_win_rate',
      key: 'observed_win_rate',
      width: 110,
      render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
    },
    {
      title: '校准状态',
      key: 'calibrated',
      width: 110,
      render: (_, record) => <Tag color={record.calibrated ? 'green' : 'gold'}>{record.calibrated ? '可校准' : '样本不足'}</Tag>,
    },
  ]), [])

  const strategyBreakdownColumns = useMemo(() => ([
    {
      title: '策略版本',
      key: 'strategy',
      render: (_, record) => (
        <div className="strategy-breakdown-name">
          <strong>{record.strategy_version || record.key}</strong>
          <span>{record.model_version_id || (record.snapshot_quality === 'complete' ? '无模型版本' : '旧仓/缺快照')}</span>
        </div>
      ),
    },
    {
      title: '样本',
      dataIndex: 'sample_count',
      key: 'sample_count',
      width: 70,
    },
    {
      title: '资金加权',
      dataIndex: 'capital_weighted_return_pct',
      key: 'capital_weighted_return_pct',
      width: 100,
      render: (v) => <strong style={{ color: pctColor(v) }}>{formatMaybePct(v)}</strong>,
    },
    {
      title: '等权收益',
      dataIndex: 'equal_weighted_return_pct',
      key: 'equal_weighted_return_pct',
      width: 100,
      render: (v) => <span style={{ color: pctColor(v) }}>{formatMaybePct(v)}</span>,
    },
  ]), [])

  const reviewMetrics = review?.metrics || {}
  const monitorSummary = monitorOverview?.summary || {}
  const feedbackSummary = monitorFeedback?.summary || {}
  const feedbackSuggestions = monitorFeedback?.suggestions || []
  const performanceSummary = paperPerformance?.summary || {}
  const lowReturnDiagnosis = paperPerformance?.low_return_diagnosis || {}
  const currentStrategyReturn = paperPerformance?.current_strategy_return || {}
  const legacyPositionReturn = paperPerformance?.legacy_position_return || {}
  const strategyVersionBreakdown = paperPerformance?.strategy_version_breakdown || []
  const attributionSummary = paperAttribution?.attribution_summary || []
  const strategyAdjustments = paperAttribution?.strategy_adjustments || monitorFeedback?.strategy_adjustments || []
  const probabilityCalibration = paperAttribution?.probability_calibration || {}
  const retrainReadiness = paperPerformance?.model_retrain_readiness || {}
  const topFailureReasons = paperAttribution?.failure_reasons || monitorFeedback?.failure_reasons || []

  const unifiedMonitorRows = useMemo(() => {
    const monitorMap = new Map()
    ;(monitorPositions || []).forEach((item) => {
      if (item?.symbol) monitorMap.set(String(item.symbol), item)
    })

    const merged = (rows || []).map((row) => {
      const monitor = monitorMap.get(String(row.symbol || '')) || {}
      const metrics = monitor.metrics || {}
      const conclusion = monitor.conclusion || {}
      const type = monitor.track_type || (row.action_type === 'paper_buy' ? 'paper_position' : 'watch_candidate')
      const entryPrice = row.avg_price || row.action_price || metrics.entry_price
      const currentPrice = row.current_price || metrics.current_price
      const returnPct = metrics.current_return_pct ?? row.unrealized_pnl_pct
      const maxDrawdownPct = metrics.max_drawdown_pct
      return {
        ...monitor,
        ...row,
        metrics,
        conclusion,
        track_type: type,
        monitor_return_pct: returnPct,
        monitor_max_drawdown_pct: maxDrawdownPct,
        monitor_entry_price: entryPrice,
        monitor_current_price: currentPrice,
        monitor_holding_days: metrics.holding_days,
        money_flow_quality: monitor.money_flow_quality || row.money_flow_quality,
        data_quality: monitor.data_quality || row.data_quality,
        path: monitor.path || [],
      }
    }).filter((item) => {
      const isPaperPosition = item.action_type === 'paper_buy' || item.track_type === 'paper_position'
      const hasOpenQty = Number(item.position_qty || 0) > 0
      return !isPaperPosition || hasOpenQty
    })

    const existingSymbols = new Set(merged.map((item) => String(item.symbol || '')))
    ;(monitorPositions || []).forEach((monitor) => {
      const symbol = String(monitor?.symbol || '')
      if (!symbol || existingSymbols.has(symbol) || monitor.track_type === 'paper_position') return
      const metrics = monitor.metrics || {}
      merged.push({
        ...monitor,
        action_type: monitor.track_type === 'paper_position' ? 'paper_buy' : 'added_watchlist',
        metrics,
        monitor_return_pct: metrics.current_return_pct,
        monitor_max_drawdown_pct: metrics.max_drawdown_pct,
        monitor_entry_price: metrics.entry_price,
        monitor_current_price: metrics.current_price,
        monitor_holding_days: metrics.holding_days,
      })
    })

    const severityRank = {
      stop_loss: 1,
      take_profit: 2,
      suggest_exit: 3,
      risk_review: 4,
      validation_failed: 5,
      profit_watch: 6,
      warning: 7,
      waiting_trigger: 8,
      continue_hold: 9,
      normal: 10,
    }
    return merged.sort((a, b) => {
      const aKey = a.risk_status || a.conclusion?.status || 'normal'
      const bKey = b.risk_status || b.conclusion?.status || 'normal'
      return (severityRank[aKey] || 20) - (severityRank[bKey] || 20)
    })
  }, [monitorPositions, rows])

  const needsActionRows = useMemo(() => unifiedMonitorRows.filter((row) => {
    const status = row.conclusion?.status
    const risk = row.risk_status
    return ['risk_review', 'suggest_exit', 'validation_failed', 'missed_opportunity'].includes(status)
      || ['warning', 'stop_loss', 'take_profit', 'profit_watch'].includes(risk)
  }), [unifiedMonitorRows])

  const filteredMonitorRows = useMemo(() => {
    if (monitorTab === 'action') return needsActionRows
    if (monitorTab === 'positions') return unifiedMonitorRows.filter((row) => Number(row.position_qty || 0) > 0)
    if (monitorTab === 'watch') return unifiedMonitorRows.filter((row) => Number(row.position_qty || 0) <= 0)
    return unifiedMonitorRows
  }, [monitorTab, needsActionRows, unifiedMonitorRows])

  const monitorColumns = useMemo(() => ([
    {
      title: '股票',
      key: 'stock',
      width: 170,
      render: (_, record) => (
        <div className="watchlist-stock compact">
          <div className="stock-name">{record.name}</div>
          <div className="stock-code">{record.symbol}</div>
          <Tag className="group-tag" color={record.track_type === 'paper_position' ? 'red' : 'blue'}>
            {record.track_type === 'paper_position' ? '模拟持仓' : '观察验证'}
          </Tag>
        </div>
      ),
    },
    {
      title: '收益率',
      key: 'return',
      width: 120,
      sorter: (a, b) => Number(a.metrics?.current_return_pct || 0) - Number(b.metrics?.current_return_pct || 0),
      render: (_, record) => {
        const value = Number(record.metrics?.current_return_pct || 0)
        return <strong style={{ color: pctColor(value) }}>{value.toFixed(2)}%</strong>
      },
    },
    {
      title: '最大回撤',
      key: 'max_drawdown',
      width: 120,
      sorter: (a, b) => Number(a.metrics?.max_drawdown_pct || 0) - Number(b.metrics?.max_drawdown_pct || 0),
      render: (_, record) => `${Number(record.metrics?.max_drawdown_pct || 0).toFixed(2)}%`,
    },
    {
      title: '成本/现价',
      key: 'price',
      width: 150,
      render: (_, record) => (
        <div className="monitor-price-stack">
          <span>成本 ¥{Number(record.metrics?.entry_price || 0).toFixed(2)}</span>
          <strong>现价 ¥{Number(record.metrics?.current_price || 0).toFixed(2)}</strong>
        </div>
      ),
    },
    {
      title: '持有天数',
      key: 'holding_days',
      width: 95,
      render: (_, record) => `${Number(record.metrics?.holding_days || 0).toFixed(0)}天`,
    },
    {
      title: '资金状态',
      key: 'money_flow_quality',
      width: 120,
      render: (_, record) => {
        const meta = MONEY_FLOW_META[record.money_flow_quality] || MONEY_FLOW_META.unavailable
        return <Tag color={meta.color}>{meta.text}</Tag>
      },
    },
    {
      title: '监控结论',
      key: 'conclusion',
      width: 140,
      render: (_, record) => {
        const meta = MONITOR_META[record.conclusion?.status] || MONITOR_META.waiting_trigger
        return (
          <Tooltip title={record.conclusion?.reason}>
            <Tag color={meta.color}>{record.conclusion?.label || meta.text}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '建议原因',
      key: 'reason',
      render: (_, record) => (
        <div className="monitor-reason">
          <span>{record.conclusion?.reason || '-'}</span>
          <Space size={4} wrap>
            {(record.conclusion?.flags || []).map((flag) => <Tag key={flag}>{flag}</Tag>)}
          </Space>
        </div>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, record) => (
        <Button size="small" ghost icon={<LineChartOutlined />} onClick={() => navigate(`/stock/${record.symbol}`)}>
          分析
        </Button>
      ),
    },
  ]), [navigate])

  const unifiedMonitorColumns = useMemo(() => ([
    {
      title: '股票',
      key: 'stock',
      width: 190,
      render: (_, record) => (
        <div className="watchlist-stock compact">
          <div className="stock-name">{record.name}</div>
          <div className="stock-code">{record.symbol}</div>
          <Space size={4} wrap>
            <Tag color={Number(record.position_qty || 0) > 0 ? 'red' : 'blue'}>
              {Number(record.position_qty || 0) > 0 ? '模拟持仓' : '观察验证'}
            </Tag>
            {record.risk_status && (
              <Tag color={(RISK_META[record.risk_status] || RISK_META.normal).color}>
                {(RISK_META[record.risk_status] || RISK_META.normal).text}
              </Tag>
            )}
          </Space>
        </div>
      ),
    },
    {
      title: '收益 / 回撤',
      key: 'return',
      width: 140,
      sorter: (a, b) => Number(a.monitor_return_pct || 0) - Number(b.monitor_return_pct || 0),
      render: (_, record) => {
        const value = Number(record.monitor_return_pct ?? 0)
        const drawdown = record.monitor_max_drawdown_pct
        return (
          <div className="return-stack">
            <strong style={{ color: pctColor(value) }}>{Number.isFinite(value) ? `${value.toFixed(2)}%` : '-'}</strong>
            <span>回撤 {drawdown !== undefined && drawdown !== null ? `${Number(drawdown).toFixed(2)}%` : '-'}</span>
          </div>
        )
      },
    },
    {
      title: '成本 / 现价',
      key: 'price',
      width: 150,
      render: (_, record) => (
        <div className="monitor-price-stack">
          <span>成本 ¥{Number(record.monitor_entry_price || 0).toFixed(2)}</span>
          <strong>现价 ¥{Number(record.monitor_current_price || 0).toFixed(2)}</strong>
        </div>
      ),
    },
    {
      title: '仓位 / 信号',
      key: 'position_signal',
      width: 170,
      render: (_, record) => {
        const cost = Number(record.position_qty || 0) * Number(record.avg_price || record.monitor_entry_price || 0)
        const weight = portfolioTotalCost > 0 && cost > 0 ? cost / portfolioTotalCost * 100 : null
        const modelMeta = MODEL_ROLE_META[
          record.model_status === 'paper_only' ? 'ml_paper_only_correction' : record.model_version_id ? 'ml_correction' : 'rule_proxy_or_legacy'
        ] || MODEL_ROLE_META.rule_proxy_or_legacy
        return (
          <div className="strategy-signal-cell">
            <Space size={4} wrap>
              {record.position_qty ? <Tag>{Number(record.position_qty).toFixed(0)}股</Tag> : <Tag>未持仓</Tag>}
              {weight !== null && <Tag color={weight >= 25 ? 'red' : weight >= 12 ? 'gold' : 'blue'}>{weight.toFixed(1)}%</Tag>}
            </Space>
            <Space size={4} wrap>
              <Tag color={modelMeta.color}>{modelMeta.text}</Tag>
              <Tag color={record.snapshot_quality === 'complete' ? 'green' : 'default'}>{record.signal_date || '无信号日'}</Tag>
            </Space>
          </div>
        )
      },
    },
    {
      title: '风控计划',
      key: 'risk_plan',
      width: 160,
      render: (_, record) => (
        <div className="risk-plan-stack">
          <span>止损 ¥{Number(record.stop_loss || 0).toFixed(2)}</span>
          <span>止盈 ¥{Number(record.take_profit || 0).toFixed(2)}</span>
          <span>持有 {Number(record.monitor_holding_days || 0).toFixed(0)}天</span>
        </div>
      ),
    },
    {
      title: '今日建议',
      key: 'conclusion',
      render: (_, record) => {
        const meta = MONITOR_META[record.conclusion?.status] || MONITOR_META.waiting_trigger
        const reason = record.conclusion?.reason || record.risk_message || '等待触发条件'
        return (
          <div className="monitor-reason">
            <Space size={4} wrap>
              <Tag color={meta.color}>{record.conclusion?.label || meta.text}</Tag>
              {(record.conclusion?.flags || []).slice(0, 2).map((flag) => <Tag key={flag}>{flag}</Tag>)}
            </Space>
            <span>{reason}</span>
          </div>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_, record) => (
        <Space size={6} wrap>
          <Button size="small" ghost icon={<LineChartOutlined />} onClick={() => navigate(`/stock/${record.symbol}`)}>
            分析
          </Button>
          {record.pick_id && (
            <Button
              danger={Number(record.position_qty || 0) > 0}
              size="small"
              icon={Number(record.position_qty || 0) > 0 ? <MinusCircleOutlined /> : <DeleteOutlined />}
              loading={actionLoading === `${record.pick_id}-${Number(record.position_qty || 0) > 0 ? 'closed' : 'ignored'}`}
              onClick={() => handleRemove(record, Number(record.position_qty || 0) > 0)}
            >
              {Number(record.position_qty || 0) > 0 ? '平仓' : '移除'}
            </Button>
          )}
        </Space>
      ),
    },
  ]), [actionLoading, navigate, portfolioTotalCost])

  const expandedMonitorRow = (record) => {
    const data = (record.path || []).map((item) => ({
      date: item.date,
      value: Number(item.return_pct || 0),
    }))
    return (
      <div className="monitor-expand">
        <div className="monitor-expand-chart">
          {data.length > 1 ? (
            <Line
              data={data}
              xField="date"
              yField="value"
              height={170}
              smooth
              color={pctColor(record.metrics?.current_return_pct)}
              point={false}
              yAxis={{ label: { formatter: (v) => `${Number(v).toFixed(1)}%` } }}
              tooltip={{ formatter: (item) => ({ name: '收益率', value: `${Number(item.value || 0).toFixed(2)}%` }) }}
            />
          ) : (
            <Alert type="info" showIcon message="收益路径样本不足，当前只展示最新标记价格。" />
          )}
        </div>
        <div className="monitor-expand-notes">
          <div><span>入选评分</span><strong>{record.score !== undefined && record.score !== null ? Number(record.score).toFixed(1) : '-'}</strong></div>
          <div><span>上涨概率</span><strong>{record.up_prob !== undefined && record.up_prob !== null ? `${(Number(record.up_prob) * 100).toFixed(1)}%` : '-'}</strong></div>
          <div><span>回撤概率</span><strong>{record.dd_prob !== undefined && record.dd_prob !== null ? `${(Number(record.dd_prob) * 100).toFixed(1)}%` : '-'}</strong></div>
          <div><span>数据质量</span><strong>{record.data_quality?.history || '-'}</strong></div>
        </div>
      </div>
    )
  }

  return (
    <div className="watchlist-container">
      <div className="watchlist-header">
        <h1 className="page-title">
          <StarFilled style={{ color: 'var(--warning-color)' }} /> 监控复盘
        </h1>
        <Space>
          <Button icon={<ThunderboltOutlined />} loading={reviewRunning} onClick={runDailyReview}>
            生成收盘复盘
          </Button>
          <Button type="primary" icon={<ReloadOutlined />} loading={loading} onClick={loadWatchlist}>
            刷新
          </Button>
        </Space>
      </div>

      {error && <Alert type="error" showIcon style={{ marginBottom: 16 }} message={error} />}

      <Card className="monitor-hero-card" variant="borderless" loading={loading && !monitorOverview}>
        <Row gutter={[20, 20]} align="middle">
          <Col xs={24} xl={9}>
            <div className="section-eyebrow">
              <AuditOutlined /> Daily Monitor
            </div>
            <h2>{feedbackSummary.headline || monitorSummary.headline || '等待已选股票形成监控样本'}</h2>
            <p>
              {feedbackSummary.diagnostic_note || '系统会按日跟踪模拟持仓和观察池，把收益路径、回撤、止盈止损和错过机会转成策略反馈。'}
            </p>
            <Space wrap>
              <Tag color={monitorSummary.review_status === 'tracking' ? 'green' : 'gold'}>
                {monitorSummary.review_status === 'tracking' ? '样本跟踪中' : '样本待积累'}
              </Tag>
              {monitorOverview?.latest_report?.report_date && (
                <Tag color={monitorOverview.latest_report.is_current === false ? 'orange' : 'default'}>
                  {monitorOverview.latest_report.is_current === false ? '复盘待更新' : '最新复盘'} {monitorOverview.latest_report.report_date}
                </Tag>
              )}
            </Space>
          </Col>
          <Col xs={24} xl={5}>
            <div className="health-meter">
              <Progress
                type="dashboard"
                percent={Number(monitorSummary.strategy_health_score || feedbackSummary.strategy_health_score || 0)}
                strokeColor={{ '0%': '#22c55e', '60%': '#f59e0b', '100%': '#ef4444' }}
                format={(v) => `${Number(v || 0).toFixed(0)}`}
              />
              <span>策略健康度</span>
            </div>
          </Col>
          <Col xs={24} xl={10}>
            <div className="monitor-kpi-grid">
              <div>
                <span>组合浮盈亏</span>
                <strong style={{ color: pctColor(monitorSummary.total_unrealized_pnl_pct) }}>
                  {Number(monitorSummary.total_unrealized_pnl_pct || 0).toFixed(2)}%
                </strong>
              </div>
              <div>
                <span>最大回撤</span>
                <strong>{Number(monitorSummary.max_drawdown_pct || feedbackSummary.max_drawdown_pct || 0).toFixed(2)}%</strong>
              </div>
              <div>
                <span>风险提醒</span>
                <strong>{monitorSummary.risk_flag_count || feedbackSummary.risk_flag_count || 0}</strong>
              </div>
              <div>
                <span>错过机会</span>
                <strong>{monitorSummary.missed_opportunity_count || feedbackSummary.missed_opportunity_count || 0}</strong>
              </div>
            </div>
          </Col>
        </Row>
      </Card>

      <Card className="action-list-card" variant="borderless" loading={loading && !monitorOverview}>
        <div className="action-list-head">
          <div>
            <div className="section-eyebrow">
              <ThunderboltOutlined /> Today Actions
            </div>
            <h2>今日待处理</h2>
            <p>只把需要处理的票放在这里：止盈、止损、风险复核、验证失败或明显错过机会。</p>
          </div>
          <Space wrap>
            <Tag color={needsActionRows.length ? 'orange' : 'green'}>
              {needsActionRows.length ? `${needsActionRows.length} 只需处理` : '暂无强制动作'}
            </Tag>
            <Tag>模拟持仓 {portfolio?.summary?.position_count || 0} 只</Tag>
            <Tag>观察池 {Math.max(0, unifiedMonitorRows.length - Number(portfolio?.summary?.position_count || 0))} 只</Tag>
          </Space>
        </div>
        {needsActionRows.length ? (
          <div className="action-item-grid">
            {needsActionRows.slice(0, 6).map((item) => {
              const meta = MONITOR_META[item.conclusion?.status] || MONITOR_META.waiting_trigger
              return (
                <div className="action-item" key={`${item.symbol}-${item.track_type || item.action_type}`}>
                  <div>
                    <strong>{item.name}</strong>
                    <span>{item.symbol}</span>
                  </div>
                  <Tag color={meta.color}>{item.conclusion?.label || meta.text}</Tag>
                  <p>{item.conclusion?.reason || item.risk_message || '等待复核'}</p>
                  <Space size={6}>
                    <Button size="small" ghost onClick={() => navigate(`/stock/${item.symbol}`)}>分析</Button>
                    {item.pick_id && Number(item.position_qty || 0) > 0 && (
                      <Button
                        size="small"
                        danger
                        loading={actionLoading === `${item.pick_id}-closed`}
                        onClick={() => handleRemove(item, true)}
                      >
                        平仓
                      </Button>
                    )}
                  </Space>
                </div>
              )
            })}
          </div>
        ) : (
          <Alert type="success" showIcon message="当前没有必须处理的样本" description="可以继续观察持仓路径，等待止盈、止损或资金/回撤信号触发。" />
        )}
      </Card>

      <Card className="watchlist-card unified-monitor-card" variant="borderless">
        <div className="unified-monitor-head">
          <div>
            <div className="section-eyebrow">
              <LineChartOutlined /> Portfolio Monitor
            </div>
            <h2>持仓与观察监控</h2>
            <p>合并模拟持仓、观察验证和每日跟踪，每只股票只出现一次。</p>
          </div>
          <Tabs
            activeKey={monitorTab}
            onChange={setMonitorTab}
            items={[
              { key: 'all', label: `全部 ${unifiedMonitorRows.length}` },
              { key: 'action', label: `需处理 ${needsActionRows.length}` },
              { key: 'positions', label: `模拟持仓 ${portfolio?.summary?.position_count || 0}` },
              { key: 'watch', label: '观察池' },
            ]}
          />
        </div>
        <Table
          columns={unifiedMonitorColumns}
          dataSource={filteredMonitorRows}
          rowKey={(row) => `${row.symbol}-${row.pick_id || row.track_type || row.action_type}`}
          loading={loading}
          pagination={{ pageSize: 14 }}
          expandable={{ expandedRowRender: expandedMonitorRow }}
          scroll={{ x: 1260 }}
        />
      </Card>

      <Collapse
        className="diagnostic-collapse"
        bordered={false}
        items={[
          {
            key: 'review',
            label: '复盘与策略诊断',
            children: (
              <div className="diagnostic-content">
                <div className="review-card-main compact">
                  <div>
                    <div className="section-eyebrow">
                      <AuditOutlined /> Review Summary
                    </div>
                    <h2>复盘摘要</h2>
                    <p>{feedbackSummary.headline || review?.summary || '正在读取模拟交易反馈。'}</p>
                    <Space wrap>
                      {(feedbackSuggestions.length ? feedbackSuggestions : (review?.warnings || [])).slice(0, 4).map((item) => (
                        <Tag color={item.priority === 'high' ? 'red' : item.priority === 'medium' ? 'gold' : 'cyan'} key={item.id || item}>
                          {item.title || item}
                        </Tag>
                      ))}
                    </Space>
                  </div>
                  <div className="review-metrics compact">
                    <div><span>监控样本</span><strong>{feedbackSummary.tracked_count ?? reviewMetrics.reviewed_position_count ?? 0}</strong></div>
                    <div><span>持仓胜率</span><strong>{((feedbackSummary.open_win_rate ?? reviewMetrics.open_win_rate ?? 0) * 100).toFixed(1)}%</strong></div>
                    <div><span>平均收益</span><strong className={Number(feedbackSummary.avg_return_pct ?? reviewMetrics.avg_unrealized_pnl_pct ?? 0) >= 0 ? 'metric-up' : 'metric-down'}>{Number(feedbackSummary.avg_return_pct ?? reviewMetrics.avg_unrealized_pnl_pct ?? 0).toFixed(2)}%</strong></div>
                    <div><span>最大回撤</span><strong>{Number(feedbackSummary.max_drawdown_pct || 0).toFixed(2)}%</strong></div>
                    <div><span>风险提醒</span><strong>{feedbackSummary.risk_flag_count ?? reviewMetrics.risk_flag_count ?? 0}</strong></div>
                  </div>
                </div>

                <div className="diagnostic-split">
                  <div className="diagnostic-panel">
                    <h3>收益归因</h3>
                    <div className="compact-kpi-row">
                      <div><span>组合浮盈</span><strong style={{ color: pctColor(performanceSummary.portfolio_return_pct) }}>{formatMaybePct(performanceSummary.portfolio_return_pct)}</strong></div>
                      <div><span>当前策略</span><strong style={{ color: pctColor(currentStrategyReturn.capital_weighted_return_pct) }}>{formatMaybePct(currentStrategyReturn.capital_weighted_return_pct)}</strong></div>
                      <div><span>旧仓/缺快照</span><strong style={{ color: pctColor(legacyPositionReturn.capital_weighted_return_pct) }}>{formatMaybePct(legacyPositionReturn.capital_weighted_return_pct)}</strong></div>
                    </div>
                    {(lowReturnDiagnosis.issues || []).slice(0, 3).map((item) => (
                      <Alert
                        key={item.code}
                        type={item.severity === 'high' ? 'warning' : 'info'}
                        showIcon
                        message={`${item.label}：${item.evidence || ''}`}
                        description={item.suggestion}
                      />
                    ))}
                    <Table
                      className="strategy-breakdown-table"
                      size="small"
                      columns={strategyBreakdownColumns}
                      dataSource={strategyVersionBreakdown}
                      rowKey={(row) => row.key}
                      pagination={false}
                      locale={{ emptyText: '暂无策略版本拆分样本' }}
                    />
                  </div>
                  <div className="diagnostic-panel">
                    <h3>反馈池</h3>
                    {topFailureReasons.length > 0 && (
                      <Alert
                        className="learning-alert"
                        type="warning"
                        showIcon
                        message="近期反馈已经进入推荐闸门"
                        description={topFailureReasons.slice(0, 3).map((item) => item.label || item.attribution || item.code).join('；')}
                      />
                    )}
                    <Table
                      size="small"
                      columns={attributionColumns}
                      dataSource={attributionSummary.slice(0, 6)}
                      rowKey={(row) => row.code}
                      pagination={false}
                      locale={{ emptyText: '暂无归因样本' }}
                    />
                  </div>
                </div>

                {review?.items?.length > 0 && (
                  <Table
                    className="review-table"
                    size="small"
                    columns={reviewColumns}
                    dataSource={review.items}
                    rowKey={(row) => `${row.symbol}-${row.verdict}`}
                    pagination={false}
                    loading={loading}
                  />
                )}
              </div>
            ),
          },
          {
            key: 'model',
            label: '模型校准与推荐调整',
            children: (
              <div className="diagnostic-split">
                <div className="diagnostic-panel">
                  <h3>概率校准池</h3>
                  <p>{probabilityCalibration.message || '等待模拟平仓闭环样本。'}</p>
                  <Table
                    size="small"
                    columns={calibrationColumns}
                    dataSource={(probabilityCalibration.buckets || []).slice(0, 5)}
                    rowKey={(row) => row.label}
                    pagination={false}
                  />
                </div>
                <div className="diagnostic-panel adjustment-panel">
                  <h3>下一次推荐调整</h3>
                  <Space wrap>
                    <Tag color={probabilityCalibration.calibrated ? 'green' : 'gold'}>
                      {probabilityCalibration.label || '模拟闭环样本不足'}
                    </Tag>
                    <Tag color={retrainReadiness.ready ? 'green' : 'blue'}>
                      {retrainReadiness.ready
                        ? '反馈样本可重训'
                        : `重训样本 ${Number(retrainReadiness.eligible_feedback_sample_count || 0)}/${Number(retrainReadiness.min_feedback_samples || 50)}`}
                    </Tag>
                  </Space>
                  {(strategyAdjustments.length ? strategyAdjustments : []).slice(0, 5).map((item) => (
                    <div className="adjustment-item" key={item.id || item.action}>
                      <Tag color={item.priority === 'high' ? 'red' : item.priority === 'medium' ? 'gold' : 'blue'}>
                        {item.priority || 'review'}
                      </Tag>
                      <strong>{item.action || item.title}</strong>
                      <span>{item.reason}</span>
                    </div>
                  ))}
                  {!strategyAdjustments.length && (
                    <Alert type="info" showIcon message="暂无触发调整" description="当前反馈样本还不足以改变推荐闸门。" />
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'trades',
            label: '模拟交易流水',
            children: (
              <Table
                columns={tradeColumns}
                dataSource={trades}
                rowKey={(row) => row.trade_id}
                loading={loading}
                pagination={{ pageSize: 10 }}
              />
            ),
          },
        ]}
      />
    </div>
  )
}

export default Watchlist
