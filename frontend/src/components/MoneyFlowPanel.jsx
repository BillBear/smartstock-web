import React from 'react'
import { Card, Row, Col, Statistic, Tag, Divider, Timeline } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, DollarOutlined } from '@ant-design/icons'

const MoneyFlowPanel = ({ data }) => {
  if (!data) {
    return (
      <Card title="资金流向分析" variant="borderless">
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
          暂无资金流向数据
        </div>
      </Card>
    )
  }

  const { money_flow = {}, signal = {} } = data
  const isAvailable = data.available !== false && money_flow.available !== false && data.display_mode !== 'unavailable'
  const isProxy = data.display_mode === 'proxy' || money_flow.display_mode === 'proxy'
  const isInflow = Number(money_flow.main_net_inflow || 0) > 0

  if (!isAvailable) {
    const details = money_flow.analysis?.details || signal.signals || []
    return (
      <Card
        title="资金流向分析"
        variant="borderless"
        style={{ marginTop: 16 }}
      >
        <div style={{
          padding: '20px',
          borderRadius: 12,
          background: 'var(--bg-inset)',
          border: '1px solid var(--border-secondary)'
        }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
            <Tag color="gold" style={{ fontSize: 14 }}>资金流数据暂不可用</Tag>
            <Tag color="blue" style={{ fontSize: 14 }}>未评分</Tag>
            <Tag color="default" style={{ fontSize: 14 }}>不展示 0 值</Tag>
          </div>
          <div style={{ color: 'rgba(255,255,255,0.86)', fontWeight: 600, marginBottom: 8 }}>
            {money_flow.analysis?.conclusion || signal.overall || '真实资金流数据源暂不可用'}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.68)', lineHeight: 1.8 }}>
            {data.reason || money_flow.reason || '资金流接口当前没有返回有效数据，系统不会把缺失数据当作净流入或净流出。'}
          </div>
          <Timeline style={{ marginTop: 16 }}>
            {details.map((sig, index) => (
              <Timeline.Item key={index} color="gold">
                {sig}
              </Timeline.Item>
            ))}
          </Timeline>
        </div>
      </Card>
    )
  }

  return (
    <Card
      title="资金流向分析"
      variant="borderless"
      style={{ marginTop: 16 }}
    >
      {/* 资金流向概览 */}
      <Row gutter={16}>
        <Col span={8}>
          <Statistic
            title="主力净流入"
            value={Math.abs(money_flow.main_net_inflow / 100000000).toFixed(2)}
            precision={2}
            valueStyle={{ color: isInflow ? 'var(--bull-color)' : 'var(--bear-color)' }}
            prefix={isInflow ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
            suffix="亿元"
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="主力控盘度"
            value={money_flow.control_ratio}
            precision={1}
            suffix="%"
            valueStyle={{ color: 'var(--info-color)' }}
          />
        </Col>
        <Col span={8}>
          <div>
            <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 8 }}>资金趋势</div>
            <Tag color={isInflow ? 'red' : 'green'} style={{ fontSize: 16 }}>
              {money_flow.trend} ({money_flow.strength})
            </Tag>
            {isProxy && (
              <Tag color="orange" style={{ fontSize: 13, marginLeft: 8 }}>
                代理数据
              </Tag>
            )}
          </div>
        </Col>
      </Row>

      <Divider />

      {/* 资金流向信号 */}
      <div style={{ marginTop: 16 }}>
        <h4>
          <DollarOutlined /> 资金面评价
        </h4>
        <div style={{ marginTop: 8 }}>
          <Tag color={Number(signal.score || 0) > 0 ? 'red' : 'green'} style={{ fontSize: 14 }}>
            {signal.overall}
          </Tag>
          <span style={{ marginLeft: 8, color: 'var(--text-secondary)' }}>
            评分: {signal.score ?? '未评分'}
          </span>
        </div>

        <Timeline style={{ marginTop: 16 }}>
          {signal.signals.map((sig, index) => (
            <Timeline.Item
              key={index}
              color={sig.startsWith('✓') ? 'green' : sig.startsWith('✗') ? 'red' : 'blue'}
            >
              {sig}
            </Timeline.Item>
          ))}
        </Timeline>
      </div>

      {/* 资金流向分析 */}
      {money_flow.analysis && (
        <>
          <Divider />
          <div>
            <h4>详细分析</h4>
            <div style={{
              padding: '12px',
              background: 'var(--bg-inset)',
              border: '1px solid var(--border-secondary)',
              borderRadius: 8,
              marginTop: 8
            }}>
              <div style={{ fontWeight: 500, marginBottom: 8 }}>
                {money_flow.analysis.conclusion}
              </div>
              {money_flow.analysis.details.map((detail, index) => (
                <div key={index} style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 4 }}>
                  {detail}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </Card>
  )
}

export default MoneyFlowPanel
