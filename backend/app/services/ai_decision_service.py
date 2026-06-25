"""
AI决策引擎服务
综合技术分析、资金流向、市场情绪等多维度数据，提供智能投资决策
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
import numpy as np

logger = logging.getLogger(__name__)


class AIDecisionEngine:
    """AI决策引擎"""

    @staticmethod
    def make_decision(
        symbol: str,
        name: str,
        price: float,
        technical_signals: Dict[str, Any],
        money_flow_data: Dict[str, Any],
        user_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        综合决策分析

        Args:
            symbol: 股票代码
            name: 股票名称
            price: 当前价格
            technical_signals: 技术分析信号
            money_flow_data: 资金流向数据
            user_profile: 用户画像（风险偏好、持有期等）

        Returns:
            AI决策结果
        """
        try:
            # 1. 获取各维度评分
            tech_score = technical_signals.get('score', 0)
            money_score = AIDecisionEngine._calculate_money_flow_score(money_flow_data)

            # 2. 计算综合评分（技术面60%，资金面40%）
            total_score = tech_score * 0.6 + money_score * 0.4

            # 3. 根据用户风险偏好调整
            risk_level = user_profile.get('risk_level', 'medium')
            holding_period = user_profile.get('holding_period', 'medium')

            adjusted_score = AIDecisionEngine._adjust_by_user_profile(
                total_score, risk_level, holding_period
            )

            # 4. 生成决策建议
            decision = AIDecisionEngine._generate_decision(adjusted_score)

            # 5. 计算建议仓位
            position_size = AIDecisionEngine._calculate_position_size(
                adjusted_score, risk_level
            )

            # 6. 设置止盈止损
            stop_profit, stop_loss = AIDecisionEngine._calculate_stop_levels(
                price, adjusted_score, risk_level, holding_period
            )

            # 7. 生成操作建议
            action_plan = AIDecisionEngine._generate_action_plan(
                decision, position_size, price, stop_profit, stop_loss
            )

            # 8. 风险评估
            risk_assessment = AIDecisionEngine._assess_risk(
                technical_signals, money_flow_data, adjusted_score
            )

            # 9. 预期收益预测
            expected_return = AIDecisionEngine._predict_return(
                adjusted_score, holding_period
            )

            return {
                "symbol": symbol,
                "name": name,
                "price": price,
                "decision": decision,
                "confidence": AIDecisionEngine._calculate_confidence(adjusted_score),
                "scores": {
                    "technical": tech_score,
                    "money_flow": money_score,
                    "total": total_score,
                    "adjusted": adjusted_score
                },
                "position_advice": {
                    "action": decision,
                    "position_size": position_size,
                    "entry_price": price,
                    "stop_profit": stop_profit,
                    "stop_loss": stop_loss
                },
                "action_plan": action_plan,
                "risk_assessment": risk_assessment,
                "expected_return": expected_return,
                "key_points": AIDecisionEngine._extract_key_points(
                    technical_signals, money_flow_data, decision
                ),
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            logger.error(f"AI决策生成失败: {str(e)}")
            raise Exception(f"AI决策生成失败: {str(e)}")

    @staticmethod
    def make_coach_aligned_decision(
        symbol: str,
        name: str,
        price: float,
        coach_context: Dict[str, Any],
        technical_signals: Dict[str, Any],
        money_flow_data: Dict[str, Any],
        user_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build the stock-detail AI panel from Smart Screen strategy context.

        The final action must come from CoachService so stock detail pages do not
        produce a second, lower-threshold buy/sell decision.
        """
        legacy = AIDecisionEngine.make_decision(
            symbol=symbol,
            name=name,
            price=price,
            technical_signals=technical_signals,
            money_flow_data=money_flow_data,
            user_profile=user_profile,
        )
        context = coach_context or {}
        available = bool(context.get("available"))
        breakdown = context.get("score_breakdown") or {}

        if available:
            action = str(context.get("action") or "watch")
            decision = AIDecisionEngine._coach_action_label(action)
            total_score = AIDecisionEngine._safe_float(breakdown.get("total"), 0.0)
            ranking_score = AIDecisionEngine._safe_float(
                context.get("ranking_score"),
                AIDecisionEngine._safe_float(breakdown.get("ranking_score"), total_score),
            )
            technical_score = AIDecisionEngine._first_score(
                breakdown,
                ("technical", "trend", "momentum"),
                total_score,
            )
            money_score = AIDecisionEngine._safe_float(breakdown.get("money_flow"), 0.0)
            position_pct = AIDecisionEngine._safe_float(context.get("position_pct"), 0.0)
            take_profit = AIDecisionEngine._safe_float(context.get("take_profit"), price)
            stop_loss = AIDecisionEngine._safe_float(context.get("stop_loss"), price)
            risk_factors = AIDecisionEngine._coach_risk_factors(context)
            expected_return_pct = context.get("expected_return_pct")
            up_prob = context.get("up_prob")
            horizon_days = context.get("horizon_days")
            action_plan = AIDecisionEngine._coach_action_plan(context, decision, price)
        else:
            reason = str(context.get("reason") or "该股不在当前智能选股输出池中，未生成交易计划。")
            decision = "未入选候选池"
            total_score = None
            ranking_score = None
            technical_score = None
            money_score = None
            position_pct = 0.0
            take_profit = None
            stop_loss = None
            risk_factors = [reason, "个股页不再使用旧AI低阈值直接给出买入建议。"]
            expected_return_pct = None
            up_prob = None
            horizon_days = None
            action_plan = [
                reason,
                "请以智能选股候选池、观察池或模拟验证结果作为交易计划来源。",
            ]

        confidence = AIDecisionEngine._coach_confidence(context, ranking_score)
        entry_range = context.get("entry_range") or []
        entry_price = price if available else None
        if available and isinstance(entry_range, list) and entry_range:
            entry_price = AIDecisionEngine._safe_float(entry_range[0], price)

        return {
            "symbol": symbol,
            "name": name,
            "price": price,
            "decision": decision,
            "decision_source": "coach_service",
            "confidence": confidence,
            "scores": {
                "technical": AIDecisionEngine._optional_round(technical_score),
                "money_flow": AIDecisionEngine._optional_round(money_score),
                "total": AIDecisionEngine._optional_round(total_score),
                "adjusted": AIDecisionEngine._optional_round(ranking_score),
            },
            "legacy_scores": legacy.get("scores") or {},
            "position_advice": {
                "action": decision,
                "position_size": f"{position_pct:.1f}%" if position_pct > 0 else "0%",
                "entry_price": AIDecisionEngine._optional_round(entry_price),
                "stop_profit": AIDecisionEngine._optional_round(take_profit),
                "stop_loss": AIDecisionEngine._optional_round(stop_loss),
            },
            "action_plan": action_plan,
            "risk_assessment": {
                "level": AIDecisionEngine._coach_risk_level(context, available),
                "factors": risk_factors,
            },
            "expected_return": AIDecisionEngine._coach_expected_return(
                horizon_days=horizon_days,
                expected_return_pct=expected_return_pct,
                up_prob=up_prob,
                available=available,
            ),
            "key_points": AIDecisionEngine._coach_key_points(context, decision),
            "coach_context": AIDecisionEngine._compact_coach_context(context),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            result = float(value)
            if not np.isfinite(result):
                return default
            return result
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optional_round(value: Any, digits: int = 2) -> Optional[float]:
        if value is None:
            return None
        try:
            result = float(value)
            if not np.isfinite(result):
                return None
            return round(result, digits)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_score(values: Dict[str, Any], keys: tuple, default: float = 0.0) -> float:
        for key in keys:
            if key in values:
                return AIDecisionEngine._safe_float(values.get(key), default)
        return default

    @staticmethod
    def _coach_action_label(action: str) -> str:
        mapping = {
            "buy": "买入",
            "paper_validate": "模拟验证",
            "watch": "观察",
            "added_watchlist": "观察",
            "ignored": "暂不关注",
            "closed": "持仓管理",
        }
        return mapping.get(action, "观察")

    @staticmethod
    def _coach_confidence(context: Dict[str, Any], ranking_score: float) -> str:
        raw = str(context.get("confidence_level") or "").upper()
        if raw in {"A", "S"}:
            return "高"
        if raw == "B":
            return "中等"
        if raw in {"C", "D"}:
            return "低"
        if ranking_score is None:
            return "低"
        return AIDecisionEngine._calculate_confidence(ranking_score)

    @staticmethod
    def _coach_risk_level(context: Dict[str, Any], available: bool) -> str:
        if not available:
            return "高"
        action = str(context.get("action") or "")
        dd_prob = AIDecisionEngine._safe_float(context.get("dd_prob"), 0.0)
        if action == "buy" and dd_prob <= 0.25:
            return "低"
        if dd_prob >= 0.4:
            return "偏高"
        return "中等"

    @staticmethod
    def _coach_risk_factors(context: Dict[str, Any]) -> List[str]:
        factors: List[str] = []
        for key in ("exclusion_reason",):
            value = context.get(key)
            if value:
                factors.append(str(value))
        for item in (context.get("risks") or []) + (context.get("reasons") or []):
            if item and str(item) not in factors:
                factors.append(str(item))
        if not factors:
            factors.append("风险提示来自智能选股策略上下文。")
        return factors[:6]

    @staticmethod
    def _coach_action_plan(context: Dict[str, Any], decision: str, price: float) -> List[str]:
        action = str(context.get("action") or "watch")
        trade_date = context.get("trade_date") or "当前"
        plan: List[str] = [f"使用智能选股 {trade_date} 候选池动作：{decision}。"]
        if action == "buy":
            plan.append("按智能选股交易计划执行，需同时遵守止盈、止损和仓位限制。")
        elif action == "paper_validate":
            plan.append("仅允许记录模拟验证仓位，用于复盘和策略反馈，不作为实盘买入信号。")
        else:
            plan.append("未进入严格买入或模拟验证名单，建议加入观察并等待下一次候选池确认。")
        entry_range = context.get("entry_range") or []
        if isinstance(entry_range, list) and len(entry_range) >= 2:
            low = AIDecisionEngine._safe_float(entry_range[0], price)
            high = AIDecisionEngine._safe_float(entry_range[1], price)
            plan.append(f"候选池参考入场区间：{low:.2f}-{high:.2f}。")
        return plan

    @staticmethod
    def _coach_expected_return(
        horizon_days: Any,
        expected_return_pct: Any,
        up_prob: Any,
        available: bool,
    ) -> Dict[str, Any]:
        if not available:
            return {
                "period": "不适用",
                "expected_return": "不适用",
                "probability": "不适用",
                "description": "未进入当前智能选股候选池，不生成收益预测。",
            }
        horizon = int(AIDecisionEngine._safe_float(horizon_days, 0))
        expected = AIDecisionEngine._safe_float(expected_return_pct, 0.0)
        probability = AIDecisionEngine._safe_float(up_prob, 0.0)
        if 0 <= probability <= 1:
            probability *= 100
        period = f"{horizon}个交易日" if horizon > 0 else "策略持有期"
        return {
            "period": period,
            "expected_return": f"{expected:.1f}%",
            "probability": f"{probability:.0f}%",
            "description": "收益与概率来自智能选股候选池快照，用于复盘参考。",
        }

    @staticmethod
    def _coach_key_points(context: Dict[str, Any], decision: str) -> List[str]:
        points = [f"🎯 智能选股动作：{decision}"]
        if context.get("rank_no"):
            points.append(f"📌 候选池排名：{context.get('rank_no')}")
        if context.get("source"):
            points.append(f"🔗 评分来源：{context.get('source')}")
        if not context.get("available"):
            points.append("⚠️ 未进入当前智能选股输出池")
        return points

    @staticmethod
    def _compact_coach_context(context: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "available",
            "source",
            "trade_date",
            "pick_id",
            "rank_no",
            "action",
            "paper_validation",
            "reason",
            "exclusion_reason",
        )
        return {key: context.get(key) for key in keys if key in context}

    @staticmethod
    def _calculate_money_flow_score(money_flow: Dict[str, Any]) -> float:
        """计算资金流向评分"""
        score = 0

        main_net = money_flow.get('main_net_inflow', 0)
        control_ratio = money_flow.get('control_ratio', 0)

        # 主力净流入评分
        if main_net > 0:
            if control_ratio > 10:
                score += 40
            elif control_ratio > 5:
                score += 25
            else:
                score += 10
        else:
            if control_ratio > 10:
                score -= 40
            elif control_ratio > 5:
                score -= 25
            else:
                score -= 10

        # 趋势强度评分
        strength = money_flow.get('strength', '')
        if strength == '强':
            score *= 1.2

        return min(max(score, -100), 100)

    @staticmethod
    def _adjust_by_user_profile(score: float, risk_level: str, holding_period: str) -> float:
        """根据用户画像调整评分"""
        # 风险调整系数
        risk_multiplier = {
            'low': 0.7,
            'medium': 1.0,
            'high': 1.3
        }.get(risk_level, 1.0)

        # 持有期调整系数
        period_multiplier = {
            'short': 0.8,
            'medium': 1.0,
            'long': 1.2
        }.get(holding_period, 1.0)

        return score * risk_multiplier * period_multiplier

    @staticmethod
    def _generate_decision(score: float) -> str:
        """生成决策建议"""
        if score >= 50:
            return "强烈买入"
        elif score >= 25:
            return "买入"
        elif score >= 10:
            return "谨慎买入"
        elif score >= -10:
            return "观望"
        elif score >= -25:
            return "谨慎卖出"
        elif score >= -50:
            return "卖出"
        else:
            return "强烈卖出"

    @staticmethod
    def _calculate_position_size(score: float, risk_level: str) -> str:
        """计算建议仓位"""
        base_position = {
            'low': 0.3,
            'medium': 0.5,
            'high': 0.7
        }.get(risk_level, 0.5)

        if score >= 50:
            ratio = min(base_position * 1.5, 0.8)
        elif score >= 25:
            ratio = base_position * 1.2
        elif score >= 10:
            ratio = base_position * 0.8
        elif score >= 0:
            ratio = base_position * 0.5
        else:
            ratio = 0

        if ratio >= 0.7:
            return "70-80%（重仓）"
        elif ratio >= 0.5:
            return "50-60%（中等仓位）"
        elif ratio >= 0.3:
            return "30-40%（轻仓）"
        elif ratio > 0:
            return "10-20%（试探仓）"
        else:
            return "空仓观望"

    @staticmethod
    def _calculate_stop_levels(
        price: float,
        score: float,
        risk_level: str,
        holding_period: str
    ) -> tuple:
        """计算止盈止损位"""
        # 止盈比例
        if holding_period == 'short':
            profit_ratio = 0.08 if score > 30 else 0.05
        elif holding_period == 'medium':
            profit_ratio = 0.15 if score > 30 else 0.10
        else:
            profit_ratio = 0.25 if score > 30 else 0.18

        # 止损比例
        loss_ratio = {
            'low': 0.05,
            'medium': 0.08,
            'high': 0.10
        }.get(risk_level, 0.08)

        stop_profit = round(price * (1 + profit_ratio), 2)
        stop_loss = round(price * (1 - loss_ratio), 2)

        return stop_profit, stop_loss

    @staticmethod
    def _generate_action_plan(
        decision: str,
        position_size: str,
        price: float,
        stop_profit: float,
        stop_loss: float
    ) -> List[str]:
        """生成操作计划"""
        plan = []

        if "买入" in decision:
            plan.append(f"📊 建仓策略：{position_size}")
            plan.append(f"💰 建议买入价：{price:.2f}元附近")
            plan.append(f"🎯 目标止盈位：{stop_profit:.2f}元")
            plan.append(f"🛡️ 设置止损位：{stop_loss:.2f}元")

            if "强烈" in decision:
                plan.append("⚡ 可适当加快建仓节奏")
            elif "谨慎" in decision:
                plan.append("⏱️ 建议分批建仓，等待更好买点")

        elif "卖出" in decision:
            plan.append("📉 建议减仓或清仓")
            plan.append(f"💸 卖出参考价：{price:.2f}元附近")

            if "强烈" in decision:
                plan.append("⚡ 建议尽快止损离场")
            else:
                plan.append("⏱️ 可等待反弹后减仓")

        else:  # 观望
            plan.append("👀 暂时观望，等待更明确信号")
            plan.append(f"📍 关注价格是否突破{price * 1.03:.2f}元（上涨3%）")
            plan.append(f"⚠️ 警惕跌破{price * 0.97:.2f}元（下跌3%）")

        return plan

    @staticmethod
    def _assess_risk(
        technical_signals: Dict[str, Any],
        money_flow: Dict[str, Any],
        score: float
    ) -> Dict[str, Any]:
        """风险评估"""
        risk_factors = []
        risk_level = "中等"

        # 技术面风险
        tech_score = technical_signals.get('score', 0)
        if tech_score < -30:
            risk_factors.append("⚠️ 技术面严重超卖，下跌风险较大")
            risk_level = "高"
        elif tech_score > 50:
            risk_factors.append("⚠️ 技术面超买，注意回调风险")

        # 资金面风险
        main_net = money_flow.get('main_net_inflow', 0)
        if main_net < 0:
            risk_factors.append("⚠️ 主力资金持续流出，需警惕")
            if risk_level == "中等":
                risk_level = "偏高"

        # 综合评分风险
        if abs(score) < 10:
            risk_factors.append("⚠️ 信号不明确，方向不清晰")

        if score > 40:
            risk_level = "低"
            risk_factors.append("✓ 多重指标共振向上，风险可控")
        elif score < -40:
            risk_level = "高"
            risk_factors.append("⚠️ 多重指标共振向下，风险较高")

        if len(risk_factors) == 0:
            risk_factors.append("○ 整体风险适中，建议控制仓位")

        return {
            "level": risk_level,
            "factors": risk_factors
        }

    @staticmethod
    def _predict_return(score: float, holding_period: str) -> Dict[str, Any]:
        """预测收益"""
        if holding_period == 'short':
            base_return = 5
            period_text = "短期（1-7天）"
        elif holding_period == 'medium':
            base_return = 12
            period_text = "中期（1-3个月）"
        else:
            base_return = 20
            period_text = "长期（3个月以上）"

        # 根据评分调整预期收益
        if score >= 50:
            expected = base_return * 1.5
            probability = 65
        elif score >= 25:
            expected = base_return * 1.2
            probability = 60
        elif score >= 10:
            expected = base_return * 0.8
            probability = 55
        elif score >= -10:
            expected = 0
            probability = 50
        else:
            expected = -base_return * 0.5
            probability = 45

        return {
            "period": period_text,
            "expected_return": f"{expected:.1f}%",
            "probability": f"{probability}%",
            "description": f"预期{period_text}收益率约{expected:.1f}%，实现概率约{probability}%"
        }

    @staticmethod
    def _calculate_confidence(score: float) -> str:
        """计算决策信心度"""
        confidence = min(abs(score), 100)

        if confidence >= 70:
            return "非常高"
        elif confidence >= 50:
            return "高"
        elif confidence >= 30:
            return "中等"
        else:
            return "低"

    @staticmethod
    def _extract_key_points(
        technical_signals: Dict[str, Any],
        money_flow: Dict[str, Any],
        decision: str
    ) -> List[str]:
        """提取关键要点"""
        points = []

        # 决策要点
        points.append(f"🎯 AI决策：{decision}")

        # 技术面要点
        tech_trend = technical_signals.get('trend', '')
        if tech_trend:
            points.append(f"📈 技术趋势：{tech_trend}")

        # 资金面要点
        money_trend = money_flow.get('trend', '')
        if money_trend:
            points.append(f"💰 资金流向：{money_trend}")

        # 关键信号
        tech_signals_list = technical_signals.get('signals', [])
        if tech_signals_list:
            key_signal = tech_signals_list[0]
            points.append(f"📊 {key_signal}")

        return points
