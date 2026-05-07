# 03. 后端接口契约（V1）

## 1. 约定

1. Base URL：`/api/coach`
2. 响应包装：沿用现有风格

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

3. 时间：ISO8601 或 `YYYY-MM-DD`（字段注明）。
4. 概率字段统一 0~1。

---

## 2. 接口清单

1. `GET /api/coach/picks/today`
2. `GET /api/coach/picks/{pick_id}`
3. `GET /api/coach/picks/history`
4. `POST /api/coach/risk-profile`
5. `GET /api/coach/market-state/today`
6. `GET /api/coach/strategy/{strategy_code}/evidence`
7. `POST /api/coach/backtest/run`
8. `GET /api/coach/backtest/{run_id}`
9. `POST /api/coach/picks/{pick_id}/actions`
10. `GET /api/coach/lessons/weekly/latest`

---

## 3. 详细契约

## 3.1 今日可投列表

### GET `/api/coach/picks/today`

Query:

- `risk_level`（可选）：`low|medium|high`
- `max_count`（可选，默认 5，最大 10）

Response:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "trade_date": "2026-02-24",
    "market_state": {
      "state_tag": "neutral",
      "state_score": 56.2,
      "state_confidence": "medium",
      "suggested_exposure_min_pct": 30,
      "suggested_exposure_max_pct": 50,
      "summary": "震荡市，精选个股，避免追高"
    },
    "picks": [
      {
        "pick_id": "2026-02-24-300058-S1",
        "symbol": "300058",
        "name": "蓝色光标",
        "action": "buy",
        "rank_no": 1,
        "up_prob": 0.64,
        "dd_prob": 0.22,
        "confidence_level": "medium",
        "horizon_days": 15,
        "entry_range": [18.20, 18.70],
        "take_profit": 20.90,
        "stop_loss": 17.30,
        "position_pct": 8,
        "reasons": [
          "趋势突破后回踩确认",
          "主力资金3日净流入",
          "同类形态样本外命中率较高"
        ],
        "risks": [
          "板块轮动过快",
          "放量失败风险"
        ],
        "evidence_summary": {
          "strategy_code": "trend_breakout",
          "oos_win_rate": 0.58,
          "oos_max_drawdown": 0.12
        }
      }
    ]
  }
}
```

---

## 3.2 单票决策详情

### GET `/api/coach/picks/{pick_id}`

Response 除列表字段外，补充：

1. `score_breakdown`
2. `invalid_conditions`
3. `strategy_evidence_detail`
4. `teaching_points`

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "pick_id": "2026-02-24-300058-S1",
    "score_breakdown": {
      "trend": 78.1,
      "money_flow": 72.5,
      "quality": 65.2,
      "risk_adjusted": 68.0,
      "total": 71.0
    },
    "invalid_conditions": [
      "收盘价跌破17.30",
      "成交量连续2日低于20日均量的70%"
    ],
    "strategy_evidence_detail": {
      "walk_forward_windows": 12,
      "oos_annual_return": 0.186,
      "oos_sharpe": 1.24,
      "state_segment": "neutral"
    },
    "teaching_points": [
      "先看趋势，再看资金，最后看风险",
      "入场前先定义失效条件"
    ]
  }
}
```

---

## 3.3 历史推荐查询

### GET `/api/coach/picks/history`

Query:

- `start_date`、`end_date`
- `symbol`（可选）
- `action`（可选）

用途：复盘和教学模块。

---

## 3.4 用户风险偏好

### POST `/api/coach/risk-profile`

Request:

```json
{
  "risk_level": "medium",
  "horizon_days_min": 5,
  "horizon_days_max": 20,
  "max_position_pct": 10,
  "max_industry_pct": 30
}
```

Response:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "saved": true
  }
}
```

---

## 3.5 今日市场状态

### GET `/api/coach/market-state/today`

返回市场状态评分、状态标签、仓位建议与解释。

---

## 3.6 策略证据

### GET `/api/coach/strategy/{strategy_code}/evidence`

Query:

- `state_tag`（可选）
- `window`（可选，默认最近24个月）

Response:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "strategy_code": "trend_breakout",
    "version_no": "1.0.3",
    "overall": {
      "annual_return": 0.186,
      "max_drawdown": 0.119,
      "sharpe": 1.24,
      "win_rate": 0.58,
      "profit_loss_ratio": 1.72
    },
    "by_state": [
      {"state_tag": "offensive", "win_rate": 0.62, "max_drawdown": 0.14},
      {"state_tag": "neutral", "win_rate": 0.58, "max_drawdown": 0.12},
      {"state_tag": "defensive", "win_rate": 0.42, "max_drawdown": 0.16}
    ]
  }
}
```

---

## 3.7 回测运行

### POST `/api/coach/backtest/run`

Request:

```json
{
  "strategy_code": "trend_breakout",
  "strategy_version_id": "s_trend_breakout_1_0_3",
  "test_start": "2024-01-01",
  "test_end": "2026-01-31",
  "config": {
    "holding_days": 15,
    "stop_profit_pct": 15,
    "stop_loss_pct": 8,
    "score_threshold": 70,
    "commission": 0.0003,
    "slippage": 0.001
  }
}
```

Response:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "run_id": "bt_20260224_001",
    "status": "running"
  }
}
```

---

## 3.8 回测结果查询

### GET `/api/coach/backtest/{run_id}`

Response:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "run_id": "bt_20260224_001",
    "status": "success",
    "metrics": {
      "annual_return": 0.21,
      "max_drawdown": 0.14,
      "sharpe": 1.31,
      "win_rate": 0.57
    },
    "equity_curve": [],
    "drawdown_curve": [],
    "trades": []
  }
}
```

---

## 3.9 用户执行动作上报

### POST `/api/coach/picks/{pick_id}/actions`

Request:

```json
{
  "action_type": "paper_buy",
  "action_price": 18.45,
  "action_qty": 1000,
  "note": "按系统建议执行"
}
```

---

## 3.10 每周复盘课

### GET `/api/coach/lessons/weekly/latest`

返回：

1. 上周推荐结果统计
2. 典型成功/失败案例
3. 下周执行建议

---

## 4. 错误码约定

1. `4001` 参数错误
2. `4002` 日期区间非法
3. `4041` 推荐不存在
4. `4091` 回测任务冲突
5. `4221` 风险偏好不合法
6. `5001` 推荐生成失败
7. `5002` 回测执行失败

HTTP 状态建议：

1. 参数错误：`400`
2. 不存在：`404`
3. 可恢复业务失败：`409/422`
4. 系统失败：`500`

---

## 5. 状态流（回测）

`running -> success | failed`

`failed` 必须返回 `error_message`。

---

## 6. 与现有接口兼容建议

1. 保留现有 `/api/analysis/*`，用于个股分析页。
2. 新增 `/api/coach/*`，避免破坏已有前端逻辑。
3. 推荐页优先走 `/api/coach/picks/today`，降低前端拼接口复杂度。
