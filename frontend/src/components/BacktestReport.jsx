import React from 'react'
import { Card, Row, Col, Statistic, Divider, Table, Tag } from 'antd'
import { RiseOutlined, FallOutlined, TrophyOutlined, WarningOutlined } from '@ant-design/icons'
import { Line, Column } from '@ant-design/plots'

const BacktestReport = ({ data }) => {
  const { performance, equityCurve, monthlyReturns, trades } = data

  // 收益曲线配置
  const equityConfig = {
    data: equityCurve,
    xField: 'date',
    yField: 'value',
    smooth: true,
    color: '#27C08A',
    lineStyle: {
      lineWidth: 3,
    },
    point: {
      size: 5,
      shape: 'circle',
      style: {
        fill: '#27C08A',
        stroke: '#F2F5F8',
        lineWidth: 2,
      },
    },
    yAxis: {
      label: {
        formatter: (v) => `${v}%`,
        style: {
          fill: 'rgba(255, 255, 255, 0.65)',
        },
      },
      grid: {
        line: {
          style: {
            stroke: 'rgba(255, 255, 255, 0.1)',
          },
        },
      },
    },
    xAxis: {
      label: {
        style: {
          fill: 'rgba(255, 255, 255, 0.65)',
        },
      },
    },
  }

  // 月度收益配置
  const monthlyConfig = {
    data: monthlyReturns,
    xField: 'month',
    yField: 'return',
    color: ({ return: ret }) => (ret >= 0 ? '#D95F59' : '#27C08A'),
    columnStyle: {
      radius: [4, 4, 0, 0],
    },
    yAxis: {
      label: {
        formatter: (v) => `${v}%`,
        style: {
          fill: 'rgba(255, 255, 255, 0.65)',
        },
      },
      grid: {
        line: {
          style: {
            stroke: 'rgba(255, 255, 255, 0.1)',
          },
        },
      },
    },
    xAxis: {
      label: {
        style: {
          fill: 'rgba(255, 255, 255, 0.65)',
        },
      },
    },
  }

  const tradeColumns = [
    {
      title: '日期',
      dataIndex: 'date',
      key: 'date',
    },
    {
      title: '股票',
      key: 'stock',
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 500 }}>{record.name}</div>
          <span style={{ fontSize: 12, color: 'rgba(255, 255, 255, 0.45)' }}>
            {record.symbol}
          </span>
        </div>
      ),
    },
    {
      title: '操作',
      dataIndex: 'action',
      key: 'action',
      render: (action) => (
        <Tag color={action === 'buy' ? 'red' : 'green'}>
          {action === 'buy' ? '买入' : '卖出'}
        </Tag>
      ),
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      render: (price) => `¥${price.toFixed(2)}`,
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
      render: (qty) => `${qty}股`,
    },
    {
      title: '盈亏',
      dataIndex: 'profit',
      key: 'profit',
      render: (profit) =>
        profit ? (
          <span style={{ color: profit > 0 ? 'var(--bull-color)' : 'var(--bear-color)', fontWeight: 500 }}>
            {profit > 0 ? '+' : ''}
            {profit.toFixed(2)}
          </span>
        ) : (
          '-'
        ),
    },
    {
      title: '收益率',
      dataIndex: 'return',
      key: 'return',
      render: (ret) =>
        ret ? (
          <span style={{ color: ret > 0 ? 'var(--bull-color)' : 'var(--bear-color)', fontWeight: 600 }}>
            {ret > 0 ? '+' : ''}
            {ret}%
          </span>
        ) : (
          '-'
        ),
    },
  ]

  return (
    <div className="backtest-report">
      {/* 核心指标 */}
      <Card className="report-card" title="回测结果概览" variant="borderless">
        <Row gutter={16}>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="总收益率"
              value={performance.totalReturn}
              precision={1}
              suffix="%"
              valueStyle={{ color: 'var(--bull-color)', fontSize: 24 }}
              prefix={<RiseOutlined />}
            />
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="年化收益率"
              value={performance.annualReturn}
              precision={1}
              suffix="%"
              valueStyle={{ color: 'var(--bull-color)', fontSize: 24 }}
            />
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="最大回撤"
              value={Math.abs(performance.maxDrawdown)}
              precision={1}
              suffix="%"
              valueStyle={{ color: 'var(--bear-color)', fontSize: 24 }}
              prefix={<FallOutlined />}
            />
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="夏普比率"
              value={performance.sharpeRatio}
              precision={2}
              valueStyle={{ color: 'var(--info-color)', fontSize: 24 }}
            />
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="胜率"
              value={performance.winRate}
              precision={1}
              suffix="%"
              valueStyle={{ fontSize: 20 }}
            />
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="盈亏比"
              value={performance.profitLossRatio}
              precision={1}
              valueStyle={{ fontSize: 20 }}
            />
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="总交易次数"
              value={performance.totalTrades}
              valueStyle={{ fontSize: 20 }}
            />
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Statistic
              title="平均持仓天数"
              value={performance.avgHoldingDays}
              suffix="天"
              valueStyle={{ fontSize: 20 }}
            />
          </Col>
        </Row>

        <Divider />

        <Row gutter={16}>
          <Col xs={12} md={6}>
            <Statistic
              title="Alpha（超额收益）"
              value={performance.alpha}
              precision={1}
              suffix="%"
              valueStyle={{ color: 'var(--warning-color)' }}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="Beta（系统风险）"
              value={performance.beta}
              precision={2}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="索提诺比率"
              value={performance.sortinoRatio}
              precision={2}
            />
          </Col>
          <Col xs={12} md={6}>
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Tag
                icon={<TrophyOutlined />}
                color="gold"
                style={{ fontSize: 16, padding: '8px 16px' }}
              >
                跑赢沪深300: +98.3%
              </Tag>
            </div>
          </Col>
        </Row>
      </Card>

      {/* 收益曲线 */}
      <Card className="report-card" title="收益曲线" variant="borderless">
        <Line {...equityConfig} height={300} />
      </Card>

      {/* 月度收益 */}
      <Card className="report-card" title="月度收益统计" variant="borderless">
        <Column {...monthlyConfig} height={300} />
      </Card>

      {/* 交易明细 */}
      <Card className="report-card" title="交易明细" variant="borderless">
        <Table
          columns={tradeColumns}
          dataSource={trades}
          pagination={{ pageSize: 10 }}
          rowKey={(record, index) => index}
        />
      </Card>

      {/* 策略评价 */}
      <Card className="report-card evaluation-card" variant="borderless">
        <h3>
          <TrophyOutlined /> 策略评价
        </h3>
        <div className="evaluation-content">
          <div className="evaluation-item good">
            <strong>✓ 优势</strong>
            <ul>
              <li>年化收益率23.5%，显著跑赢大盘</li>
              <li>夏普比率1.82，风险调整后收益优秀</li>
              <li>胜率64.3%，超过60%阈值</li>
              <li>盈亏比2.1，赚多亏少</li>
            </ul>
          </div>
          <div className="evaluation-item warning">
            <strong>
              <WarningOutlined /> 风险提示
            </strong>
            <ul>
              <li>最大回撤-18.2%，需做好心理准备</li>
              <li>回测基于历史数据，未来表现可能不同</li>
              <li>实盘交易可能面临流动性、成交限制等问题</li>
              <li>建议先小仓位验证，再逐步加仓</li>
            </ul>
          </div>
        </div>
      </Card>
    </div>
  )
}

export default BacktestReport
