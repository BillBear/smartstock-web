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
  const [isCompact, setIsCompact] = React.useState(false)
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

  React.useEffect(() => {
    const media = window.matchMedia('(max-width: 768px)')
    const syncViewport = () => {
      setIsCompact(media.matches)
      if (media.matches) {
        setCollapsed(true)
      }
    }
    syncViewport()
    media.addEventListener('change', syncViewport)
    return () => media.removeEventListener('change', syncViewport)
  }, [])

  const expandedWidth = 216
  const collapsedWidth = 72
  const siderWidth = collapsed ? collapsedWidth : expandedWidth

  return (
    <Layout style={{ minHeight: '100dvh' }}>
      {/* 侧边栏 */}
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={expandedWidth}
        collapsedWidth={collapsedWidth}
        style={{
          overflow: 'auto',
          height: '100dvh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
        }}
      >
        <div className="logo">
          <LineChartOutlined style={{ fontSize: 24, color: 'var(--focus-color)' }} />
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
      <Layout style={{ marginLeft: isCompact ? collapsedWidth : siderWidth, transition: 'margin-left 0.2s ease' }}>
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
  const terminalTheme = {
    canvas: '#080B10',
    shell: '#0D1118',
    panel: '#111720',
    panelElevated: '#161D28',
    panelInset: '#0A0F16',
    border: '#263142',
    borderSoft: '#1B2532',
    text: '#F2F5F8',
    textSecondary: '#A7B0BD',
    textMuted: '#6E7A89',
    accent: '#27C08A',
  }

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: terminalTheme.accent,
          colorInfo: '#4DA3FF',
          colorSuccess: '#27C08A',
          colorWarning: '#D7A84A',
          colorError: '#D95F59',
          colorBgBase: terminalTheme.canvas,
          colorBgLayout: terminalTheme.canvas,
          colorBgContainer: terminalTheme.panel,
          colorBgElevated: terminalTheme.panelElevated,
          colorFillSecondary: 'rgba(167, 176, 189, 0.08)',
          colorFillTertiary: 'rgba(167, 176, 189, 0.05)',
          colorBorder: terminalTheme.border,
          colorBorderSecondary: terminalTheme.borderSoft,
          colorText: terminalTheme.text,
          colorTextSecondary: terminalTheme.textSecondary,
          colorTextTertiary: terminalTheme.textMuted,
          colorTextQuaternary: terminalTheme.textMuted,
          borderRadius: 8,
          borderRadiusLG: 10,
          borderRadiusSM: 6,
          boxShadow: '0 18px 40px rgba(0, 0, 0, 0.28)',
          boxShadowSecondary: '0 10px 28px rgba(0, 0, 0, 0.22)',
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        },
        algorithm: theme.darkAlgorithm,
        components: {
          Layout: {
            headerBg: terminalTheme.shell,
            siderBg: terminalTheme.shell,
            bodyBg: terminalTheme.canvas,
          },
          Menu: {
            darkItemBg: terminalTheme.shell,
            darkItemHoverBg: 'rgba(167, 176, 189, 0.07)',
            darkItemSelectedBg: 'rgba(39, 192, 138, 0.12)',
            darkItemColor: terminalTheme.textSecondary,
            darkItemSelectedColor: terminalTheme.accent,
          },
          Card: {
            colorBgContainer: terminalTheme.panel,
            colorBorderSecondary: terminalTheme.borderSoft,
            headerBg: terminalTheme.panel,
          },
          Table: {
            headerBg: terminalTheme.panelElevated,
            headerColor: terminalTheme.textSecondary,
            rowHoverBg: 'rgba(39, 192, 138, 0.055)',
            borderColor: terminalTheme.borderSoft,
          },
          Button: {
            defaultBg: terminalTheme.panelElevated,
            defaultBorderColor: terminalTheme.border,
            defaultColor: terminalTheme.text,
          },
          Input: {
            colorBgContainer: terminalTheme.panelElevated,
            colorBorder: terminalTheme.border,
          },
          Select: {
            colorBgContainer: terminalTheme.panelElevated,
            colorBorder: terminalTheme.border,
          },
          Drawer: {
            colorBgElevated: terminalTheme.panel,
          },
          Modal: {
            contentBg: terminalTheme.panel,
            headerBg: terminalTheme.panel,
          },
        }
      }}
    >
      <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppShell />
      </Router>
    </ConfigProvider>
  )
}

export default App
