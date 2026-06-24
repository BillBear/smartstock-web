import React from 'react'
import { Card, Row, Col, Alert, Divider, Tag, Progress } from 'antd'
import {
  RiseOutlined,
  FallOutlined,
  MinusOutlined,
  WarningOutlined,
  CheckCircleOutlined
} from '@ant-design/icons'
import './TechnicalPanel.css'

const TechnicalPanel = ({ indicators, signalAnalysis }) => {
  if (!indicators || !signalAnalysis) return null

  // 解读MACD
  const getMACDExplanation = () => {
    const { macd, macd_signal, macd_hist } = indicators
    if (macd_hist > 0 && macd > macd_signal) {
      return { signal: '看涨', color: 'var(--bull-color)', icon: <RiseOutlined />, desc: 'MACD金叉，短期趋势向上，可以考虑买入' }
    } else if (macd_hist < 0 && macd < macd_signal) {
      return { signal: '看跌', color: 'var(--bear-color)', icon: <FallOutlined />, desc: 'MACD死叉，短期趋势向下，建议观望或减仓' }
    }
    return { signal: '中性', color: 'var(--warning-color)', icon: <MinusOutlined />, desc: 'MACD处于震荡区间，等待明确信号' }
  }

  // 解读RSI
  const getRSIExplanation = () => {
    const { rsi } = indicators
    if (rsi > 70) {
      return { signal: '超买', color: 'var(--bear-color)', icon: <WarningOutlined />, desc: `RSI=${rsi.toFixed(1)}，市场过热，股价可能回调，不建议追高` }
    } else if (rsi < 30) {
      return { signal: '超卖', color: 'var(--bull-color)', icon: <CheckCircleOutlined />, desc: `RSI=${rsi.toFixed(1)}，市场超卖，股价可能反弹，可以关注买入机会` }
    }
    return { signal: '正常', color: 'var(--info-color)', icon: <CheckCircleOutlined />, desc: `RSI=${rsi.toFixed(1)}，市场情绪正常，可以结合其他指标判断` }
  }

  // 解读KDJ
  const getKDJExplanation = () => {
    const { k, d, j } = indicators
    if (k > 80 && d > 80) {
      return { signal: '超买', color: 'var(--bear-color)', desc: 'KDJ高位，短期可能回调' }
    } else if (k < 20 && d < 20) {
      return { signal: '超卖', color: 'var(--bull-color)', desc: 'KDJ低位，短期可能反弹' }
    } else if (k > d && j > k) {
      return { signal: '金叉', color: 'var(--bull-color)', desc: 'KDJ金叉形成，短线看涨' }
    } else if (k < d && j < k) {
      return { signal: '死叉', color: 'var(--bear-color)', desc: 'KDJ死叉形成，短线看跌' }
    }
    return { signal: '震荡', color: 'var(--warning-color)', desc: 'KDJ震荡中，等待方向' }
  }

  // 综合建议
  const getOverallAdvice = () => {
    const score = signalAnalysis.score || 0
    const macd = getMACDExplanation()
    const rsi = getRSIExplanation()
    const kdj = getKDJExplanation()

    let action, actionColor, actionIcon, reason

    if (score > 30) {
      action = '买入'
      actionColor = 'var(--bull-color)'
      actionIcon = <RiseOutlined />
      reason = '多个指标显示上涨信号，短期趋势向好'
    } else if (score < -30) {
      action = '卖出'
      actionColor = 'var(--bear-color)'
      actionIcon = <FallOutlined />
      reason = '多个指标显示下跌信号，建议减仓规避风险'
    } else {
      action = '观望'
      actionColor = 'var(--warning-color)'
      actionIcon = <MinusOutlined />
      reason = '指标信号不明确，建议等待更清晰的趋势'
    }

    return { action, actionColor, actionIcon, reason, macd, rsi, kdj }
  }

  const advice = getOverallAdvice()

  return (
    <Card
      title="交易信号分析"
      className="technical-panel-card"
      variant="borderless"
    >
      {/* 综合建议 */}
      <Alert
        message={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: advice.actionColor }}>
              {advice.actionIcon} 综合建议：{advice.action}
            </span>
            <Tag color={advice.action === '买入' ? 'red' : advice.action === '卖出' ? 'green' : 'warning'}>
              评分：{signalAnalysis.score}
            </Tag>
          </div>
        }
        description={
          <div style={{ marginTop: 8, fontSize: 14 }}>
            <div style={{ marginBottom: 8 }}><strong>原因：</strong>{advice.reason}</div>
            <div style={{ color: 'var(--text-secondary)' }}>
              提示：建议结合基本面和资金流向综合判断，不要仅依赖技术指标
            </div>
          </div>
        }
        type={advice.action === '买入' ? 'success' : advice.action === '卖出' ? 'error' : 'warning'}
        showIcon
        style={{ marginBottom: 24 }}
      />

      {/* 趋势判断 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
          市场趋势
        </div>
        <Tag color={signalAnalysis.trend === '上升' ? 'success' : 'error'} style={{ fontSize: 14, padding: '4px 12px' }}>
          当前趋势：{signalAnalysis.trend}
        </Tag>
      </div>

      <Divider />

      {/* 指标详细解读 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 16 }}>
          📚 指标详解（小白必看）
        </div>

        <Row gutter={[16, 16]}>
          {/* MACD解读 */}
          <Col span={24}>
            <div className="indicator-explanation">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                    MACD指标
                  </span>
                  <Tag color={advice.macd.color} icon={advice.macd.icon}>
                    {advice.macd.signal}
                  </Tag>
                </div>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  值: {indicators.macd?.toFixed(2)}
                </span>
              </div>
              <div style={{
                background: 'var(--bg-elevated)',
                padding: 12,
                borderRadius: 6,
                borderLeft: `3px solid ${advice.macd.color}`
              }}>
                <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
                  <strong style={{ color: 'var(--text-primary)' }}>什么是MACD？</strong>
                  MACD是判断趋势的指标，像股票的"体温计"。
                </div>
                <div style={{ fontSize: 14, color: advice.macd.color, fontWeight: 500 }}>
                  {advice.macd.desc}
                </div>
              </div>
            </div>
          </Col>

          {/* RSI解读 */}
          <Col span={24}>
            <div className="indicator-explanation">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                    RSI指标
                  </span>
                  <Tag color={advice.rsi.color} icon={advice.rsi.icon}>
                    {advice.rsi.signal}
                  </Tag>
                </div>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  值: {indicators.rsi?.toFixed(1)}
                </span>
              </div>
              <div style={{
                background: 'var(--bg-elevated)',
                padding: 12,
                borderRadius: 6,
                borderLeft: `3px solid ${advice.rsi.color}`
              }}>
                <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
                  <strong style={{ color: 'var(--text-primary)' }}>什么是RSI？</strong>
                  RSI是判断超买超卖的指标，范围0-100。＞70超买（太贵），＜30超卖（太便宜）。
                </div>
                <div style={{ marginBottom: 8 }}>
                  <Progress
                    percent={indicators.rsi}
                    strokeColor={advice.rsi.color}
                    showInfo={false}
                  />
                </div>
                <div style={{ fontSize: 14, color: advice.rsi.color, fontWeight: 500 }}>
                  {advice.rsi.desc}
                </div>
              </div>
            </div>
          </Col>

          {/* KDJ解读 */}
          <Col span={24}>
            <div className="indicator-explanation">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                    KDJ指标
                  </span>
                  <Tag color={advice.kdj.color}>
                    {advice.kdj.signal}
                  </Tag>
                </div>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  K:{indicators.k?.toFixed(1)} D:{indicators.d?.toFixed(1)} J:{indicators.j?.toFixed(1)}
                </span>
              </div>
              <div style={{
                background: 'var(--bg-elevated)',
                padding: 12,
                borderRadius: 6,
                borderLeft: `3px solid ${advice.kdj.color}`
              }}>
                <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
                  <strong style={{ color: 'var(--text-primary)' }}>什么是KDJ？</strong>
                  KDJ是判断短线买卖点的指标。K线上穿D线=金叉（买入信号），K线下穿D线=死叉（卖出信号）。
                </div>
                <div style={{ fontSize: 14, color: advice.kdj.color, fontWeight: 500 }}>
                  {advice.kdj.desc}
                </div>
              </div>
            </div>
          </Col>
        </Row>
      </div>

      <Divider />

      {/* 详细信号列表 */}
      <div>
        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
          🔍 详细信号
        </div>
        <div className="signal-details">
          {signalAnalysis.signals && signalAnalysis.signals.map((signal, index) => (
            <div key={index} className="signal-item">
              <span className="signal-bullet">•</span>
              <span>{signal}</span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  )
}

export default TechnicalPanel
