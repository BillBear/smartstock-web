import React from 'react'
import { Card, Row, Col, Statistic, Tag, Divider, Timeline } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, DollarOutlined } from '@ant-design/icons'

const MoneyFlowPanel = ({ data }) => {
  if (!data) {
    return (
      <Card title="💰 资金流向分析" variant="borderless">
        <div style={{ textAlign: 'center', padding: '40px', color: '#999' }}>
          暂无资金流向数据
        </div>
      </Card>
    )
  }

  const { money_flow, signal } = data
  const isInflow = money_flow.main_net_inflow > 0

  return (
    <Card
      title="💰 资金流向分析"
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
            valueStyle={{ color: isInflow ? '#cf1322' : '#3f8600' }}
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
            valueStyle={{ color: '#1890ff' }}
          />
        </Col>
        <Col span={8}>
          <div>
            <div style={{ fontSize: 14, color: '#666', marginBottom: 8 }}>资金趋势</div>
            <Tag color={isInflow ? 'red' : 'green'} style={{ fontSize: 16 }}>
              {money_flow.trend} ({money_flow.strength})
            </Tag>
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
          <Tag color={signal.score > 0 ? 'red' : 'green'} style={{ fontSize: 14 }}>
            {signal.overall}
          </Tag>
          <span style={{ marginLeft: 8, color: '#666' }}>
            评分: {signal.score}
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
            <h4>📊 详细分析</h4>
            <div style={{
              padding: '12px',
              background: 'var(--bg-elevated)',
              borderRadius: 4,
              marginTop: 8
            }}>
              <div style={{ fontWeight: 500, marginBottom: 8 }}>
                {money_flow.analysis.conclusion}
              </div>
              {money_flow.analysis.details.map((detail, index) => (
                <div key={index} style={{ color: '#666', fontSize: 13, marginTop: 4 }}>
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
