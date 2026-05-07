import React, { useRef, useState } from 'react'
import {
  AutoComplete,
  Layout,
  Input,
  Button,
  Select,
  Form,
  Row,
  Col,
  Card,
  message,
  Spin,
  Empty,
  Tabs,
} from 'antd'
import {
  SearchOutlined,
  StockOutlined,
  LineChartOutlined,
  BulbOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import StockInfo from '../components/StockInfo'
import KLineChart from '../components/KLineChart'
import TechnicalPanel from '../components/TechnicalPanel'
import TechnicalIndicators from '../components/TechnicalIndicators'
import AdvicePanel from '../components/AdvicePanel'
import MoneyFlowPanel from '../components/MoneyFlowPanel'
import AIDecisionPanel from '../components/AIDecisionPanel'
import { stockApi, analysisApi, adviceApi, moneyFlowApi, aiDecisionApi } from '../services/api'
import { getStockCodePlaceholder } from '../utils/format'
import './Home.css'

const { Header, Content, Footer } = Layout
const { Option } = Select

const Home = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [advancedLoading, setAdvancedLoading] = useState(false)
  const [stockData, setStockData] = useState(null)
  const [historyData, setHistoryData] = useState([])
  const [indicators, setIndicators] = useState(null)
  const [signalAnalysis, setSignalAnalysis] = useState(null)
  const [advice, setAdvice] = useState(null)
  const [moneyFlow, setMoneyFlow] = useState(null)
  const [aiDecision, setAiDecision] = useState(null)
  const [activeTab, setActiveTab] = useState('1')
  const [stockOptions, setStockOptions] = useState([])
  const optionReqRef = useRef(0)

  const handleKeywordSearch = async (value) => {
    const keyword = String(value || '').trim()
    const reqId = optionReqRef.current + 1
    optionReqRef.current = reqId
    if (!keyword) {
      setStockOptions([])
      return
    }
    try {
      const payload = await stockApi.searchStocks(keyword, 8)
      if (reqId !== optionReqRef.current) return
      const items = payload?.items || []
      setStockOptions(
        items.map((item) => ({
          value: item.symbol,
          label: (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <span>{item.name} ({item.symbol})</span>
              <span style={{ color: '#8c8c8c', fontSize: 12 }}>{item.industry || '未知行业'}</span>
            </div>
          ),
          meta: item,
        }))
      )
    } catch (error) {
      if (reqId !== optionReqRef.current) return
      setStockOptions([])
    }
  }

  const resolveSymbolInput = async (rawInput) => {
    const input = String(rawInput || '').trim()
    if (!input) {
      throw new Error('请输入股票代码或名称')
    }
    if (/^\d{6}$/.test(input)) {
      return input
    }
    const payload = await stockApi.searchStocks(input, 8)
    const items = payload?.items || []
    const exact = items.find(
      (item) => item.symbol === input || String(item.name || '').trim() === input
    )
    const matched = exact || items[0]
    if (!matched?.symbol) {
      throw new Error(`未找到匹配股票: ${input}`)
    }
    form.setFieldValue('symbol', matched.symbol)
    if (!exact) {
      message.info(`已匹配到 ${matched.name}（${matched.symbol}）`)
    }
    return matched.symbol
  }

  // 查询股票 - 一次性获取所有数据
  const handleSearch = async (values) => {
    const { symbol: rawSymbol, holding_period, risk_level, target_return } = values

    setLoading(true)
    setStockData(null)
    setHistoryData([])
    setIndicators(null)
    setSignalAnalysis(null)
    setAdvice(null)
    setMoneyFlow(null)
    setAiDecision(null)
    setAdvancedLoading(false)

    try {
      const symbol = await resolveSymbolInput(rawSymbol)
      // 第一阶段：核心数据并行加载（先让页面可用）
      const [realtimeData, technicalData] = await Promise.all([
        stockApi.getRealtime(symbol),
        analysisApi.technical({
          symbol,
          period: 'daily',
          days: 120,
        }),
      ])

      setHistoryData(technicalData.history_data)
      setIndicators(technicalData.latest_indicators)
      setStockData(realtimeData)
      setLoading(false)
      setAdvancedLoading(true)

      // 第二阶段：深度分析并行加载（结果逐步补齐）
      const signalTask = analysisApi
        .signal({ symbol })
        .then((signalData) => {
          setSignalAnalysis(signalData.signal_analysis)
        })
        .catch((error) => {
          console.error('获取交易信号失败:', error)
        })

      const moneyFlowTask = moneyFlowApi
        .getMoneyFlow({ symbol, days: 5 })
        .then((flowData) => {
          setMoneyFlow(flowData)
        })
        .catch((error) => {
          console.error('获取资金流向失败:', error)
        })

      const adviceTask = adviceApi
        .getAdvice({
          symbol,
          holding_period,
          risk_level,
          target_return,
        })
        .then((adviceData) => {
          setAdvice(adviceData)
        })
        .catch((error) => {
          console.error('获取投资建议失败:', error)
        })

      const aiTask = aiDecisionApi
        .getDecision({
          symbol,
          holding_period,
          risk_level,
        })
        .then((decisionData) => {
          setAiDecision(decisionData)
        })
        .catch((error) => {
          console.error('获取AI决策失败:', error)
        })

      await Promise.allSettled([signalTask, moneyFlowTask, adviceTask, aiTask])
      message.success('数据加载成功')
    } catch (error) {
      console.error('查询失败:', error)
      message.error('查询失败，请检查股票代码或稍后重试')
      setStockData(null)
      setHistoryData([])
      setIndicators(null)
      setSignalAnalysis(null)
      setAdvice(null)
      setMoneyFlow(null)
      setAiDecision(null)
    } finally {
      setLoading(false)
      setAdvancedLoading(false)
    }
  }

  // Tab切换 - 仅用于切换显示，不加载数据
  const handleTabChange = (key) => {
    setActiveTab(key)
  }

  const renderAdvancedLoadingCard = (tip) => (
    <Card className="card-shadow" variant="borderless">
      <Spin tip={tip} />
    </Card>
  )

  const renderAdvancedEmptyCard = (description) => (
    <Card className="card-shadow" variant="borderless">
      <Empty description={description} image={Empty.PRESENTED_IMAGE_SIMPLE} />
    </Card>
  )

  return (
    <Layout className="app-layout">
      {/* 主内容 */}
      <Content className="app-content">
        <div className="content-wrapper">
          {/* 搜索区域 */}
          <Card className="search-card card-shadow" variant="borderless">
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSearch}
              initialValues={{
                holding_period: 'medium',
                risk_level: 'medium',
                target_return: 15,
              }}
            >
              <Row gutter={16}>
                <Col xs={24} sm={12} md={8}>
                  <Form.Item
                    label="股票代码 / 名称"
                    name="symbol"
                    rules={[{ required: true, message: '请输入股票代码或名称' }]}
                  >
                    <AutoComplete
                      options={stockOptions}
                      onSearch={handleKeywordSearch}
                      onSelect={(value) => form.setFieldValue('symbol', value)}
                      filterOption={false}
                    >
                      <Input
                        size="large"
                        placeholder={getStockCodePlaceholder()}
                        prefix={<SearchOutlined />}
                        allowClear
                      />
                    </AutoComplete>
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12} md={4}>
                  <Form.Item label="持有周期" name="holding_period">
                    <Select size="large">
                      <Option value="short">短期(1-7天)</Option>
                      <Option value="medium">中期(1-3月)</Option>
                      <Option value="long">长期(3月+)</Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12} md={4}>
                  <Form.Item label="风险等级" name="risk_level">
                    <Select size="large">
                      <Option value="low">低风险</Option>
                      <Option value="medium">中等风险</Option>
                      <Option value="high">高风险</Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12} md={4}>
                  <Form.Item label="目标收益(%)" name="target_return">
                    <Input size="large" type="number" min={0} max={100} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={4}>
                  <Form.Item label=" ">
                    <Button
                      type="primary"
                      size="large"
                      icon={<SearchOutlined />}
                      htmlType="submit"
                      loading={loading || advancedLoading}
                      block
                    >
                      查询分析
                    </Button>
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Card>

          {/* 加载中 */}
          {loading && (
            <Card className="loading-card card-shadow" variant="borderless">
              <Spin size="large" tip="正在加载核心数据，请稍候..." />
            </Card>
          )}

          {/* 股票信息和分析结果 */}
          {!loading && stockData && (
            <div>
              <StockInfo data={stockData} />

              {/* 标签页 */}
              <Tabs
                activeKey={activeTab}
                onChange={handleTabChange}
                size="large"
                items={[
                  {
                    key: '1',
                    label: (
                      <span>
                        <LineChartOutlined /> K线图表
                      </span>
                    ),
                    children: historyData.length > 0 && (
                      <KLineChart data={historyData} indicators={indicators} />
                    ),
                  },
                  {
                    key: '2',
                    label: (
                      <span>
                        <StockOutlined /> 技术指标
                      </span>
                    ),
                    children: historyData.length > 0 && indicators && (
                      <TechnicalIndicators data={historyData} indicators={indicators} />
                    ),
                  },
                  {
                    key: '3',
                    label: (
                      <span>
                        <RocketOutlined /> 交易信号
                      </span>
                    ),
                    children: signalAnalysis ? (
                      <TechnicalPanel
                        indicators={indicators}
                        signalAnalysis={signalAnalysis}
                      />
                    ) : advancedLoading ? (
                      renderAdvancedLoadingCard('正在生成交易信号...')
                    ) : (
                      renderAdvancedEmptyCard('暂无交易信号数据')
                    ),
                  },
                  {
                    key: '4',
                    label: (
                      <span>
                        <BulbOutlined /> 投资建议
                      </span>
                    ),
                    children: advice ? (
                      <AdvicePanel advice={advice} />
                    ) : advancedLoading ? (
                      renderAdvancedLoadingCard('正在生成投资建议...')
                    ) : (
                      renderAdvancedEmptyCard('暂无投资建议数据')
                    ),
                  },
                  {
                    key: '5',
                    label: (
                      <span>
                        <RocketOutlined /> AI决策
                      </span>
                    ),
                    children: aiDecision ? (
                      <AIDecisionPanel data={aiDecision} />
                    ) : advancedLoading ? (
                      renderAdvancedLoadingCard('正在生成AI决策...')
                    ) : (
                      renderAdvancedEmptyCard('暂无AI决策数据')
                    ),
                  },
                  {
                    key: '6',
                    label: (
                      <span>
                        <StockOutlined /> 资金流向
                      </span>
                    ),
                    children: moneyFlow ? (
                      <MoneyFlowPanel data={moneyFlow} />
                    ) : advancedLoading ? (
                      renderAdvancedLoadingCard('正在加载资金流向...')
                    ) : (
                      renderAdvancedEmptyCard('暂无资金流向数据')
                    ),
                  },
                ]}
              />
            </div>
          )}

          {/* 空状态 */}
          {!loading && !stockData && (
            <Card className="empty-card card-shadow" variant="borderless">
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <div>
                    <p>请输入股票代码开始分析</p>
                    <p className="empty-tips">
                      示例: 000001(平安银行)、600519(贵州茅台)、002594(比亚迪)
                    </p>
                  </div>
                }
              />
            </Card>
          )}
        </div>
      </Content>

      {/* 底部 */}
      <Footer className="app-footer">
        <div className="footer-content">
          <div>SmartStock AI © 2024 - 智能股票投资助手</div>
          <div className="footer-disclaimer">
            ⚠️ 免责声明: 本系统仅供学习参考，不构成投资建议。股市有风险，投资需谨慎。
          </div>
        </div>
      </Footer>
    </Layout>
  )
}

export default Home
