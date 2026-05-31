"""
数据源管理器
实现多数据源容错策略，提高系统鲁棒性
支持：TuShare Pro（主） -> Tencent（备用1） -> AKShare（备用2）
项目原则：Mock 数据不得作为真实数据展示或用于策略决策。
"""
import logging
from typing import Optional, Dict, Any, List
import time
import copy
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
import pandas as pd

logger = logging.getLogger(__name__)

MINIMAL_STOCK_BASIC_MAP: Dict[str, Dict[str, str]] = {
    "000001": {"symbol": "000001", "name": "平安银行", "industry": "银行"},
    "000333": {"symbol": "000333", "name": "美的集团", "industry": "家用电器"},
    "000651": {"symbol": "000651", "name": "格力电器", "industry": "家用电器"},
    "000858": {"symbol": "000858", "name": "五粮液", "industry": "白酒"},
    "002415": {"symbol": "002415", "name": "海康威视", "industry": "计算机设备"},
    "002594": {"symbol": "002594", "name": "比亚迪", "industry": "汽车"},
    "300059": {"symbol": "300059", "name": "东方财富", "industry": "证券"},
    "300750": {"symbol": "300750", "name": "宁德时代", "industry": "电池"},
    "600000": {"symbol": "600000", "name": "浦发银行", "industry": "银行"},
    "600036": {"symbol": "600036", "name": "招商银行", "industry": "银行"},
    "600519": {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"},
    "600900": {"symbol": "600900", "name": "长江电力", "industry": "电力"},
    "601318": {"symbol": "601318", "name": "中国平安", "industry": "保险"},
    "601398": {"symbol": "601398", "name": "工商银行", "industry": "银行"},
    "601888": {"symbol": "601888", "name": "中国中免", "industry": "旅游零售"},
}


class DataSourceManager:
    """数据源管理器 - 多数据源容错"""

    def __init__(
        self,
        tushare_service=None,
        tencent_service=None,
        akshare_service=None,
        mock_service=None,
        allow_mock_fallback: bool = False,
    ):
        """初始化数据源管理器

        Args:
            tushare_service: TuShare服务实例
            tencent_service: Tencent服务实例
            akshare_service: AKShare服务实例
            mock_service: 保留给旧调用签名，不会注册为业务数据源
            allow_mock_fallback: 禁止开启，开启会直接报错
        """
        if allow_mock_fallback:
            raise ValueError("SmartStock 禁止启用 Mock 兜底，避免把假数据作为真实数据展示或用于策略决策")
        self.tushare = tushare_service
        self.tencent = tencent_service
        self.akshare = akshare_service
        self.mock = None
        self.allow_mock_fallback = False

        # 数据源优先级
        self.sources = []
        if tushare_service:
            self.sources.append(('TuShare', tushare_service))
        if tencent_service:
            self.sources.append(('Tencent', tencent_service))
        if akshare_service:
            self.sources.append(('AKShare', akshare_service))
        if mock_service:
            logger.warning("Mock数据源已被硬性禁用：不会注册、不会兜底、不会进入策略计算")

        # 结果缓存：避免同一轮查询重复请求外部数据源
        self._result_cache = {}
        self._cache_ttl_seconds = 20
        # 分级缓存TTL，降低高成本接口重复请求
        self._cache_ttl_map = {
            "realtime": 20,
            "moneyflow": 180,
            "history": 300,
            "market": 300,
        }

        # 熔断器：连续失败后短期跳过不稳定数据源
        self._breaker_state = {}
        self._breaker_fail_threshold = 2
        self._breaker_cooldown_seconds = 60

        logger.info(
            f"数据源管理器初始化完成，可用数据源: {[name for name, _ in self.sources]}, "
            "mock_fallback=forbidden"
        )

    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时行情（多数据源容错）

        Args:
            symbol: 股票代码，如 '000001'

        Returns:
            dict: 实时行情数据，失败返回None
        """
        cache_key = f"realtime:{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # 实时行情只走真正的分时源。AKShare/TuShare在本项目里容易慢或变成T+1口径，
        # 不能用于页面实时详情兜底，否则会造成长时间卡顿和数据口径混乱。
        source_map = {name: svc for name, svc in self.sources}
        preferred_order = ["Tencent"]

        for source_name in preferred_order:
            service = source_map.get(source_name)
            if not service:
                continue
            if self._is_circuit_open(source_name, "realtime"):
                logger.info(f"⏭️ 跳过 {source_name}（realtime）: 熔断冷却中")
                continue
            try:
                logger.info(f"尝试从 {source_name} 获取实时行情: {symbol}")

                if source_name != 'Tencent':
                    continue
                data = service.get_realtime_quote(symbol)

                if data:
                    data = self._normalize_realtime_quote(data, symbol)
                    self._record_success(source_name, "realtime")
                    self._set_cache(cache_key, data)
                    logger.info(f"✅ 成功从 {source_name} 获取数据: {symbol}")
                    return data
                else:
                    self._record_failure(source_name, "realtime", "empty data")
                    logger.warning(f"⚠️ {source_name} 返回空数据: {symbol}")

            except Exception as e:
                self._record_failure(source_name, "realtime", str(e))
                logger.warning(f"❌ {source_name} 获取失败: {symbol}, 错误: {str(e)}")
                continue

        logger.error(f"所有数据源均失败: {symbol}")
        return None

    def get_realtime_quotes_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取实时行情。

        批量列表页不再逐只兜底外部数据源。逐只兜底会在数据源慢/代理不稳定时把页面拖到
        数十秒甚至卡住；列表宁可返回已有缓存/腾讯批量结果，也不要阻塞主流程。
        """
        normalized_symbols = []
        seen = set()
        for sym in symbols or []:
            code = str(sym or "").strip()
            if len(code) != 6 or not code.isdigit() or code in seen:
                continue
            seen.add(code)
            normalized_symbols.append(code)
        if not normalized_symbols:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        missing: List[str] = []

        for symbol in normalized_symbols:
            cached = self._get_cache(f"realtime:{symbol}")
            if cached is not None:
                result[symbol] = cached
            else:
                missing.append(symbol)

        if not missing:
            return result

        source_map = {name: svc for name, svc in self.sources}
        tencent_service = source_map.get("Tencent")
        if tencent_service and hasattr(tencent_service, "get_realtime_quotes_batch") and (
            not self._is_circuit_open("Tencent", "realtime")
        ):
            try:
                batched = tencent_service.get_realtime_quotes_batch(missing) or {}
                if batched:
                    for symbol, quote in batched.items():
                        if not quote:
                            continue
                        normalized = self._normalize_realtime_quote(quote, symbol)
                        result[symbol] = normalized
                        self._set_cache(f"realtime:{symbol}", normalized)
                    self._record_success("Tencent", "realtime")
                    missing = [symbol for symbol in missing if symbol not in result]
            except Exception as e:
                self._record_failure("Tencent", "realtime", str(e))
                logger.warning(f"❌ Tencent批量实时行情失败: {str(e)}")

        return result

    def get_history_data(self, symbol: str, days: int = 120) -> pd.DataFrame:
        """获取历史K线数据（多数据源容错）

        Args:
            symbol: 股票代码
            days: 天数

        Returns:
            pd.DataFrame: 历史K线数据
        """
        cache_key = f"history:{symbol}:{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        ts_code = self._convert_to_tushare_code(symbol)
        source_map = {name: svc for name, svc in self.sources}
        preferred_order = ["Tencent", "AKShare", "TuShare"]

        for source_name in preferred_order:
            service = source_map.get(source_name)
            if not service:
                continue
            if self._is_circuit_open(source_name, "history"):
                logger.info(f"⏭️ 跳过 {source_name}（history）: 熔断冷却中")
                continue
            try:
                logger.info(f"尝试从 {source_name} 获取历史数据: {symbol}")

                if source_name == 'TuShare':
                    df = service.get_history_data(ts_code, days=days)
                elif source_name in ('AKShare', 'Tencent'):
                    df = service.get_history_data(symbol, days=days)
                else:
                    continue

                if not df.empty:
                    df = self._normalize_history_data(df)
                    if df.empty:
                        self._record_failure(source_name, "history", "missing required columns")
                        logger.warning(f"⚠️ {source_name} 字段不完整: {symbol}")
                        continue
                    self._record_success(source_name, "history")
                    self._set_cache(cache_key, df)
                    logger.info(f"✅ 成功从 {source_name} 获取历史数据: {symbol}, 共 {len(df)} 条")
                    return df
                else:
                    self._record_failure(source_name, "history", "empty data")
                    logger.warning(f"⚠️ {source_name} 返回空数据: {symbol}")

            except Exception as e:
                self._record_failure(source_name, "history", str(e))
                logger.warning(f"❌ {source_name} 获取失败: {symbol}, 错误: {str(e)}")
                continue

        logger.error(f"所有数据源均失败: {symbol}")
        return pd.DataFrame()

    def get_money_flow(self, symbol: str, days: int = 5) -> Optional[Dict[str, Any]]:
        """获取资金流向数据（多数据源容错）

        Args:
            symbol: 股票代码
            days: 天数

        Returns:
            dict: 资金流向数据
        """
        cache_key = f"moneyflow:{symbol}:{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        ts_code = self._convert_to_tushare_code(symbol)
        source_map = {name: svc for name, svc in self.sources}
        preferred_order = ["TuShare", "AKShare"]

        for source_name in preferred_order:
            service = source_map.get(source_name)
            if not service:
                continue
            if self._is_circuit_open(source_name, "moneyflow"):
                logger.info(f"⏭️ 跳过 {source_name}（moneyflow）: 熔断冷却中")
                continue
            try:
                logger.info(f"尝试从 {source_name} 获取资金流向: {symbol}")

                if source_name == 'TuShare':
                    data = service.get_money_flow(ts_code, days)
                elif source_name == 'AKShare':
                    data = service.get_money_flow(symbol, days)
                else:
                    continue

                if data:
                    raw_source = source_name
                    data = self._normalize_money_flow(data, symbol)
                    data["source"] = raw_source
                    data["quality"] = "proxy" if data.get("estimated") else "real"
                    data["available"] = True
                    data["display_mode"] = "proxy" if data["quality"] == "proxy" else "normal"
                    data["source_status"] = "available"
                    self._record_success(source_name, "moneyflow")
                    self._set_cache(cache_key, data)
                    logger.info(f"✅ 成功从 {source_name} 获取资金流向: {symbol}")
                    return data
                else:
                    self._record_failure(source_name, "moneyflow", "empty data")
                    logger.warning(f"⚠️ {source_name} 返回空数据: {symbol}")

            except Exception as e:
                self._record_failure(source_name, "moneyflow", str(e))
                logger.warning(f"❌ {source_name} 获取失败: {symbol}, 错误: {str(e)}")
                continue

        logger.error(f"所有数据源均失败: {symbol}")
        return None

    def get_a_share_snapshot(self) -> List[Dict[str, Any]]:
        """获取全A实时快照（优先 AKShare）。"""
        cache_key = "market:a_share_snapshot"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        source_map = {name: svc for name, svc in self.sources}
        preferred_order = ["AKShare", "TuShare"]

        for source_name in preferred_order:
            service = source_map.get(source_name)
            if not service:
                continue
            if self._is_circuit_open(source_name, "snapshot"):
                logger.info(f"⏭️ 跳过 {source_name}（snapshot）: 熔断冷却中")
                continue
            try:
                if not hasattr(service, "get_a_share_spot_snapshot"):
                    items = []
                else:
                    items = service.get_a_share_spot_snapshot()

                if items:
                    normalized = self._normalize_market_snapshot(items)
                    if normalized:
                        self._record_success(source_name, "snapshot")
                        self._set_cache(cache_key, normalized)
                        logger.info(f"✅ 成功从 {source_name} 获取全A快照: {len(normalized)} 条")
                        return normalized
                self._record_failure(source_name, "snapshot", "empty data")
            except Exception as e:
                self._record_failure(source_name, "snapshot", str(e))
                logger.warning(f"❌ {source_name} 全A快照失败: {str(e)}")
                continue

        # fallback: TuShare行业清单 + Tencent批量实时行情，构建全A快照
        tushare_service = source_map.get("TuShare")
        tencent_service = source_map.get("Tencent")
        if tushare_service and tencent_service and hasattr(tencent_service, "get_realtime_quotes_batch"):
            try:
                industry_map = self.get_stock_industry_map()
                symbols = [s for s in industry_map.keys() if len(str(s)) == 6 and str(s).isdigit()]
                if symbols:
                    quotes_map = tencent_service.get_realtime_quotes_batch(symbols)
                    items = []
                    for symbol, quote in quotes_map.items():
                        items.append(
                            {
                                "symbol": symbol,
                                "name": quote.get("name", symbol),
                                "industry": industry_map.get(symbol, "未知行业"),
                                "price": quote.get("price"),
                                "change": quote.get("change"),
                                "pct_change": quote.get("pct_change"),
                                "open": quote.get("open"),
                                "high": quote.get("high"),
                                "low": quote.get("low"),
                                "volume": quote.get("volume"),
                                "amount": quote.get("amount"),
                                "turnover_rate": quote.get("turnover_rate"),
                                "update_time": quote.get("update_time"),
                            }
                        )
                    normalized = self._normalize_market_snapshot(items)
                    if normalized:
                        self._set_cache(cache_key, normalized)
                        logger.info(f"✅ 成功从 TuShare+Tencent 构建全A快照: {len(normalized)} 条")
                        return normalized
            except Exception as e:
                logger.warning(f"❌ TuShare+Tencent 全A快照构建失败: {str(e)}")

        logger.error("所有数据源均失败: 全A快照")
        return []

    def get_stock_industry_map(self) -> Dict[str, str]:
        """获取A股行业映射（优先 TuShare）。"""
        cache_key = "market:industry_map"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        source_map = {name: svc for name, svc in self.sources}
        preferred_order = ["TuShare", "AKShare"]

        for source_name in preferred_order:
            service = source_map.get(source_name)
            if not service:
                continue
            if self._is_circuit_open(source_name, "industry_map"):
                logger.info(f"⏭️ 跳过 {source_name}（industry_map）: 熔断冷却中")
                continue
            try:
                if hasattr(service, "get_stock_industry_map"):
                    mapping = service.get_stock_industry_map()
                else:
                    mapping = {}
                if mapping:
                    self._record_success(source_name, "industry_map")
                    self._set_cache(cache_key, mapping)
                    logger.info(f"✅ 成功从 {source_name} 获取行业映射: {len(mapping)} 条")
                    return mapping
                self._record_failure(source_name, "industry_map", "empty data")
            except Exception as e:
                self._record_failure(source_name, "industry_map", str(e))
                logger.warning(f"❌ {source_name} 行业映射失败: {str(e)}")
                continue

        logger.warning("所有数据源均失败: 行业映射")
        return {}

    def get_stock_basic_map(self) -> Dict[str, Dict[str, Any]]:
        """获取A股基础信息映射（代码/名称/行业）。"""
        cache_key = "market:stock_basic_map"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        source_map = {name: svc for name, svc in self.sources}
        tushare_service = source_map.get("TuShare")
        if tushare_service and hasattr(tushare_service, "get_stock_basic_map"):
            try:
                mapping = tushare_service.get_stock_basic_map()
                if mapping:
                    self._set_cache(cache_key, mapping)
                    return mapping
            except Exception as e:
                logger.warning(f"❌ TuShare股票基础映射失败: {str(e)}")

        snapshot = self.get_a_share_snapshot()
        if snapshot:
            mapping = {}
            for item in snapshot:
                symbol = str(item.get("symbol") or "").strip()
                if len(symbol) != 6 or not symbol.isdigit():
                    continue
                mapping[symbol] = {
                    "symbol": symbol,
                    "name": str(item.get("name") or symbol).strip() or symbol,
                    "industry": str(item.get("industry") or "未知行业").strip() or "未知行业",
                }
            if mapping:
                self._set_cache(cache_key, mapping)
                return mapping

        # 仅用于搜索/名称解析兜底，不提供价格数据，避免外部基础信息源短暂不可用时搜索完全失效。
        return copy.deepcopy(MINIMAL_STOCK_BASIC_MAP)

    def search_stocks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """按代码或名称搜索A股。"""
        keyword = str(query or "").strip()
        if not keyword:
            return []
        normalized = keyword.upper()
        max_limit = max(1, min(int(limit or 10), 20))

        minimal_matches = self._search_basic_mapping(
            MINIMAL_STOCK_BASIC_MAP,
            normalized,
            max_limit,
        )
        if minimal_matches and (
            len(keyword) >= 2
            or any(item.get("symbol") == keyword for item in minimal_matches)
        ):
            return minimal_matches

        basic_map = self.get_stock_basic_map() or {}
        snapshot_items = self.get_a_share_snapshot() or []
        merged: Dict[str, Dict[str, Any]] = {
            symbol: {
                "symbol": symbol,
                "name": str(item.get("name") or symbol).strip() or symbol,
                "industry": str(item.get("industry") or "未知行业").strip() or "未知行业",
            }
            for symbol, item in basic_map.items()
        }

        for item in snapshot_items:
            symbol = str(item.get("symbol") or "").strip()
            if len(symbol) != 6 or not symbol.isdigit():
                continue
            merged.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": str(item.get("name") or symbol).strip() or symbol,
                    "industry": str(item.get("industry") or "未知行业").strip() or "未知行业",
                },
            )
            merged[symbol].update(
                {
                    "name": str(item.get("name") or merged[symbol].get("name") or symbol).strip() or symbol,
                    "industry": str(item.get("industry") or merged[symbol].get("industry") or "未知行业").strip() or "未知行业",
                    "price": self._safe_float(item.get("price")),
                    "pct_change": self._safe_float(item.get("pct_change")),
                    "amount": self._safe_float(item.get("amount")),
                    "turnover_rate": self._safe_float(item.get("turnover_rate")),
                    "update_time": item.get("update_time"),
                }
            )

        results: List[Dict[str, Any]] = []
        for item in merged.values():
            scored = self._score_stock_search_item(item, normalized)
            if not scored:
                continue
            results.append(scored)

        results.sort(key=lambda item: (item.get("_score", 0), self._safe_float(item.get("amount"))), reverse=True)
        return [
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "industry": item.get("industry"),
                "price": item.get("price"),
                "pct_change": item.get("pct_change"),
                "turnover_rate": item.get("turnover_rate"),
                "update_time": item.get("update_time"),
            }
            for item in results[:max_limit]
        ]

    def _search_basic_mapping(
        self,
        mapping: Dict[str, Dict[str, Any]],
        normalized_keyword: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        results = []
        for item in (mapping or {}).values():
            scored = self._score_stock_search_item(item, normalized_keyword)
            if scored:
                results.append(scored)
        results.sort(key=lambda item: item.get("_score", 0), reverse=True)
        return [
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "industry": item.get("industry"),
                "price": item.get("price"),
                "pct_change": item.get("pct_change"),
                "turnover_rate": item.get("turnover_rate"),
                "update_time": item.get("update_time"),
            }
            for item in results[:limit]
        ]

    def _score_stock_search_item(
        self,
        item: Dict[str, Any],
        normalized_keyword: str,
    ) -> Optional[Dict[str, Any]]:
        symbol = str(item.get("symbol") or "").strip()
        name = str(item.get("name") or "").strip()
        if not symbol or not name:
            return None

        name_upper = name.upper()
        score = -1
        if normalized_keyword == symbol:
            score = 1200
        elif normalized_keyword == name_upper:
            score = 1150
        elif symbol.startswith(normalized_keyword):
            score = 1020 - len(symbol)
        elif normalized_keyword in symbol:
            score = 920 - symbol.index(normalized_keyword) * 5
        elif name_upper.startswith(normalized_keyword):
            score = 980 - len(name)
        elif normalized_keyword in name_upper:
            score = 860 - name_upper.index(normalized_keyword) * 8

        if score < 0:
            return None

        liquidity_bonus = min(60.0, self._safe_float(item.get("amount")) / 100000000)
        return {
            **item,
            "_score": score + liquidity_bonus,
        }

    def resolve_stock(self, query: str) -> Optional[Dict[str, Any]]:
        """将代码/名称解析为标准股票对象。"""
        keyword = str(query or "").strip()
        if not keyword:
            return None
        if len(keyword) == 6 and keyword.isdigit():
            cached_snapshot = self._get_cache("market:a_share_snapshot") or []
            for item in cached_snapshot:
                if str(item.get("symbol") or "") == keyword:
                    return {
                        "symbol": keyword,
                        "name": item.get("name") or keyword,
                        "industry": item.get("industry") or "未知行业",
                    }
            return {
                "symbol": keyword,
                "name": keyword,
                "industry": "未知行业",
            }

        results = self.search_stocks(keyword, limit=8)
        if not results:
            return None

        upper_keyword = keyword.upper()
        for item in results:
            if upper_keyword == str(item.get("name") or "").upper():
                return item
        return results[0]

    def _convert_to_tushare_code(self, symbol: str) -> str:
        """转换为TuShare格式代码"""
        if '.' in symbol:
            return symbol

        if symbol.startswith('6'):
            return f"{symbol}.SH"
        elif symbol.startswith(('0', '3')):
            return f"{symbol}.SZ"
        elif symbol.startswith(('4', '8')):
            return f"{symbol}.BJ"
        else:
            return f"{symbol}.SH"

    def get_health_status(self) -> Dict[str, Any]:
        """获取各数据源健康状态

        Returns:
            dict: 健康状态信息
        """
        status = {
            'total_sources': len(self.sources),
            'sources': []
        }

        for source_name, service in self.sources:
            operations = {}
            for operation in ["realtime", "history", "moneyflow", "snapshot", "industry_map"]:
                breaker = self._breaker_state.get(self._breaker_key(source_name, operation), {})
                open_until = float(breaker.get("open_until") or 0)
                operations[operation] = {
                    "failures": int(breaker.get("failures") or 0),
                    "circuit_open": open_until > time.time(),
                    "open_until": open_until or None,
                }
            source_info = {
                'name': source_name,
                'available': service is not None,
                'type': 'primary' if source_name == 'TuShare' else 'fallback',
                'operations': operations,
            }
            status['sources'].append(source_info)
        status["cache"] = {
            "moneyflow_keys": len([key for key in self._result_cache.keys() if str(key).startswith("moneyflow:")]),
            "snapshot_cached": "market:a_share_snapshot" in self._result_cache,
            "industry_map_cached": "market:industry_map" in self._result_cache,
        }
        status["mock_fallback"] = False
        status["mock_policy"] = "forbidden"

        return status

    def get_money_flow_coverage_status(self) -> Dict[str, Any]:
        """Return lightweight money-flow data quality diagnostics."""
        health = self.get_health_status()
        capability_names = {"TuShare", "AKShare"}
        moneyflow_sources = []
        for item in health.get("sources", []):
            name = item.get("name")
            if name not in capability_names:
                continue
            operation = (item.get("operations") or {}).get("moneyflow") or {}
            moneyflow_sources.append(
                {
                    "name": name,
                    "available": item.get("available"),
                    "circuit_open": operation.get("circuit_open"),
                    "failures": operation.get("failures"),
                    "type": item.get("type"),
                    "supports_money_flow": True,
                }
            )
        open_sources = [item for item in moneyflow_sources if item.get("available") and not item.get("circuit_open")]
        cached_count = int((health.get("cache") or {}).get("moneyflow_keys") or 0)
        cached_moneyflow = [
            (value[0] if isinstance(value, tuple) and value else value)
            for key, value in self._result_cache.items()
            if str(key).startswith("moneyflow:")
        ]
        real_cached = len([item for item in cached_moneyflow if isinstance(item, dict) and item.get("quality") == "real"])
        proxy_cached = len([item for item in cached_moneyflow if isinstance(item, dict) and item.get("quality") == "proxy"])
        return {
            "status": "available" if open_sources else "degraded",
            "coverage_label": "真实资金流优先，代理因子仅作降级展示",
            "cached_symbol_count": cached_count,
            "real_cached_symbol_count": real_cached,
            "proxy_cached_symbol_count": proxy_cached,
            "unavailable_symbol_count": 0,
            "failure_reasons": [
                {
                    "source": item.get("name"),
                    "failures": item.get("failures"),
                    "reason": "circuit_open" if item.get("circuit_open") else None,
                }
                for item in moneyflow_sources
                if item.get("failures") or item.get("circuit_open")
            ],
            "source_count": len(open_sources),
            "sources": moneyflow_sources,
            "mock_fallback": False,
            "mock_policy": "forbidden",
            "quality_levels": [
                {"key": "real", "label": "真实资金流", "description": "来自 AKShare/TuShare 的个股资金流接口。"},
                {"key": "proxy", "label": "代理资金强度", "description": "真实接口不可用时由成交额、涨跌幅和换手率构造。"},
                {"key": "unavailable", "label": "暂不可用", "description": "不参与资金评分，不显示为 0 分。"},
            ],
        }

    def get_market_theme_boards(self) -> List[Dict[str, Any]]:
        """获取市场板块/概念资金流主题数据。"""
        cache_key = "market:theme_boards"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        records: List[Dict[str, Any]] = []
        source_map = {name: svc for name, svc in self.sources}
        for source_name in ["AKShare", "TuShare"]:
            service = source_map.get(source_name)
            if not service or not hasattr(service, "get_market_theme_boards"):
                continue
            if self._is_circuit_open(source_name, "theme_boards"):
                continue
            try:
                records = service.get_market_theme_boards() or []
                if records:
                    self._record_success(source_name, "theme_boards")
                    self._set_cache(cache_key, records)
                    logger.info(f"✅ 成功从 {source_name} 获取市场主题板块: {len(records)} 条")
                    return records
                self._record_failure(source_name, "theme_boards", "empty data")
            except Exception as e:
                self._record_failure(source_name, "theme_boards", str(e))
                logger.warning(f"❌ {source_name} 市场主题板块失败: {str(e)}")
        return []

    def get_theme_constituents(self, theme_name: str, category: str = "concept") -> List[Dict[str, Any]]:
        """获取主题成分股。"""
        safe_name = str(theme_name or "").strip()
        safe_category = str(category or "concept").strip() or "concept"
        if not safe_name:
            return []
        cache_key = f"market:theme_constituents:{safe_category}:{safe_name}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        source_map = {name: svc for name, svc in self.sources}
        for source_name in ["AKShare", "TuShare"]:
            service = source_map.get(source_name)
            if not service or not hasattr(service, "get_theme_constituents"):
                continue
            if self._is_circuit_open(source_name, "theme_constituents"):
                continue
            try:
                executor = ThreadPoolExecutor(max_workers=1)
                future = executor.submit(service.get_theme_constituents, safe_name, safe_category)
                try:
                    rows = future.result(timeout=2.5) or []
                except TimeoutError:
                    future.cancel()
                    rows = []
                    self._record_failure(source_name, "theme_constituents", "timeout")
                    logger.warning(f"⏱️ {source_name} 主题成分股超时: {safe_name}")
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
                if rows:
                    self._record_success(source_name, "theme_constituents")
                    self._set_cache(cache_key, rows)
                    return rows
                self._set_cache(cache_key, [])
                self._record_failure(source_name, "theme_constituents", "empty data")
            except Exception as e:
                self._record_failure(source_name, "theme_constituents", str(e))
                logger.warning(f"❌ {source_name} 主题成分股失败: {safe_name}, {str(e)}")
                self._set_cache(cache_key, [])
        return []

    def _normalize_realtime_quote(self, data: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """统一实时行情字段，避免不同数据源字段不一致导致上层报错。"""
        return {
            "code": data.get("code") or data.get("symbol") or symbol,
            "name": data.get("name") or symbol,
            "price": data.get("price", data.get("current_price")),
            "change": data.get("change", data.get("change_amount", 0)),
            "pct_change": data.get("pct_change", data.get("change_percent", 0)),
            "open": data.get("open", data.get("open_price")),
            "high": data.get("high", data.get("high_price")),
            "low": data.get("low", data.get("low_price")),
            "volume": data.get("volume", 0),
            "amount": data.get("amount", data.get("turnover", 0)),
            "turnover_rate": data.get("turnover_rate"),
            "update_time": data.get("update_time", data.get("timestamp")),
        }

    def _normalize_history_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """统一历史K线字段，保证技术分析链路始终可用。"""
        rename_map = {
            "trade_date": "date",
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "turnover": "amount",
        }
        normalized = df.rename(columns=rename_map).copy()

        required_cols = ["date", "open", "high", "low", "close", "volume"]
        if any(col not in normalized.columns for col in required_cols):
            return pd.DataFrame()

        normalized["date"] = normalized["date"].astype(str)
        return normalized.sort_values("date").reset_index(drop=True)

    def _normalize_money_flow(self, data: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """统一资金流向字段，仅面向真实数据源或明确标记的代理数据。"""
        if "main_net_inflow" in data:
            amount_unit = str(data.get("amount_unit") or "").strip().lower()
            unit_multiplier = 1.0
            if amount_unit in {"wan", "万元", "10k_yuan", "wan_yuan"}:
                unit_multiplier = 10000.0
            return {
                "symbol": symbol,
                "main_net_inflow": float(data.get("main_net_inflow", 0)) * unit_multiplier,
                "control_ratio": float(data.get("control_ratio", 0)),
                "trend": data.get("trend", "主力流入"),
                "strength": data.get("strength", "中"),
                "super_large_net": float(data.get("super_large_net", 0)) * unit_multiplier,
                "large_net": float(data.get("large_net", 0)) * unit_multiplier,
                "medium_net": float(data.get("medium_net", 0)) * unit_multiplier,
                "small_net": float(data.get("small_net", 0)) * unit_multiplier,
                "estimated": bool(data.get("estimated")),
            }

        summary = data.get("main_flow_summary", {})
        total_main_flow = float(summary.get("total_main_flow", 0))
        super_large_flow = float(summary.get("super_large_flow", 0))
        large_flow = float(summary.get("large_flow", 0))
        medium_flow = float(summary.get("medium_flow", 0))
        small_flow = float(summary.get("small_flow", 0))

        to_yuan = 100000000
        return {
            "symbol": symbol,
            "main_net_inflow": total_main_flow * to_yuan,
            "control_ratio": round(abs(total_main_flow) / 10, 1),
            "trend": "主力流入" if total_main_flow > 0 else "主力流出",
            "strength": "强" if abs(total_main_flow) > 200 else ("中" if abs(total_main_flow) > 50 else "弱"),
            "super_large_net": super_large_flow * to_yuan,
            "large_net": large_flow * to_yuan,
            "medium_net": medium_flow * to_yuan,
            "small_net": small_flow * to_yuan,
        }

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    def _normalize_market_snapshot(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for item in items:
            symbol = str(item.get("symbol") or item.get("code") or "").strip()
            if len(symbol) != 6 or not symbol.isdigit():
                continue
            normalized.append(
                {
                    "symbol": symbol,
                    "name": item.get("name") or symbol,
                    "industry": item.get("industry") or "未知行业",
                    "price": self._safe_float(item.get("price")),
                    "change": self._safe_float(item.get("change")),
                    "pct_change": self._safe_float(item.get("pct_change")),
                    "open": self._safe_float(item.get("open")),
                    "high": self._safe_float(item.get("high")),
                    "low": self._safe_float(item.get("low")),
                    "volume": self._safe_float(item.get("volume")),
                    "amount": self._safe_float(item.get("amount")),
                    "turnover_rate": self._safe_float(item.get("turnover_rate")),
                    "pe": self._safe_float(item.get("pe")),
                    "pb": self._safe_float(item.get("pb")),
                    "total_mv": self._safe_float(item.get("total_mv")),
                    "circ_mv": self._safe_float(item.get("circ_mv")),
                    "update_time": item.get("update_time"),
                }
            )
        return normalized

    def _get_cache(self, key: str):
        item = self._result_cache.get(key)
        if not item:
            return None
        value, expires_at = item
        if time.time() >= expires_at:
            self._result_cache.pop(key, None)
            return None
        return self._clone_value(value)

    def _set_cache(self, key: str, value):
        ttl = self._cache_ttl_for_key(key)
        self._result_cache[key] = (self._clone_value(value), time.time() + ttl)

    def _cache_ttl_for_key(self, key: str) -> int:
        prefix = str(key or "").split(":", 1)[0]
        ttl = self._cache_ttl_map.get(prefix)
        if ttl is None:
            return self._cache_ttl_seconds
        return int(ttl)

    def _clone_value(self, value):
        if isinstance(value, pd.DataFrame):
            return value.copy(deep=True)
        if isinstance(value, list):
            return copy.deepcopy(value)
        if isinstance(value, dict):
            return copy.deepcopy(value)
        return value

    def _breaker_key(self, source_name: str, operation: str) -> str:
        return f"{source_name}:{operation}"

    def _is_circuit_open(self, source_name: str, operation: str) -> bool:
        key = self._breaker_key(source_name, operation)
        state = self._breaker_state.get(key)
        if not state:
            return False
        open_until = state.get("open_until", 0)
        if open_until > time.time():
            return True
        if state.get("open_until"):
            state["open_until"] = 0
            state["failures"] = 0
        return False

    def _record_success(self, source_name: str, operation: str):
        key = self._breaker_key(source_name, operation)
        self._breaker_state[key] = {"failures": 0, "open_until": 0}

    def _record_failure(self, source_name: str, operation: str, reason: str):
        key = self._breaker_key(source_name, operation)
        state = self._breaker_state.get(key, {"failures": 0, "open_until": 0})
        state["failures"] = state.get("failures", 0) + 1
        if state["failures"] >= self._breaker_fail_threshold:
            state["open_until"] = time.time() + self._breaker_cooldown_seconds
            logger.warning(
                f"🔌 打开熔断 {source_name}/{operation} {self._breaker_cooldown_seconds}s, reason={reason}"
            )
        self._breaker_state[key] = state
