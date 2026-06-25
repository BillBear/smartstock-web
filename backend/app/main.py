"""
FastAPI主应用程序
"""
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.models.schemas import (
    StockQueryRequest,
    HistoryQueryRequest,
    TechnicalAnalysisRequest,
    SignalRequest,
    AdviceRequest,
    MoneyFlowRequest,
    AIDecisionRequest,
    FullAnalysisRequest,
    CoachRiskProfileRequest,
    CoachPickActionRequest,
    CoachBacktestRunRequest,
    CoachStrategyConfigApplyRequest,
    CoachModelTrainRequest,
    StockRealtimeResponse,
    ApiResponse,
    ErrorResponse
)
from app.services.stock_service import StockDataService
from app.services.technical_analyzer import TechnicalAnalyzer
from app.services.advice_service import AdviceService
from app.services.money_flow_service import MoneyFlowService
from app.services.ai_decision_service import AIDecisionEngine
from app.services.akshare_service import AKShareService
from app.services.tencent_service import TencentService
from app.services.data_source_manager import DataSourceManager
from app.services.fundamental_service import FundamentalService
from app.services.coach_service import CoachService
from app.services.coach_store import CoachStore
from app.services.news_factor_service import NewsFactorService
from app.services.ml_model_service import MLModelService
from app.services.ml_explain_service import MLExplainService
from app.services.market_theme_service import MarketThemeService
from app.services.market_data_snapshot_service import MarketDataSnapshotService
from app.services.data_quality_service import DataQualityService
from app.services.recommendation_service import RecommendationService
from app.services.universe_service import UniverseService
from app.services.feature_service import FeatureService
from app.services.scoring_service import ScoringService
import logging
from datetime import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np

try:
    from app.services.tushare_service import TuShareService
    TUSHARE_IMPORT_ERROR = None
except Exception as e:
    TuShareService = None
    TUSHARE_IMPORT_ERROR = str(e)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化服务
stock_service = StockDataService()
technical_analyzer = TechnicalAnalyzer()
advice_service = AdviceService()
money_flow_service = MoneyFlowService()
ai_decision_engine = AIDecisionEngine()

# 初始化数据源（多数据源容错策略）
tushare_service = (
    TuShareService(settings.TUSHARE_TOKEN)
    if (
        settings.TUSHARE_TOKEN
        and TuShareService is not None
    )
    else None
)
akshare_service = AKShareService(disable_system_proxy=settings.DISABLE_SYSTEM_PROXY_FOR_DATA_SOURCE)
tencent_service = TencentService()

# 创建数据源管理器
data_source_manager = DataSourceManager(
    tushare_service=tushare_service,
    tencent_service=tencent_service,
    akshare_service=akshare_service,
    mock_service=None,
    allow_mock_fallback=False,
)
coach_store = CoachStore(settings.COACH_DB_URL)
news_factor_service = NewsFactorService(
    store=coach_store,
    refresh_seconds=settings.NEWS_REFRESH_SECONDS,
    symbol_refresh_seconds=settings.NEWS_SYMBOL_REFRESH_SECONDS,
)
ml_model_service = MLModelService(
    data_source_manager=data_source_manager,
    store=coach_store,
)
ml_explain_service = MLExplainService()
market_theme_service = MarketThemeService(data_source_manager=data_source_manager, store=coach_store)
market_snapshot_service = MarketDataSnapshotService(
    data_source_manager=data_source_manager,
    store=coach_store,
)
data_quality_service = DataQualityService(
    data_source_manager=data_source_manager,
    store=coach_store,
)
universe_service = UniverseService(
    data_source_manager=data_source_manager,
    market_snapshot_service=market_snapshot_service,
    universe_refresh_seconds=settings.COACH_UNIVERSE_REFRESH_SECONDS,
    universe_intraday_refresh_seconds=settings.COACH_UNIVERSE_INTRADAY_REFRESH_SECONDS,
    universe_min_amount_yi=settings.COACH_UNIVERSE_MIN_AMOUNT_YI,
    universe_max_analyze_count=settings.COACH_UNIVERSE_MAX_ANALYZE_COUNT,
    universe_industry_cap=settings.COACH_UNIVERSE_INDUSTRY_CAP,
    universe_min_price=settings.COACH_UNIVERSE_MIN_PRICE,
)
feature_service = FeatureService(
    data_source_manager=data_source_manager,
    news_service=news_factor_service,
)
scoring_service = ScoringService()
coach_service = CoachService(
    data_source_manager,
    store=coach_store,
    news_service=news_factor_service,
    ml_model_service=ml_model_service,
    ml_explain_service=ml_explain_service,
    market_snapshot_service=market_snapshot_service,
    data_quality_service=data_quality_service,
    universe_service=universe_service,
    feature_service=feature_service,
    market_theme_service=market_theme_service,
    scoring_service=scoring_service,
    today_picks_cache_ttl_seconds=settings.COACH_PICKS_CACHE_TTL_SECONDS,
    universe_refresh_seconds=settings.COACH_UNIVERSE_REFRESH_SECONDS,
    universe_intraday_refresh_seconds=settings.COACH_UNIVERSE_INTRADAY_REFRESH_SECONDS,
    universe_min_amount_yi=settings.COACH_UNIVERSE_MIN_AMOUNT_YI,
    universe_max_analyze_count=settings.COACH_UNIVERSE_MAX_ANALYZE_COUNT,
    universe_industry_cap=settings.COACH_UNIVERSE_INDUSTRY_CAP,
    universe_min_price=settings.COACH_UNIVERSE_MIN_PRICE,
)
recommendation_service = RecommendationService(coach_service)
coach_refresh_executor = ThreadPoolExecutor(max_workers=1)
coach_refresh_lock = threading.Lock()

logger.info("=" * 60)
logger.info("数据源配置完成:")
logger.info(f"  - TuShare服务: {'已启用' if tushare_service else '未启用'}")
if not settings.TUSHARE_TOKEN:
    logger.warning("  - TuShare未配置 TUSHARE_TOKEN，将使用其他真实数据源")
