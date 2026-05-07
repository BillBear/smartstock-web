import React, { useEffect, useRef } from 'react'
import { Card } from 'antd'
import * as echarts from 'echarts'
import './KLineChart.css'

const KLineChart = ({ data, indicators }) => {
  const chartRef = useRef(null)
  const chartInstance = useRef(null)

  useEffect(() => {
    if (!data || data.length === 0) return

    // 初始化图表
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current)
    }

    // 准备数据
    const dates = data.map(item => item.date)
    const values = data.map(item => [
      item.open,
      item.close,
      item.low,
      item.high
    ])
    const volumes = data.map(item => item.volume)

    // MA数据
    const ma5Data = data.map(item => item.ma5 || null)
    const ma10Data = data.map(item => item.ma10 || null)
    const ma20Data = data.map(item => item.ma20 || null)

    // 配置项
    const option = {
      backgroundColor: '#fff',
      animation: true,
      legend: {
        data: ['K线', 'MA5', 'MA10', 'MA20', '成交量'],
        top: 10,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross'
        },
        backgroundColor: 'rgba(255, 255, 255, 0.95)',
        borderColor: '#ccc',
        borderWidth: 1,
        textStyle: {
          color: '#000'
        },
        formatter: function (params) {
          let result = params[0].axisValue + '<br/>'
          params.forEach(item => {
            if (item.seriesName === 'K线') {
              result += `开盘: ${item.data[1]}<br/>`
              result += `收盘: ${item.data[2]}<br/>`
              result += `最低: ${item.data[3]}<br/>`
              result += `最高: ${item.data[4]}<br/>`
            } else {
              result += `${item.marker}${item.seriesName}: ${item.data || '--'}<br/>`
            }
          })
          return result
        }
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
        label: {
          backgroundColor: '#777'
        }
      },
      grid: [
        {
          left: '10%',
          right: '8%',
          top: '12%',
          height: '50%'
        },
        {
          left: '10%',
          right: '8%',
          top: '68%',
          height: '18%'
        }
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          scale: true,
          boundaryGap: true,
          axisLine: { onZero: false },
          splitLine: { show: false },
          min: 'dataMin',
          max: 'dataMax',
          axisPointer: {
            z: 100
          }
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          scale: true,
          boundaryGap: true,
          axisLine: { onZero: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          min: 'dataMin',
          max: 'dataMax'
        }
      ],
      yAxis: [
        {
          scale: true,
          splitArea: {
            show: true
          }
        },
        {
          scale: true,
          gridIndex: 1,
          splitNumber: 2,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: false }
        }
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 70,
          end: 100
        },
        {
          show: true,
          xAxisIndex: [0, 1],
          type: 'slider',
          top: '90%',
          start: 70,
          end: 100
        }
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: values,
          itemStyle: {
            color: '#ef232a',
            color0: '#14b143',
            borderColor: '#ef232a',
            borderColor0: '#14b143'
          }
        },
        {
          name: 'MA5',
          type: 'line',
          data: ma5Data,
          smooth: true,
          lineStyle: {
            opacity: 0.8,
            width: 1.5
          },
          itemStyle: {
            color: '#f5a623'
          },
          showSymbol: false
        },
        {
          name: 'MA10',
          type: 'line',
          data: ma10Data,
          smooth: true,
          lineStyle: {
            opacity: 0.8,
            width: 1.5
          },
          itemStyle: {
            color: '#bd10e0'
          },
          showSymbol: false
        },
        {
          name: 'MA20',
          type: 'line',
          data: ma20Data,
          smooth: true,
          lineStyle: {
            opacity: 0.8,
            width: 1.5
          },
          itemStyle: {
            color: '#4a90e2'
          },
          showSymbol: false
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          itemStyle: {
            color: function (params) {
              const dataIndex = params.dataIndex
              if (dataIndex === 0) return '#14b143'
              return values[dataIndex][1] > values[dataIndex][0]
                ? '#ef232a'
                : '#14b143'
            }
          }
        }
      ]
    }

    chartInstance.current.setOption(option)

    // 响应式
    const handleResize = () => {
      chartInstance.current?.resize()
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [data, indicators])

  return (
    <Card title="K线图表" className="kline-chart-card card-shadow" variant="borderless">
      <div ref={chartRef} style={{ width: '100%', height: '500px' }} />
    </Card>
  )
}

export default KLineChart
