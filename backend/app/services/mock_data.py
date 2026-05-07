"""
Mock数据服务 - 用于开发测试
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class MockDataService:
    """Mock数据服务"""

    @staticmethod
    def get_mock_history_data(symbol: str, days: int = 120):
        """生成模拟历史K线数据"""
        end_date = datetime.now()
        dates = [(end_date - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]
        dates.reverse()

        # 生成基础价格数据（随机游走）
        base_price = 11.0
        prices = [base_price]
        for _ in range(days - 1):
            change = np.random.normal(0, 0.02)
            new_price = prices[-1] * (1 + change)
            prices.append(max(new_price, 5.0))  # 最低价5元

        data = []
        for i, date in enumerate(dates):
            close = prices[i]
            open_price = close * (1 + np.random.uniform(-0.01, 0.01))
            high = max(open_price, close) * (1 + np.random.uniform(0, 0.02))
            low = min(open_price, close) * (1 - np.random.uniform(0, 0.02))
            volume = np.random.randint(100000, 500000)

            data.append({
                'date': date,
                'open': round(open_price, 2),
                'close': round(close, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'volume': volume,
                'amount': round(volume * close / 100, 2)
            })

        return pd.DataFrame(data)

    @staticmethod
    def get_mock_realtime_quote(symbol: str):
        """生成模拟实时行情"""
        stock_names = {
            '000001': '平安银行',
            '600519': '贵州茅台',
            '002594': '比亚迪'
        }

        base_prices = {
            '000001': 11.05,
            '600519': 1427.00,
            '002594': 245.80
        }

        name = stock_names.get(symbol, f'股票{symbol}')
        current_price = base_prices.get(symbol, 50.0)
        change_percent = round(np.random.uniform(-3, 3), 2)

        return {
            'symbol': symbol,
            'name': name,
            'current_price': current_price,
            'change_percent': change_percent,
            'change_amount': round(current_price * change_percent / 100, 2),
            'open': round(current_price * (1 - change_percent / 200), 2),
            'high': round(current_price * 1.02, 2),
            'low': round(current_price * 0.98, 2),
            'volume': np.random.randint(1000000, 10000000),
            'amount': round(current_price * np.random.randint(1000000, 10000000) / 100, 2),
            'turnover': round(np.random.uniform(1, 5), 2),
            'pe': round(np.random.uniform(10, 30), 2),
            'pb': round(np.random.uniform(1, 5), 2),
            'market_cap': round(current_price * 1000000000 / 100000000, 2),
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def get_mock_money_flow(symbol: str, days: int = 5):
        """生成模拟资金流向数据"""
        dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]
        dates.reverse()

        data = {
            'symbol': symbol,
            'main_flow_summary': {
                'total_main_flow': round(np.random.uniform(-500, 500), 2),
                'super_large_flow': round(np.random.uniform(-200, 200), 2),
                'large_flow': round(np.random.uniform(-200, 200), 2),
                'medium_flow': round(np.random.uniform(-100, 100), 2),
                'small_flow': round(np.random.uniform(-100, 100), 2)
            },
            'daily_flows': [
                {
                    'date': date,
                    'main_flow': round(np.random.uniform(-100, 100), 2),
                    'super_large': round(np.random.uniform(-50, 50), 2),
                    'large': round(np.random.uniform(-50, 50), 2),
                    'medium': round(np.random.uniform(-30, 30), 2),
                    'small': round(np.random.uniform(-30, 30), 2)
                }
                for date in dates
            ]
        }

        return data
