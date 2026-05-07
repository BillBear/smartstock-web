import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Row, Space, Statistic, Table, Tag, Tooltip, message } from 'antd'
import {
  AuditOutlined,
  DeleteOutlined,
  LineChartOutlined,
  MinusCircleOutlined,
  ReloadOutlined,
  StarFilled,
} from '@ant-design/icons'
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

const Watchlist = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [actionLoading, setActionLoading] = useState('')
  const [rows, setRows] = useState([])
  const [portfolio, setPortfolio] = useState(null)
  const [trades, setTrades] = useState([])
  const [review, setReview] = useState(null)

  const loadWatchlist = async () => {
    setLoading(true)
    setError('')
    try {
      const [watchlistData, tradeData, reviewData] = await Promise.all([
        coachApi.getWatchlist({ user_id: 'default' }),
        coachApi.getPaperTrades({ user_id: 'default', limit: 50 }),
        coachApi.getPaperReview({ user_id: 'default' }),
      ])
      setRows(watchlistData?.items || [])
      setPortfolio({ summary: watchlistData?.portfolio_summary || {} })
      setTrades(tradeData?.items || [])
      setReview(reviewData || null)
    } catch (err) {
      console.error('加载自选池失败', err)
      setError(err?.response?.data?.message || err?.message || '加载失败')
      setRows([])
      setPortfolio(null)
      setTrades([])
      setReview(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadWatchlist()
  }, [])

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

  return (
    <div className="watchlist-container">
      <div className="watchlist-header">
        <h1 className="page-title">
          <StarFilled style={{ color: '#faad14' }} /> 我的自选股
        </h1>
        <Button type="primary" icon={<ReloadOutlined />} loading={loading} onClick={loadWatchlist}>
          刷新
        </Button>
      </div>

      {error && <Alert type="error" showIcon style={{ marginBottom: 16 }} message={error} />}

      <Card className="review-card" variant="borderless">
        <div className="review-card-main">
          <div>
            <div className="section-eyebrow">
              <AuditOutlined /> 模拟复盘摘要
            </div>
            <h2>用真实模拟反馈校验智能选股</h2>
            <p>{review?.summary || '正在读取模拟交易反馈。'}</p>
            <Space wrap>
              {(review?.warnings || []).map((text) => (
                <Tag color="gold" key={text}>{text}</Tag>
              ))}
            </Space>
          </div>
          <div className="review-metrics">
            <div>
              <span>复盘样本</span>
              <strong>{reviewMetrics.reviewed_position_count || 0}</strong>
            </div>
            <div>
              <span>持仓胜率</span>
              <strong>{((reviewMetrics.open_win_rate || 0) * 100).toFixed(1)}%</strong>
            </div>
            <div>
              <span>平均浮盈亏</span>
              <strong className={Number(reviewMetrics.avg_unrealized_pnl_pct || 0) >= 0 ? 'metric-up' : 'metric-down'}>
                {Number(reviewMetrics.avg_unrealized_pnl_pct || 0).toFixed(2)}%
              </strong>
            </div>
            <div>
              <span>快照覆盖</span>
              <strong>{((reviewMetrics.snapshot_coverage || 0) * 100).toFixed(0)}%</strong>
            </div>
            <div>
              <span>风险提醒</span>
              <strong>{reviewMetrics.risk_flag_count || 0}</strong>
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
