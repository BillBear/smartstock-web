import React, { useEffect, useRef, useState } from 'react'
import { Card, Row, Col, Tabs, Spin } from 'antd'
import * as echarts from 'echarts'

const TechnicalIndicators = ({ data, indicators }) => {
  const macdChartRef = useRef(null)
  const rsiChartRef = useRef(null)
  const kdjChartRef = useRef(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!data || data.length === 0 || !indicators) {
      setLoading(false)
      return
    }

    // 延迟初始化，确保DOM已渲染
    const timer = setTimeout(() => {
      try {
        initCharts()
        setLoading(false)
      } catch (error) {
        console.error('图表初始化失败:', error)
        setLoading(false)
      }
    }, 100)

    return () => {
      clearTimeout(timer)
      // 清理图表实例
      if (macdChartRef.current) {
        const chart = echarts.getInstanceByDom(macdChartRef.current)
        if (chart) chart.dispose()
      }
      if (rsiChartRef.current) {
        const chart = echarts.getInstanceByDom(rsiChartRef.current)
        if (chart) chart.dispose()
      }
      if (kdjChartRef.current) {
        const chart = echarts.getInstanceByDom(kdjChartRef.current)
        if (chart) chart.dispose()
      }
    }
  }, [data, indicators])

  const initCharts = () => {
    if (!macdChartRef.current || !rsiChartRef.current || !kdjChartRef.current) return

    const dates = data.map(item => item.date)
    const macdData = data.map(item => item.macd || 0)
    const signalData = data.map(item => item.macd_signal || 0)
    const histData = data.map(item => item.macd_hist || 0)
    const rsiData = data.map(item => item.rsi || 50)
    const kData = data.map(item => item.k || 50)
    const dData = data.map(item => item.d || 50)
    const jData = data.map(item => item.j || 50)

    // MACD图表
    const macdChart = echarts.init(macdChartRef.current)
    macdChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(50, 50, 50, 0.9)',
        borderColor: '#333',
        textStyle: { color: '#E8EAED' }
      },
      legend: {
        data: ['MACD', '信号线', '柱状图'],
        textStyle: { color: '#9AA0A6' },
        top: 10
      },
      grid: {
        left: '5%',
        right: '5%',
        bottom: '15%',
        top: '15%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#2A2F38' } },
        axisLabel: { color: '#9AA0A6', fontSize: 10 }
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#2A2F38' } },
        splitLine: { lineStyle: { color: '#2A2F38' } },
        axisLabel: { color: '#9AA0A6' }
      },
      series: [
        {
          name: 'MACD',
          type: 'line',
          data: macdData,
          lineStyle: { color: '#27C08A', width: 2 },
          showSymbol: false
        },
        {
          name: '信号线',
          type: 'line',
          data: signalData,
          lineStyle: { color: '#FF5550', width: 2 },
          showSymbol: false
        },
        {
          name: '柱状图',
          type: 'bar',
          data: histData,
          itemStyle: {
            color: function(params) {
              return params.value >= 0 ? '#D95F59' : '#27C08A'
            }
          }
        }
      ]
    })

    // RSI图表
    const rsiChart = echarts.init(rsiChartRef.current)
    rsiChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: '{b}<br/>RSI: {c}',
        backgroundColor: 'rgba(50, 50, 50, 0.9)',
        textStyle: { color: '#E8EAED' }
      },
      grid: {
        left: '5%',
        right: '5%',
        bottom: '10%',
        top: '10%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#2A2F38' } },
        axisLabel: { color: '#9AA0A6', fontSize: 10 }
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: '#2A2F38' } },
        splitLine: { lineStyle: { color: '#2A2F38' } },
        axisLabel: { color: '#9AA0A6' }
      },
      series: [
        {
          name: 'RSI',
          type: 'line',
          data: rsiData,
          lineStyle: { color: '#4DA3FF', width: 2 },
          showSymbol: false,
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: '#FF5550', type: 'dashed', width: 1 },
            data: [
              { yAxis: 70, label: { formatter: '超买 70', color: '#9AA0A6' } },
              { yAxis: 30, label: { formatter: '超卖 30', color: '#9AA0A6' } }
            ]
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(77, 163, 255, 0.3)' },
                { offset: 1, color: 'rgba(77, 163, 255, 0.05)' }
              ]
            }
          }
        }
      ]
    })

    // KDJ图表
    const kdjChart = echarts.init(kdjChartRef.current)
    kdjChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(50, 50, 50, 0.9)',
        textStyle: { color: '#E8EAED' }
      },
      legend: {
        data: ['K值', 'D值', 'J值'],
        textStyle: { color: '#9AA0A6' },
        top: 10
      },
      grid: {
        left: '5%',
        right: '5%',
        bottom: '15%',
        top: '15%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#2A2F38' } },
        axisLabel: { color: '#9AA0A6', fontSize: 10 }
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: '#2A2F38' } },
        splitLine: { lineStyle: { color: '#2A2F38' } },
        axisLabel: { color: '#9AA0A6' }
      },
      series: [
        {
          name: 'K值',
          type: 'line',
          data: kData,
          lineStyle: { color: '#27C08A', width: 2 },
          showSymbol: false
        },
        {
          name: 'D值',
          type: 'line',
          data: dData,
          lineStyle: { color: '#FFB020', width: 2 },
          showSymbol: false
        },
        {
          name: 'J值',
          type: 'line',
          data: jData,
          lineStyle: { color: '#A78BFA', width: 2 },
          showSymbol: false
        }
      ]
    })

    // 响应式处理
    const handleResize = () => {
      macdChart.resize()
      rsiChart.resize()
      kdjChart.resize()
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }

  if (!indicators) {
    return (
      <Card title="技术指标详情" variant="borderless">
        <div style={{ textAlign: 'center', padding: 40, color: '#9AA0A6' }}>
          暂无技术指标数据
        </div>
      </Card>
    )
  }

  const items = [
    {
      key: 'macd',
      label: 'MACD指标',
      children: (
        <Spin spinning={loading}>
          <div>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#9AA0A6', fontSize: 12 }}>MACD</div>
                  <div style={{ color: '#E8EAED', fontSize: 18, fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace' }}>
                    {indicators.macd?.toFixed(2) || '--'}
                  </div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#9AA0A6', fontSize: 12 }}>信号线</div>
                  <div style={{ color: '#E8EAED', fontSize: 18, fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace' }}>
                    {indicators.macd_signal?.toFixed(2) || '--'}
                  </div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#9AA0A6', fontSize: 12 }}>柱状图</div>
                  <div style={{
                    color: (indicators.macd_hist || 0) > 0 ? 'var(--bull-color)' : 'var(--bear-color)',
                    fontSize: 18,
                    fontWeight: 600,
                    fontFamily: 'IBM Plex Mono, monospace'
                  }}>
                    {indicators.macd_hist?.toFixed(2) || '--'}
                  </div>
                </div>
              </Col>
            </Row>
            <div ref={macdChartRef} style={{ width: '100%', height: '300px' }} />
          </div>
        </Spin>
      )
    },
    {
      key: 'rsi',
      label: 'RSI指标',
      children: (
        <Spin spinning={loading}>
          <div>
            <div style={{ textAlign: 'center', marginBottom: 16 }}>
              <div style={{ color: '#9AA0A6', fontSize: 12 }}>RSI值</div>
              <div style={{
                color: indicators.rsi > 70 ? 'var(--bear-color)' : indicators.rsi < 30 ? 'var(--bull-color)' : 'var(--info-color)',
                fontSize: 32,
                fontWeight: 700,
                fontFamily: 'IBM Plex Mono, monospace'
              }}>
                {indicators.rsi?.toFixed(1) || '--'}
              </div>
              <div style={{ color: '#9AA0A6', fontSize: 12, marginTop: 4 }}>
                {indicators.rsi > 70 ? '超买区域' : indicators.rsi < 30 ? '超卖区域' : '正常区域'}
              </div>
            </div>
            <div ref={rsiChartRef} style={{ width: '100%', height: '300px' }} />
          </div>
        </Spin>
      )
    },
    {
      key: 'kdj',
      label: 'KDJ指标',
      children: (
        <Spin spinning={loading}>
          <div>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#9AA0A6', fontSize: 12 }}>K值</div>
                  <div style={{ color: 'var(--bull-color)', fontSize: 18, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                    {indicators.k?.toFixed(1) || '--'}
                  </div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#9AA0A6', fontSize: 12 }}>D值</div>
                  <div style={{ color: '#FFB020', fontSize: 18, fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace' }}>
                    {indicators.d?.toFixed(1) || '--'}
                  </div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#9AA0A6', fontSize: 12 }}>J值</div>
                  <div style={{ color: '#A78BFA', fontSize: 18, fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace' }}>
                    {indicators.j?.toFixed(1) || '--'}
                  </div>
                </div>
              </Col>
            </Row>
            <div ref={kdjChartRef} style={{ width: '100%', height: '300px' }} />
          </div>
        </Spin>
      )
    }
  ]

  return (
    <Card title="技术指标详情" variant="borderless" style={{ background: 'var(--bg-card)' }}>
      <Tabs defaultActiveKey="macd" items={items} />
    </Card>
  )
}

export default TechnicalIndicators
