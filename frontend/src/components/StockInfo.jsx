import React from 'react'
import { Card, Row, Col, Statistic, Tag } from 'antd'
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  StockOutlined,
  DollarOutlined,
} from '@ant-design/icons'
import { formatNumber, formatPercent, formatLargeNumber } from '../utils/format'
import './StockInfo.css'

const StockInfo = ({ data }) => {
  if (!data) return null

  const isUp = data.pct_change >= 0

  return (
    <Card className="stock-info-card card-shadow" variant="borderless">
      <div className="stock-header">
        <div>
          <h2 className="stock-title">
            {data.name}
            <span className="stock-code">{data.code}</span>
          </h2>
          <div className="stock-time">更新时间: {data.update_time}</div>
        </div>
        <div className="stock-status">
          <Tag color={isUp ? 'red' : 'green'} className="status-tag">
            {isUp ? '上涨' : '下跌'}
          </Tag>
        </div>
      </div>

      <div className="current-price stock-price-strip">
        <div className="price-main">
          <span className={`price ${isUp ? 'price-up' : 'price-down'}`}>
            ¥{formatNumber(data.price)}
          </span>
        </div>
        <div className={`change-card ${isUp ? 'change-card-up' : 'change-card-down'}`}>
          <span className="change-direction">
            {isUp ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
            {isUp ? '上涨' : '下跌'}
          </span>
          <span className="change-percent">{formatPercent(data.pct_change)}</span>
          <span className="change-amount">
            {data.change > 0 ? '+' : ''}
            {formatNumber(data.change)}
          </span>
        </div>
      </div>

      <Row gutter={16} className="stock-stats">
        <Col xs={12} sm={6}>
          <Statistic
            title="今开"
            value={formatNumber(data.open)}
            prefix="¥"
            valueStyle={{ fontSize: '16px' }}
          />
        </Col>
        <Col xs={12} sm={6}>
          <Statistic
            title="昨收"
            value={formatNumber(data.price - data.change)}
            prefix="¥"
            valueStyle={{ fontSize: '16px' }}
          />
        </Col>
        <Col xs={12} sm={6}>
          <Statistic
            title="最高"
            value={formatNumber(data.high)}
            prefix="¥"
            valueStyle={{ fontSize: '16px', color: 'var(--bull-color)' }}
          />
        </Col>
        <Col xs={12} sm={6}>
          <Statistic
            title="最低"
            value={formatNumber(data.low)}
            prefix="¥"
            valueStyle={{ fontSize: '16px', color: 'var(--bear-color)' }}
          />
        </Col>
      </Row>

      <Row gutter={16} className="stock-stats" style={{ marginTop: 16 }}>
        <Col xs={12} sm={6}>
          <div className="stat-item">
            <div className="stat-label">
              <StockOutlined /> 成交量
            </div>
            <div className="stat-value">{formatLargeNumber(data.volume)}</div>
          </div>
        </Col>
        <Col xs={12} sm={6}>
          <div className="stat-item">
            <div className="stat-label">
              <DollarOutlined /> 成交额
            </div>
            <div className="stat-value">{formatLargeNumber(data.amount)}</div>
          </div>
        </Col>
      </Row>
    </Card>
  )
}

export default StockInfo
