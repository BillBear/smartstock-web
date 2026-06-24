import React from 'react'
import { Card, Tag, Alert, Divider, Row, Col } from 'antd'
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  RiseOutlined,
  FallOutlined,
  DollarOutlined,
  SafetyOutlined,
  BulbOutlined,
  RocketOutlined
} from '@ant-design/icons'
import { getSignalClass } from '../utils/format'
import './AdvicePanel.css'

const AdvicePanel = ({ advice }) => {
  if (!advice) return null

  const { signal_analysis, advice: adviceData, risk_warning } = advice

  // 获取信号颜色
  const getSignalColor = (signal) => {
    if (signal.includes('强烈买入') || signal.includes('买入')) return 'var(--bull-color)'
    if (signal.includes('卖出')) return 'var(--bear-color)'
    return 'var(--warning-color)'
  }

  const signalColor = getSignalColor(signal_analysis.overall_signal)

  return (
    <Card
      title="投资建议（小白版）"
      className="advice-panel-card"
      variant="borderless"
    >
      {/* 核心建议 */}
      <Alert
        message={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: signalColor }}>
              <RocketOutlined /> 当前建议：{signal_analysis.overall_signal}
            </span>
            <Tag color={adviceData.signal?.includes('买入') ? 'red' : adviceData.signal?.includes('卖出') ? 'green' : 'warning'}>
              {adviceData.entry.action}
            </Tag>
          </div>
        }
        description={
          <div style={{ marginTop: 8, fontSize: 14 }}>
            <div style={{ marginBottom: 8 }}>
              <strong>推荐仓位：</strong>
              <span style={{ color: '#4DA3FF', fontWeight: 600, fontSize: 16, marginLeft: 8 }}>
                {adviceData.entry.position_size}
              </span>
            </div>
            <div style={{ color: 'var(--text-secondary)' }}>
              <BulbOutlined /> 建议：{adviceData.entry.strategy}
            </div>
          </div>
        }
        type={signal_analysis.overall_signal.includes('买入') ? 'success' : signal_analysis.overall_signal.includes('卖出') ? 'error' : 'warning'}
        showIcon
        style={{ marginBottom: 24 }}
      />

      {/* 新手指南 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 16 }}>
          📚 投资术语解释（小白必看）
        </div>

        <Row gutter={[16, 16]}>
          {/* 建仓解释 */}
          <Col span={24}>
            <div style={{
              background: 'var(--bg-elevated)',
              padding: 16,
              borderRadius: 8,
              borderLeft: `3px solid #4DA3FF`
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <CheckCircleOutlined style={{ color: '#4DA3FF', fontSize: 16 }} />
                <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                  什么是建仓？
                </span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                建仓就是<strong style={{ color: 'var(--text-primary)' }}>第一次买入股票</strong>。就像你去超市买东西，建仓就是把商品放进购物车。
              </div>
              <div style={{ fontSize: 14, color: '#4DA3FF', fontWeight: 500 }}>
                建议价位：{adviceData.entry.entry_price} | 仓位：{adviceData.entry.position_size}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8 }}>
                策略：{adviceData.entry.strategy}
              </div>
            </div>
          </Col>

          {/* 止盈解释 */}
          <Col span={24}>
            <div style={{
              background: 'var(--bg-elevated)',
              padding: 16,
              borderRadius: 8,
              border: '1px solid var(--border-secondary)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <RiseOutlined style={{ color: 'var(--bull-color)', fontSize: 16 }} />
                <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                  什么是止盈？
                </span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                止盈就是<strong style={{ color: 'var(--text-primary)' }}>赚够了就卖出</strong>。设定一个目标价格，涨到这个价格就卖掉赚钱，别太贪心！
              </div>
              <div style={{ fontSize: 14, color: 'var(--bull-color)', fontWeight: 500 }}>
                目标收益：{adviceData.take_profit.target_return} | 目标价：¥{adviceData.take_profit.target_price}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8 }}>
                策略：{adviceData.take_profit.strategy}
              </div>
            </div>
          </Col>

          {/* 止损解释 */}
          <Col span={24}>
            <div style={{
              background: 'var(--bg-elevated)',
              padding: 16,
              borderRadius: 8,
              borderLeft: `3px solid #FF5550`
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <FallOutlined style={{ color: '#FF5550', fontSize: 16 }} />
                <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                  什么是止损？
                </span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                止损就是<strong style={{ color: 'var(--text-primary)' }}>亏太多就卖出止血</strong>。设定一个底线价格，跌到这个价格就卖掉，防止亏更多！
              </div>
              <div style={{ fontSize: 14, color: '#FF5550', fontWeight: 500 }}>
                止损比例：{adviceData.stop_loss.stop_loss_ratio} | 止损价：¥{adviceData.stop_loss.stop_loss_price}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8 }}>
                策略：{adviceData.stop_loss.strategy}
              </div>
            </div>
          </Col>

          {/* 加仓解释 */}
          <Col span={24}>
            <div style={{
              background: 'var(--bg-elevated)',
              padding: 16,
              borderRadius: 8,
              borderLeft: `3px solid #FFB020`
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <DollarOutlined style={{ color: '#FFB020', fontSize: 16 }} />
                <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                  什么是加仓？
                </span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                加仓就是<strong style={{ color: 'var(--text-primary)' }}>趋势好的时候再买一些</strong>。就像你发现商品在打折，再多买一点囤货。
              </div>
              <div style={{ fontSize: 14, color: '#FFB020', fontWeight: 500 }}>
                加仓条件：{adviceData.add_position.condition}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8 }}>
                加仓仓位：{adviceData.add_position.size}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
                策略：{adviceData.add_position.strategy}
              </div>
            </div>
          </Col>
        </Row>
      </div>

      <Divider />

      {/* 风险提示 */}
      <div>
        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
          风险提示（必读）
        </div>
        <Alert
          message="投资有风险，入市需谨慎"
          description={
            <ul className="risk-list">
              {risk_warning.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          }
          type="warning"
          showIcon
          icon={<SafetyOutlined />}
        />
      </div>

      <div className="advice-footer">
        生成时间: {advice.generated_at}
      </div>
    </Card>
  )
}

export default AdvicePanel
