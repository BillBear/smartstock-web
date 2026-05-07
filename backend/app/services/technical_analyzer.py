"""
技术指标分析服务
计算MACD、RSI、KDJ、均线、布林带等技术指标
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """技术指标分析器"""

    @staticmethod
    def calculate_ma(df: pd.DataFrame, periods: List[int] = [5, 10, 20, 60]) -> pd.DataFrame:
        """
        计算移动平均线

        Args:
            df: 包含close列的DataFrame
            periods: MA周期列表

        Returns:
            添加了MA列的DataFrame
        """
        for period in periods:
            df[f'ma{period}'] = df['close'].rolling(window=period).mean()
        return df

    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
        """
        计算MACD指标

        Args:
            df: 包含close列的DataFrame
            fast: 快线周期
            slow: 慢线周期
            signal: 信号线周期

        Returns:
            添加了MACD列的DataFrame
        """
        # 计算EMA
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()

        # MACD线
        df['macd'] = ema_fast - ema_slow

        # 信号线
        df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()

        # MACD柱状图
        df['macd_hist'] = df['macd'] - df['macd_signal']

        return df

    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
        """
        计算RSI指标

        Args:
            df: 包含close列的DataFrame
            period: RSI周期

        Returns:
            添加了RSI列的DataFrame
        """
        # 计算价格变化
        delta = df['close'].diff()

        # 分离上涨和下跌
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        # 计算RS和RSI
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        return df

    @staticmethod
    def calculate_kdj(df: pd.DataFrame, n=9, m1=3, m2=3) -> pd.DataFrame:
        """
        计算KDJ指标

        Args:
            df: 包含high、low、close列的DataFrame
            n: RSV周期
            m1: K值平滑周期
            m2: D值平滑周期

        Returns:
            添加了KDJ列的DataFrame
        """
        # 计算RSV
        low_min = df['low'].rolling(window=n).min()
        high_max = df['high'].rolling(window=n).max()
        rsv = (df['close'] - low_min) / (high_max - low_min) * 100

        # 计算K值
        df['k'] = rsv.ewm(com=m1-1, adjust=False).mean()

        # 计算D值
        df['d'] = df['k'].ewm(com=m2-1, adjust=False).mean()

        # 计算J值
        df['j'] = 3 * df['k'] - 2 * df['d']

        return df

    @staticmethod
    def calculate_boll(df: pd.DataFrame, period=20, std=2) -> pd.DataFrame:
        """
        计算布林带

        Args:
            df: 包含close列的DataFrame
            period: 周期
            std: 标准差倍数

        Returns:
            添加了BOLL列的DataFrame
        """
        # 中轨
        df['boll_middle'] = df['close'].rolling(window=period).mean()

        # 标准差
        rolling_std = df['close'].rolling(window=period).std()

        # 上轨和下轨
        df['boll_upper'] = df['boll_middle'] + (rolling_std * std)
        df['boll_lower'] = df['boll_middle'] - (rolling_std * std)

        return df

    @staticmethod
    def analyze_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算所有技术指标

        Args:
            df: 原始OHLCV数据

        Returns:
            包含所有技术指标的DataFrame
        """
        if df.empty or len(df) < 60:
            logger.warning("数据不足，无法计算技术指标")
            return df

        try:
            # 计算各项指标
            df = TechnicalAnalyzer.calculate_ma(df)
            df = TechnicalAnalyzer.calculate_macd(df)
            df = TechnicalAnalyzer.calculate_rsi(df)
            df = TechnicalAnalyzer.calculate_kdj(df)
            df = TechnicalAnalyzer.calculate_boll(df)

            return df
        except Exception as e:
            logger.error(f"计算技术指标失败: {str(e)}")
            return df

    @staticmethod
    def get_latest_indicators(df: pd.DataFrame) -> Dict[str, Any]:
        """
        获取最新的技术指标数值

        Args:
            df: 包含技术指标的DataFrame

        Returns:
            最新指标值字典
        """
        if df.empty:
            return {"error": "无数据"}

        latest = df.iloc[-1]

        return {
            "date": str(latest['date']),
            "close": float(latest['close']),
            "ma5": float(latest.get('ma5', 0)) if pd.notna(latest.get('ma5', 0)) else None,
            "ma10": float(latest.get('ma10', 0)) if pd.notna(latest.get('ma10', 0)) else None,
            "ma20": float(latest.get('ma20', 0)) if pd.notna(latest.get('ma20', 0)) else None,
            "ma60": float(latest.get('ma60', 0)) if pd.notna(latest.get('ma60', 0)) else None,
            "macd": float(latest.get('macd', 0)) if pd.notna(latest.get('macd', 0)) else None,
            "macd_signal": float(latest.get('macd_signal', 0)) if pd.notna(latest.get('macd_signal', 0)) else None,
            "macd_hist": float(latest.get('macd_hist', 0)) if pd.notna(latest.get('macd_hist', 0)) else None,
            "rsi": float(latest.get('rsi', 0)) if pd.notna(latest.get('rsi', 0)) else None,
            "k": float(latest.get('k', 0)) if pd.notna(latest.get('k', 0)) else None,
            "d": float(latest.get('d', 0)) if pd.notna(latest.get('d', 0)) else None,
            "j": float(latest.get('j', 0)) if pd.notna(latest.get('j', 0)) else None,
            "boll_upper": float(latest.get('boll_upper', 0)) if pd.notna(latest.get('boll_upper', 0)) else None,
            "boll_middle": float(latest.get('boll_middle', 0)) if pd.notna(latest.get('boll_middle', 0)) else None,
            "boll_lower": float(latest.get('boll_lower', 0)) if pd.notna(latest.get('boll_lower', 0)) else None,
        }

    @staticmethod
    def generate_signals(indicators: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据技术指标生成交易信号

        Args:
            indicators: 技术指标字典

        Returns:
            交易信号和分析
        """
        signals = []
        score = 0  # 综合评分 -100 到 100

        # MACD分析
        macd = indicators.get('macd', 0) or 0
        macd_signal = indicators.get('macd_signal', 0) or 0
        macd_hist = indicators.get('macd_hist', 0) or 0

        if macd_hist > 0:
            if macd > macd_signal:
                signals.append("✓ MACD金叉，多头信号")
                score += 20
            else:
                signals.append("✓ MACD柱状图转正，趋势可能转多")
                score += 10
        else:
            if macd < macd_signal:
                signals.append("✗ MACD死叉，空头信号")
                score -= 20
            else:
                signals.append("✗ MACD柱状图为负，趋势偏空")
                score -= 10

        # RSI分析
        rsi = indicators.get('rsi', 50) or 50
        if rsi > 70:
            signals.append(f"⚠ RSI={rsi:.2f}，超买区域，注意回调风险")
            score -= 15
        elif rsi < 30:
            signals.append(f"✓ RSI={rsi:.2f}，超卖区域，可能反弹")
            score += 15
        else:
            signals.append(f"○ RSI={rsi:.2f}，处于正常区间")

        # KDJ分析
        k = indicators.get('k', 50) or 50
        d = indicators.get('d', 50) or 50
        j = indicators.get('j', 50) or 50

        if k > d and k > 50:
            signals.append(f"✓ KDJ金叉(K={k:.2f}, D={d:.2f})，短期看多")
            score += 15
        elif k < d and k < 50:
            signals.append(f"✗ KDJ死叉(K={k:.2f}, D={d:.2f})，短期看空")
            score -= 15

        if j > 100:
            signals.append(f"⚠ J值={j:.2f}超买，注意风险")
            score -= 10
        elif j < 0:
            signals.append(f"✓ J值={j:.2f}超卖，可能反弹")
            score += 10

        # 均线分析
        close = indicators.get('close', 0) or 0
        ma5 = indicators.get('ma5', 0) or 0
        ma10 = indicators.get('ma10', 0) or 0
        ma20 = indicators.get('ma20', 0) or 0
        ma60 = indicators.get('ma60', 0) or 0

        if ma5 and ma10 and ma20 and ma60:
            if close > ma5 > ma10 > ma20:
                signals.append("✓ 均线多头排列，趋势向上")
                score += 20
            elif close < ma5 < ma10 < ma20:
                signals.append("✗ 均线空头排列，趋势向下")
                score -= 20

        # 布林带分析
        boll_upper = indicators.get('boll_upper', 0) or 0
        boll_lower = indicators.get('boll_lower', 0) or 0
        boll_middle = indicators.get('boll_middle', 0) or 0

        if boll_upper and boll_lower:
            if close > boll_upper:
                signals.append("⚠ 价格突破布林带上轨，强势但需警惕回调")
                score += 5
            elif close < boll_lower:
                signals.append("✓ 价格跌破布林带下轨，超跌可能反弹")
                score += 10

        # 综合判断
        if score > 40:
            overall = "强烈买入"
        elif score > 20:
            overall = "买入"
        elif score > 0:
            overall = "谨慎买入"
        elif score > -20:
            overall = "观望"
        elif score > -40:
            overall = "谨慎卖出"
        else:
            overall = "卖出"

        return {
            "overall_signal": overall,
            "score": score,
            "signals": signals,
            "trend": "上升" if score > 0 else "下降",
        }
