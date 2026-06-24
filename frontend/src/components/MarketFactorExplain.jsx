import React from 'react'
import { Card, Collapse, Progress, Row, Col, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'

const FACTOR_META = {
  trend_score: {
    label: '趋势',
    formula: 'trend_score = clamp(50 + avg_change * 4, 0, 100)',
    meaning: '样本股票平均涨跌幅越高，趋势分越高。',
  },
  breadth_score: {
    label: '宽度',
    formula: 'breadth_score = clamp(up_ratio * 100, 0, 100)',
    meaning: '样本中上涨家数占比越高，市场宽度分越高。',
  },
  money_flow_score: {
    label: '资金',
    formula: 'money_flow_score = clamp(45 + avg_change * 3, 0, 100)',
    meaning: '当前版本用涨跌幅作为资金强弱近似量，分值越高代表资金环境偏强。',
  },
  risk_score: {
    label: '风险',
    formula: 'risk_score = clamp(65 - abs(avg_change) * 4, 0, 100)',
    meaning: '波动越大，风险分越低；分值高表示短期环境更可控。',
  },
  news_score: {
    label: '资讯',
    formula: 'news_score = 50 + policy_net（基于国务院/央行/证监会/发改委/工信部/交易所/公告结构化事件聚合）',
    meaning: '使用官方政策、监管、产业和公告事件聚合得到的资讯温度，分值越高表示政策与事件环境越偏正面。',
  },
}

const scoreColor = (value) => {
  if (value >= 65) return '#D95F59'
  if (value >= 45) return '#D7A84A'
  return '#27C08A'
}

const MarketFactorExplain = ({ drivers, loadedAt, mode = 'dashboard' }) => {
  const tips = mode === 'smart-screen'
    ? '更新触发：进入页面、切换风险等级或点击刷新。筛选结果同风险等级缓存约180秒；底层实时行情缓存约20秒。'
    : '更新触发：进入页面或点击刷新。底层实时行情缓存约20秒。'

  return (
    <Card
      className="data-table-card"
      variant="borderless"
      style={{ marginBottom: 16 }}
      title={(
        <span>
          因子定义与计算口径
          <Tooltip title="当前版本为V1简化口径，后续可升级为指数级宽度/北向资金/波动率等更完整因子">
            <InfoCircleOutlined style={{ marginLeft: 8 }} />
          </Tooltip>
        </span>
      )}
    >
      <Row gutter={[12, 12]}>
        {Object.entries(FACTOR_META).map(([key, meta]) => {
          const value = Number(drivers?.[key] || 0)
          return (
            <Col xs={24} md={12} key={key}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{meta.label}评分: {value.toFixed(2)}</div>
              <Progress percent={value} size="small" strokeColor={scoreColor(value)} />
              <div style={{ color: 'rgba(255,255,255,0.85)', marginTop: 6 }}>{meta.meaning}</div>
              <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: 12, marginTop: 4 }}>{meta.formula}</div>
            </Col>
          )
        })}
      </Row>

      <Collapse
        style={{ marginTop: 12 }}
        items={[
          {
            key: 'basis',
            label: '查看完整计算口径与周期说明',
            children: (
              <div style={{ color: 'rgba(255,255,255,0.78)', lineHeight: 1.8 }}>
                <div>样本池：000001、000333、002594、300750、600519、601318（6只）</div>
                <div>avg_change：样本平均涨跌幅；up_ratio：样本上涨占比</div>
                <div>综合评分：state_score = 0.28*趋势 + 0.22*宽度 + 0.16*资金 + 0.16*风险 + 0.18*资讯</div>
                <div>{tips}</div>
                <div>本次页面数据时间：{loadedAt || '-'}</div>
              </div>
            ),
          },
        ]}
      />
    </Card>
  )
}

export default MarketFactorExplain
