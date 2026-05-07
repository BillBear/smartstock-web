"""
多因子评分引擎
实现专业的量化选股评分系统
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class FactorEngine:
    """多因子评分引擎"""

    # 因子权重配置
    WEIGHTS = {
        'technical': 0.35,      # 技术面 35%
        'money_flow': 0.30,     # 资金面 30%
        'fundamental': 0.25,    # 基本面 25%
        'valuation': 0.10       # 估值 10%
    }

    @staticmethod
    def calculate_comprehensive_score(
        technical_score: float,
        money_flow_score: float,
        fundamental_score: float,
        valuation_score: float
    ) -> float:
        """
        计算综合评分

        Args:
            technical_score: 技术面得分 (0-100)
            money_flow_score: 资金面得分 (0-100)
            fundamental_score: 基本面得分 (0-100)
            valuation_score: 估值得分 (0-100)

        Returns:
            综合得分 (0-100)
        """
        total_score = (
            technical_score * FactorEngine.WEIGHTS['technical'] +
            money_flow_score * FactorEngine.WEIGHTS['money_flow'] +
            fundamental_score * FactorEngine.WEIGHTS['fundamental'] +
            valuation_score * FactorEngine.WEIGHTS['valuation']
        )

        return round(total_score, 2)

    @staticmethod
    def calculate_technical_score(indicators: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算技术面评分

        评分维度：
        1. 趋势强度 (40%)
        2. 指标共振度 (35%)
        3. 形态评分 (25%)
        """
        score = 0
        signals = []

        # 1. 趋势强度评分 (40分)
        trend_score = 0

        # MACD
        macd = indicators.get('macd', 0) or 0
        macd_signal = indicators.get('macd_signal', 0) or 0
        macd_hist = indicators.get('macd_hist', 0) or 0

        if macd_hist > 0:
            if macd > macd_signal:
                trend_score += 15
                signals.append('✓ MACD金叉，多头信号')
            else:
                trend_score += 8
                signals.append('○ MACD柱状图转正')
        else:
            if macd < macd_signal:
                signals.append('✗ MACD死叉，空头信号')
            else:
                trend_score += 3

        # 均线排列
        close = indicators.get('close', 0) or 0
        ma5 = indicators.get('ma5', 0) or 0
        ma10 = indicators.get('ma10', 0) or 0
        ma20 = indicators.get('ma20', 0) or 0

        if ma5 and ma10 and ma20:
            if close > ma5 > ma10 > ma20:
                trend_score += 25
                signals.append('✓ 均线多头排列，趋势强劲')
            elif close < ma5 < ma10 < ma20:
                signals.append('✗ 均线空头排列')
            else:
                trend_score += 10

        # 2. 指标共振度 (35分)
        resonance_score = 0

        # RSI
        rsi = indicators.get('rsi', 50) or 50
        if 40 <= rsi <= 60:
            resonance_score += 15
            signals.append('○ RSI处于正常区间')
        elif rsi < 30:
            resonance_score += 20
            signals.append('✓ RSI超卖，可能反弹')
        elif rsi > 70:
            resonance_score += 5
            signals.append('⚠ RSI超买，注意回调')
        else:
            resonance_score += 10

        # KDJ
        k = indicators.get('k', 50) or 50
        d = indicators.get('d', 50) or 50

        if k > d and k > 50:
            resonance_score += 20
            signals.append('✓ KDJ金叉，短期看多')
        elif k < d and k < 50:
            signals.append('✗ KDJ死叉，短期看空')
        else:
            resonance_score += 10

        # 3. 形态评分 (25分)
        pattern_score = 0

        # 布林带位置
        boll_upper = indicators.get('boll_upper', 0) or 0
        boll_lower = indicators.get('boll_lower', 0) or 0

        if boll_upper and boll_lower:
            if close < boll_lower:
                pattern_score += 25
                signals.append('✓ 突破布林带下轨，超跌反弹机会')
            elif close > boll_upper:
                pattern_score += 10
                signals.append('⚠ 突破布林带上轨，强势但需警惕')
            else:
                pattern_score += 15

        # 汇总
        total_score = trend_score + resonance_score + pattern_score

        return {
            'score': min(total_score, 100),
            'trend': '上升' if total_score > 60 else '下降',
            'signals': signals
        }

    @staticmethod
    def calculate_money_flow_score(money_flow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算资金面评分

        评分维度：
        1. 主力流入强度 (50%)
        2. 资金持续性 (30%)
        3. 大单占比 (20%)
        """
        score = 0
        signals = []

        main_net_inflow = money_flow_data.get('main_net_inflow', 0)
        control_ratio = money_flow_data.get('control_ratio', 0)

        # 1. 主力流入强度 (50分)
        if main_net_inflow > 0:
            if control_ratio > 10:
                score += 50
                signals.append('✓ 主力大幅净流入，控盘强度高')
            elif control_ratio > 5:
                score += 35
                signals.append('✓ 主力净流入，资金面向好')
            else:
                score += 20
                signals.append('○ 主力小幅流入')
        else:
            if control_ratio > 10:
                signals.append('✗ 主力大幅流出，需警惕')
            elif control_ratio > 5:
                score += 10
                signals.append('⚠ 主力净流出，资金面承压')
            else:
                score += 15
                signals.append('○ 主力小幅流出')

        # 2. 资金持续性 (30分)
        trend = money_flow_data.get('trend', '')
        strength = money_flow_data.get('strength', '')

        if '流入' in trend:
            if strength == '强':
                score += 30
                signals.append('✓ 资金持续强势流入')
            else:
                score += 20
                signals.append('○ 资金流入趋势')
        else:
            if strength == '强':
                signals.append('✗ 资金持续流出')
            else:
                score += 10

        # 3. 大单占比 (20分)
        if control_ratio > 15:
            score += 20
            signals.append('✓ 大单占比极高，主力高度关注')
        elif control_ratio > 10:
            score += 15
        elif control_ratio > 5:
            score += 10
        else:
            score += 5

        return {
            'score': min(score, 100),
            'signals': signals
        }

    @staticmethod
    def calculate_fundamental_score(fundamental_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算基本面评分

        评分维度：
        1. 盈利能力 (40%) - ROE, 净利率
        2. 成长性 (35%) - 营收增长, 利润增长
        3. 经营质量 (25%) - 现金流, 负债率
        """
        score = 0
        signals = []

        # 1. 盈利能力 (40分)
        roe = fundamental_data.get('roe', 0)
        if roe:
            if roe > 20:
                score += 40
                signals.append(f'✓ ROE={roe}%，盈利能力优秀')
            elif roe > 15:
                score += 30
                signals.append(f'○ ROE={roe}%，盈利能力良好')
            elif roe > 10:
                score += 20
                signals.append(f'○ ROE={roe}%，盈利能力一般')
            else:
                score += 10
                signals.append(f'⚠ ROE={roe}%，盈利能力较弱')

        # 2. 成长性 (35分)
        revenue_growth = fundamental_data.get('revenue_growth', 0)
        profit_growth = fundamental_data.get('net_profit_growth', 0)

        if revenue_growth > 20:
            score += 20
            signals.append(f'✓ 营收增长{revenue_growth}%，成长性优秀')
        elif revenue_growth > 10:
            score += 15
            signals.append(f'○ 营收增长{revenue_growth}%')
        elif revenue_growth > 0:
            score += 10
        else:
            signals.append(f'⚠ 营收增长{revenue_growth}%，需关注')

        if profit_growth > 20:
            score += 15
            signals.append(f'✓ 净利润增长{profit_growth}%')
        elif profit_growth > 10:
            score += 10
        elif profit_growth > 0:
            score += 5

        # 3. 经营质量 (25分)
        # 简化处理，基于ROE和增长率综合判断
        if roe > 15 and revenue_growth > 10:
            score += 25
            signals.append('✓ 经营质量优秀')
        elif roe > 10 and revenue_growth > 5:
            score += 15
            signals.append('○ 经营质量良好')
        else:
            score += 10

        return {
            'score': min(score, 100),
            'signals': signals
        }

    @staticmethod
    def calculate_valuation_score(valuation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算估值评分

        评分维度：
        1. PE水平 (50%)
        2. PB水平 (30%)
        3. 行业对比 (20%)
        """
        score = 0
        signals = []

        pe = valuation_data.get('pe', 0)
        pb = valuation_data.get('pb', 0)

        # 1. PE评分 (50分)
        # 简化：PE越低估值越好，但考虑行业差异
        if pe:
            if pe < 15:
                score += 50
                signals.append(f'✓ PE={pe}倍，估值偏低')
            elif pe < 25:
                score += 35
                signals.append(f'○ PE={pe}倍，估值合理')
            elif pe < 40:
                score += 20
                signals.append(f'⚠ PE={pe}倍，估值偏高')
            else:
                score += 10
                signals.append(f'⚠ PE={pe}倍，估值较高')

        # 2. PB评分 (30分)
        if pb:
            if pb < 2:
                score += 30
                signals.append(f'✓ PB={pb}倍，账面价值低估')
            elif pb < 4:
                score += 20
                signals.append(f'○ PB={pb}倍')
            elif pb < 6:
                score += 10
            else:
                score += 5

        # 3. 行业对比 (20分)
        # 简化处理
        score += 15

        return {
            'score': min(score, 100),
            'signals': signals
        }

    @staticmethod
    def generate_stock_rating(
        symbol: str,
        name: str,
        technical_result: Dict[str, Any],
        money_flow_result: Dict[str, Any],
        fundamental_result: Dict[str, Any],
        valuation_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成股票综合评级

        Returns:
            完整的评分报告
        """
        # 计算综合评分
        total_score = FactorEngine.calculate_comprehensive_score(
            technical_result['score'],
            money_flow_result['score'],
            fundamental_result['score'],
            valuation_result['score']
        )

        # 评级
        if total_score >= 85:
            rating = '优秀'
            recommendation = '强烈关注'
        elif total_score >= 75:
            rating = '良好'
            recommendation = '值得关注'
        elif total_score >= 65:
            rating = '中等'
            recommendation = '谨慎观察'
        elif total_score >= 55:
            rating = '一般'
            recommendation = '暂时观望'
        else:
            rating = '较弱'
            recommendation = '不建议'

        return {
            'symbol': symbol,
            'name': name,
            'total_score': total_score,
            'rating': rating,
            'recommendation': recommendation,
            'scores': {
                'technical': technical_result['score'],
                'money_flow': money_flow_result['score'],
                'fundamental': fundamental_result['score'],
                'valuation': valuation_result['score']
            },
            'analysis': {
                'technical': technical_result,
                'money_flow': money_flow_result,
                'fundamental': fundamental_result,
                'valuation': valuation_result
            },
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
