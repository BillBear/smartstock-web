import React, { Suspense } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Spin } from 'antd'
import {
  DashboardOutlined,
  ThunderboltOutlined,
  StarOutlined,
  LineChartOutlined,
  BarChartOutlined,
  HomeOutlined
} from '@ant-design/icons'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import './App.css'

const { Content, Sider } = Layout

const Home = React.lazy(() => import('./pages/Home'))
const Dashboard = React.lazy(() => import('./pages/Dashboard'))
const SmartScreen = React.lazy(() => import('./pages/SmartScreen'))
const Watchlist = React.lazy(() => import('./pages/Watchlist'))
const StockDetail = React.lazy(() => import('./pages/StockDetail'))
const Backtest = React.lazy(() => import('./pages/Backtest'))

const menuItems = [
  {
    key: 'home',
    icon: <HomeOutlined />,
    label: '个股分析',
    path: '/'
  },
  {
    key: 'dashboard',
    icon: <DashboardOutlined />,
    label: '市场全景',
    path: '/dashboard'
  },
  {
    key: 'smart-screen',
    icon: <ThunderboltOutlined />,
    label: '智能选股',
    path: '/smart-screen'
  },
  {
    key: 'watchlist',
    icon: <StarOutlined />,
    label: '自选股',
    path: '/watchlist'
  },
  {
    key: 'backtest',
    icon: <BarChartOutlined />,
    label: '策略回测',
    path: '/backtest'
  }
]

function AppShell() {
  const [collapsed, setCollapsed] = React.useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  const handleMenuClick = ({ key }) => {
    const item = menuItems.find(i => i.key === key)
    if (item) {
      navigate(item.path)
    }
  }

  const selectedKey = React.useMemo(() => {
    const exact = menuItems.find(i => i.path === location.pathname)
    if (exact) return exact.key
    if (location.pathname.startsWith('/stock/')) return 'home'
    return 'home'
  }, [location.pathname])

  React.useEffect(() => {
    // 兼容旧逻辑遗留的 hash 路由，自动迁移到 BrowserRouter 路径
    const hash = window.location.hash
    if (hash && hash.startsWith('#/')) {
      const hashPath = hash.slice(1)
      if (hashPath !== location.pathname) {
        navigate(hashPath, { replace: true })
      }
    }
  }, [location.pathname, navigate])

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 侧边栏 */}
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        style={{
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
        }}
      >
        <div className="logo">
          <LineChartOutlined style={{ fontSize: 24, color: '#1890ff' }} />
          {!collapsed && <span className="logo-text">SmartStock AI</span>}
        </div>
        <Menu
          theme="dark"
          selectedKeys={[selectedKey]}
          mode="inline"
          items={menuItems}
          onClick={handleMenuClick}
        />
      </Sider>

      {/* 主内容区 */}
      <Layout style={{ marginLeft: collapsed ? 80 : 200, transition: 'margin-left 0.2s ease' }}>
        <Content style={{ margin: 0, overflowY: 'auto', overflowX: 'hidden', scrollbarGutter: 'stable' }}>
          <Suspense fallback={<div className="route-loading"><Spin /><span>加载页面...</span></div>}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/smart-screen" element={<SmartScreen />} />
              <Route path="/watchlist" element={<Watchlist />} />
              <Route path="/stock/:symbol" element={<StockDetail />} />
              <Route path="/backtest" element={<Backtest />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  )
}

function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#00C076',
          colorBgContainer: '#151A21',
          colorBgElevated: '#1A1F28',
          colorBorder: '#2A2F38',
          colorText: '#E8EAED',
          colorTextSecondary: '#9AA0A6',
          borderRadius: 8,
        },
        algorithm: theme.darkAlgorithm,
        components: {
          Layout: {
            headerBg: '#0B0E11',
            siderBg: '#151A21',
            bodyBg: '#0B0E11',
          },
          Menu: {
            darkItemBg: '#151A21',
            darkItemSelectedBg: 'rgba(0, 192, 118, 0.1)',
            darkItemColor: '#9AA0A6',
            darkItemSelectedColor: '#00C076',
          }
        }
      }}
    >
      <Router>
        <AppShell />
      </Router>
    </ConfigProvider>
  )
}

export default App
