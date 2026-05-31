"""
应用配置文件
"""
from pydantic_settings import BaseSettings
from typing import List
from pathlib import Path


class Settings(BaseSettings):
    """应用配置"""

    # 应用信息
    APP_NAME: str = "SmartStock AI"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "智能股票投资助手"

    # API配置
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api"

    # CORS配置
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3601",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3601",
    ]

    # 数据缓存配置（秒）
    CACHE_TTL: int = 60

    # 技术指标默认参数
    MA_PERIODS: List[int] = [5, 10, 20, 60]
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9
    RSI_PERIOD: int = 14
    KDJ_N: int = 9
    KDJ_M1: int = 3
    KDJ_M2: int = 3
    BOLL_PERIOD: int = 20
    BOLL_STD: int = 2

    # 数据获取配置
    DEFAULT_HISTORY_DAYS: int = 120
    MAX_HISTORY_DAYS: int = 365

    # 数据源容错策略
    USE_MOCK_DATA: bool = False
    TUSHARE_TOKEN: str = ""
    ENABLE_MOCK_FALLBACK: bool = False
    DISABLE_SYSTEM_PROXY_FOR_DATA_SOURCE: bool = True
    COACH_DB_PATH: str = str(Path(__file__).resolve().parents[2] / "data" / "coach.db")
    COACH_DB_URL: str = "postgresql+psycopg2://smartstock@127.0.0.1:5432/smartstock"
    COACH_PICKS_CACHE_TTL_SECONDS: int = 30
    COACH_UNIVERSE_REFRESH_SECONDS: int = 1200
    COACH_UNIVERSE_INTRADAY_REFRESH_SECONDS: int = 90
    COACH_UNIVERSE_MIN_AMOUNT_YI: float = 2.0
    COACH_UNIVERSE_MAX_ANALYZE_COUNT: int = 120
    COACH_UNIVERSE_INDUSTRY_CAP: int = 4
    COACH_UNIVERSE_MIN_PRICE: float = 2.0
    NEWS_REFRESH_SECONDS: int = 900
    NEWS_SYMBOL_REFRESH_SECONDS: int = 1800

    class Config:
        case_sensitive = True
        env_file = ".env"


def validate_no_mock_data_policy(config: Settings) -> None:
    """Mock data is forbidden for product data display and strategy decisions."""
    if bool(config.USE_MOCK_DATA) or bool(config.ENABLE_MOCK_FALLBACK):
        raise RuntimeError(
            "SmartStock 禁止把 mock 数据作为真实数据展示或用于策略决策。"
            "请设置 USE_MOCK_DATA=False 且 ENABLE_MOCK_FALLBACK=False。"
        )


# 创建全局配置实例
settings = Settings()
validate_no_mock_data_policy(settings)
