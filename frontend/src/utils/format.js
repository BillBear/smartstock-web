/**
 * 工具函数
 */

/**
 * 格式化数字
 */
export const formatNumber = (num, precision = 2) => {
  if (num === null || num === undefined || isNaN(num)) return '--'
  return Number(num).toFixed(precision)
}

/**
 * 格式化大数字（成交量、成交额）
 */
export const formatLargeNumber = (num) => {
  if (num === null || num === undefined || isNaN(num)) return '--'

  if (num >= 100000000) {
    return (num / 100000000).toFixed(2) + '亿'
  } else if (num >= 10000) {
    return (num / 10000).toFixed(2) + '万'
  }
  return num.toFixed(2)
}

/**
 * 格式化涨跌幅
 */
export const formatPercent = (num) => {
  if (num === null || num === undefined || isNaN(num)) return '--'
  const formatted = num.toFixed(2)
  return num > 0 ? `+${formatted}%` : `${formatted}%`
}

/**
 * 获取涨跌颜色类名
 */
export const getTrendClass = (value) => {
  if (value > 0) return 'trend-up'
  if (value < 0) return 'trend-down'
  return ''
}

/**
 * 获取信号徽章类名
 */
export const getSignalClass = (signal) => {
  const signalMap = {
    '强烈买入': 'buy-strong',
    '买入': 'buy',
    '谨慎买入': 'buy',
    '观望': 'hold',
    '谨慎卖出': 'sell',
    '卖出': 'sell',
  }
  return signalMap[signal] || 'hold'
}

/**
 * 验证股票代码
 */
export const validateStockCode = (code) => {
  if (!code) return false
  // A股代码：6位数字
  return /^\d{6}$/.test(code)
}

/**
 * 获取股票代码提示
 */
export const getStockCodePlaceholder = () => {
  const examples = [
    '000001 平安银行',
    '600519 贵州茅台',
    '000858 五粮液',
    '002594 比亚迪',
  ]
  return examples[Math.floor(Math.random() * examples.length)]
}
