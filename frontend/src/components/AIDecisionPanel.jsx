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
    if (decision.includes('模拟验证')) return 'var(--warning-color)'
    if (decision.includes('未入选')) return 'var(--text-secondary)'
    if (decision.includes('观察')) return 'var(--info-color)'
    if (decision.includes('谨慎买入')) return 'var(--warning-color)'
    if (decision.includes('观望')) return 'var(--info-color)'
    if (decision.includes('卖出')) return 'var(--bear-color)'
    return 'var(--text-secondary)'
  }

  const decisionColor = getDecisionColor(data.decision)
  const isCoachAligned = data.decision_source === 'coach_service'
  const coachContext = data.coach_context || {}
  const scores = data.scores || {}
  const legacyScores = data.legacy_scores || {}
  const positionAdvice = data.position_advice || {}
  const hasNumber = (value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
  const hasCoachScore = hasNumber(scores.adjusted)
  const formatScore = (value) => hasNumber(value) ? Number(value).toFixed(1) : '未评分'
  const formatPrice = (value) => hasNumber(value) ? `${Number(value).toFixed(2)}元` : '不适用'
  const scoreStyle = (value) => {
    if (!hasNumber(value)) return { color: 'var(--text-secondary)' }
    return { color: Number(value) > 0 ? 'var(--bull-color)' : 'var(--bear-color)' }
  }

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
            <RocketOutlined /> {isCoachAligned ? '智能选股动作' : 'AI最终决策'}: <span style={{ color: decisionColor }}>{data.decision}</span>
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
                综合评分: <Tag color={hasCoachScore && scores.adjusted > 0 ? 'red' : 'default'}>{formatScore(scores.adjusted)}</Tag>
              </span>
              {isCoachAligned && (
                <span style={{ marginLeft: 16, color: 'var(--text-secondary)' }}>
                  来源: <Tag color="blue">{coachContext.source || 'coach_service'}</Tag>
                </span>
              )}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              <BulbOutlined /> {isCoachAligned
                ? '最终动作来自智能选股 CoachService，与候选池、观察池和模拟验证门槛保持一致。'
                : 'AI综合了技术面、资金面等多个维度后给出的建议，信心度越高越可靠'}
            </div>
          </div>
        }
        type={isCoachAligned && data.decision.includes('未入选') ? 'warning' : 'info'}
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
          {isCoachAligned ? '这和智能选股是什么关系？' : '什么是AI决策？'}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {isCoachAligned ? (
            <>
              个股页不再单独用旧 AI 阈值生成买入/卖出结论。这里复用<strong style={{ color: 'var(--text-primary)' }}>智能选股候选池</strong>里的评分上下文：
              入选则显示候选池动作；未入选则不生成交易计划，只保留行情和技术分析作参考。
            </>
          ) : (
            <>
              AI决策就像一个<strong style={{ color: 'var(--text-primary)' }}>专业投资顾问</strong>，帮你综合分析技术指标、资金流向、市场情绪等多个因素，最后给出一个明确的操作建议。
              信心度代表AI对这个建议的把握程度，<strong style={{ color: 'var(--focus-color)' }}>信心度越高，建议越可靠</strong>。
            </>
          )}
        </div>
      </div>

      <Divider />

      {/* 评分详情 */}
      <Row gutter={16}>
        <Col span={6}>
          <Statistic
            title={isCoachAligned ? '趋势评分' : '技术面评分'}
            value={formatScore(scores.technical)}
            valueStyle={scoreStyle(scores.technical)}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="资金面评分"
            value={formatScore(scores.money_flow)}
            valueStyle={scoreStyle(scores.money_flow)}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title={isCoachAligned ? '策略总分' : '综合评分'}
            value={formatScore(scores.total)}
            valueStyle={scoreStyle(scores.total)}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title={isCoachAligned ? '排序评分' : '调整后评分'}
            value={formatScore(scores.adjusted)}
            valueStyle={scoreStyle(scores.adjusted)}
          />
        </Col>
      </Row>
      {isCoachAligned && !hasCoachScore && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message="当前没有智能选股策略评分"
          description={`该股未进入当前候选池，因此策略总分、排序评分显示为未评分。行情技术参考分：${formatScore(legacyScores.technical)}，资金参考分：${formatScore(legacyScores.money_flow)}，旧综合参考：${formatScore(legacyScores.total)}；这些参考分不参与最终动作。`}
        />
      )}

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
                  {positionAdvice.action}
                </Tag>
              </div>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--text-secondary)' }}>建议仓位:</span>
                <span style={{ marginLeft: 8, fontWeight: 500 }}>
                  {positionAdvice.position_size}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-secondary)' }}>建仓价格:</span>
                <span style={{ marginLeft: 8, fontWeight: 500, color: 'var(--info-color)' }}>
                  {formatPrice(positionAdvice.entry_price)}
                </span>
              </div>
            </Card>
          </Col>
          <Col span={12}>
            <Card size="small" variant="borderless" style={{ background: 'var(--bg-inset)', border: '1px solid var(--border-secondary)' }}>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--text-secondary)' }}>目标止盈:</span>
                <span style={{ marginLeft: 8, fontWeight: 500, color: 'var(--bull-color)' }}>
                  {formatPrice(positionAdvice.stop_profit)}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-secondary)' }}>设置止损:</span>
                <span style={{ marginLeft: 8, fontWeight: 500, color: 'var(--bear-color)' }}>
                  {formatPrice(positionAdvice.stop_loss)}
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
