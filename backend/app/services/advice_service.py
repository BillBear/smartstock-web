"""
投资建议服务
根据技术分析和用户偏好生成个性化投资建议
"""
from typing import Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class AdviceService:
    """投资建议服务"""

    @staticmethod
    def generate_advice(
        symbol: str,
        name: str,
        price: float,  # 修改：改为price
        signal_analysis: Dict[str, Any],
        holding_period: str,
        risk_level: str,
        target_return: float
    ) -> Dict[str, Any]:
        """
        生成投资建议

        Args:
            symbol: 股票代码
            name: 股票名称
            price: 当前价格
            signal_analysis: 信号分析结果
            holding_period: 持有周期 short/medium/long
            risk_level: 风险等级 low/medium/high
            target_return: 目标收益率(%)

        Returns:
            投资建议字典
        """
        score = signal_analysis.get('score', 0)
        overall_signal = signal_analysis.get('overall_signal', '观望')

        # 根据持有周期调整建议
        period_multiplier = {
            'short': 0.8,   # 短期更保守
            'medium': 1.0,  # 中期标准
            'long': 1.2     # 长期更激进
        }.get(holding_period, 1.0)

        # 根据风险等级调整建议
        risk_multiplier = {
            'low': 0.7,     # 低风险更保守
            'medium': 1.0,  # 中等风险标准
            'high': 1.3     # 高风险更激进
        }.get(risk_level, 1.0)

        # 调整后的评分
        adjusted_score = score * period_multiplier * risk_multiplier

        # 生成具体建议
        advice = {}

        # 1. 建仓建议
        if adjusted_score > 30:
            advice['entry'] = {
                'action': '建议建仓',
                'position_size': '可考虑30-50%仓位',
                'entry_price': f'{price:.2f}附近',
                'strategy': '可分批建仓，降低成本'
            }
        elif adjusted_score > 10:
            advice['entry'] = {
                'action': '谨慎建仓',
                'position_size': '建议20-30%仓位',
                'entry_price': f'回调至{price * 0.97:.2f}附近',
                'strategy': '等待更好的买点'
            }
        else:
            advice['entry'] = {
                'action': '暂不建议建仓',
                'position_size': '观望为主',
                'entry_price': '等待信号改善',
                'strategy': '关注技术指标变化'
            }

        # 2. 止盈建议
        if holding_period == 'short':
            take_profit_ratio = min(target_return * 0.6, 8)  # 短期止盈6-8%
        elif holding_period == 'medium':
            take_profit_ratio = min(target_return * 0.8, 15)  # 中期止盈10-15%
        else:
            take_profit_ratio = min(target_return, 25)  # 长期止盈15-25%

        advice['take_profit'] = {
            'target_return': f'{take_profit_ratio:.1f}%',
            'target_price': f'{price * (1 + take_profit_ratio / 100):.2f}',
            'strategy': '分批止盈，保留底仓' if holding_period == 'long' else '达到目标及时止盈'
        }

        # 3. 止损建议
        if risk_level == 'low':
            stop_loss_ratio = 5  # 低风险止损5%
        elif risk_level == 'medium':
            stop_loss_ratio = 8  # 中等风险止损8%
        else:
            stop_loss_ratio = 10  # 高风险止损10%

        advice['stop_loss'] = {
            'stop_loss_ratio': f'{stop_loss_ratio}%',
            'stop_loss_price': f'{price * (1 - stop_loss_ratio / 100):.2f}',
            'strategy': '严格执行止损纪律，避免深套'
        }

        # 4. 加仓建议
        if adjusted_score > 40:
            advice['add_position'] = {
                'condition': '突破关键阻力位后可适当加仓',
                'size': '10-20%仓位',
                'strategy': '强势上涨时追加'
            }
        elif adjusted_score > 20:
            advice['add_position'] = {
                'condition': '回调不破支撑位可考虑加仓',
                'size': '10-15%仓位',
                'strategy': '逢低加仓'
            }
        else:
            advice['add_position'] = {
                'condition': '暂不建议加仓',
                'size': '观望',
                'strategy': '等待趋势明朗'
            }

        # 5. 风险提示
        risk_warnings = [
            '⚠️ 股市有风险，投资需谨慎',
            '⚠️ 本建议仅供参考，不构成投资决策依据',
        ]

        if adjusted_score < 0:
            risk_warnings.append('⚠️ 当前技术面偏空，建议谨慎操作')

        if holding_period == 'short':
            risk_warnings.append('⚠️ 短期交易风险较高，注意控制仓位')

        if risk_level == 'high':
            risk_warnings.append('⚠️ 您的风险承受能力较高，但仍需做好风险管理')

        # 添加市场风险提示
        risk_warnings.extend([
            '⚠️ 注意大盘走势和市场情绪变化',
            '⚠️ 关注个股基本面变化和重大消息',
            '⚠️ 严格执行止损止盈策略'
        ])

        return {
            'symbol': symbol,
            'name': name,
            'price': price,
            'signal_analysis': signal_analysis,
            'advice': advice,
            'risk_warning': risk_warnings,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def get_holding_period_description(period: str) -> str:
        """获取持有周期描述"""
        descriptions = {
            'short': '短期（1-7天）',
            'medium': '中期（1-3个月）',
            'long': '长期（3个月以上）'
        }
        return descriptions.get(period, '未知')

    @staticmethod
    def get_risk_level_description(level: str) -> str:
        """获取风险等级描述"""
        descriptions = {
            'low': '低风险（保守型）',
            'medium': '中等风险（稳健型）',
            'high': '高风险（激进型）'
        }
        return descriptions.get(level, '未知')
