import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Progress, Row, Space, Statistic, Table, Tag, Tooltip, message } from 'antd'
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

const pctColor = (value) => (Number(value || 0) >= 0 ? '#ff5a5f' : '#22c55e')

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
  const [reviewRunning, setReviewRunning] = useState(false)

  const loadWatchlist = async () => {
    setLoading(true)
    setError('')
    try {
      const [watchlistData, tradeData, reviewData, overviewData, positionsData, feedbackData] = await Promise.all([
        coachApi.getWatchlist({ user_id: 'default' }),
        coachApi.getPaperTrades({ user_id: 'default', limit: 50 }),
        coachApi.getPaperReview({ user_id: 'default' }),
        coachApi.getMonitorOverview({ user_id: 'default' }),
        coachApi.getMonitorPositions({ user_id: 'default' }),
        coachApi.getMonitorFeedback({ user_id: 'default' }),
      ])
      setRows(watchlistData?.items || [])
      setPortfolio({ summary: watchlistData?.portfolio_summary || {} })
      setTrades(tradeData?.items || [])
      setReview(reviewData || null)
      setMonitorOverview(overviewData || null)
      setMonitorPositions(positionsData?.items || [])
      setMonitorFeedback(feedbackData || null)
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
      title: '现价',
      key: 'current_price',
      render: (_, record) => (record.current_price ? `¥${Number(record.current_price).toFixed(2)}` : '-'),
    },
    {
      title: '浮盈亏',
      key: 'unrealized_pnl',
      render: (_, record) => {
        if (record.unrealized_pnl === undefined || record.unrealized_pnl === null) return '-'
        const color = Number(record.unrealized_pnl) >= 0 ? '#ff4d4f' : '#52c41a'
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
  ]), [actionLoading, navigate])

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
          <span style={{ color: pnl >= 0 ? '#ff4d4f' : '#52c41a' }}>
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

  const reviewMetrics = review?.metrics || {}
  const monitorSummary = monitorOverview?.summary || {}
  const feedbackSummary = monitorFeedback?.summary || {}
  const feedbackSuggestions = monitorFeedback?.suggestions || []

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
          <StarFilled style={{ color: '#faad14' }} /> 监控复盘
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
              {monitorOverview?.latest_report?.report_date && <Tag>最新复盘 {monitorOverview.latest_report.report_date}</Tag>}
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

      <Card className="watchlist-card monitor-table-card" variant="borderless" title="逐票监控">
        <Table
          columns={monitorColumns}
          dataSource={monitorPositions}
          rowKey={(row) => `${row.symbol}-${row.track_type}`}
          loading={loading}
          pagination={{ pageSize: 10 }}
          expandable={{ expandedRowRender: expandedMonitorRow }}
          scroll={{ x: 1160 }}
        />
      </Card>

      <Card className="review-card" variant="borderless">
        <div className="review-card-main">
          <div>
            <div className="section-eyebrow">
              <AuditOutlined /> 模拟复盘摘要
            </div>
            <h2>策略反馈与参数建议</h2>
            <p>{feedbackSummary.headline || review?.summary || '正在读取模拟交易反馈。'}</p>
            <Space wrap>
              {(feedbackSuggestions.length ? feedbackSuggestions : (review?.warnings || [])).slice(0, 4).map((item) => (
                <Tag color={item.priority === 'high' ? 'red' : item.priority === 'medium' ? 'gold' : 'cyan'} key={item.id || item}>
                  {item.title || item}
                </Tag>
              ))}
            </Space>
          </div>
          <div className="review-metrics">
            <div>
              <span>监控样本</span>
              <strong>{feedbackSummary.tracked_count ?? reviewMetrics.reviewed_position_count ?? 0}</strong>
            </div>
            <div>
              <span>持仓胜率</span>
              <strong>{((feedbackSummary.open_win_rate ?? reviewMetrics.open_win_rate ?? 0) * 100).toFixed(1)}%</strong>
            </div>
            <div>
              <span>平均收益</span>
              <strong className={Number(feedbackSummary.avg_return_pct ?? reviewMetrics.avg_unrealized_pnl_pct ?? 0) >= 0 ? 'metric-up' : 'metric-down'}>
                {Number(feedbackSummary.avg_return_pct ?? reviewMetrics.avg_unrealized_pnl_pct ?? 0).toFixed(2)}%
              </strong>
            </div>
            <div>
              <span>最大回撤</span>
              <strong>{Number(feedbackSummary.max_drawdown_pct || 0).toFixed(2)}%</strong>
            </div>
            <div>
              <span>风险提醒</span>
              <strong>{feedbackSummary.risk_flag_count ?? reviewMetrics.risk_flag_count ?? 0}</strong>
            </div>
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
      </Card>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic title="观察+持仓总数" value={rows.length} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic title="模拟持仓数" value={portfolio?.summary?.position_count || 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic title="持仓总市值" value={portfolio?.summary?.total_market_value || 0} precision={2} prefix="¥" />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic
              title="浮动盈亏"
              value={portfolio?.summary?.total_unrealized_pnl || 0}
              precision={2}
              valueStyle={{ color: Number(portfolio?.summary?.total_unrealized_pnl || 0) >= 0 ? '#ff4d4f' : '#52c41a' }}
              suffix={`(${Number(portfolio?.summary?.total_unrealized_pnl_pct || 0).toFixed(2)}%)`}
            />
          </Card>
        </Col>
      </Row>

      <Card className="watchlist-card" variant="borderless">
        <Table
          columns={columns}
          dataSource={rows}
          rowKey={(row) => `${row.pick_id}-${row.action_type}`}
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Card className="watchlist-card" variant="borderless" style={{ marginTop: 16 }} title="模拟交易流水">
        <Table
          columns={tradeColumns}
          dataSource={trades}
          rowKey={(row) => row.trade_id}
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  )
}

export default Watchlist
