"""
数据模型定义（Pydantic Schemas）
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime


# ========== 请求模型 ==========

class StockQueryRequest(BaseModel):
    """股票查询请求"""
    symbol: str = Field(..., description="股票代码，如 000001")
    market: Optional[str] = Field(None, description="市场类型：sz/sh，不传则自动判断")


class HistoryQueryRequest(BaseModel):
    """历史数据查询请求"""
    symbol: str = Field(..., description="股票代码")
    period: str = Field("daily", description="周期：daily/weekly/monthly")
    start_date: Optional[str] = Field(None, description="开始日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="结束日期 YYYY-MM-DD")
    adjust: str = Field("qfq", description="复权类型：qfq前复权/hfq后复权/空不复权")


class TechnicalAnalysisRequest(BaseModel):
    """技术分析请求"""
    symbol: str = Field(..., description="股票代码")
    period: str = Field("daily", description="周期")
    days: int = Field(60, description="分析天数", ge=30, le=365)


class SignalRequest(BaseModel):
    """交易信号请求"""
    symbol: str = Field(..., description="股票代码")


class AdviceRequest(BaseModel):
    """投资建议请求"""
    symbol: str = Field(..., description="股票代码")
    holding_period: str = Field("medium", description="持有周期：short短期/medium中期/long长期")
    risk_level: str = Field("medium", description="风险等级：low低/medium中/high高")
    target_return: float = Field(15.0, description="目标收益率(%)", ge=0, le=100)


class MoneyFlowRequest(BaseModel):
    """资金流向请求"""
    symbol: str = Field(..., description="股票代码")
    days: int = Field(5, description="查询天数", ge=1, le=30)


class AIDecisionRequest(BaseModel):
    """AI决策请求"""
    symbol: str = Field(..., description="股票代码")
    holding_period: str = Field("medium", description="持有周期：short短期/medium中期/long长期")
    risk_level: str = Field("medium", description="风险等级：low低/medium中/high高")


class FullAnalysisRequest(BaseModel):
    """聚合分析请求"""
    symbol: str = Field(..., description="股票代码")
    period: str = Field("daily", description="周期")
    days: int = Field(120, description="分析天数", ge=30, le=365)
    money_flow_days: int = Field(5, description="资金流向天数", ge=1, le=30)
    holding_period: str = Field("medium", description="持有周期：short短期/medium中期/long长期")
    risk_level: str = Field("medium", description="风险等级：low低/medium中/high高")
    target_return: float = Field(15.0, description="目标收益率(%)", ge=0, le=100)


class CoachRiskProfileRequest(BaseModel):
    """投资教练风险偏好设置请求"""
    risk_level: str = Field("medium", description="风险等级：low/medium/high")
    horizon_days_min: int = Field(5, description="最短持有天数", ge=1, le=120)
    horizon_days_max: int = Field(20, description="最长持有天数", ge=1, le=240)
    max_position_pct: float = Field(10.0, description="单票最大仓位(%)", ge=1, le=100)
    max_industry_pct: float = Field(30.0, description="行业最大集中度(%)", ge=1, le=100)


class CoachPickActionRequest(BaseModel):
    """投资教练推荐执行动作请求"""
    action_type: str = Field(..., description="动作类型: added_watchlist/paper_buy/ignored/closed")
    action_price: Optional[float] = Field(None, description="执行价格")
    action_qty: Optional[float] = Field(None, description="执行数量")
    note: Optional[str] = Field(None, description="备注")


class CoachBacktestRunRequest(BaseModel):
    """投资教练策略回溯请求"""
    strategy_code: str = Field("trend_breakout", description="策略编码")
    strategy_version_id: Optional[str] = Field(None, description="策略版本ID")
    test_start: Optional[str] = Field(None, description="测试开始日期 YYYY-MM-DD")
    test_end: Optional[str] = Field(None, description="测试结束日期 YYYY-MM-DD")
    config: Dict[str, Any] = Field(default_factory=dict, description="回测配置")


class CoachStrategyConfigApplyRequest(BaseModel):
    """策略配置应用请求（用于一键回填到智能选股）"""
    strategy_code: str = Field("trend_breakout", description="策略编码")
    profile_key: Optional[str] = Field(None, description="配置模板编码")
    config: Dict[str, Any] = Field(default_factory=dict, description="覆盖配置")
    set_active: bool = Field(True, description="是否设置为当前激活策略")


class CoachModelTrainRequest(BaseModel):
    """可解释概率模型训练请求"""
    strategy_code: str = Field("all", description="策略编码")
    train_start: Optional[str] = Field(None, description="训练开始日期 YYYY-MM-DD")
    train_end: Optional[str] = Field(None, description="训练结束日期 YYYY-MM-DD")
    horizon_days: int = Field(15, description="预测持有期/标签窗口", ge=5, le=60)
    target_return_pct: float = Field(8.0, description="上涨标签收益阈值(%)", ge=1, le=50)
    drawdown_pct: float = Field(6.0, description="回撤标签阈值(%)", ge=1, le=40)
    max_symbols: int = Field(120, description="最大训练股票数", ge=5, le=300)
    sample_step: int = Field(3, description="样本抽样步长，降低高度重叠标签", ge=1, le=20)
    tree_max_depth: int = Field(4, description="解释用决策树深度", ge=3, le=5)
    symbols: Optional[List[str]] = Field(None, description="可选指定股票池")


class CoachRankingEvaluationRunRequest(BaseModel):
    """候选池排序质量评估请求"""
    strategy_code: str = Field("trend_breakout", description="策略编码")
    risk_level: str = Field("medium", description="风险等级：low/medium/high")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")
    horizons: List[int] = Field(default_factory=lambda: [3, 5, 10, 20], description="未来收益窗口")
    top_k: List[int] = Field(default_factory=lambda: [3, 5, 10], description="Top-K 指标")
    commission: float = Field(0.0003, description="交易佣金", ge=0)
    slippage: float = Field(0.001, description="滑点", ge=0)
    fixture: Optional[str] = Field(None, description="可选 smoke fixture，仅用于测试和本地冒烟验证")
    output_dir: Optional[str] = Field(None, description="报告输出目录；为空时写入默认策略证据目录")


# ========== 响应模型 ==========

class StockRealtimeResponse(BaseModel):
    """股票实时行情响应"""
    symbol: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    current_price: float = Field(..., description="当前价格")
    change_percent: float = Field(..., description="涨跌幅(%)")
    change_amount: float = Field(..., description="涨跌额")
    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    prev_close: float = Field(..., description="昨收价")
    volume: float = Field(..., description="成交量")
    turnover: float = Field(..., description="成交额")
    timestamp: str = Field(..., description="更新时间")


class KLineData(BaseModel):
    """K线数据"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class TechnicalIndicators(BaseModel):
    """技术指标"""
    date: str
    close: float
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    rsi: Optional[float] = None
    k: Optional[float] = None
    d: Optional[float] = None
    j: Optional[float] = None
    boll_upper: Optional[float] = None
    boll_middle: Optional[float] = None
    boll_lower: Optional[float] = None


class SignalAnalysis(BaseModel):
    """信号分析"""
    overall_signal: str = Field(..., description="综合信号")
    score: int = Field(..., description="评分 -100到100")
    signals: List[str] = Field(..., description="信号列表")
    trend: str = Field(..., description="趋势：上升/下降")


class InvestmentAdvice(BaseModel):
    """投资建议"""
    symbol: str
    name: str
    current_price: float
    signal_analysis: SignalAnalysis
    advice: Dict[str, Any] = Field(..., description="具体建议")
    risk_warning: List[str] = Field(..., description="风险提示")
    generated_at: str


class ApiResponse(BaseModel):
    """通用API响应"""
    code: int = Field(200, description="状态码")
    message: str = Field("success", description="消息")
    data: Optional[Any] = Field(None, description="数据")


class ErrorResponse(BaseModel):
    """错误响应"""
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误信息")
    detail: Optional[str] = Field(None, description="详细信息")
