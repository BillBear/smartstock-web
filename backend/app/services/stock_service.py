"""
股票数据服务
使用AkShare获取股票实时行情和历史数据
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class StockDataService:
    """股票数据服务类"""

    @staticmethod
    def get_realtime_quote(symbol: str) -> Dict[str, Any]:
        """
        获取股票实时行情

        Args:
            symbol: 股票代码，如 000001

        Returns:
            实时行情数据字典
        """
        try:
            # 方法1: 使用spot接口（更稳定）
            try:
                df = ak.stock_zh_a_spot_em()
                stock_data = df[df['代码'] == symbol]

                if not stock_data.empty:
                    row = stock_data.iloc[0]
                    return {
                        "symbol": symbol,
                        "name": row['名称'],
                        "current_price": float(row['最新价']),
                        "change_percent": float(row['涨跌幅']),
                        "change_amount": float(row['涨跌额']),
                        "open_price": float(row['今开']),
                        "high_price": float(row['最高']),
                        "low_price": float(row['最低']),
                        "prev_close": float(row['昨收']),
                        "volume": float(row['成交量']),
                        "turnover": float(row['成交额']),
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
            except Exception as e1:
                logger.warning(f"方法1失败: {str(e1)}, 尝试方法2")

                # 方法2: 使用历史数据的最新一条作为实时数据
                try:
                    df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
                    if df.empty:
                        raise ValueError(f"未找到股票代码: {symbol}")

                    # 获取最新一条数据
                    latest = df.iloc[-1]

                    # 获取股票名称
                    name = StockDataService.get_stock_name(symbol)

                    return {
                        "symbol": symbol,
                        "name": name,
                        "current_price": float(latest['收盘']),
                        "change_percent": float(latest['涨跌幅']),
                        "change_amount": float(latest['涨跌额']),
                        "open_price": float(latest['开盘']),
                        "high_price": float(latest['最高']),
                        "low_price": float(latest['最低']),
                        "prev_close": float(latest['收盘']) - float(latest['涨跌额']),
                        "volume": float(latest['成交量']),
                        "turnover": float(latest['成交额']),
                        "timestamp": str(latest['日期'])
                    }
                except Exception as e2:
                    logger.error(f"方法2也失败: {str(e2)}")
                    raise ValueError(f"无法获取股票 {symbol} 的数据，请检查股票代码是否正确")

        except Exception as e:
            logger.error(f"获取实时行情失败: {symbol}, 错误: {str(e)}")
            raise Exception(f"获取实时行情失败: {str(e)}")

    @staticmethod
    def get_stock_name(symbol: str) -> str:
        """
        获取股票名称

        Args:
            symbol: 股票代码

        Returns:
            股票名称
        """
        try:
            df = ak.stock_zh_a_spot_em()
            stock_data = df[df['代码'] == symbol]

            if stock_data.empty:
                return symbol

            return stock_data.iloc[0]['名称']
        except Exception as e:
            logger.error(f"获取股票名称失败: {symbol}, 错误: {str(e)}")
            return symbol

    @staticmethod
    def get_history_data(
        symbol: str,
        period: str = "daily",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq"
    ) -> pd.DataFrame:
        """
        获取股票历史K线数据

        Args:
            symbol: 股票代码
            period: 周期 daily/weekly/monthly
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            adjust: 复权类型 qfq前复权/hfq后复权/空不复权

        Returns:
            历史K线数据DataFrame
        """
        try:
            # 设置默认日期
            if not end_date:
                end_date = datetime.now().strftime("%Y%m%d")
            else:
                end_date = end_date.replace("-", "")

            if not start_date:
                start_date = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
            else:
                start_date = start_date.replace("-", "")

            # 获取历史数据
            if period == "daily":
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
            elif period == "weekly":
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="weekly",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
            elif period == "monthly":
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="monthly",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
            else:
                raise ValueError(f"不支持的周期类型: {period}")

            if df.empty:
                raise ValueError(f"未获取到历史数据: {symbol}")

            # 标准化列名
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'turnover',
                '振幅': 'amplitude',
                '涨跌幅': 'change_percent',
                '涨跌额': 'change_amount',
                '换手率': 'turnover_rate'
            })

            # 确保数据类型正确
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            df['open'] = df['open'].astype(float)
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['volume'] = df['volume'].astype(float)

            # 按日期排序
            df = df.sort_values('date').reset_index(drop=True)

            return df

        except Exception as e:
            logger.error(f"获取历史数据失败: {symbol}, 错误: {str(e)}")
            raise Exception(f"获取历史数据失败: {str(e)}")

    @staticmethod
    def get_stock_info(symbol: str) -> Dict[str, Any]:
        """
        获取股票基本信息

        Args:
            symbol: 股票代码

        Returns:
            股票基本信息
        """
        try:
            # 获取股票基本信息
            df = ak.stock_individual_info_em(symbol=symbol)

            info = {}
            for _, row in df.iterrows():
                info[row['item']] = row['value']

            return info
        except Exception as e:
            logger.error(f"获取股票信息失败: {symbol}, 错误: {str(e)}")
            return {}
