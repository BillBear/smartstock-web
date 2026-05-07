"""
TuShare Pro数据服务
封装TuShare API调用，提供股票数据获取功能
"""
import tushare as ts
import pandas as pd
from datetime import datetime, timedelta
import logging
import time
from functools import lru_cache

logger = logging.getLogger(__name__)

class TuShareService:
    """TuShare数据服务"""
    MONEYFLOW_AMOUNT_UNIT = 10000  # TuShare moneyflow 金额字段单位为万元

    def __init__(self, token: str):
        """初始化TuShare服务

        Args:
            token: TuShare Pro token
        """
        self.token = token
        ts.set_token(token)
        self.pro = ts.pro_api()
        self._cache = {}  # 简单的内存缓存
        self._cache_ttl = 7200  # 缓存2小时（7200秒），避免频率限制
        logger.info("TuShare服务初始化成功")

    def _get_cache(self, key: str):
        """从缓存获取数据"""
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                logger.info(f"从缓存返回数据: {key}")
                return data
        return None

    def _set_cache(self, key: str, data):
        """设置缓存"""
        self._cache[key] = (data, time.time())

    def get_stock_basic_map(self, force_refresh: bool = False):
        """获取A股基础信息映射。"""
        cache_key = "stock_basic_all_a"
        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        try:
            df = self.pro.stock_basic(
                exchange="",
                list_status="L",
                fields="symbol,industry,name",
            )
            if df is None or df.empty:
                logger.warning("TuShare行业映射为空")
                return {}

            mapping = {}
            for _, row in df.iterrows():
                symbol = str(row.get("symbol") or "").strip()
                if len(symbol) != 6 or not symbol.isdigit():
                    continue
                name = str(row.get("name") or symbol).strip() or symbol
                industry = str(row.get("industry") or "").strip() or "未知行业"
                mapping[symbol] = {
                    "symbol": symbol,
                    "name": name,
                    "industry": industry,
                }

            self._set_cache(cache_key, mapping)
            logger.info(f"TuShare股票基础映射加载成功: {len(mapping)} 条")
            return mapping
        except Exception as e:
            logger.warning(f"获取TuShare股票基础映射失败: {str(e)}")
            stale = self._get_stale_cache(cache_key)
            return stale or {}

    def get_stock_industry_map(self, force_refresh: bool = False):
        """获取A股代码->行业映射。"""
        basic_map = self.get_stock_basic_map(force_refresh=force_refresh)
        return {
            symbol: str(item.get("industry") or "未知行业")
            for symbol, item in (basic_map or {}).items()
        }

    def get_realtime_quote(self, ts_code: str):
        """获取实时行情数据（带缓存和fallback）

        Args:
            ts_code: 股票代码，如 '000001.SZ'

        Returns:
            dict: 实时行情数据
        """
        # 检查缓存
        cache_key = f"quote_{ts_code}"
        cached_data = self._get_cache(cache_key)
        if cached_data:
            return cached_data

        try:
            # 先获取股票基本信息
            stock_basic = self.pro.stock_basic(ts_code=ts_code, fields='ts_code,name,industry,area,list_date')
            if stock_basic.empty:
                logger.warning(f"未找到股票 {ts_code} 的基本信息")
                # 尝试从历史缓存获取（即使过期也返回）
                return self._get_stale_cache(cache_key)

            stock_info = stock_basic.iloc[0]

            # 获取最近30天的交易数据（确保能获取到数据）
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')

            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                logger.warning(f"未找到股票 {ts_code} 的交易数据")
                return self._get_stale_cache(cache_key)

            # 按日期降序排列，取最新一条
            df = df.sort_values('trade_date', ascending=False)
            latest = df.iloc[0]

            # 计算涨跌
            pct_change = latest['pct_chg'] if pd.notna(latest['pct_chg']) else 0
            change = latest['close'] - latest['pre_close']

            result = {
                'code': ts_code.split('.')[0],
                'name': stock_info.get('name', '未知'),
                'price': float(latest['close']),
                'change': float(change),
                'pct_change': float(pct_change),
                'high': float(latest['high']),
                'low': float(latest['low']),
                'open': float(latest['open']),
                'volume': float(latest['vol'] * 100),  # 手转为股
                'amount': float(latest['amount'] * 1000),  # 千元转为元
                'turnover_rate': float(latest.get('turnover_rate', 0) if pd.notna(latest.get('turnover_rate')) else 0),
                'pe': float(latest.get('pe', 0) if pd.notna(latest.get('pe')) else 0),
                'pb': float(latest.get('pb', 0) if pd.notna(latest.get('pb')) else 0),
                'total_mv': float(latest.get('total_mv', 0) if pd.notna(latest.get('total_mv')) else 0),
                'circ_mv': float(latest.get('circ_mv', 0) if pd.notna(latest.get('circ_mv')) else 0),
                'update_time': latest['trade_date']
            }

            # 缓存结果（永久存储以便fallback使用）
            self._set_cache(cache_key, result)
            self._set_permanent_cache(cache_key, result)
            return result

        except Exception as e:
            logger.warning(f"获取实时行情失败 {ts_code}: {str(e)}，尝试使用缓存数据")
            # API失败时，返回过期缓存或永久缓存
            stale_data = self._get_stale_cache(cache_key)
            if stale_data:
                logger.info(f"使用历史缓存数据: {ts_code}")
                return stale_data

            logger.error(f"无可用缓存数据: {ts_code}")
            return None

    def _get_stale_cache(self, key: str):
        """获取过期缓存（用于API失败时的fallback）"""
        # 先检查永久缓存
        perm_key = f"perm_{key}"
        if perm_key in self._cache:
            data, _ = self._cache[perm_key]
            return data
        # 检查普通缓存（即使过期）
        if key in self._cache:
            data, _ = self._cache[key]
            return data
        return None

    def _set_permanent_cache(self, key: str, data):
        """设置永久缓存（用于fallback）"""
        perm_key = f"perm_{key}"
        self._cache[perm_key] = (data, time.time())

    def get_history_data(self, ts_code: str, start_date: str = None, end_date: str = None, days: int = 120):
        """获取历史K线数据

        Args:
            ts_code: 股票代码
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            days: 天数（如果未指定日期范围）

        Returns:
            pd.DataFrame: 历史K线数据
        """
        try:
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')

            if not start_date:
                start = datetime.now() - timedelta(days=days)
                start_date = start.strftime('%Y%m%d')

            # 获取日K线数据
            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                logger.warning(f"未找到股票 {ts_code} 的历史数据")
                return pd.DataFrame()

            # 按日期排序（从旧到新）
            df = df.sort_values('trade_date')

            # 重命名列以匹配前端需求
            df = df.rename(columns={
                'trade_date': 'date',
                'vol': 'volume',
                'amount': 'amount'
            })

            # 成交量和成交额单位转换
            df['volume'] = df['volume'] * 100  # 手转股
            df['amount'] = df['amount'] * 1000  # 千元转元

            return df

        except Exception as e:
            logger.error(f"获取历史数据失败 {ts_code}: {str(e)}")
            return pd.DataFrame()

    def get_money_flow(self, ts_code: str, days: int = 5):
        """获取资金流向数据

        注意：TuShare的moneyflow接口需要2000积分以上权限
        如果权限不足，将返回模拟数据

        Args:
            ts_code: 股票代码
            days: 天数

        Returns:
            dict: 资金流向数据
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days*2)

            # 尝试获取资金流向数据
            df = self.pro.moneyflow(
                ts_code=ts_code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )

            if df.empty:
                logger.warning(f"未找到股票 {ts_code} 的资金流向数据，返回估算数据")
                return self._get_estimated_money_flow(ts_code, days)

            # 取最近的数据
            df = df.sort_values('trade_date', ascending=False).head(days)

            # 计算汇总数据
            buy_elg = df['buy_elg_amount'].sum()
            sell_elg = df['sell_elg_amount'].sum()
            buy_lg = df['buy_lg_amount'].sum()
            sell_lg = df['sell_lg_amount'].sum()
            buy_md = df['buy_md_amount'].sum()
            sell_md = df['sell_md_amount'].sum()
            buy_sm = df['buy_sm_amount'].sum()
            sell_sm = df['sell_sm_amount'].sum()

            # TuShare moneyflow 的 amount 字段口径为“万元”，统一换算为“元”返回
            main_net_inflow_wan = (buy_elg - sell_elg) + (buy_lg - sell_lg)
            main_net_inflow = main_net_inflow_wan * self.MONEYFLOW_AMOUNT_UNIT
            total_amount = abs(buy_elg) + abs(sell_elg) + abs(buy_lg) + abs(sell_lg)
            control_ratio = (abs(main_net_inflow_wan) / total_amount * 100) if total_amount > 0 else 0

            if main_net_inflow_wan > 0:
                trend = "主力流入"
                strength = "强势" if main_net_inflow_wan > total_amount * 0.1 else "一般"
            else:
                trend = "主力流出"
                strength = "强势" if abs(main_net_inflow_wan) > total_amount * 0.1 else "一般"

            return {
                'main_net_inflow': float(main_net_inflow),
                'control_ratio': float(control_ratio),
                'trend': trend,
                'strength': strength,
                'super_large_net': float((buy_elg - sell_elg) * self.MONEYFLOW_AMOUNT_UNIT),
                'large_net': float((buy_lg - sell_lg) * self.MONEYFLOW_AMOUNT_UNIT),
                'medium_net': float((buy_md - sell_md) * self.MONEYFLOW_AMOUNT_UNIT),
                'small_net': float((buy_sm - sell_sm) * self.MONEYFLOW_AMOUNT_UNIT),
                'amount_unit': 'yuan',
            }

        except Exception as e:
            logger.warning(f"获取资金流向失败 {ts_code}: {str(e)}，返回估算数据")
            return self._get_estimated_money_flow(ts_code, days)

    def _get_estimated_money_flow(self, ts_code: str, days: int = 5):
        """基于成交量估算资金流向（当无权限访问moneyflow接口时使用）"""
        try:
            # 获取最近的交易数据
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y%m%d')

            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                return None

            df = df.sort_values('trade_date', ascending=False).head(days)

            # 基于价格和成交量估算资金流向
            total_amount = df['amount'].sum() * 1000  # 千元转元
            avg_pct_change = df['pct_chg'].mean()

            # 估算主力净流入（根据涨跌幅和成交额）
            estimated_inflow = total_amount * (avg_pct_change / 100) * 0.3

            return {
                'main_net_inflow': float(estimated_inflow),
                'control_ratio': min(abs(avg_pct_change) * 5, 50),  # 简化估算
                'trend': "主力流入" if avg_pct_change > 0 else "主力流出",
                'strength': "强势" if abs(avg_pct_change) > 3 else "一般",
                'super_large_net': float(estimated_inflow * 0.6),
                'large_net': float(estimated_inflow * 0.4),
                'medium_net': float(-estimated_inflow * 0.3),
                'small_net': float(-estimated_inflow * 0.7),
            }
        except Exception as e:
            logger.error(f"估算资金流向失败 {ts_code}: {str(e)}")
            return None

    def convert_stock_code(self, code: str) -> str:
        """转换股票代码为TuShare格式

        Args:
            code: 股票代码，如 '000001' 或 '600000'

        Returns:
            str: TuShare格式代码，如 '000001.SZ' 或 '600000.SH'
        """
        if '.' in code:
            return code

        # 根据代码判断市场
        if code.startswith('6'):
            return f"{code}.SH"  # 上海
        elif code.startswith(('0', '3')):
            return f"{code}.SZ"  # 深圳
        elif code.startswith('4') or code.startswith('8'):
            return f"{code}.BJ"  # 北京
        else:
            return f"{code}.SH"  # 默认上海
