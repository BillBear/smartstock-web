import React from 'react'
import ReactECharts from 'echarts-for-react'

const METRIC_META = [
  { key: 'technical', label: '技术面', color: '#40A9FF' },
  { key: 'moneyFlow', label: '资金面', color: '#36CFC9' },
  { key: 'fundamental', label: '基本面', color: '#FFC53D' },
  { key: 'valuation', label: '估值', color: '#B37FEB' },
]

const clampScore = (value) => {
  const n = Number(value)
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(100, Math.round(n)))
}

const scoreLevel = (value) => {
  if (value >= 85) return '优秀'
  if (value >= 70) return '良好'
  if (value >= 55) return '中性'
  return '偏弱'
}

const ScoreRadar = ({ data = {}, metricMeta = METRIC_META }) => {
  const metrics = metricMeta.map((item) => ({
    ...item,
    value: clampScore(data[item.key]),
  }))
  const values = metrics.map((item) => item.value)
  const avgScore = values.length ? Math.round(values.reduce((a, b) => a + b, 0) / values.length) : 0
  const best = metrics.reduce((prev, cur) => (cur.value > prev.value ? cur : prev), metrics[0])
  const weakest = metrics.reduce((prev, cur) => (cur.value < prev.value ? cur : prev), metrics[0])

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15, 23, 42, 0.94)',
      borderColor: 'rgba(64, 169, 255, 0.45)',
      borderWidth: 1,
      textStyle: { color: '#E6F7FF' },
      formatter: () => {
        const body = metrics
          .map((item) => `${item.label}: ${item.value} (${scoreLevel(item.value)})`)
          .join('<br/>')
        return `多维度评分<br/>${body}`
      },
    },
    radar: {
      center: ['50%', '54%'],
      radius: '68%',
      startAngle: 90,
      splitNumber: 5,
      shape: 'polygon',
      nameGap: 10,
      indicator: metrics.map((item) => ({
        name: item.label,
        max: 100,
      })),
      axisName: {
        formatter: '{label|{value}}',
        rich: {
          label: {
            color: 'rgba(230, 247, 255, 0.88)',
            fontSize: 14,
            fontWeight: 600,
            lineHeight: 16,
            align: 'center',
          },
        },
      },
      axisLine: {
        lineStyle: {
          color: 'rgba(100, 116, 139, 0.45)',
        },
      },
      splitLine: {
        lineStyle: {
          color: [
            'rgba(56, 189, 248, 0.16)',
            'rgba(56, 189, 248, 0.14)',
            'rgba(56, 189, 248, 0.12)',
            'rgba(56, 189, 248, 0.1)',
            'rgba(56, 189, 248, 0.08)',
          ],
        },
      },
      splitArea: {
        areaStyle: {
          color: [
            'rgba(7, 23, 44, 0.24)',
            'rgba(7, 23, 44, 0.16)',
            'rgba(7, 23, 44, 0.1)',
            'rgba(7, 23, 44, 0.06)',
            'rgba(7, 23, 44, 0.02)',
          ],
        },
      },
    },
    series: [
      {
        type: 'radar',
        symbol: 'circle',
        symbolSize: 9,
        data: [
          {
            value: values,
            name: '多维评分',
            lineStyle: {
              width: 3,
              color: '#22D3EE',
              shadowColor: 'rgba(34, 211, 238, 0.45)',
              shadowBlur: 12,
            },
            itemStyle: {
              color: '#BAE6FD',
              borderColor: '#38BDF8',
              borderWidth: 2,
            },
            areaStyle: {
              color: 'rgba(34, 211, 238, 0.2)',
            },
          },
        ],
      },
    ],
    animationDuration: 650,
    animationEasing: 'cubicOut',
  }

  return (
    <div className="score-radar-shell">
      <div className="score-radar-layout">
        <div className="score-radar-chart">
          <ReactECharts
            option={option}
            notMerge
            lazyUpdate
            style={{ width: '100%', height: 300 }}
          />
        </div>
        <div className="score-radar-panel">
          <div className="radar-summary-card">
            <div className="summary-main">
              <span className="summary-title">平均分</span>
              <span className="summary-score">{avgScore}</span>
            </div>
            <div className="summary-sub">
              强项：{best?.label || '-'} {best?.value || 0}分
            </div>
            <div className="summary-sub weak">
              短板：{weakest?.label || '-'} {weakest?.value || 0}分
            </div>
          </div>
          {metrics.map((item) => (
            <div key={item.key} className="radar-side-row">
              <div className="radar-side-label-wrap">
                <span className="chip-dot" style={{ background: item.color }} />
                <span className="radar-side-label">{item.label}</span>
                <span className="radar-side-level">{scoreLevel(item.value)}</span>
              </div>
              <div className="radar-side-track">
                <div
                  className="radar-side-fill"
                  style={{ width: `${item.value}%`, background: item.color }}
                />
              </div>
              <span className="radar-side-value">{item.value}分</span>
            </div>
          ))}
        </div>
      </div>
      <div className="score-radar-tip">
        提示：悬浮雷达图可查看各维度详细评分。
      </div>
    </div>
  )
}

export default ScoreRadar
