import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Input, Pagination, Progress, Row, Select, Space, Spin, Statistic, Table, Tag } from 'antd'
import { BookOutlined, CheckCircleOutlined, ReloadOutlined, ThunderboltOutlined, FireOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { coachApi } from '../services/api'
import MarketFactorExplain from '../components/MarketFactorExplain'
import './Dashboard.css'

const TAG_META = {
  offensive: { text: '进攻', color: 'red' },
  neutral: { text: '均衡', color: 'gold' },
  defensive: { text: '防守', color: 'green' },
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

const Dashboard = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [newsLoading, setNewsLoading] = useState(false)
  const [error, setError] = useState('')
  const [marketState, setMarketState] = useState(null)
  const [previewPicks, setPreviewPicks] = useState([])
  const [weeklyLesson, setWeeklyLesson] = useState(null)
  const [paperReview, setPaperReview] = useState(null)
  const [monitorFeedback, setMonitorFeedback] = useState(null)
  const [latestModel, setLatestModel] = useState(null)
  const [newsList, setNewsList] = useState([])
  const [newsPage, setNewsPage] = useState(1)
  const [newsHasNext, setNewsHasNext] = useState(false)
  const [newsKeyword, setNewsKeyword] = useState('')
  const [newsLevel, setNewsLevel] = useState('')
  const [newsSource, setNewsSource] = useState('')
  const [loadedAt, setLoadedAt] = useState('')

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [state, lesson, review, feedback, model] = await Promise.all([
        coachApi.getMarketStateToday(),
        coachApi.getWeeklyLessonLatest(),
        coachApi.getPaperReview({ user_id: 'default' }),
        coachApi.getMonitorFeedback({ user_id: 'default' }),
        coachApi.getLatestModel(),
      ])
      setMarketState(state)
      setWeeklyLesson(lesson)
      setPaperReview(review)
      setMonitorFeedback(feedback)
      setLatestModel(model)
      setPreviewPicks([])
      setLoadedAt(new Date().toLocaleString('zh-CN'))
    } catch (err) {
      console.error('加载市场全景失败', err)
      setError(err?.response?.data?.message || err?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadNews = async (page = newsPage, filters = {}) => {
    setNewsLoading(true)
    try {
      const data = await coachApi.getNewsEvents({
        page,
        page_size: 10,
        keyword: (filters.keyword ?? newsKeyword) || undefined,
        event_level: (filters.event_level ?? newsLevel) || undefined,
        source: (filters.source ?? newsSource) || undefined,
      })
      setNewsList(data?.items || [])
      setNewsPage(data?.page || page)
      setNewsHasNext(Boolean(data?.has_next))
    } catch (err) {
      console.error('加载资讯列表失败', err)
    } finally {
      setNewsLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    loadNews(1)
  }, [])

  const driverRows = useMemo(() => {
    if (!marketState?.drivers) return []
    const map = marketState.drivers
    return [
      { key: 'trend_score', name: '趋势', value: map.trend_score },
      { key: 'breadth_score', name: '宽度', value: map.breadth_score },
      { key: 'money_flow_score', name: '资金', value: map.money_flow_score },
      { key: 'risk_score', name: '风险调整', value: map.risk_score },
      { key: 'news_score', name: '资讯温度', value: map.news_score },
    ]
  }, [marketState])

  const driverColumns = [
    {
      title: '维度',
      dataIndex: 'name',
      key: 'name',
      render: (name) => <span style={{ fontWeight: 600 }}>{name}</span>,
    },
    {
      title: '得分',
      dataIndex: 'value',
      key: 'value',
      render: (value) => (
        <Progress
          percent={Number(value || 0)}
          size="small"
          strokeColor={value >= 65 ? '#D95F59' : value >= 45 ? '#D7A84A' : '#27C08A'}
        />
      ),
    },
  ]

  const pickColumns = [
    {
      title: '股票',
      key: 'stock',
      render: (_, row) => (
        <div>
          <div style={{ fontWeight: 600 }}>{row.name}</div>
          <div style={{ color: '#9AA0A6', fontSize: 12 }}>{row.symbol}</div>
        </div>
      ),
    },
    {
      title: '动作',
      dataIndex: 'action',
      key: 'action',
      render: (action) => {
        const color = action === 'buy' ? 'red' : 'blue'
        return <Tag color={color}>{action === 'buy' ? '可买入' : '观察'}</Tag>
      },
    },
    {
      title: '上涨概率',
      dataIndex: 'up_prob',
      key: 'up_prob',
      render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
    },
    {
      title: '回撤概率',
      dataIndex: 'dd_prob',
      key: 'dd_prob',
      render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
    },
  ]

  const stateMeta = TAG_META[marketState?.state_tag] || TAG_META.neutral
  const newsEvents = newsList
  const sourceCounts = marketState?.news_context?.source_counts || {}
  const reviewMetrics = paperReview?.metrics || {}
  const feedbackSummary = monitorFeedback?.summary || {}
  const feedbackReasons = monitorFeedback?.failure_reasons || []
  const strategyAdjustments = monitorFeedback?.strategy_adjustments || []
  const modelStatus = latestModel?.available ? latestModel.status : 'unavailable'
  const systemBetterStatus = feedbackSummary.review_status === 'tracking' && Number(feedbackSummary.strategy_health_score || 0) >= 60
    ? '改善中'
    : feedbackSummary.review_status === 'insufficient_sample'
      ? '样本不足'
      : '需收紧'
  const coachAction = marketState?.state_tag === 'defensive'
    ? '先防守复盘，暂停追高'
    : reviewMetrics.reviewed_position_count < 10
      ? '先模拟验证，别急实盘'
      : '按交易计划小步执行'

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="page-title">
          <FireOutlined /> 市场全景
        </h1>
        <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
          刷新
        </Button>
      </div>

      {error && <Alert type="error" showIcon style={{ marginBottom: 16 }} message={error} />}

      {loading ? (
        <Card variant="borderless" className="sentiment-card">
          <Spin tip="加载市场状态中...">
            <div style={{ minHeight: 96 }} />
          </Spin>
        </Card>
      ) : (
        <>
          <Card variant="borderless" className="coach-workbench-card">
            <Row gutter={[18, 18]} align="middle">
              <Col xs={24} xl={9}>
                <div className="coach-eyebrow">
                  <BookOutlined /> 新手投资教练
                </div>
                <h2>{coachAction}</h2>
                <p>{paperReview?.summary || '先把选股、模拟买入和复盘连起来，不要只看单次推荐分数。'}</p>
                <Space wrap>
                  <Button type="primary" onClick={() => navigate('/smart-screen')}>查看今日选股</Button>
                  <Button onClick={() => navigate('/watchlist')}>复盘模拟持仓</Button>
                  <Button onClick={() => navigate('/backtest')}>验证策略回测</Button>
                </Space>
              </Col>
              <Col xs={24} xl={9}>
                <div className="coach-steps">
                  {[
                    ['1', '先看市场状态', marketState?.summary || '市场状态未知'],
                    ['2', '只执行 A/B 级计划', '未通过实盘准入前，只允许模拟买入。'],
                    ['3', '用复盘淘汰策略', `当前模拟胜率 ${(Number(reviewMetrics.open_win_rate || 0) * 100).toFixed(1)}%，样本 ${reviewMetrics.reviewed_position_count || 0} 笔。`],
                  ].map(([idx, title, text]) => (
                    <div className="coach-step" key={idx}>
                      <span>{idx}</span>
                      <div>
                        <strong>{title}</strong>
                        <p>{text}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </Col>
              <Col xs={24} xl={6}>
                <div className="lesson-card">
                  <div className="lesson-title">
                    <CheckCircleOutlined /> 本周训练重点
                  </div>
                  {(weeklyLesson?.highlights || []).slice(0, 3).map((item) => (
                    <Tag key={item} color="cyan">{item}</Tag>
                  ))}
                  <div className="lesson-mistakes">要避免：{(weeklyLesson?.mistakes || []).slice(0, 2).join('；') || '暂无'}</div>
                </div>
              </Col>
            </Row>
          </Card>

          <Card variant="borderless" className="sentiment-card">
            <Row gutter={24} align="middle">
              <Col xs={24} md={16}>
                <div className="sentiment-label">市场状态评分</div>
                <Progress
                  percent={Number(marketState?.state_score || 0)}
                  strokeColor={{ '0%': '#27C08A', '50%': '#D7A84A', '100%': '#D95F59' }}
                />
                <div style={{ marginTop: 10, color: '#d9d9d9' }}>{marketState?.summary || '-'}</div>
              </Col>
              <Col xs={24} md={8}>
                <div className="sentiment-status">
                  <Tag color={stateMeta.color} style={{ fontSize: 16, padding: '6px 14px' }}>
                    {stateMeta.text}
                  </Tag>
                  <div style={{ marginTop: 10, color: '#d9d9d9' }}>
                    建议仓位 {marketState?.suggested_exposure_min_pct || 0}% - {marketState?.suggested_exposure_max_pct || 0}%
                  </div>
                  <div style={{ marginTop: 6, color: '#9AA0A6' }}>
                    置信度: {marketState?.state_confidence || '-'}
                  </div>
                </div>
              </Col>
            </Row>
          </Card>

          <Card className="statistics-card" variant="borderless" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              <Col xs={12} sm={6}>
                <Statistic title="趋势评分" value={marketState?.drivers?.trend_score || 0} precision={1} />
              </Col>
              <Col xs={12} sm={6}>
                <Statistic title="宽度评分" value={marketState?.drivers?.breadth_score || 0} precision={1} />
              </Col>
              <Col xs={12} sm={6}>
                <Statistic title="资金评分" value={marketState?.drivers?.money_flow_score || 0} precision={1} />
              </Col>
              <Col xs={12} sm={6}>
                <Statistic title="风险评分" value={marketState?.drivers?.risk_score || 0} precision={1} />
              </Col>
              <Col xs={12} sm={6}>
                <Statistic title="资讯评分" value={marketState?.drivers?.news_score || 0} precision={1} />
              </Col>
            </Row>
          </Card>

          <Card className="statistics-card" variant="borderless" style={{ marginBottom: 16 }}>
            <div className="system-status-title">本周系统状态</div>
            <Row gutter={[16, 16]}>
              <Col xs={12} md={6}>
                <Statistic title="系统是否变好" value={systemBetterStatus} />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="策略健康分" value={Number(feedbackSummary.strategy_health_score || 0)} precision={1} />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="风险样本" value={Number(feedbackSummary.risk_flag_count || 0)} suffix="个" />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="模型状态" value={modelStatus === 'live_ready' ? '可准入' : modelStatus === 'paper_only' ? '仅模拟' : '未训练'} />
              </Col>
            </Row>
            <Space wrap style={{ marginTop: 12 }}>
              <Tag color={feedbackReasons.length ? 'orange' : 'green'}>
                归因 {feedbackReasons.length}
              </Tag>
              <Tag color={strategyAdjustments.length ? 'gold' : 'blue'}>
                策略调整 {strategyAdjustments.length}
              </Tag>
              {latestModel?.model_id && <Tag color="cyan">{latestModel.model_id}</Tag>}
            </Space>
          </Card>

          <MarketFactorExplain
            drivers={marketState?.drivers}
            loadedAt={loadedAt}
            mode="dashboard"
          />

          <Row gutter={16}>
            <Col xs={24} lg={12}>
              <Card className="data-table-card" title="状态驱动因子" variant="borderless">
                <Table pagination={false} columns={driverColumns} dataSource={driverRows} rowKey="key" />
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card className="data-table-card" title="今日推荐预览" variant="borderless">
                <Alert
                  type="info"
                  showIcon
                  message="市场全景已改为轻量加载"
                  description="推荐列表请进入智能选股页查看，避免市场全景首屏等待完整选股计算。"
                />
              </Card>
            </Col>
          </Row>

          <Card className="ai-insight-card" variant="borderless" style={{ marginTop: 16 }}>
            <h3>
              <ThunderboltOutlined /> 交易提示
            </h3>
            <div className="ai-insight-content">
              <p>{marketState?.summary || '暂无结论'}</p>
              <div className="insight-tips">
                {(marketState?.reasons || []).map((text) => (
                  <Tag key={text} color="blue">
                    {text}
                  </Tag>
                ))}
              </div>
            </div>
          </Card>

          <Card className="ai-insight-card" variant="borderless" style={{ marginTop: 16 }}>
            <h3>官方资讯脉冲</h3>
            <div className="news-toolbar">
              <Input.Search
                allowClear
                placeholder="搜索政策、公司、关键词"
                onSearch={(value) => {
                  setNewsKeyword(value)
                  loadNews(1, { keyword: value })
                }}
                style={{ maxWidth: 280 }}
              />
              <Select
                value={newsLevel}
                onChange={(value) => {
                  setNewsLevel(value)
                  loadNews(1, { event_level: value })
                }}
                style={{ width: 120 }}
              >
                <Select.Option value="">全部层级</Select.Option>
                <Select.Option value="macro">宏观</Select.Option>
                <Select.Option value="industry">行业</Select.Option>
                <Select.Option value="stock">个股</Select.Option>
              </Select>
              <Select
                value={newsSource}
                onChange={(value) => {
                  setNewsSource(value)
                  loadNews(1, { source: value })
                }}
                style={{ width: 130 }}
              >
                <Select.Option value="">全部来源</Select.Option>
                {Object.entries(NEWS_SOURCE_META).map(([key, meta]) => (
                  <Select.Option key={key} value={key}>{meta.label}</Select.Option>
                ))}
              </Select>
              <Button onClick={() => loadNews(1)} loading={newsLoading}>刷新资讯</Button>
            </div>
            <Row gutter={[16, 16]}>
              <Col xs={24} xl={8}>
                <div className="news-matrix">
                  <div className="news-matrix-item">
                    <span className="news-matrix-label">资讯温度</span>
                    <strong>{Number(marketState?.news_context?.policy_score || 50).toFixed(1)}</strong>
                  </div>
                  <div className="news-matrix-item">
                    <span className="news-matrix-label">更新时间</span>
                    <strong>{marketState?.news_context?.updated_at || '-'}</strong>
                  </div>
                  <div className="news-matrix-item">
                    <span className="news-matrix-label">风险偏向</span>
                    <strong>{marketState?.news_context?.risk_bias === 'positive' ? '偏正面' : marketState?.news_context?.risk_bias === 'negative' ? '偏负面' : '中性'}</strong>
                  </div>
                </div>

                <div className="news-source-grid">
                  {Object.entries(sourceCounts).map(([source, count]) => {
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
                <div className="news-event-list">
                  <Spin spinning={newsLoading}>
                  {newsEvents.length === 0 && !newsLoading ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={newsKeyword ? `未找到与“${newsKeyword}”相关的官方资讯` : '暂无官方资讯'}
                    />
                  ) : newsEvents.map((item) => {
                    const sourceMeta = NEWS_SOURCE_META[item.source] || { label: item.source?.toUpperCase() || '资讯', color: 'default' }
                    const levelMeta = EVENT_LEVEL_META[item.event_level] || { label: item.event_level || '事件', color: 'default' }
                    return (
                      <div className="news-event-row" key={`${item.source}-${item.title}`}>
                        <div className="news-event-tags">
                          <Tag color={sourceMeta.color}>{sourceMeta.label}</Tag>
                          <Tag color={levelMeta.color}>{levelMeta.label}</Tag>
                          <Tag color={item.direction === 'positive' ? 'green' : item.direction === 'negative' ? 'red' : 'blue'}>
                            {item.direction === 'positive' ? '偏利多' : item.direction === 'negative' ? '偏利空' : '中性'}
                          </Tag>
                        </div>
                        <div className="news-event-title">
                          {item.url ? (
                            <a href={item.url} target="_blank" rel="noreferrer">
                              {item.title}
                            </a>
                          ) : item.title}
                        </div>
                        <div className="news-event-time">{item.publish_time || '-'}</div>
                      </div>
                    )
                  })}
                  </Spin>
                </div>
                <Pagination
                  className="news-pagination"
                  current={newsPage}
                  pageSize={10}
                  total={(newsPage + (newsHasNext ? 1 : 0)) * 10}
                  showSizeChanger={false}
                  onChange={(page) => loadNews(page)}
                />
              </Col>
            </Row>
          </Card>
        </>
      )}
    </div>
  )
}

export default Dashboard
