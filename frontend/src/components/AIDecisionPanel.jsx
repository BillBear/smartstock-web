import React from 'react'
import { Card, Row, Col, Statistic, Tag, Divider, Alert, Timeline, Progress, Space } from 'antd'
import {
  RocketOutlined,
  TrophyOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  BulbOutlined
} from '@ant-design/icons'

const AIDecisionPanel = ({ data }) => {
  if (!data) {
    return (
      <Card title="AI智能决策" variant="borderless">
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
          暂无AI决策数据
        </div>
      </Card>
    )
  }

  // 决策颜色映射
  const getDecisionColor = (decision) => {
    if (decision.includes('强烈买入')) return 'var(--bull-color)'
    if (decision.includes('买入')) return 'var(--bull-color)'
    if (decision.includes('谨慎买入')) return 'var(--warning-color)'
    if (decision.includes('观望')) return 'var(--info-color)'
    if (decision.includes('卖出')) return 'var(--bear-color)'
    return 'var(--text-secondary)'
  }

  const decisionColor = getDecisionColor(data.decision)

  // 信心度进度条颜色
  const getConfidenceColor = (confidence) => {
    if (confidence === '非常高') return 'var(--bull-color)'
    if (confidence === '高') return 'var(--bull-color)'
    if (confidence === '中等') return 'var(--warning-color)'
    return 'var(--info-color)'
  }

  const confidenceValue = {
    '非常高': 90,
    '高': 70,
    '中等': 50,
    '低': 30
  }[data.confidence] || 50

  return (
    <Card
      title="AI智能决策（小白版）"
      variant="borderless"
      style={{ marginTop: 16 }}
    >
      {/* AI决策核心 */}
      <Alert
        message={
          <div style={{ fontSize: 18, fontWeight: 600 }}>
            <RocketOutlined /> AI最终决策: <span style={{ color: decisionColor }}>{data.decision}</span>
          </div>
        }
        description={
          <div style={{ marginTop: 8 }}>
            <div style={{ marginBottom: 8 }}>
              <strong>信心度：</strong>
              <Tag color={getConfidenceColor(data.confidence)} style={{ marginLeft: 8 }}>
                {data.confidence}
              </Tag>
              <span style={{ marginLeft: 16, color: 'var(--text-secondary)' }}>
                综合评分: <Tag color={data.scores.adjusted > 0 ? 'red' : 'green'}>{data.scores.adjusted.toFixed(1)}</Tag>
              </span>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              <BulbOutlined /> AI综合了技术面、资金面等多个维度后给出的建议，信心度越高越可靠
            </div>
          </div>
        }
        type="info"
        showIcon
        icon={<ThunderboltOutlined />}
      />

      {/* 信心度进度条 */}
      <div style={{ marginTop: 16, marginBottom: 24 }}>
        <Progress
          percent={confidenceValue}
          strokeColor={getConfidenceColor(data.confidence)}
          format={() => `AI信心度: ${data.confidence} (${confidenceValue}%)`}
        />
      </div>

      {/* 小白解释 */}
      <div style={{
        background: 'var(--bg-elevated)',
        padding: 16,
        borderRadius: 8,
        marginBottom: 24,
        border: '1px solid var(--border-secondary)'
      }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
          什么是AI决策？
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          AI决策就像一个<strong style={{ color: 'var(--text-primary)' }}>专业投资顾问</strong>，帮你综合分析技术指标、资金流向、市场情绪等多个因素，最后给出一个明确的操作建议。
          信心度代表AI对这个建议的把握程度，<strong style={{ color: 'var(--focus-color)' }}>信心度越高，建议越可靠</strong>。
        </div>
      </div>

      <Divider />

      {/* 评分详情 */}
      <Row gutter={16}>
        <Col span={6}>
          <Statistic
            title="技术面评分"
            value={data.scores.technical}
            valueStyle={{ color: data.scores.technical > 0 ? 'var(--bull-color)' : 'var(--bear-color)' }}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="资金面评分"
            value={data.scores.money_flow.toFixed(1)}
            valueStyle={{ color: data.scores.money_flow > 0 ? 'var(--bull-color)' : 'var(--bear-color)' }}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="综合评分"
            value={data.scores.total.toFixed(1)}
            valueStyle={{ color: data.scores.total > 0 ? 'var(--bull-color)' : 'var(--bear-color)' }}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="调整后评分"
            value={data.scores.adjusted.toFixed(1)}
            valueStyle={{ color: data.scores.adjusted > 0 ? 'var(--bull-color)' : 'var(--bear-color)' }}
          />
        </Col>
      </Row>

      <Divider />

      {/* 仓位建议 */}
      <div>
        <h4><TrophyOutlined /> 仓位建议</h4>
        <Row gutter={16} style={{ marginTop: 12 }}>
          <Col span={12}>
            <Card size="small" variant="borderless" style={{ background: 'var(--bg-inset)', border: '1px solid var(--border-secondary)' }}>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--text-secondary)' }}>建议操作:</span>
                <Tag color={decisionColor} style={{ marginLeft: 8 }}>
                  {data.position_advice.action}
                </Tag>
              </div>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--text-secondary)' }}>建议仓位:</span>
                <span style={{ marginLeft: 8, fontWeight: 500 }}>
                  {data.position_advice.position_size}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-secondary)' }}>建仓价格:</span>
                <span style={{ marginLeft: 8, fontWeight: 500, color: 'var(--info-color)' }}>
                  {data.position_advice.entry_price.toFixed(2)}元
                </span>
              </div>
            </Card>
          </Col>
          <Col span={12}>
            <Card size="small" variant="borderless" style={{ background: 'var(--bg-inset)', border: '1px solid var(--border-secondary)' }}>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--text-secondary)' }}>目标止盈:</span>
                <span style={{ marginLeft: 8, fontWeight: 500, color: 'var(--bull-color)' }}>
                  {data.position_advice.stop_profit.toFixed(2)}元
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-secondary)' }}>设置止损:</span>
                <span style={{ marginLeft: 8, fontWeight: 500, color: 'var(--bear-color)' }}>
                  {data.position_advice.stop_loss.toFixed(2)}元
                </span>
              </div>
            </Card>
          </Col>
        </Row>
      </div>

      <Divider />

      {/* 操作计划 */}
      <div>
        <h4><BulbOutlined /> 操作计划</h4>
        <Timeline style={{ marginTop: 12 }}>
          {data.action_plan.map((plan, index) => (
            <Timeline.Item key={index} color="blue">
              {plan}
            </Timeline.Item>
          ))}
        </Timeline>
      </div>

      <Divider />

      {/* 预期收益 */}
      <div>
        <h4><TrophyOutlined /> 预期收益</h4>
        <Card size="small" variant="borderless" style={{ background: 'var(--bg-inset)', border: '1px solid var(--border-secondary)', marginTop: 12 }}>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic
                title="持有周期"
                value={data.expected_return.period}
                valueStyle={{ fontSize: 14 }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="预期收益率"
                value={data.expected_return.expected_return}
                valueStyle={{ fontSize: 14, color: 'var(--bull-color)' }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="实现概率"
                value={data.expected_return.probability}
                valueStyle={{ fontSize: 14, color: 'var(--info-color)' }}
              />
            </Col>
          </Row>
          <div style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: 13 }}>
            {data.expected_return.description}
          </div>
        </Card>
      </div>

      <Divider />

      {/* 风险评估 */}
      <div>
        <h4><SafetyOutlined /> 风险评估</h4>
        <Alert
          message={`风险等级: ${data.risk_assessment.level}`}
          description={
            <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
              {data.risk_assessment.factors.map((factor, index) => (
                <li key={index} style={{ marginTop: 4 }}>{factor}</li>
              ))}
            </ul>
          }
          type={
            data.risk_assessment.level === '低' ? 'success' :
            data.risk_assessment.level === '高' ? 'error' : 'warning'
          }
          showIcon
          style={{ marginTop: 12 }}
        />
      </div>

      <Divider />

      {/* 关键要点 */}
      <div>
        <h4>关键要点</h4>
        <div style={{ marginTop: 12 }}>
          {data.key_points.map((point, index) => (
            <Tag key={index} style={{ marginBottom: 8, fontSize: 13 }}>
              {point}
            </Tag>
          ))}
        </div>
      </div>

      {/* 生成时间 */}
      <div style={{ marginTop: 16, textAlign: 'right', color: 'var(--text-muted)', fontSize: 12 }}>
        生成时间: {data.generated_at}
      </div>
    </Card>
  )
}

export default AIDecisionPanel
