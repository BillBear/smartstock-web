import React, { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, Col, DatePicker, Descriptions, Form, InputNumber, Row, Select, Space, Spin, Statistic, Table, Tag, message } from 'antd'
import { LineChartOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Line } from '@ant-design/plots'
import dayjs from 'dayjs'
import { coachApi } from '../services/api'
import './Backtest.css'

const { RangePicker } = DatePicker

const STRATEGY_OPTIONS = [
  { label: '趋势突破策略', value: 'trend_breakout' },
  { label: '回调修复策略', value: 'pullback_rebound' },
]

const DEFAULT_FORM_CONFIG = {
  holding_days: 15,
  stop_profit_pct: 15,
  stop_loss_pct: 8,
  score_threshold: 70,
  commission: 0.0003,
  slippage: 0.001,
  max_positions: 5,
  universe_size: 90,
}

const pickConfigFields = (values = {}) => ({
  holding_days: values.holding_days,
  stop_profit_pct: values.stop_profit_pct,
  stop_loss_pct: values.stop_loss_pct,
  score_threshold: values.score_threshold,
  commission: values.commission,
  slippage: values.slippage,
  max_positions: values.max_positions,
  universe_size: values.universe_size,
})

const Backtest = () => {
  const [form] = Form.useForm()
  const [searchParams, setSearchParams] = useSearchParams()
  const [loadingEvidence, setLoadingEvidence] = useState(false)
  const [runningBacktest, setRunningBacktest] = useState(false)
  const [loadingBacktestResult, setLoadingBacktestResult] = useState(false)
  const [loadingConfigOptions, setLoadingConfigOptions] = useState(false)
  const [applyingStrategyConfig, setApplyingStrategyConfig] = useState(false)
  const [evidence, setEvidence] = useState(null)
  const [result, setResult] = useState(null)
  const [strategyConfigOptions, setStrategyConfigOptions] = useState([])
  const [recommendedProfileKey, setRecommendedProfileKey] = useState(null)

  const strategyCode = Form.useWatch('strategy_code', form) || 'trend_breakout'
  const queryRunId = searchParams.get('run_id')
  const queryStrategyCode = searchParams.get('strategy_code') || searchParams.get('strategy')

  const loadEvidence = async (code) => {
    setLoadingEvidence(true)
    try {
      const data = await coachApi.getStrategyEvidence(code, { state_tag: 'neutral' })
      setEvidence(data)
    } catch (err) {
      console.error('加载策略证据失败', err)
      message.error(err?.response?.data?.message || err?.message || '策略证据加载失败')
      setEvidence(null)
    } finally {
      setLoadingEvidence(false)
    }
  }

  const loadStrategyConfigOptions = async (code) => {
    setLoadingConfigOptions(true)
    try {
      const data = await coachApi.getStrategyConfigOptions(code, 'default')
      const presets = data?.presets || []
      setStrategyConfigOptions(presets)
      setRecommendedProfileKey(data?.recommended_profile_key || presets?.[0]?.profile_key || null)
      const nextProfileKey = data?.current_profile_key || data?.recommended_profile_key || presets?.[0]?.profile_key
      const nextConfig = data?.current_config || presets?.[0]?.config || {}
      form.setFieldsValue({
        profile_key: nextProfileKey,
        ...DEFAULT_FORM_CONFIG,
        ...nextConfig,
      })
    } catch (err) {
      console.error('加载策略配置模板失败', err)
      message.error(err?.response?.data?.message || err?.message || '策略配置模板加载失败')
      setStrategyConfigOptions([])
      setRecommendedProfileKey(null)
      form.setFieldsValue({ profile_key: null, ...DEFAULT_FORM_CONFIG })
    } finally {
      setLoadingConfigOptions(false)
    }
  }

  useEffect(() => {
    loadEvidence(strategyCode)
    loadStrategyConfigOptions(strategyCode)
  }, [strategyCode])

  useEffect(() => {
    if (queryStrategyCode && queryStrategyCode !== form.getFieldValue('strategy_code')) {
      form.setFieldsValue({ strategy_code: queryStrategyCode })
    }
  }, [queryStrategyCode, form])

  const loadBacktestResult = async (runId, options = {}) => {
    if (!runId) return
    setLoadingBacktestResult(true)
    try {
      const data = await coachApi.getBacktestResult(runId)
      setResult(data)
      if (data?.strategy_code && data.strategy_code !== form.getFieldValue('strategy_code')) {
        form.setFieldsValue({ strategy_code: data.strategy_code })
      }
      if (data?.config) {
        const cfg = data.config
        form.setFieldsValue({
          profile_key: cfg.profile_key || form.getFieldValue('profile_key'),
          holding_days: cfg.holding_days,
          stop_profit_pct: cfg.stop_profit_pct,
          stop_loss_pct: cfg.stop_loss_pct,
          score_threshold: cfg.score_threshold,
          commission: cfg.commission,
          slippage: cfg.slippage,
          max_positions: cfg.max_positions,
          universe_size: cfg.universe_size,
          period: cfg.test_start && cfg.test_end ? [dayjs(cfg.test_start), dayjs(cfg.test_end)] : form.getFieldValue('period'),
        })
      }
      if (options.syncUrl !== false) {
        setSearchParams({
          strategy_code: data?.strategy_code || strategyCode,
          run_id: runId,
        })
      }
    } catch (err) {
      console.error('加载回测证据失败', err)
      message.error(err?.response?.data?.message || err?.message || '回测证据加载失败')
      setResult(null)
    } finally {
      setLoadingBacktestResult(false)
    }
  }

  useEffect(() => {
    if (queryRunId) {
      loadBacktestResult(queryRunId, { syncUrl: false })
    }
  }, [queryRunId])

  const waitResult = async (runId) => {
    for (let i = 0; i < 5; i += 1) {
      try {
        const data = await coachApi.getBacktestResult(runId)
        if (data) return data
      } catch (err) {
        if (i === 4) throw err
      }
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
    throw new Error('回测结果超时')
  }

  const applyPresetToForm = (profileKey) => {
    const preset = (strategyConfigOptions || []).find((item) => item.profile_key === profileKey)
    if (!preset) return
    form.setFieldsValue({
      profile_key: preset.profile_key,
      ...DEFAULT_FORM_CONFIG,
      ...(preset.config || {}),
    })
  }

  const applyCurrentConfigToSmartScreen = async () => {
    setApplyingStrategyConfig(true)
    try {
      const values = form.getFieldsValue()
      const payload = {
        strategy_code: values.strategy_code || strategyCode,
        profile_key: values.profile_key || null,
        config: pickConfigFields(values),
        set_active: true,
      }
      const data = await coachApi.applyStrategyConfig(payload, 'default')
      message.success(
        `已应用到智能选股：${data?.strategy_code || strategyCode} / ${data?.profile_key || '自定义配置'}`
      )
    } catch (err) {
      console.error('应用策略配置失败', err)
      message.error(err?.response?.data?.message || err?.message || '应用策略配置失败')
    } finally {
      setApplyingStrategyConfig(false)
    }
  }

  const onSubmit = async (values) => {
    setRunningBacktest(true)
    try {
      const payload = {
        strategy_code: values.strategy_code,
        profile_key: values.profile_key || null,
        strategy_version_id: values.strategy_version_id || null,
        test_start: values.period?.[0]?.format('YYYY-MM-DD') || null,
        test_end: values.period?.[1]?.format('YYYY-MM-DD') || null,
        config: pickConfigFields(values),
      }

      const run = await coachApi.runBacktest(payload)
      const data = await waitResult(run.run_id)
      setResult(data)
      setSearchParams({
        strategy_code: data?.strategy_code || values.strategy_code,
        run_id: run.run_id,
      })
      message.success(`回测完成：${run.run_id}`)
    } catch (err) {
      console.error('回测失败', err)
      message.error(err?.response?.data?.message || err?.message || '回测失败')
      setResult(null)
    } finally {
      setRunningBacktest(false)
    }
  }

  const equitySeries = useMemo(() => (result?.equity_curve || []).map((item) => ({
    date: item.date,
    value: Number(item.value || 0) * 100,
  })), [result])

  const drawdownSeries = useMemo(() => (result?.drawdown_curve || []).map((item) => ({
    date: item.date,
    value: Number(item.value || 0) * 100,
  })), [result])

  const lineConfig = {
    data: equitySeries,
    xField: 'date',
    yField: 'value',
    smooth: true,
    color: '#00C076',
    point: { size: 4 },
    yAxis: { label: { formatter: (v) => `${v}%` } },
  }

  const drawdownConfig = {
    data: drawdownSeries,
    xField: 'date',
    yField: 'value',
    smooth: true,
    color: '#ff7875',
    point: { size: 4 },
    yAxis: { label: { formatter: (v) => `${v}%` } },
  }

  const tradeColumns = [
    { title: '日期', dataIndex: 'trade_date', key: 'trade_date' },
    {
      title: '股票',
      key: 'symbol',
      render: (_, row) => `${row.name || row.symbol} (${row.symbol})`,
    },
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      render: (side) => <Tag color={side === 'buy' ? 'red' : 'green'}>{side === 'buy' ? '买入' : '卖出'}</Tag>,
    },
    { title: '价格', dataIndex: 'price', key: 'price' },
    { title: '数量', dataIndex: 'qty', key: 'qty' },
    {
      title: '金额',
      dataIndex: 'amount',
      key: 'amount',
      render: (v) => v !== undefined && v !== null ? Number(v).toFixed(2) : '-',
    },
    { title: '原因', dataIndex: 'reason', key: 'reason' },
  ]

  const suggestionColumns = [
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 100,
      render: (v) => {
        const color = v === 'high' ? 'red' : (v === 'medium' ? 'gold' : 'blue')
        const text = v === 'high' ? '高' : (v === 'medium' ? '中' : '低')
        return <Tag color={color}>{text}</Tag>
      },
    },
    { title: '建议', dataIndex: 'title', key: 'title', width: 260 },
    { title: '原因', dataIndex: 'reason', key: 'reason' },
    {
      title: '建议参数',
      key: 'changes',
      width: 260,
      render: (_, row) => Object.entries(row.changes || {}).map(([k, v]) => `${k}: ${v}`).join(' | ') || '-',
    },
    { title: '预期效果', dataIndex: 'expected_effect', key: 'expected_effect', width: 240 },
  ]

  const gateColumns = [
    { title: '检查项', dataIndex: 'label', key: 'label', width: 180 },
    {
      title: '当前值',
      dataIndex: 'value',
      key: 'value',
      width: 140,
      render: (v) => {
        if (typeof v === 'boolean') return v ? '是' : '否'
        if (typeof v === 'number') return Number(v).toFixed(4)
        return String(v ?? '-')
      },
    },
    { title: '门槛', dataIndex: 'threshold', key: 'threshold', width: 150 },
    {
      title: '状态',
      dataIndex: 'passed',
      key: 'passed',
      width: 100,
      render: (v) => <Tag color={v ? 'green' : 'red'}>{v ? '通过' : '未通过'}</Tag>,
    },
  ]

  const roundTripColumns = [
    { title: '股票', key: 'symbol', render: (_, row) => `${row.name || row.symbol} (${row.symbol})` },
    { title: '开仓', dataIndex: 'entry_date', key: 'entry_date', width: 170 },
    { title: '平仓', dataIndex: 'exit_date', key: 'exit_date', width: 170 },
    { title: '持有天数', dataIndex: 'holding_days', key: 'holding_days', width: 100 },
    {
      title: '收益率',
      dataIndex: 'return_pct',
      key: 'return_pct',
      width: 100,
      render: (v) => <span style={{ color: Number(v || 0) >= 0 ? '#ff7875' : '#95de64' }}>{Number(v || 0).toFixed(2)}%</span>,
    },
    {
      title: '盈亏',
      dataIndex: 'pnl_amount',
      key: 'pnl_amount',
      width: 100,
      render: (v) => <span style={{ color: Number(v || 0) >= 0 ? '#ff7875' : '#95de64' }}>{Number(v || 0).toFixed(2)}</span>,
    },
  ]

  const runHistoryColumns = [
    {
      title: '回测ID',
      dataIndex: 'run_id',
      key: 'run_id',
      width: 180,
      render: (v, row) => (
        <Button type="link" size="small" onClick={() => loadBacktestResult(v)}>
          {v || row.evidence_hash || '-'}
        </Button>
      ),
    },
    { title: '时间', dataIndex: 'started_at', key: 'started_at', width: 170 },
    {
      title: '闭环交易',
      key: 'closed_roundtrips',
      width: 100,
      render: (_, row) => Number(row?.sample_summary?.closed_roundtrips || row?.diagnostics?.closed_roundtrips || 0),
    },
    {
      title: '年化收益',
      key: 'annual_return',
      width: 110,
      render: (_, row) => `${(Number(row?.metrics?.annual_return || 0) * 100).toFixed(2)}%`,
    },
    {
      title: '最大回撤',
      key: 'max_drawdown',
      width: 110,
      render: (_, row) => `${(Number(row?.metrics?.max_drawdown || 0) * 100).toFixed(2)}%`,
    },
    {
      title: '可信度',
      key: 'credibility',
      width: 120,
      render: (_, row) => <Tag color={row?.credibility?.live_ready ? 'green' : 'orange'}>{row?.credibility?.grade || '待验证'}</Tag>,
    },
  ]

  return (
    <div className="backtest-container">
      <div className="backtest-header">
        <h1 className="page-title">
          <ThunderboltOutlined /> 策略回溯
        </h1>
        <p className="page-subtitle">验证策略在不同市场状态下的有效性，并追踪风险收益特征</p>
      </div>

      <Card className="config-card" title="回测配置" variant="borderless">
        <Form
          form={form}
          layout="vertical"
          onFinish={onSubmit}
          initialValues={{
            strategy_code: 'trend_breakout',
            profile_key: 'breakout_balanced',
            strategy_version_id: 'v1.0.0',
            period: [dayjs().subtract(18, 'month'), dayjs()],
            holding_days: 15,
            stop_profit_pct: 15,
            stop_loss_pct: 8,
            score_threshold: 70,
            commission: 0.0003,
            slippage: 0.001,
            max_positions: 5,
            universe_size: 90,
          }}
        >
          <Row gutter={16}>
            <Col xs={24} md={6}>
              <Form.Item label="策略" name="strategy_code" rules={[{ required: true }]}>
                <Select options={STRATEGY_OPTIONS} />
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item label="策略配置模板" name="profile_key">
                <Select
                  loading={loadingConfigOptions}
                  placeholder="请选择配置模板"
                  options={(strategyConfigOptions || []).map((item) => ({
                    value: item.profile_key,
                    label: `${item.label}${item.profile_key === recommendedProfileKey ? ' · 推荐' : ''}`,
                  }))}
                  onChange={applyPresetToForm}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item label="策略版本" name="strategy_version_id">
                <Select
                  options={[
                    { label: 'v1.0.0', value: 'v1.0.0' },
                    { label: 'v1.1.0', value: 'v1.1.0' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item label="回测区间" name="period" rules={[{ required: true, message: '请选择回测区间' }]}>
                <RangePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="持有天数" name="holding_days">
                <InputNumber min={3} max={60} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="止盈(%)" name="stop_profit_pct">
                <InputNumber min={5} max={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="止损(%)" name="stop_loss_pct">
                <InputNumber min={2} max={30} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="阈值" name="score_threshold">
                <InputNumber min={50} max={95} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="手续费" name="commission">
                <InputNumber min={0} step={0.0001} max={0.01} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="滑点" name="slippage">
                <InputNumber min={0} step={0.0001} max={0.01} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="最大持仓数" name="max_positions">
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label="样本池规模" name="universe_size">
                <InputNumber min={20} max={300} step={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Space style={{ width: '100%', marginBottom: 12 }} wrap>
            <Button onClick={() => applyPresetToForm(form.getFieldValue('profile_key'))}>
              使用模板参数
            </Button>
            <Button
              type="default"
              loading={applyingStrategyConfig}
              onClick={applyCurrentConfigToSmartScreen}
            >
              应用到智能选股
            </Button>
          </Space>

          <Button
            type="primary"
            htmlType="submit"
            icon={<LineChartOutlined />}
            loading={runningBacktest}
            block
          >
            {runningBacktest ? '回测执行中...' : '运行回测'}
          </Button>
        </Form>
      </Card>

      <Card className="config-card" title="策略证据（样本外）" variant="borderless">
        {loadingEvidence ? (
          <Spin tip="策略证据加载中..." />
        ) : evidence ? (
          <>
            <Alert
              showIcon
              type={evidence?.unavailable ? 'warning' : 'info'}
              style={{ marginBottom: 12 }}
              message={evidence?.evidence_source?.label || '策略级历史回放证据'}
              description={`展示口径：${evidence?.evidence_source?.display_scope || 'overall'}；闭环交易合计 ${Number(evidence?.sample_summary?.closed_roundtrips || 0)} 笔；回放次数 ${Number(evidence?.sample_summary?.sample_runs || 0)} 次。`}
            />
            <Row gutter={16}>
              <Col xs={12} md={6}>
                <Statistic title="年化收益" value={Number(evidence?.overall?.annual_return || 0) * 100} suffix="%" precision={2} />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="最大回撤" value={Number(evidence?.overall?.max_drawdown || 0) * 100} suffix="%" precision={2} />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="夏普" value={Number(evidence?.overall?.sharpe || 0)} precision={2} />
              </Col>
              <Col xs={12} md={6}>
                <Statistic title="胜率" value={Number(evidence?.overall?.win_rate || 0) * 100} suffix="%" precision={2} />
              </Col>
            </Row>
            <Descriptions bordered column={3} size="small" style={{ marginTop: 12 }} title="证据摘要">
              <Descriptions.Item label="可验证回测ID">{evidence?.display_run?.run_id || '总体聚合证据'}</Descriptions.Item>
              <Descriptions.Item label="最新回测ID">{evidence?.latest_run?.run_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="证据指纹">{evidence?.display_run?.evidence_hash || '-'}</Descriptions.Item>
              <Descriptions.Item label="样本标的">{Number(evidence?.sample_summary?.valid_history_symbols || 0)} / {Number(evidence?.sample_summary?.universe_size || 0)}</Descriptions.Item>
              <Descriptions.Item label="回测天数">{Number(evidence?.sample_summary?.calendar_days || 0)}</Descriptions.Item>
              <Descriptions.Item label="可信等级">{evidence?.credibility_summary?.grade || '-'}</Descriptions.Item>
            </Descriptions>
            <Table
              style={{ marginTop: 12 }}
              pagination={false}
              rowKey="state_tag"
              dataSource={evidence?.by_state || []}
              columns={[
                { title: '市场状态', dataIndex: 'state_tag', key: 'state_tag' },
                {
                  title: '胜率',
                  dataIndex: 'win_rate',
                  key: 'win_rate',
                  render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
                },
                {
                  title: '最大回撤',
                  dataIndex: 'max_drawdown',
                  key: 'max_drawdown',
                  render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
                },
              ]}
            />
            <Table
              style={{ marginTop: 12 }}
              title={() => '历史回测列表'}
              rowKey={(row) => row.run_id || row.evidence_hash}
              columns={runHistoryColumns}
              dataSource={evidence?.recent_runs || []}
              pagination={false}
              size="small"
            />
          </>
        ) : (
          <Alert showIcon type="warning" message="暂无策略证据" />
        )}
      </Card>

      {loadingBacktestResult && (
        <Card className="config-card" variant="borderless">
          <Space>
            <Spin />
            <span style={{ color: 'rgba(255, 255, 255, 0.78)' }}>正在加载指定回测证据...</span>
          </Space>
        </Card>
      )}

      {result && (
        <>
          <Card className="config-card" title={`回测结果 (${result.run_id})`} variant="borderless">
            <Descriptions bordered column={3} size="small">
              <Descriptions.Item label="状态">{result.status}</Descriptions.Item>
              <Descriptions.Item label="策略">{result.strategy_code}</Descriptions.Item>
              <Descriptions.Item label="完成时间">{result.finished_at}</Descriptions.Item>
              <Descriptions.Item label="年化收益">{(Number(result?.metrics?.annual_return || 0) * 100).toFixed(2)}%</Descriptions.Item>
              <Descriptions.Item label="最大回撤">{(Number(result?.metrics?.max_drawdown || 0) * 100).toFixed(2)}%</Descriptions.Item>
              <Descriptions.Item label="夏普">{Number(result?.metrics?.sharpe || 0).toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="胜率">{(Number(result?.metrics?.win_rate || 0) * 100).toFixed(2)}%</Descriptions.Item>
              <Descriptions.Item label="盈亏比">{Number(result?.metrics?.profit_loss_ratio || 0).toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="可信度评分">{Number(result?.credibility?.score || 0).toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="可信等级">{result?.credibility?.grade || '-'}</Descriptions.Item>
              <Descriptions.Item label="实盘准入">
                <Tag color={result?.live_readiness?.ready ? 'green' : 'red'}>
                  {result?.live_readiness?.ready ? '通过' : '未通过'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
            <Alert
              style={{ marginTop: 12 }}
              type="info"
              showIcon
              message={`回放样本置信权重：${(Number(result?.metrics_blend_weight || 0) * 100).toFixed(1)}%，闭环交易：${Number(result?.diagnostics?.closed_roundtrips || 0)}笔，样本标的：${Number(result?.diagnostics?.valid_history_symbols || 0)}只`}
            />
            <Alert
              style={{ marginTop: 12 }}
              type={result?.live_readiness?.ready ? 'success' : 'error'}
              showIcon
              message={result?.live_readiness?.summary || result?.credibility?.summary || '暂无实盘准入结论'}
            />
          </Card>

          <Card className="config-card evidence-package-card" title="证据包" variant="borderless">
            <Descriptions bordered column={3} size="small">
              <Descriptions.Item label="证据来源">策略级历史回放</Descriptions.Item>
              <Descriptions.Item label="回测引擎">{result?.backtest_engine || 'historical_replay_v1'}</Descriptions.Item>
              <Descriptions.Item label="策略代码">{result?.strategy_code || '-'}</Descriptions.Item>
              <Descriptions.Item label="回测区间">{result?.config?.test_start || '-'} → {result?.config?.test_end || '-'}</Descriptions.Item>
              <Descriptions.Item label="有效样本">{Number(result?.diagnostics?.valid_history_symbols || 0)} / {Number(result?.diagnostics?.universe_size || result?.config?.universe_size || 0)}</Descriptions.Item>
              <Descriptions.Item label="闭环交易">{Number(result?.diagnostics?.closed_roundtrips || 0)} 笔</Descriptions.Item>
              <Descriptions.Item label="买入规则">信号后下一交易日开盘成交</Descriptions.Item>
              <Descriptions.Item label="卖出规则">止盈/止损/持有期/评分退出后收盘近似成交</Descriptions.Item>
              <Descriptions.Item label="成本假设">佣金 {result?.config?.commission ?? '-'}，滑点 {result?.config?.slippage ?? '-'}</Descriptions.Item>
            </Descriptions>
            <Alert
              style={{ marginTop: 12 }}
              showIcon
              type="warning"
              message="证据边界"
              description="本页展示的是策略级历史回放证据，不是单只股票的确定收益承诺；历史资金流因子包含量价代理，需结合模拟盘继续验证执行一致性。"
            />
          </Card>

          <Card className="config-card" title="概率校准结果" variant="borderless">
            <Alert
              showIcon
              type={result?.probability_calibration?.calibrated ? 'success' : 'warning'}
              message={result?.probability_calibration?.message || '暂无概率校准数据'}
              description={`闭环样本：${Number(result?.probability_calibration?.sample_count || 0)} 笔；校准要求：总样本不少于 ${Number(result?.probability_calibration?.min_total_sample || 30)} 笔，且至少两个评分分层样本充足。`}
            />
            <Table
              style={{ marginTop: 12 }}
              rowKey={(row) => row.label}
              columns={[
                { title: '评分分层', dataIndex: 'label', key: 'label' },
                { title: '样本数', dataIndex: 'sample_count', key: 'sample_count' },
                {
                  title: '历史胜率',
                  dataIndex: 'win_rate',
                  key: 'win_rate',
                  render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
                },
                {
                  title: '亏损率',
                  dataIndex: 'loss_rate',
                  key: 'loss_rate',
                  render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%`,
                },
                {
                  title: '平均收益',
                  dataIndex: 'avg_return_pct',
                  key: 'avg_return_pct',
                  render: (v) => `${Number(v || 0).toFixed(2)}%`,
                },
                {
                  title: '是否可校准',
                  dataIndex: 'calibrated',
                  key: 'calibrated',
                  render: (v) => <Tag color={v ? 'green' : 'orange'}>{v ? '可校准' : '样本不足'}</Tag>,
                },
              ]}
              dataSource={result?.probability_calibration?.buckets || []}
              pagination={false}
            />
          </Card>

          <Card className="config-card" title="实盘准入检查" variant="borderless">
            <Table
              rowKey={(row) => row.key || row.label}
              columns={gateColumns}
              dataSource={(result?.credibility?.gate_checks || []).map((item) => ({ ...item, key: item.key || item.label }))}
              pagination={false}
            />
          </Card>

          <Card className="config-card" title="可信度维度分解" variant="borderless">
            <Table
              rowKey={(row) => row.factor}
              columns={[
                { title: '维度', dataIndex: 'factor', key: 'factor', width: 160 },
                {
                  title: '得分',
                  dataIndex: 'score',
                  key: 'score',
                  width: 120,
                  render: (v) => Number(v || 0).toFixed(2),
                },
                {
                  title: '权重',
                  dataIndex: 'weight',
                  key: 'weight',
                  width: 120,
                  render: (v) => `${(Number(v || 0) * 100).toFixed(0)}%`,
                },
              ]}
              dataSource={result?.credibility?.dimensions || []}
              pagination={false}
            />
            <Alert
              style={{ marginTop: 12 }}
              type="warning"
              showIcon
              message="当前历史回放中的资金流因子为量价代理，不等同于逐日真实主力流数据。若要进一步提升实盘可信度，需接入可回溯的逐日资金流原始数据。"
            />
          </Card>

          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Card className="config-card" variant="borderless">
                <Statistic title="样本交易数" value={Number(result?.diagnostics?.trade_count || 0)} />
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card className="config-card" variant="borderless">
                <Statistic title="平均持有天数" value={Number(result?.diagnostics?.avg_holding_days || 0)} precision={2} />
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card className="config-card" variant="borderless">
                <Statistic
                  title="总实现收益率"
                  value={Number(result?.diagnostics?.total_realized_return_pct || 0)}
                  precision={2}
                  suffix="%"
                  valueStyle={{ color: Number(result?.diagnostics?.total_realized_return_pct || 0) >= 0 ? '#ff7875' : '#95de64' }}
                />
              </Card>
            </Col>
          </Row>

          <Card className="config-card" title="参数优化建议" variant="borderless">
            <Table
              rowKey={(row) => row.id}
              columns={suggestionColumns}
              dataSource={result?.optimization_suggestions || []}
              pagination={false}
              scroll={{ x: 1200 }}
            />
            <Descriptions bordered size="small" style={{ marginTop: 12 }} title="建议参数配置">
              {Object.entries(result?.suggested_config || {}).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </Card>

          <Row gutter={16}>
            <Col xs={24} lg={12}>
              <Card className="config-card" title="权益曲线" variant="borderless">
                {equitySeries.length > 0 ? <Line {...lineConfig} height={280} /> : <Alert type="info" showIcon message="暂无曲线数据" />}
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card className="config-card" title="回撤曲线" variant="borderless">
                {drawdownSeries.length > 0 ? <Line {...drawdownConfig} height={280} /> : <Alert type="info" showIcon message="暂无回撤数据" />}
              </Card>
            </Col>
          </Row>

          <Card className="config-card" title="交易明细" variant="borderless">
            <Table
              rowKey={(row) => `${row.trade_date}-${row.symbol}-${row.side}-${row.price}-${row.qty}`}
              columns={tradeColumns}
              dataSource={result.trades || []}
              pagination={false}
            />
          </Card>

          <Card className="config-card" title="闭环交易表现（买卖配对）" variant="borderless">
            <Table
              rowKey={(row) => `${row.symbol}-${row.entry_date}-${row.exit_date}-${row.return_pct}-${row.holding_days}`}
              columns={roundTripColumns}
              dataSource={result?.closed_roundtrips || []}
              pagination={{ pageSize: 10 }}
            />
          </Card>
        </>
      )}

      <Card className="info-card" variant="borderless">
        <h3>回测说明</h3>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert type="info" showIcon message="回测结果仅用于策略有效性验证，不构成投资建议。" />
          <Alert type="warning" showIcon message="建议先使用模拟盘验证执行一致性，再决定实盘仓位。" />
        </Space>
      </Card>
    </div>
  )
}

export default Backtest
