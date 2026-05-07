"""
基本面数据服务
获取和分析股票基本面数据
"""
import akshare as ak
import pandas as pd
from typing import Dict, Any, Optional
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)


class FundamentalService:
    """基本面数据服务"""

    @staticmethod
    def _empty_fundamental(symbol: str, reason: str = "暂无可靠财务摘要数据") -> Dict[str, Any]:
        return {
            'symbol': symbol,
            'pe': None,
            'pb': None,
            'roe': None,
            'revenue_growth': None,
            'net_profit_growth': None,
            'gross_margin': None,
            'debt_ratio': None,
            'net_profit_yi': None,
            'revenue_yi': None,
            'report_date': None,
            'source': None,
            'is_available': False,
            'is_estimated': False,
            'reason': reason,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        if not text or text in {"-", "--", "nan", "None"}:
            return None
        multiplier = 1.0
        if text.endswith("%"):
            text = text[:-1]
        if text.endswith("亿"):
            multiplier = 1.0
            text = text[:-1]
        elif text.endswith("万"):
            multiplier = 0.0001
            text = text[:-1]
        text = text.replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            return round(float(match.group(0)) * multiplier, 4)
        except Exception:
            return None

    @staticmethod
    def _get_ths_fundamental(symbol: str) -> Dict[str, Any]:
        df = ak.stock_financial_abstract_ths(symbol=symbol)
        if df is None or df.empty:
            return FundamentalService._empty_fundamental(symbol)

        latest = df.sort_values("报告期").iloc[-1]
        return {
            'symbol': symbol,
            'pe': None,
            'pb': None,
            'roe': FundamentalService._to_float(latest.get('净资产收益率')),
            'revenue_growth': FundamentalService._to_float(latest.get('营业总收入同比增长率')),
            'net_profit_growth': FundamentalService._to_float(latest.get('净利润同比增长率')),
            'gross_margin': FundamentalService._to_float(latest.get('销售毛利率')),
            'debt_ratio': FundamentalService._to_float(latest.get('资产负债率')),
            'net_profit_yi': FundamentalService._to_float(latest.get('净利润')),
            'revenue_yi': FundamentalService._to_float(latest.get('营业总收入')),
            'report_date': str(latest.get('报告期') or ''),
            'source': 'akshare_ths_financial_abstract',
            'is_available': True,
            'is_estimated': False,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def get_fundamental_data(symbol: str) -> Dict[str, Any]:
        """
        获取股票基本面数据

        Args:
            symbol: 股票代码

        Returns:
            基本面数据字典
        """
        try:
            data = FundamentalService._get_ths_fundamental(symbol)
            if data.get("is_available"):
                return data
            return data
        except Exception as e:
            logger.warning(f"获取基本面数据失败: {symbol}, 错误: {str(e)}")
            return FundamentalService._empty_fundamental(symbol, reason=str(e))

    @staticmethod
    def _get_estimated_fundamental(symbol: str) -> Dict[str, Any]:
        """
        获取估算的基本面数据（备用方案）

        基于行业平均值和简单估算
        """
        # 简化处理：使用合理的默认值
        # 实际生产环境应该接入专业的财务数据API

        # 根据股票代码首位判断板块
        first_digit = symbol[0]

        if first_digit == '6':  # 上海主板，通常是大盘股
            default_pe = 15.0
            default_pb = 1.8
            default_roe = 12.0
            default_growth = 8.0
        elif first_digit == '0':  # 深圳主板
            default_pe = 18.0
            default_pb = 2.2
            default_roe = 14.0
            default_growth = 12.0
        elif first_digit == '3':  # 创业板
            default_pe = 35.0
            default_pb = 4.5
            default_roe = 16.0
            default_growth = 25.0
        else:
            default_pe = 20.0
            default_pb = 2.5
            default_roe = 13.0
            default_growth = 10.0

        return {
            'symbol': symbol,
            'pe': default_pe,
            'pb': default_pb,
            'roe': default_roe,
            'revenue_growth': default_growth,
            'net_profit_growth': default_growth * 1.2,  # 利润增长通常高于营收
            'gross_margin': 30.0,
            'debt_ratio': 45.0,
            'is_estimated': True,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def analyze_fundamental(fundamental_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析基本面数据

        Returns:
            分析结果
        """
        analysis = {
            'strengths': [],
            'weaknesses': [],
            'summary': ''
        }

        pe = fundamental_data.get('pe', 0)
        pb = fundamental_data.get('pb', 0)
        roe = fundamental_data.get('roe', 0)
        revenue_growth = fundamental_data.get('revenue_growth', 0)
        net_profit_growth = fundamental_data.get('net_profit_growth', 0)

        # 优势分析
        if roe and roe > 15:
            analysis['strengths'].append(f'ROE={roe}%，盈利能力强')

        if revenue_growth and revenue_growth > 15:
            analysis['strengths'].append(f'营收增长{revenue_growth}%，成长性好')

        if net_profit_growth and net_profit_growth > 20:
            analysis['strengths'].append(f'净利润增长{net_profit_growth}%，盈利加速')

        if pe and pe < 20:
            analysis['strengths'].append(f'PE={pe}倍，估值合理')

        # 劣势分析
        if roe and roe < 10:
            analysis['weaknesses'].append(f'ROE={roe}%，盈利能力偏弱')

        if revenue_growth and revenue_growth < 5:
            analysis['weaknesses'].append('营收增长缓慢')

        if pe and pe > 40:
            analysis['weaknesses'].append(f'PE={pe}倍，估值偏高')

        # 综合评价
        if len(analysis['strengths']) > len(analysis['weaknesses']):
            analysis['summary'] = '基本面整体向好，具备投资价值'
        elif len(analysis['strengths']) == len(analysis['weaknesses']):
            analysis['summary'] = '基本面中性，需结合技术面综合判断'
        else:
            analysis['summary'] = '基本面存在一定压力，建议谨慎'

        return analysis