if TUSHARE_IMPORT_ERROR:
    logger.warning(f"  - TuShare不可用，将自动降级到其他数据源: {TUSHARE_IMPORT_ERROR}")
logger.info(f"  - AKShare服务: {'已启用（备用）' if akshare_service else '未启用'}")
logger.info(f"  - Tencent服务: {'已启用（备用）' if tencent_service else '未启用'}")
logger.info(f"  - 资金流能力源: {[item.get('name') for item in data_source_manager.get_money_flow_coverage_status().get('sources', [])]}")
logger.info(
    f"  - 代理处理: {'禁用系统代理' if settings.DISABLE_SYSTEM_PROXY_FOR_DATA_SOURCE else '沿用系统代理'}"
)
logger.info("  - Mock服务: 已禁用（项目原则：禁止作为真实数据展示或用于策略决策）")
logger.info("  - 容错策略: TuShare -> Tencent -> AKShare（无Mock兜底）")
logger.info("=" * 60)

# 辅助函数：清理NaN/Infinity值
def clean_nan_values(data):
    """清理字典或列表中的NaN/Infinity值"""
    if isinstance(data, dict):
        return {k: clean_nan_values(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_nan_values(item) for item in data]
    elif isinstance(data, float):
        if np.isnan(data) or np.isinf(data):
            return None
        return data
    return data


def get_quote_price(quote: dict) -> float:
    """兼容不同数据源字段，统一获取最新价格。"""
    if not quote:
        raise ValueError("实时行情为空")
    price = quote.get("price")
    if price is None:
        price = quote.get("current_price")
    if price is None:
        raise ValueError("实时行情缺少价格字段")
    return float(price)


def build_money_flow_payload(money_flow_raw: dict) -> dict:
    """构造资金流向统一响应结构。"""
    quality = money_flow_raw.get("quality") or ("proxy" if money_flow_raw.get("estimated") else "real")
    display_mode = "proxy" if quality == "proxy" else "normal"
    score = int(money_flow_raw['main_net_inflow'] / 10000000)
    flow_signal = {
        'overall': money_flow_raw['trend'],
        'score': score,
        'available': True,
        'display_mode': display_mode,
        'quality': quality,
        'signals': [
            f"✓ 主力净流入 {abs(money_flow_raw['main_net_inflow']/100000000):.2f}亿" if money_flow_raw['main_net_inflow'] > 0 else f"✗ 主力净流出 {abs(money_flow_raw['main_net_inflow']/100000000):.2f}亿",
            f"✓ 超大单净流入 {abs(money_flow_raw['super_large_net']/100000000):.2f}亿" if money_flow_raw['super_large_net'] > 0 else f"✗ 超大单净流出 {abs(money_flow_raw['super_large_net']/100000000):.2f}亿",
            f"✓ 大单净流入 {abs(money_flow_raw['large_net']/100000000):.2f}亿" if money_flow_raw['large_net'] > 0 else f"✗ 大单净流出 {abs(money_flow_raw['large_net']/100000000):.2f}亿"
        ]
    }

    money_flow = {
        **money_flow_raw,
        'available': True,
        'display_mode': display_mode,
        'quality': quality,
        'score': score,
        'analysis': {
            'conclusion': '主力资金持续流入，短期看涨' if money_flow_raw['main_net_inflow'] > 0 else '主力资金持续流出，短期承压',
            'details': [
                f"主力资金合计: {money_flow_raw['main_net_inflow']/100000000:.2f}亿",
                f"超大单: {money_flow_raw['super_large_net']/100000000:.2f}亿",
                f"大单: {money_flow_raw['large_net']/100000000:.2f}亿"
            ]
        }
    }

    return {
        "money_flow": money_flow,
        "signal": flow_signal,
        "available": True,
        "source": money_flow_raw.get("source") or "real_money_flow",
        "source_status": "available",
        "display_mode": display_mode,
        "quality": quality,
        "score": score,
        "reason": "真实资金流" if quality == "real" else "代理资金强度，仅作降级参考",
    }


def build_unavailable_money_flow(symbol: str, days: int, reason: str = "真实资金流数据源暂不可用") -> dict:
    """构造资金流不可用时的中性响应，避免拖垮行情详情页。"""
    return {
        "symbol": symbol,
        "days": days,
        "available": False,
        "source": None,
        "source_status": "unavailable",
        "display_mode": "unavailable",
        "quality": "unavailable",
        "score": None,
        "reason": reason,
        "main_net_inflow": 0,
        "main_inflow": 0,
        "main_outflow": 0,
        "retail_net_inflow": 0,
        "control_ratio": 0,
        "trend": "暂无数据",
        "strength": "不可用",
        "super_large_net": 0,
        "large_net": 0,
        "medium_net": 0,
        "small_net": 0,
        "analysis": {
            "conclusion": "资金流向暂不可用",
            "details": [
                reason,
                "当前页面仍展示实时行情、K线、技术指标和基本面数据。",
            ],
        },
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_unavailable_money_flow_payload(symbol: str, days: int, reason: str = "真实资金流数据源暂不可用") -> dict:
    """构造前端可直接渲染的资金流空态。"""
    money_flow = build_unavailable_money_flow(symbol, days, reason)
    return {
        "money_flow": money_flow,
        "signal": {
            "overall": "资金流向暂不可用",
            "score": None,
            "available": False,
            "display_mode": "unavailable",
            "signals": [
                reason,
                "资金面本次不参与评分，避免把数据缺失误判为资金流出。",
            ],
        },
        "available": False,
        "source": None,
        "source_status": "unavailable",
        "display_mode": "unavailable",
        "quality": "unavailable",
        "score": None,
        "reason": reason,
    }


def serialize_news_event(item: dict) -> dict:
    """输出前端需要的资讯字段，避免暴露数据库内部JSON字段。"""
    return {
        "id": item.get("id"),
        "source": item.get("source"),
        "event_level": item.get("event_level"),
        "event_type": item.get("event_type"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "url": item.get("url"),
        "publish_time": item.get("publish_time"),
        "symbol": item.get("symbol"),
        "symbol_name": item.get("symbol_name"),
        "industry_tags": item.get("industry_tags") or [],
        "direction": item.get("direction"),
        "impact_score": item.get("impact_score"),
        "confidence_score": item.get("confidence_score"),
        "event_score": item.get("event_score"),
    }


def resolve_stock_or_404(symbol_or_name: str) -> dict:
    """支持股票代码或名称输入，统一解析为标准标的。"""
    query = str(symbol_or_name or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="股票代码或名称不能为空")
    resolved = data_source_manager.resolve_stock(query)
    if not resolved or not resolved.get("symbol"):
        raise HTTPException(status_code=404, detail=f"未找到匹配股票: {query}")
    return resolved

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _warmup_coach_cache():
    """后台预热轻量数据，不在启动阶段生成推荐。"""
    try:
        news_factor_service.refresh_if_needed(force=True)
        coach_service.get_market_state_today()
        market_snapshot_service.get_latest_valid_snapshot()
        logger.info("✅ 投资教练轻量数据预热完成")
    except Exception as e:
        logger.warning(f"⚠️ 投资教练缓存预热失败: {str(e)}")


@app.on_event("startup")
def startup_warmup() -> None:
    threading.Thread(target=_warmup_coach_cache, daemon=True, name="coach-cache-warmup").start()


# ========== 健康检查 ==========

@app.get("/")
async def root():
    """根路径"""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


# ========== 股票数据接口 ==========

@app.get(f"{settings.API_PREFIX}/stock/realtime")
async def get_stock_realtime(symbol: str):
    """
    获取股票实时行情（多数据源容错）

    Args:
        symbol: 股票代码，如 000001

    Returns:
        实时行情数据
    """
    try:
        resolved = resolve_stock_or_404(symbol)
        symbol = resolved["symbol"]
        logger.info(f"获取实时行情: {symbol}")

        # 使用数据源管理器（自动容错）
        data = await run_in_threadpool(data_source_manager.get_realtime_quote, symbol)
        if not data:
            raise HTTPException(
                status_code=503,
                detail="真实实时行情暂不可用，请检查网络/代理配置后重试"
            )
        data["code"] = symbol
        data["name"] = data.get("name") or resolved.get("name") or symbol

        return ApiResponse(code=200, message="success", data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实时行情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/stock/search")
async def search_stocks(q: str, limit: int = 8):
    """股票名称/代码模糊搜索。"""
    try:
        items = data_source_manager.search_stocks(q, limit=limit)
        return ApiResponse(code=200, message="success", data={"items": items})
    except Exception as e:
        logger.error(f"搜索股票失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/stock/history")
async def get_stock_history(
    symbol: str,
    period: str = "daily",
    start_date: str = None,
    end_date: str = None,
    adjust: str = "qfq"
):
    """
    获取股票历史K线数据

    Args:
        symbol: 股票代码
        period: 周期 daily/weekly/monthly
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        adjust: 复权类型 qfq/hfq/空

    Returns:
        历史K线数据
    """
    try:
        resolved = resolve_stock_or_404(symbol)
        symbol = resolved["symbol"]
        logger.info(f"获取历史数据: {symbol}, period={period}")

        # 使用数据源管理器（自动容错）
        df = data_source_manager.get_history_data(symbol, days=120)
        if df.empty:
            raise HTTPException(
                status_code=503,
                detail="真实历史行情暂不可用，请检查网络/代理配置后重试"
            )

        # 转换为JSON格式
        data = df.to_dict(orient='records')

        return ApiResponse(
            code=200,
            message="success",
            data={
                "symbol": symbol,
                "period": period,
                "count": len(data),
                "data": data
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取历史数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 技术分析接口 ==========

@app.post(f"{settings.API_PREFIX}/analysis/technical")
async def analyze_technical(request: TechnicalAnalysisRequest):
    """
    技术指标分析

    Args:
        request: 技术分析请求

    Returns:
        技术指标分析结果
    """
    try:
        resolved = resolve_stock_or_404(request.symbol)
        symbol = resolved["symbol"]
        logger.info(f"技术分析: {symbol}")

        # 获取历史数据
        df = data_source_manager.get_history_data(symbol, days=request.days)
        if df.empty:
            raise HTTPException(
                status_code=503,
                detail="真实历史行情暂不可用，无法完成技术分析"
            )

        # 限制数据量
        if len(df) > request.days:
            df = df.tail(request.days)

        # 计算技术指标
        df = TechnicalAnalyzer.analyze_all_indicators(df)

        # 获取最新指标
        latest_indicators = TechnicalAnalyzer.get_latest_indicators(df)

        # 获取股票名称
        realtime = data_source_manager.get_realtime_quote(symbol) or {}
        name = realtime.get("name") or resolved.get("name") or StockDataService.get_stock_name(symbol)

        # 转换为JSON格式（包含所有历史数据和指标）
        history_data = df.replace([np.inf, -np.inf], np.nan).to_dict(orient='records')
        # 清理NaN值
        history_data = clean_nan_values(history_data)
        latest_indicators = clean_nan_values(latest_indicators)

        return ApiResponse(
            code=200,
            message="success",
            data={
                "symbol": symbol,
                "name": name,
                "latest_indicators": latest_indicators,
                "history_data": history_data
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"技术分析失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/analysis/full")
async def analyze_full(request: FullAnalysisRequest):
    """
    聚合分析接口（单次取数，复用计算）

    说明:
    - 一次请求返回核心数据 + 高级分析，避免前端多次重复请求导致的慢加载。
    """
    try:
        resolved = resolve_stock_or_404(request.symbol)
        symbol = resolved["symbol"]
        logger.info(f"聚合分析: {symbol}")

        realtime = data_source_manager.get_realtime_quote(symbol)
        if not realtime:
            raise HTTPException(status_code=503, detail="无法获取实时行情数据")
        price = get_quote_price(realtime)

        df = data_source_manager.get_history_data(symbol, days=request.days)
        if df.empty:
            raise HTTPException(status_code=503, detail="无法获取历史K线数据")

        if len(df) > request.days:
            df = df.tail(request.days)

        df = TechnicalAnalyzer.analyze_all_indicators(df)
        latest_indicators = TechnicalAnalyzer.get_latest_indicators(df)
        signal_analysis = TechnicalAnalyzer.generate_signals(latest_indicators)

        money_flow_raw = data_source_manager.get_money_flow(symbol, request.money_flow_days)
        if money_flow_raw:
            money_flow_payload = build_money_flow_payload(money_flow_raw)
        else:
            logger.warning(f"资金流向不可用，继续返回聚合行情数据: {symbol}")
            money_flow_raw = build_unavailable_money_flow(
                symbol,
                request.money_flow_days,
                "东方财富资金流接口暂不可用，已跳过资金流分析。",
            )
            money_flow_payload = build_unavailable_money_flow_payload(
                symbol,
                request.money_flow_days,
                "东方财富资金流接口暂不可用，已跳过资金流分析。",
            )
        industry = resolved.get("industry")
        news_context = news_factor_service.get_symbol_news_summary(symbol, industry=industry, allow_remote=False)
        fundamental_data = FundamentalService.get_fundamental_data(symbol)
        fundamental_data["pe"] = realtime.get("pe") or fundamental_data.get("pe")
        fundamental_data["pb"] = realtime.get("pb") or fundamental_data.get("pb")
        fundamental_analysis = FundamentalService.analyze_fundamental(fundamental_data)

        advice = AdviceService.generate_advice(
            symbol=symbol,
            name=realtime.get("name", resolved.get("name", symbol)),
            price=price,
            signal_analysis=signal_analysis,
            holding_period=request.holding_period,
            risk_level=request.risk_level,
            target_return=request.target_return
        )

        try:
            coach_context = await run_in_threadpool(
                coach_service.get_symbol_strategy_context,
                symbol,
                "default",
                request.risk_level,
            )
        except Exception as context_error:
            logger.warning(f"智能选股上下文不可用，AI决策不生成买入建议: {symbol}, {context_error}")
            coach_context = {
                "symbol": symbol,
                "available": False,
                "source": "coach_context_error",
                "reason": "智能选股策略上下文暂不可用，未生成交易计划。",
            }

        decision = AIDecisionEngine.make_coach_aligned_decision(
            symbol=symbol,
            name=realtime.get("name", resolved.get("name", symbol)),
            price=price,
            coach_context=coach_context,
            technical_signals=signal_analysis,
            money_flow_data=money_flow_raw,
            user_profile={
                "risk_level": request.risk_level,
                "holding_period": request.holding_period
            }
        )

        history_data = df.replace([np.inf, -np.inf], np.nan).to_dict(orient='records')
        history_data = clean_nan_values(history_data)
        latest_indicators = clean_nan_values(latest_indicators)
        signal_analysis = clean_nan_values(signal_analysis)
        advice = clean_nan_values(advice)
        decision = clean_nan_values(decision)
        realtime = clean_nan_values(realtime)
        money_flow_payload = clean_nan_values(money_flow_payload)
        fundamental_data = clean_nan_values(fundamental_data)
        fundamental_analysis = clean_nan_values(fundamental_analysis)

        return ApiResponse(
            code=200,
            message="success",
            data={
                "symbol": symbol,
                "name": realtime.get("name", resolved.get("name", symbol)),
                "realtime": realtime,
                "technical": {
                    "latest_indicators": latest_indicators,
                    "history_data": history_data
                },
                "signal_analysis": signal_analysis,
                "money_flow": money_flow_payload,
                "fundamental": {
                    "data": fundamental_data,
                    "analysis": fundamental_analysis,
                },
                "advice": advice,
                "ai_decision": decision,
                "news": news_context,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聚合分析失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/analysis/signal")
async def get_trade_signal(request: SignalRequest):
    """
    获取交易信号

    Args:
        request: 信号请求

    Returns:
        交易信号分析
    """
    try:
        resolved = resolve_stock_or_404(request.symbol)
        symbol = resolved["symbol"]
        logger.info(f"生成交易信号: {symbol}")

        # 使用数据源管理器（自动容错）
        realtime = data_source_manager.get_realtime_quote(symbol)
        if not realtime:
            raise HTTPException(status_code=503, detail="无法获取实时行情数据")
        name = realtime.get("name", resolved.get("name", symbol))
        df = data_source_manager.get_history_data(symbol, days=120)
        if df.empty:
            raise HTTPException(status_code=503, detail="无法获取历史K线数据")

        # 计算技术指标
        df = TechnicalAnalyzer.analyze_all_indicators(df)

        # 获取最新指标
        latest_indicators = TechnicalAnalyzer.get_latest_indicators(df)

        # 生成交易信号
        signal_analysis = TechnicalAnalyzer.generate_signals(latest_indicators)

        # 清理NaN/Infinity值
        latest_indicators = clean_nan_values(latest_indicators)
        signal_analysis = clean_nan_values(signal_analysis)

        return ApiResponse(
            code=200,
            message="success",
            data={
                "symbol": symbol,
                "name": name,
                "indicators": latest_indicators,
                "signal_analysis": signal_analysis
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成交易信号失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 投资建议接口 ==========

@app.post(f"{settings.API_PREFIX}/advice")
async def get_investment_advice(request: AdviceRequest):
    """
    获取投资建议

    Args:
        request: 投资建议请求

    Returns:
        个性化投资建议
    """
    try:
        resolved = resolve_stock_or_404(request.symbol)
        symbol = resolved["symbol"]
        logger.info(f"生成投资建议: {symbol}")

        # 获取实时行情
        realtime = data_source_manager.get_realtime_quote(symbol)
        if not realtime:
            raise HTTPException(status_code=503, detail="无法获取实时行情数据")
        df = data_source_manager.get_history_data(symbol, days=120)
        if df.empty:
            raise HTTPException(status_code=503, detail="无法获取历史K线数据")
        price = get_quote_price(realtime)

        # 计算技术指标
        df = TechnicalAnalyzer.analyze_all_indicators(df)

        # 获取最新指标
        latest_indicators = TechnicalAnalyzer.get_latest_indicators(df)

        # 生成交易信号
        signal_analysis = TechnicalAnalyzer.generate_signals(latest_indicators)

        # 生成投资建议
        advice = AdviceService.generate_advice(
            symbol=symbol,
            name=realtime.get("name", resolved.get("name", symbol)),
            price=price,
            signal_analysis=signal_analysis,
            holding_period=request.holding_period,
            risk_level=request.risk_level,
            target_return=request.target_return
        )

        return ApiResponse(code=200, message="success", data=advice)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成投资建议失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 资金流向接口 ==========

@app.post(f"{settings.API_PREFIX}/money-flow")
async def get_money_flow(request: MoneyFlowRequest):
    """
    获取资金流向分析

    Args:
        request: 资金流向请求

    Returns:
        资金流向分析数据
    """
    try:
        resolved = resolve_stock_or_404(request.symbol)
        symbol = resolved["symbol"]
        logger.info(f"获取资金流向: {symbol}")

        # 获取资金流向数据
        money_flow_raw = data_source_manager.get_money_flow(symbol, request.days)

        if money_flow_raw:
            try:
                coach_store.upsert_money_flow_snapshot(
                    trade_date=data_quality_service.current_trade_date(),
                    symbol=symbol,
                    payload=money_flow_raw,
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception:
                pass
            payload = build_money_flow_payload(money_flow_raw)
        else:
            payload = build_unavailable_money_flow_payload(
                symbol,
                request.days,
                "真实资金流数据源暂不可用，请稍后重试。",
            )

        return ApiResponse(
            code=200,
            message="success",
            data=payload
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取资金流向失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/money-flow/coverage")
async def get_money_flow_coverage():
    """获取资金流数据源覆盖与质量状态。"""
    try:
        data = await run_in_threadpool(data_quality_service.build_money_flow_coverage)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取资金流覆盖率失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== AI决策接口 ==========

@app.post(f"{settings.API_PREFIX}/ai-decision")
async def get_ai_decision(request: AIDecisionRequest):
    """
    获取AI智能决策

    Args:
        request: AI决策请求

    Returns:
        AI决策分析结果
    """
    try:
        resolved = resolve_stock_or_404(request.symbol)
        symbol = resolved["symbol"]
        logger.info(f"生成AI决策: {symbol}")

        # 获取实时行情
        realtime = data_source_manager.get_realtime_quote(symbol)
        if not realtime:
            raise HTTPException(status_code=503, detail="无法获取实时行情数据")
        df = data_source_manager.get_history_data(symbol, days=120)
        if df.empty:
            raise HTTPException(status_code=503, detail="无法获取历史K线数据")
        price = get_quote_price(realtime)

        # 计算技术指标
        df = TechnicalAnalyzer.analyze_all_indicators(df)
        latest_indicators = TechnicalAnalyzer.get_latest_indicators(df)

        # 生成技术信号
        technical_signals = TechnicalAnalyzer.generate_signals(latest_indicators)

        # 获取资金流向
        money_flow = data_source_manager.get_money_flow(symbol, 5)
        if not money_flow:
            logger.warning(f"资金流向不可用，AI决策资金面按中性处理: {symbol}")
            money_flow = build_unavailable_money_flow(
                symbol,
                5,
                "真实资金流数据源暂不可用，AI决策资金面按中性处理。",
            )

        # 生成AI决策
        user_profile = {
            "risk_level": request.risk_level,
            "holding_period": request.holding_period
        }

        try:
            coach_context = await run_in_threadpool(
                coach_service.get_symbol_strategy_context,
                symbol,
                "default",
                request.risk_level,
            )
        except Exception as context_error:
            logger.warning(f"智能选股上下文不可用，AI决策不生成买入建议: {symbol}, {context_error}")
            coach_context = {
                "symbol": symbol,
                "available": False,
                "source": "coach_context_error",
                "reason": "智能选股策略上下文暂不可用，未生成交易计划。",
            }

        decision = AIDecisionEngine.make_coach_aligned_decision(
            symbol=symbol,
            name=realtime.get("name", resolved.get("name", symbol)),
            price=price,
            coach_context=coach_context,
            technical_signals=technical_signals,
            money_flow_data=money_flow,
            user_profile=user_profile
        )

        # 清理NaN/Infinity值
        decision = clean_nan_values(decision)

        return ApiResponse(code=200, message="success", data=decision)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成AI决策失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 投资教练接口（V1） ==========

@app.get(f"{settings.API_PREFIX}/coach/market-state/today")
async def coach_market_state_today():
    """获取今日市场状态（投资教练）"""
    try:
        state = await run_in_threadpool(coach_service.get_market_state_today)
        return ApiResponse(code=200, message="success", data=state)
    except Exception as e:
        logger.error(f"获取市场状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/news/events")
async def coach_news_events(
    page: int = 1,
    page_size: int = 10,
    keyword: str = None,
    event_level: str = None,
    source: str = None,
):
    """官方资讯事件列表，支持分页、搜索和来源/层级筛选。"""
    try:
        await run_in_threadpool(news_factor_service.refresh_if_needed, False)
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(int(page_size or 10), 50))
        offset = (safe_page - 1) * safe_page_size
        use_market_levels = not event_level and not keyword and not source
        items = await run_in_threadpool(
            coach_store.list_news_events,
            event_level=event_level,
            event_levels=["macro", "industry"] if use_market_levels else None,
            limit=safe_page_size,
            offset=offset,
            keyword=keyword,
            source=source,
            relevant_only=use_market_levels,
        )
        # 多取一条判断是否还有下一页，避免全表count拖慢页面。
        next_items = await run_in_threadpool(
            coach_store.list_news_events,
            event_level=event_level,
            event_levels=["macro", "industry"] if use_market_levels else None,
            limit=1,
            offset=offset + safe_page_size,
            keyword=keyword,
            source=source,
            relevant_only=use_market_levels,
        )
        return ApiResponse(
            code=200,
            message="success",
            data={
                "items": [serialize_news_event(item) for item in items],
                "page": safe_page,
                "page_size": safe_page_size,
                "has_next": bool(next_items),
            },
        )
    except Exception as e:
        logger.error(f"获取资讯列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/news/symbol/{{symbol}}")
async def coach_symbol_news(symbol: str, limit: int = 8):
    """获取个股关联资讯，用于个股分析页。"""
    try:
        resolved = resolve_stock_or_404(symbol)
        code = resolved["symbol"]
        summary = await run_in_threadpool(
            news_factor_service.get_symbol_news_summary,
            code,
            resolved.get("industry"),
            False,
        )
        summary["latest_events"] = (summary.get("latest_events") or [])[: max(1, min(int(limit or 8), 20))]
        return ApiResponse(code=200, message="success", data=summary)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取个股资讯失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/symbol-strategy/{{symbol}}")
async def coach_symbol_strategy(symbol: str, user_id: str = "default", risk_level: str = None):
    """获取个股在智能选股策略中的评分上下文，供详情页复用同一套分数。"""
    try:
        resolved = resolve_stock_or_404(symbol)
        data = await run_in_threadpool(
            coach_service.get_symbol_strategy_context,
            resolved["symbol"],
            user_id,
            risk_level,
        )
        return ApiResponse(code=200, message="success", data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取个股策略评分失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def _run_coach_refresh(max_count: int, risk_level: str, user_id: str):
    try:
        coach_service.mark_refresh_started()
        recommendation_service.get_today_recommendations(
            max_count=max_count,
            user_id=user_id,
            risk_level=risk_level,
            cached_only=False,
        )
        coach_service.mark_refresh_finished()
    except Exception as e:
        logger.error(f"后台刷新智能选股失败: {str(e)}")
        coach_service.mark_refresh_finished(str(e))


@app.get(f"{settings.API_PREFIX}/coach/smart-screen/summary")
async def coach_smart_screen_summary(
    user_id: str = "default",
    risk_level: str = "medium",
    requested_date: str = None,
    trade_date: str = None,
):
    """快速返回智能选股首屏摘要，不触发重型全量选股。"""
    try:
        data = await run_in_threadpool(
            coach_service.get_smart_screen_summary,
            user_id=user_id,
            risk_level=risk_level,
            requested_date=requested_date,
            trade_date=trade_date,
        )
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取智能选股摘要失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/themes/today")
async def coach_themes_today(force: bool = False, limit: int = 12):
    """返回动态市场主线，不依赖固定主题池。"""
    try:
        data = await run_in_threadpool(market_theme_service.get_today_themes, force=force, limit=limit)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取市场主题失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def _enrich_theme_stocks_with_picks(payload: dict, user_id: str = "default") -> dict:
    """Annotate theme constituents with current smart-pick status without triggering heavy refresh."""
    data = dict(payload or {})
    cached = coach_service.get_cached_today_picks(max_count=60, user_id=user_id) or {}
    pick_map = {str(item.get("symbol") or ""): item for item in (cached.get("picks") or [])}
    symbols = [str(item.get("symbol") or "").strip() for item in data.get("stocks") or [] if str(item.get("symbol") or "").strip()]
    trade_date = data.get("trade_date") or data_quality_service.current_trade_date()
    money_flow_map = {}
    if symbols and hasattr(coach_store, "get_money_flow_snapshots_by_symbols"):
        try:
            money_flow_map = coach_store.get_money_flow_snapshots_by_symbols(symbols, trade_date=trade_date) or {}
        except Exception as exc:
            logger.warning(f"读取主题成分股资金流快照失败: {exc}")
    enriched = []
    for item in data.get("stocks") or []:
        row = dict(item)
        pick = pick_map.get(str(row.get("symbol") or ""))
        if pick:
            row["selected"] = True
            row["pick_id"] = pick.get("pick_id")
            row["decision_grade"] = (pick.get("decision") or {}).get("grade")
            row["money_flow_quality"] = pick.get("money_flow_quality") or row.get("money_flow_quality")
            row["exclusion_reason"] = None
        else:
            money_snapshot = money_flow_map.get(str(row.get("symbol") or ""))
            if money_snapshot:
                payload_json = money_snapshot.get("payload") or {}
                quality = str(money_snapshot.get("quality") or payload_json.get("quality") or "unavailable")
                row["money_flow_quality"] = quality
                row["money_flow_source"] = money_snapshot.get("source") or payload_json.get("source")
                row["money_flow_available"] = bool(money_snapshot.get("available"))
                row["money_flow_display_mode"] = "proxy" if quality == "proxy" else ("normal" if quality == "real" else "unavailable")
            row["selected"] = False
            row["exclusion_reason"] = row.get("exclusion_reason") or "未进入当前策略核心候选，可能未通过风险、趋势、资金或流动性闸门。"
        enriched.append(row)
    data["stocks"] = enriched
    return data


def _enrich_picks_with_current_themes(data: dict) -> dict:
    """Best-effort theme tags for picks without triggering constituent crawling."""
    if not isinstance(data, dict) or not data.get("picks"):
        return data
    try:
        themes_payload = market_theme_service.get_today_themes(force=False, limit=12)
        themes = themes_payload.get("theme_rank") or []
        for pick in data.get("picks") or []:
            if pick.get("theme_tags") or pick.get("matched_theme_ids") or pick.get("theme_rank_score"):
                continue
            symbol = str(pick.get("symbol") or "")
            industry = str(pick.get("industry") or "")
            matched = []
            for theme in themes:
                top_symbols = {str(item.get("symbol") or "") for item in (theme.get("top_symbols") or []) if item.get("symbol")}
                if symbol in top_symbols or (industry and industry == theme.get("theme_name")):
                    matched.append(theme)
            pick["theme_tags"] = [item.get("theme_name") for item in matched[:3]]
            pick["matched_theme_ids"] = [item.get("theme_id") for item in matched[:3]]
            pick["theme_rank_score"] = matched[0].get("strength_score") if matched else None
    except Exception:
        return data
    return data


@app.get(f"{settings.API_PREFIX}/coach/themes/{{theme_id}}/stocks")
async def coach_theme_stocks(theme_id: str, user_id: str = "default", limit: int = 80):
    """主题穿透：返回板块/概念成分股并标注推荐状态。"""
    try:
        data = await run_in_threadpool(market_theme_service.get_theme_stocks, theme_id=theme_id, limit=limit)
        data = await run_in_threadpool(_enrich_theme_stocks_with_picks, data, user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取主题成分股失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/coach/picks/refresh")
async def coach_picks_refresh(
    max_count: int = 30,
    risk_level: str = "medium",
    user_id: str = "default",
    requested_date: str = None,
):
    """触发后台刷新，避免智能选股页面首屏被全量分析阻塞。"""
    try:
        calendar_context = await run_in_threadpool(
            coach_service.resolve_pick_calendar_context,
            user_id=user_id,
            requested_date=requested_date,
        )
        if not ((calendar_context.get("actions") or {}).get("can_refresh")):
            snapshot_dates = await run_in_threadpool(coach_service.list_pick_snapshot_dates, user_id=user_id, limit=30)
            return ApiResponse(
                code=200,
                message="success",
                data={
                    "accepted": False,
                    "status": "non_trading_day",
                    "reason": "non_trading_day",
                    "calendar_context": calendar_context,
                    "snapshot_dates": snapshot_dates,
                    **coach_service.get_refresh_state(),
                },
            )
        state = coach_service.get_refresh_state()
        if state.get("is_refreshing"):
            return ApiResponse(code=200, message="success", data={"accepted": False, "status": "refreshing", "reason": "refreshing", **state})
        with coach_refresh_lock:
            state = coach_service.get_refresh_state()
            if state.get("is_refreshing"):
                return ApiResponse(code=200, message="success", data={"accepted": False, "status": "refreshing", "reason": "refreshing", **state})
            started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            job_id = f"coach-refresh-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            coach_service.mark_refresh_started()
            coach_refresh_executor.submit(_run_coach_refresh, max_count, risk_level, user_id)
        return ApiResponse(
            code=200,
            message="success",
            data={
                "accepted": True,
                "job_id": job_id,
                "status": "queued",
                "started_at": started_at,
                **coach_service.get_refresh_state(),
            },
        )
    except Exception as e:
        logger.error(f"触发智能选股刷新失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/picks/refresh-state")
async def coach_picks_refresh_state():
    """查询智能选股后台刷新状态。"""
    try:
        return ApiResponse(code=200, message="success", data=coach_service.get_refresh_state())
    except Exception as e:
        logger.error(f"获取智能选股刷新状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/picks/today")
async def coach_picks_today(
    max_count: int = 5,
    risk_level: str = "medium",
    user_id: str = "default",
    cached_only: bool = False,
    requested_date: str = None,
    trade_date: str = None,
):
    """获取今日可投推荐列表（投资教练）"""
    try:
        if cached_only:
            data = await run_in_threadpool(
                recommendation_service.get_today_recommendations,
                max_count=max_count,
                user_id=user_id,
                risk_level=risk_level,
                cached_only=True,
                requested_date=requested_date,
                trade_date=trade_date,
            )
            if not data:
                data = {
                    "status": "empty",
                    "picks": [],
                    "is_refreshing": coach_service.get_refresh_state().get("is_refreshing"),
                    "data_quality": {"snapshot_status": "unknown", "money_flow_coverage": 0},
                    "data_diagnostics": {"refresh_state": coach_service.get_refresh_state()},
                }
        else:
            data = await run_in_threadpool(
                recommendation_service.get_today_recommendations,
                max_count=max_count,
                user_id=user_id,
                risk_level=risk_level,
                cached_only=False,
            )
        data = await run_in_threadpool(_enrich_picks_with_current_themes, data)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取今日推荐失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/picks/history")
async def coach_picks_history(
    start_date: str = None,
    end_date: str = None,
    symbol: str = None,
    action: str = None,
):
    """历史推荐查询（投资教练）"""
    try:
        data = await run_in_threadpool(
            coach_service.get_picks_history,
            start_date=start_date,
            end_date=end_date,
            symbol=symbol,
            action=action,
        )
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取推荐历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/picks/batch-review")
async def coach_picks_batch_review(
    trade_date: str = None,
    user_id: str = "default",
    limit: int = 200,
):
    """获取同批智能选股横向复盘。"""
    try:
        data = await run_in_threadpool(
            coach_service.get_pick_batch_review,
            user_id=user_id,
            trade_date=trade_date,
            limit=limit,
        )
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取同批推荐复盘失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/watchlist")
async def coach_watchlist(user_id: str = "default"):
    """获取用户自选候选池（由推荐动作沉淀）"""
    try:
        data = await run_in_threadpool(coach_service.get_watchlist, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取自选池失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/paper-portfolio")
async def coach_paper_portfolio(user_id: str = "default"):
    """获取模拟持仓（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_paper_portfolio, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取模拟持仓失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/paper-trades")
async def coach_paper_trades(user_id: str = "default", limit: int = 200):
    """获取模拟交易流水（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_paper_trades, user_id=user_id, limit=limit)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取模拟交易流水失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/paper-review")
async def coach_paper_review(user_id: str = "default"):
    """获取模拟交易复盘摘要（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_paper_review, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取模拟复盘失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/paper/performance")
async def coach_paper_performance(user_id: str = "default"):
    """获取模拟交易收益评估（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_paper_performance, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取模拟收益评估失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/paper/attribution")
async def coach_paper_attribution(user_id: str = "default"):
    """获取模拟交易结构化归因（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_paper_attribution, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取模拟交易归因失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/monitor/overview")
async def coach_monitor_overview(user_id: str = "default"):
    """获取已选股票监控总览"""
    try:
        data = await run_in_threadpool(coach_service.get_monitor_overview, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取监控总览失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/monitor/positions")
async def coach_monitor_positions(user_id: str = "default"):
    """获取已选股票逐票监控结果"""
    try:
        data = await run_in_threadpool(coach_service.get_monitor_positions, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取逐票监控失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/monitor/feedback/latest")
async def coach_monitor_feedback_latest(user_id: str = "default"):
    """获取最新策略监控反馈报告"""
    try:
        data = await run_in_threadpool(coach_service.get_monitor_feedback_latest, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取策略监控反馈失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/coach/monitor/run-daily-review")
async def coach_monitor_run_daily_review(user_id: str = "default"):
    """手动触发每日收盘监控复盘"""
    try:
        data = await run_in_threadpool(coach_service.run_daily_monitor_review, user_id=user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"运行每日监控复盘失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/picks/{{pick_id}}")
async def coach_pick_detail(
    pick_id: str,
    risk_level: str = "medium",
    user_id: str = "default"
):
    """获取单票推荐详情（投资教练）"""
    try:
        detail = await run_in_threadpool(
            recommendation_service.get_pick_detail,
            pick_id=pick_id,
            user_id=user_id,
            risk_level=risk_level
        )
        if not detail:
            raise HTTPException(status_code=404, detail="推荐不存在或已过期")
        detail = clean_nan_values(detail)
        return ApiResponse(code=200, message="success", data=detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取推荐详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/picks/{{pick_id}}/explain")
async def coach_pick_explain(
    pick_id: str,
    risk_level: str = "medium",
    user_id: str = "default",
):
    """获取单票推荐的机器学习概率与因子贡献解释。"""
    try:
        detail = await run_in_threadpool(
            coach_service.get_pick_detail,
            pick_id=pick_id,
            user_id=user_id,
            risk_level=risk_level,
        )
        if not detail:
            raise HTTPException(status_code=404, detail="推荐不存在或已过期")
        data = ml_explain_service.build_pick_explanation(detail)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取推荐解释失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/coach/risk-profile")
async def coach_set_risk_profile(
    request: CoachRiskProfileRequest,
    user_id: str = "default"
):
    """设置投资教练风险偏好"""
    try:
        payload = await run_in_threadpool(coach_service.set_risk_profile, user_id=user_id, profile=request.dict())
        return ApiResponse(code=200, message="success", data=payload)
    except Exception as e:
        logger.error(f"设置风险偏好失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/strategy-config/options")
async def coach_strategy_config_options(
    strategy_code: str = "trend_breakout",
    user_id: str = "default",
):
    """获取策略配置模板与当前用户配置"""
    try:
        data = await run_in_threadpool(coach_service.get_strategy_config_options, user_id=user_id, strategy_code=strategy_code)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取策略配置模板失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/coach/strategy-config/apply")
async def coach_strategy_config_apply(
    request: CoachStrategyConfigApplyRequest,
    user_id: str = "default",
):
    """应用策略配置到智能选股（并设置为激活策略）"""
    try:
        data = await run_in_threadpool(
            coach_service.apply_strategy_config,
            user_id=user_id,
            strategy_code=request.strategy_code,
            profile_key=request.profile_key,
            config_overrides=request.config,
            set_active=bool(request.set_active),
        )
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"应用策略配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/strategy/{{strategy_code}}/evidence")
async def coach_strategy_evidence(strategy_code: str, state_tag: str = "neutral"):
    """获取策略证据摘要（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_strategy_evidence, strategy_code=strategy_code, state_tag=state_tag)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取策略证据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/coach/models/train")
async def coach_model_train(request: CoachModelTrainRequest, user_id: str = "default"):
    """训练可解释概率模型。"""
    try:
        payload = request.model_dump()
        payload["user_id"] = user_id
        data = await run_in_threadpool(ml_model_service.train_model, payload, user_id)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"训练可解释概率模型失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/models/latest")
async def coach_model_latest():
    """获取最新可解释概率模型。"""
    try:
        data = await run_in_threadpool(ml_model_service.get_latest_model)
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取最新模型失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/models/{{model_id}}/metrics")
async def coach_model_metrics(model_id: str):
    """获取模型指标、校准结果和因子重要性。"""
    try:
        data = await run_in_threadpool(ml_model_service.get_model_metrics, model_id)
        if not data.get("available"):
            raise HTTPException(status_code=404, detail=data.get("message") or "模型不存在")
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模型指标失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/coach/backtest/run")
async def coach_backtest_run(request: CoachBacktestRunRequest, user_id: str = "default"):
    """提交策略回溯任务（投资教练）"""
    try:
        payload = request.dict()
        payload["user_id"] = user_id
        data = await run_in_threadpool(coach_service.run_backtest, payload)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"提交回溯任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/backtest/{{run_id}}")
async def coach_backtest_result(run_id: str):
    """查询策略回溯结果（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_backtest_result, run_id)
        if not data:
            raise HTTPException(status_code=404, detail="回溯任务不存在")
        data = clean_nan_values(data)
        return ApiResponse(code=200, message="success", data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询回溯结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(f"{settings.API_PREFIX}/coach/lessons/weekly/latest")
async def coach_weekly_lesson_latest(user_id: str = "default"):
    """获取最新每周复盘课程（投资教练）"""
    try:
        data = await run_in_threadpool(coach_service.get_weekly_lesson_latest, user_id=user_id)
        return ApiResponse(code=200, message="success", data=data)
    except Exception as e:
        logger.error(f"获取周复盘失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{settings.API_PREFIX}/coach/picks/{{pick_id}}/actions")
async def coach_record_pick_action(
    pick_id: str,
    request: CoachPickActionRequest,
    user_id: str = "default"
):
    """记录用户对推荐的执行动作（投资教练）"""
    try:
        record = await run_in_threadpool(
            coach_service.record_pick_action,
            user_id=user_id,
            pick_id=pick_id,
            payload=request.dict()
        )
        return ApiResponse(code=200, message="success", data=record)
    except ValueError as e:
        logger.warning(f"记录推荐动作被拒绝: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"记录推荐动作失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 异常处理 ==========

from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP异常处理"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """通用异常处理"""
    logger.error(f"未处理的异常: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "Internal server error",
            "detail": str(exc)
        }
    )


if __name__ == "__main__":
    import uvicorn

    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"API文档: http://{settings.API_HOST}:{settings.API_PORT}/docs")

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        log_level="info"
    )
