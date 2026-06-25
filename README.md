# SmartStock AI

SmartStock AI 是一个本地运行的 A 股投资决策辅助系统。当前版本已经从早期 MVP 行情工具扩展为「个股分析 + 市场全景 + 智能选股 + 自选/模拟持仓 + 策略回测 + 投资教练」的一体化 Web 应用。

> 本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。

## 核心功能

1. 个股分析：实时行情、历史 K 线、技术指标、资金流向、基本面、资讯因子和 AI 决策。
2. 市场全景：市场状态评分、仓位建议、资讯温度和每周复盘摘要。
3. 智能选股：按风险偏好生成今日推荐，输出入场区间、止盈、止损、仓位、理由和风险。
4. 自选与模拟持仓：记录观察、模拟买入、模拟交易流水和复盘统计。
5. 策略回测：查询策略证据、应用策略配置、运行回测并查看结果。
6. 机器学习辅助：支持训练可解释概率模型，并展示模型指标和特征解释。

## 技术栈

后端：

- FastAPI + Uvicorn
- Pydantic / pydantic-settings
- Pandas / NumPy / scikit-learn
- SQLAlchemy + PostgreSQL，兼容 SQLite
- TuShare、Tencent、AKShare 多数据源

前端：

- Vite + React 18
- React Router
- Ant Design
- ECharts / echarts-for-react
- Axios

## 快速开始

推荐使用统一脚本：

```bash
cd smartstock-web
./start.sh
```

常用命令：

```bash
./status.sh
./stop.sh
./restart.sh
```

默认地址：

- 前端: http://localhost:3601
- 后端: http://localhost:8000
- API 文档: http://localhost:8000/docs

## 环境配置

后端配置从 `backend/.env` 读取。首次配置可复制样例：

```bash
cd smartstock-web/backend
cp .env.example .env
```

关键配置：

```env
USE_MOCK_DATA=False
TUSHARE_TOKEN=
ENABLE_MOCK_FALLBACK=False
DISABLE_SYSTEM_PROXY_FOR_DATA_SOURCE=True
COACH_DB_URL=postgresql+psycopg2://smartstock@127.0.0.1:5432/smartstock
```

说明：

- `TUSHARE_TOKEN` 不应写入代码或提交到版本库。
- `USE_MOCK_DATA` 和 `ENABLE_MOCK_FALLBACK` 必须保持 `False`：本项目禁止把 mock 数据作为真实数据展示或用于策略决策；如果开启，后端会拒绝启动。
- `COACH_DB_URL` 默认连接本地 PostgreSQL。

PostgreSQL 启动脚本默认使用：

```text
/opt/anaconda3/envs/smartstock-pg/bin
```

该目录需要存在 `pg_ctl`、`psql`、`initdb`、`createdb`。

## 手动启动

后端：

```bash
cd smartstock-web/backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```bash
cd smartstock-web/frontend
npm install
npm run dev -- --host 0.0.0.0 --port 3601
```

前端开发服务器会把 `/api` 代理到 `http://localhost:8000`。

## 测试和验证

后端基础回归测试：

```bash
cd smartstock-web/backend
source venv/bin/activate
python -m unittest discover -s tests
```

前端构建：

```bash
cd smartstock-web/frontend
npm run build
```

健康检查：

```bash
curl http://localhost:8000/health
```

## API 概览

基础：

- `GET /`
- `GET /health`

股票与分析：

- `GET /api/stock/realtime?symbol=000001`
- `GET /api/stock/search?q=平安`
- `GET /api/stock/history?symbol=000001&period=daily`
- `POST /api/analysis/technical`
- `POST /api/analysis/full`
- `POST /api/analysis/signal`
- `POST /api/advice`
- `POST /api/money-flow`
- `GET /api/money-flow/coverage`
- `POST /api/ai-decision`

智能选股与投资教练：

- `GET /api/coach/market-state/today`
- `GET /api/coach/news/events`
- `GET /api/coach/news/symbol/{symbol}`
- `GET /api/coach/symbol-strategy/{symbol}`
- `GET /api/coach/smart-screen/summary`
- `GET /api/coach/themes/today`
- `GET /api/coach/themes/{theme_id}/stocks`
- `POST /api/coach/picks/refresh`
- `GET /api/coach/picks/refresh-state`
- `GET /api/coach/picks/today`
- `GET /api/coach/picks/history`
- `GET /api/coach/picks/batch-review`
- `GET /api/coach/picks/{pick_id}`
- `GET /api/coach/picks/{pick_id}/explain`
- `POST /api/coach/picks/{pick_id}/actions`
- `GET /api/coach/watchlist`
- `GET /api/coach/paper-portfolio`
- `GET /api/coach/paper-trades`
- `GET /api/coach/paper-review`
- `GET /api/coach/paper/performance`
- `GET /api/coach/paper/attribution`
- `POST /api/coach/risk-profile`
- `GET /api/coach/strategy-config/options`
- `POST /api/coach/strategy-config/apply`

监控、模型与回测：

- `GET /api/coach/monitor/overview`
- `GET /api/coach/monitor/positions`
- `GET /api/coach/monitor/feedback/latest`
- `POST /api/coach/monitor/run-daily-review`
- `GET /api/coach/strategy/{strategy_code}/evidence`
- `POST /api/coach/models/train`
- `GET /api/coach/models/latest`
- `GET /api/coach/models/{model_id}/metrics`
- `POST /api/coach/backtest/run`
- `GET /api/coach/backtest/{run_id}`
- `GET /api/coach/lessons/weekly/latest`

## 项目结构

```text
smartstock-web/
├── backend/
│   ├── app/
│   │   ├── core/config.py              # 环境配置
│   │   ├── main.py                     # FastAPI 入口和路由
│   │   ├── models/schemas.py           # Pydantic 请求/响应模型
│   │   └── services/
│   │       ├── data_source_manager.py  # 多数据源容错与缓存
│   │       ├── technical_analyzer.py   # 技术指标与交易信号
│   │       ├── advice_service.py       # 投资建议
│   │       ├── ai_decision_service.py  # AI 决策规则
│   │       ├── coach_service.py        # 投资教练主业务
│   │       ├── coach_store.py          # PostgreSQL/SQLite 持久化
│   │       ├── news_factor_service.py  # 官方资讯因子
│   │       └── ml_model_service.py     # 概率模型训练与指标
│   ├── tests/                          # 标准库 unittest 回归测试
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx                     # 路由和全局布局
│   │   ├── pages/                      # Home/Dashboard/SmartScreen 等页面
│   │   ├── components/                 # K 线、指标、建议、资金流等组件
│   │   └── services/api.js             # Axios API 封装
│   ├── package.json
│   └── vite.config.js                  # 开发代理
├── postgres/                           # 本地 PostgreSQL 启停脚本和数据目录
├── docs/                               # 投资教练 V1/V2 设计文档
├── start.sh
├── stop.sh
└── status.sh
```

## 维护原则

- 不把 token、数据库密码、个人路径等敏感配置写入代码。
- 禁止把 Mock 数据作为本项目的真实行情、资金流、候选池、评分或推荐结果展示和使用；真实数据不可用时必须显示不可用/降级，而不是用假数据兜底。
- 大型业务模块重构前先补回归测试，保持接口响应结构稳定。
- 金融决策相关变更优先补充测试和页面验证。
