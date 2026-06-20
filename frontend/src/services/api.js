/**
 * API 服务配置
 */
import axios from 'axios'
import { message } from 'antd'

// 创建axios实例
const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    const res = response.data
    if (res.code === 200) {
      return res.data
    } else {
      message.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message || 'Error'))
    }
  },
  (error) => {
    console.error('API Error:', error)
    message.error(error.response?.data?.message || error.message || '网络错误')
    return Promise.reject(error)
  }
)

/**
 * 股票数据API
 */
export const stockApi = {
  // 获取实时行情
  getRealtime: (symbol) => {
    return api.get('/stock/realtime', { params: { symbol } })
  },

  // 搜索股票（代码/名称）
  searchStocks: (q, limit = 8) => {
    return api.get('/stock/search', { params: { q, limit } })
  },

  // 获取历史数据
  getHistory: (params) => {
    return api.get('/stock/history', { params })
  },
}

/**
 * 分析API
 */
export const analysisApi = {
  // 技术分析
  technical: (data) => {
    return api.post('/analysis/technical', data)
  },

  // 聚合分析（一次返回核心+高级分析）
  full: (data) => {
    return api.post('/analysis/full', data)
  },

  // 交易信号
  signal: (data) => {
    return api.post('/analysis/signal', data)
  },
}

/**
 * 投资建议API
 */
export const adviceApi = {
  // 获取投资建议
  getAdvice: (data) => {
    return api.post('/advice', data)
  },
}

/**
 * 资金流向API
 */
export const moneyFlowApi = {
  // 获取资金流向
  getMoneyFlow: (data) => {
    return api.post('/money-flow', data)
  },
}

/**
 * AI决策API
 */
export const aiDecisionApi = {
  // 获取AI决策
  getDecision: (data) => {
    return api.post('/ai-decision', data)
  },
}

/**
 * 投资教练API（V1）
 */
export const coachApi = {
  // 市场状态
  getMarketStateToday: () => {
    return api.get('/coach/market-state/today')
  },

  // 官方资讯列表
  getNewsEvents: (params) => {
    return api.get('/coach/news/events', { params })
  },

  // 个股关联资讯
  getSymbolNews: (symbol, params) => {
    return api.get(`/coach/news/symbol/${symbol}`, { params })
  },

  // 个股在智能选股策略中的评分上下文
  getSymbolStrategy: (symbol, params) => {
    return api.get(`/coach/symbol-strategy/${symbol}`, { params })
  },

  // 今日推荐
  getTodayPicks: (params) => {
    return api.get('/coach/picks/today', { params })
  },

  // 智能选股页摘要
  getSmartScreenSummary: (params) => {
    return api.get('/coach/smart-screen/summary', { params })
  },

  // 刷新今日推荐
  refreshTodayPicks: (params) => {
    return api.post('/coach/picks/refresh', null, { params })
  },

  // 推荐详情
  getPickDetail: (pickId, params) => {
    return api.get(`/coach/picks/${pickId}`, { params })
  },

  // 推荐机器学习解释
  getPickExplain: (pickId, params) => {
    return api.get(`/coach/picks/${pickId}/explain`, { params })
  },

  // 推荐历史
  getPickHistory: (params) => {
    return api.get('/coach/picks/history', { params })
  },

  // 推荐动作沉淀的自选池
  getWatchlist: (params) => {
    return api.get('/coach/watchlist', { params })
  },

  // 模拟持仓
  getPaperPortfolio: (params) => {
    return api.get('/coach/paper-portfolio', { params })
  },

  // 模拟交易流水
  getPaperTrades: (params) => {
    return api.get('/coach/paper-trades', { params })
  },

  // 模拟复盘摘要
  getPaperReview: (params) => {
    return api.get('/coach/paper-review', { params })
  },

  // 风险偏好
  setRiskProfile: (data, userId = 'default') => {
    return api.post('/coach/risk-profile', data, { params: { user_id: userId } })
  },

  // 策略配置模板
  getStrategyConfigOptions: (strategyCode, userId = 'default') => {
    return api.get('/coach/strategy-config/options', { params: { strategy_code: strategyCode, user_id: userId } })
  },

  // 应用策略配置到智能选股
  applyStrategyConfig: (data, userId = 'default') => {
    return api.post('/coach/strategy-config/apply', data, { params: { user_id: userId } })
  },

  // 策略证据
  getStrategyEvidence: (strategyCode, params) => {
    return api.get(`/coach/strategy/${strategyCode}/evidence`, { params })
  },

  // 提交回测
  runBacktest: (data, userId = 'default') => {
    return api.post('/coach/backtest/run', data, { params: { user_id: userId } })
  },

  // 查询回测结果
  getBacktestResult: (runId) => {
    return api.get(`/coach/backtest/${runId}`)
  },

  // 训练可解释概率模型
  trainModel: (data, userId = 'default') => {
    return api.post('/coach/models/train', data, { params: { user_id: userId } })
  },

  // 最新模型
  getLatestModel: () => {
    return api.get('/coach/models/latest')
  },

  // 模型指标
  getModelMetrics: (modelId) => {
    return api.get(`/coach/models/${modelId}/metrics`)
  },

  // 推荐动作上报
  recordPickAction: (pickId, data, userId = 'default') => {
    return api.post(`/coach/picks/${pickId}/actions`, data, { params: { user_id: userId } })
  },

  // 周复盘
  getWeeklyLessonLatest: () => {
    return api.get('/coach/lessons/weekly/latest')
  },
}

export default api
