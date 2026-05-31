"""
AKShare数据服务
作为TuShare的备用数据源
"""
import os
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class AKShareService:
    """AKShare数据服务"""
    # stock_individual_fund_flow 当前返回的净额字段已经是“元”口径。
    # 早期按“万元”再次乘 10000 会把个股资金流放大一万倍。
    MONEYFLOW_AMOUNT_UNIT = 1

    def __init__(self, disable_system_proxy: bool = True):
        """初始化AKShare服务"""
        self.disable_system_proxy = disable_system_proxy
        if disable_system_proxy:
            self._disable_system_proxy()
        logger.info(f"AKShare服务初始化成功（disable_system_proxy={disable_system_proxy}）")

    @staticmethod
    def _disable_system_proxy():
        """禁用系统代理，避免本地失效代理导致东财接口请求失败。"""
        proxy_keys = [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ]
        had_proxy = any(os.environ.get(key) for key in proxy_keys)
        for key in proxy_keys:
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        if had_proxy:
            logger.warning("检测到系统代理配置，已为AKShare数据请求禁用代理")

    @staticmethod
    def _first_valid(row: pd.Series, candidates, default=None):
        for col in candidates:
            if col in row and pd.notna(row[col]):
                return row[col]
        return default

    @staticmethod
    def _to_float(value, default=0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    def get_realtime_quote(self, symbol: str):
        """获取实时行情数据

        Args:
            symbol: 股票代码，如 '000001'

        Returns:
            dict: 实时行情数据
        """
        try:
            # AKShare获取实时行情
            df = ak.stock_zh_a_spot_em()

            # 查找对应股票
            stock_data = df[df['代码'] == symbol]

            if stock_data.empty:
                logger.warning(f"未找到股票 {symbol} 的数据")
                return None

            stock = stock_data.iloc[0]

            # 转换为统一格式
            return {
                'code': symbol,
                'name': stock['名称'],
                'price': float(stock['最新价']),
                'change': float(stock['涨跌额']),
                'pct_change': float(stock['涨跌幅']),
                'high': float(stock['最高']),
                'low': float(stock['最低']),
                'open': float(stock['今开']),
                'volume': float(stock['成交量']),
                'amount': float(stock['成交额']),
                'turnover_rate': float(stock.get('换手率', 0)),
                'pe': float(stock.get('市盈率-动态', 0)),
                'pb': float(stock.get('市净率', 0)),
                'total_mv': float(stock.get('总市值', 0)),
                'circ_mv': float(stock.get('流通市值', 0)),
                'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"AKShare获取实时行情失败 {symbol}: {str(e)}")
            return None

    def get_a_share_spot_snapshot(self):
        """获取全A实时快照（用于全市场候选池）。"""
        def _parse_df(df: pd.DataFrame):
            if df is None or df.empty:
                return []
            rows = []
            for _, row in df.iterrows():
                code = str(self._first_valid(row, ["代码", "code"], "")).strip()
                if code.startswith(("sh", "sz", "bj")) and len(code) >= 8:
                    code = code[-6:]
                if len(code) != 6 or not code.isdigit():
                    continue
                name = str(self._first_valid(row, ["名称", "name"], code)).strip()
                industry = str(
                    self._first_valid(
                        row,
                        ["所处行业", "行业", "所属行业", "板块", "f128"],
                        "未知行业",
                    )
                ).strip() or "未知行业"

                rows.append(
                    {
                        "symbol": code,
                        "name": name,
                        "industry": industry,
                        "price": self._to_float(self._first_valid(row, ["最新价", "price", "f2"], 0)),
                        "pct_change": self._to_float(self._first_valid(row, ["涨跌幅", "pct_change", "f3"], 0)),
                        "change": self._to_float(self._first_valid(row, ["涨跌额", "change", "f4"], 0)),
                        "open": self._to_float(self._first_valid(row, ["今开", "open", "f17"], 0)),
                        "high": self._to_float(self._first_valid(row, ["最高", "high", "f15"], 0)),
                        "low": self._to_float(self._first_valid(row, ["最低", "low", "f16"], 0)),
                        "volume": self._to_float(self._first_valid(row, ["成交量", "volume", "f5"], 0)),
                        "amount": self._to_float(self._first_valid(row, ["成交额", "amount", "f6"], 0)),
                        "turnover_rate": self._to_float(self._first_valid(row, ["换手率", "turnover_rate", "f8"], 0)),
                        "pe": self._to_float(self._first_valid(row, ["市盈率-动态", "pe", "f9"], 0)),
                        "pb": self._to_float(self._first_valid(row, ["市净率", "pb", "f23"], 0)),
                        "total_mv": self._to_float(self._first_valid(row, ["总市值", "total_mv", "f20"], 0)),
                        "circ_mv": self._to_float(self._first_valid(row, ["流通市值", "circ_mv", "f21"], 0)),
                        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            return rows

        try:
            items = []
            try:
                df = ak.stock_zh_a_spot_em()
                items = _parse_df(df)
                if items:
                    logger.info(f"AKShare全A快照(EM)获取成功: {len(items)} 条")
                    return items
            except Exception as em_err:
                # 避免触发 AKShare 的慢速全量分页接口（会显著拖慢首屏），交给上层 TuShare+Tencent 快照兜底
                logger.warning(f"AKShare EM全A快照失败，跳过慢速fallback: {str(em_err)}")
                return []

            logger.warning("AKShare全A快照为空")
            return []
        except Exception as e:
            logger.error(f"AKShare获取全A快照失败: {str(e)}")
            return []

    def get_market_theme_boards(self):
        """获取概念/行业板块资金流与涨跌数据。"""
        records = []

        def _parse(df: pd.DataFrame, category: str):
            if df is None or df.empty:
                return
            for _, row in df.iterrows():
                name = str(self._first_valid(row, ["行业", "板块", "名称"], "")).strip()
                if not name:
                    continue
                pct_change = self._to_float(self._first_valid(row, ["行业-涨跌幅", "涨跌幅", "涨跌幅%"], 0))
                inflow_yi = self._to_float(self._first_valid(row, ["流入资金"], 0))
                outflow_yi = self._to_float(self._first_valid(row, ["流出资金"], 0))
                net_yi = self._to_float(self._first_valid(row, ["净额", "主力净流入"], 0))
                company_count = int(self._to_float(self._first_valid(row, ["公司家数", "家数"], 0)))
                leader = str(self._first_valid(row, ["领涨股"], "")).strip()
                leader_pct = self._to_float(self._first_valid(row, ["领涨股-涨跌幅"], 0))
                records.append(
                    {
                        "theme_name": name,
                        "category": category,
                        "pct_change": pct_change,
                        "money_inflow_yi": inflow_yi,
                        "money_outflow_yi": outflow_yi,
                        "money_net_inflow_yi": net_yi,
                        "amount_yi": max(inflow_yi + outflow_yi, 0),
                        "stock_count": company_count,
                        "leader_name": leader,
                        "leader_pct_change": leader_pct,
                        "source": "akshare_fund_flow",
                    }
                )

        try:
            _parse(ak.stock_fund_flow_concept(), "concept")
        except Exception as e:
            logger.warning(f"AKShare概念资金流获取失败: {str(e)}")
        try:
            _parse(ak.stock_fund_flow_industry(), "industry")
        except Exception as e:
            logger.warning(f"AKShare行业资金流获取失败: {str(e)}")
        return records

    def get_theme_constituents(self, theme_name: str, category: str = "concept"):
        """获取板块/概念成分股。"""
        try:
            if category == "industry":
                df = ak.stock_board_industry_cons_em(symbol=theme_name)
            else:
                df = ak.stock_board_concept_cons_em(symbol=theme_name)
            if df is None or df.empty:
                return []
            rows = []
            for _, row in df.iterrows():
                symbol = str(self._first_valid(row, ["代码", "code"], "")).strip()
                if symbol.startswith(("sh", "sz", "bj")) and len(symbol) >= 8:
                    symbol = symbol[-6:]
                if len(symbol) != 6 or not symbol.isdigit():
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "name": str(self._first_valid(row, ["名称", "name"], symbol)).strip(),
                        "price": self._to_float(self._first_valid(row, ["最新价", "price"], 0)),
                        "pct_change": self._to_float(self._first_valid(row, ["涨跌幅", "pct_change"], 0)),
                        "amount": self._to_float(self._first_valid(row, ["成交额", "amount"], 0)),
                        "turnover_rate": self._to_float(self._first_valid(row, ["换手率", "turnover_rate"], 0)),
                    }
                )
            return rows
        except Exception as e:
            logger.warning(f"AKShare主题成分股获取失败 {theme_name}/{category}: {str(e)}")
            return []

    def get_history_data(self, symbol: str, days: int = 120):
        """获取历史K线数据

        Args:
            symbol: 股票代码
            days: 天数

        Returns:
            pd.DataFrame: 历史K线数据
        """
        try:
            # 计算日期范围
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y%m%d')

            # 获取历史数据
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )

            if df.empty:
                logger.warning(f"未找到股票 {symbol} 的历史数据")
                return pd.DataFrame()

            # 重命名列以匹配格式
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '涨跌幅': 'pct_chg',
                '涨跌额': 'change'
            })

            # 确保日期格式正确
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')

            return df.tail(days)

        except Exception as e:
            logger.error(f"AKShare获取历史数据失败 {symbol}: {str(e)}")
            return pd.DataFrame()

    def get_money_flow(self, symbol: str, days: int = 5):
        """获取资金流向数据（简化估算）

        Args:
            symbol: 股票代码
            days: 天数

        Returns:
            dict: 资金流向数据
        """
        try:
            # AKShare获取个股资金流
            df = ak.stock_individual_fund_flow(stock=symbol, market="sh" if symbol.startswith('6') else "sz")

            if df.empty:
                logger.warning(f"未找到股票 {symbol} 的资金流向数据")
                return None

            # 取最近几天的数据。该接口通常按日期升序返回，tail 才是最近 N 天。
            recent_df = df.tail(days).copy()

            # 东方财富返回可能带逗号/字符串，先做数值化
            flow_cols = [
                '主力净流入-净额',
                '超大单净流入-净额',
                '大单净流入-净额',
                '中单净流入-净额',
                '小单净流入-净额',
            ]
            for col in flow_cols:
                if col in recent_df.columns:
                    recent_df[col] = pd.to_numeric(
                        recent_df[col].astype(str).str.replace(',', '', regex=False),
                        errors='coerce',
                    ).fillna(0.0)

            # 计算汇总（原始口径：元）
            main_net_inflow_yuan = recent_df['主力净流入-净额'].sum()
            super_large_net_yuan = recent_df['超大单净流入-净额'].sum()
            large_net_yuan = recent_df['大单净流入-净额'].sum()
            medium_net_yuan = recent_df['中单净流入-净额'].sum()
            small_net_yuan = recent_df['小单净流入-净额'].sum()

            # 统一换算为元
            main_net_inflow = main_net_inflow_yuan * self.MONEYFLOW_AMOUNT_UNIT
            super_large_net = super_large_net_yuan * self.MONEYFLOW_AMOUNT_UNIT
            large_net = large_net_yuan * self.MONEYFLOW_AMOUNT_UNIT
            medium_net = medium_net_yuan * self.MONEYFLOW_AMOUNT_UNIT
            small_net = small_net_yuan * self.MONEYFLOW_AMOUNT_UNIT

            # 计算控盘度
            total_amount_yuan = abs(super_large_net_yuan) + abs(large_net_yuan)
            control_ratio = (abs(main_net_inflow_yuan) / total_amount_yuan * 100) if total_amount_yuan > 0 else 0
            control_ratio = max(0.0, min(float(control_ratio), 100.0))

            return {
                'main_net_inflow': float(main_net_inflow),
                'control_ratio': float(control_ratio),
                'trend': "主力流入" if main_net_inflow > 0 else "主力流出",
                'strength': "强势" if abs(main_net_inflow_yuan) > total_amount_yuan * 0.1 else "一般",
                'super_large_net': float(super_large_net),
                'large_net': float(large_net),
                'medium_net': float(medium_net),
                'small_net': float(small_net),
                'amount_unit': 'yuan',
            }

        except Exception as e:
            logger.error(f"AKShare获取资金流向失败 {symbol}: {str(e)}")
            return None
