"""
资金流向分析服务
分析主力资金、散户资金、北向资金等流向情况
"""
import akshare as ak
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class MoneyFlowService:
    """资金流向分析服务"""

    @staticmethod
    def get_individual_money_flow(symbol: str, days: int = 5) -> Dict[str, Any]:
        """
        获取个股资金流向

        Args:
            symbol: 股票代码
            days: 查询天数

        Returns:
            资金流向数据
        """
        try:
            # 获取个股资金流向
            df = ak.stock_individual_fund_flow_rank(symbol=symbol)

            if df.empty:
                logger.warning(f"未获取到个股资金流向数据: {symbol}")
                return MoneyFlowService._get_fallback_money_flow(symbol, days)

            # 取最近N天的数据
            if len(df) > days:
                df = df.head(days)

            # 计算汇总数据
            total_main_in = df['主力净流入-净额'].sum() if '主力净流入-净额' in df.columns else 0
            total_main_out = abs(df['主力净流入-净额'].sum()) if total_main_in < 0 else 0
            total_retail_in = df['散户净流入-净额'].sum() if '散户净流入-净额' in df.columns else 0

            # 计算主力控盘度
            total_amount = df['成交额'].sum() if '成交额' in df.columns else 1
            control_ratio = (abs(total_main_in) / total_amount * 100) if total_amount > 0 else 0

            # 判断资金流向趋势
            trend = "主力流入" if total_main_in > 0 else "主力流出"
            strength = "强" if abs(total_main_in) > total_amount * 0.05 else "弱"

            return {
                "symbol": symbol,
                "days": days,
                "main_net_inflow": float(total_main_in),
                "main_inflow": float(total_main_in) if total_main_in > 0 else 0,
                "main_outflow": float(total_main_out),
                "retail_net_inflow": float(total_retail_in),
                "control_ratio": float(control_ratio),
                "trend": trend,
                "strength": strength,
                "daily_flow": df.to_dict('records') if len(df) > 0 else [],
                "analysis": MoneyFlowService._analyze_money_flow_trend(df),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            logger.error(f"获取个股资金流向失败: {symbol}, 错误: {str(e)}")
            # 返回备用数据
            return MoneyFlowService._get_fallback_money_flow(symbol, days)

    @staticmethod
    def _get_fallback_money_flow(symbol: str, days: int) -> Dict[str, Any]:
        """
        备用资金流向数据（基于历史数据估算）

        Args:
            symbol: 股票代码
            days: 天数

        Returns:
            估算的资金流向数据
        """
        try:
            from services.stock_service import StockDataService

            # 获取历史数据
            df = StockDataService.get_history_data(symbol=symbol)

            if df.empty or len(df) < days:
                raise ValueError("历史数据不足")

            # 取最近N天
            recent_df = df.tail(days)

            # 基于成交量和价格变动估算资金流向
            recent_df['price_change'] = recent_df['close'].pct_change()
            recent_df['volume_change'] = recent_df['volume'].pct_change()

            # 估算主力净流入（价格上涨且成交量放大视为主力流入）
            recent_df['estimated_main_flow'] = recent_df.apply(
                lambda row: row['turnover'] * 0.3 if row['price_change'] > 0 and row['volume_change'] > 0
                else -row['turnover'] * 0.2 if row['price_change'] < 0
                else 0,
                axis=1
            )

            total_main_in = recent_df['estimated_main_flow'].sum()
            total_amount = recent_df['turnover'].sum()

            control_ratio = (abs(total_main_in) / total_amount * 100) if total_amount > 0 else 0
            trend = "主力流入" if total_main_in > 0 else "主力流出"
            strength = "强" if abs(total_main_in) > total_amount * 0.05 else "弱"

            return {
                "symbol": symbol,
                "days": days,
                "main_net_inflow": float(total_main_in),
                "main_inflow": float(total_main_in) if total_main_in > 0 else 0,
                "main_outflow": float(abs(total_main_in)) if total_main_in < 0 else 0,
                "retail_net_inflow": float(-total_main_in),
                "control_ratio": float(control_ratio),
                "trend": trend,
                "strength": strength,
                "daily_flow": [],
                "analysis": {
                    "conclusion": f"根据{days}日成交数据估算，{trend}（{strength}）",
                    "details": [
                        f"估算主力净流入: {total_main_in/100000000:.2f}亿元",
                        f"主力控盘度: {control_ratio:.1f}%",
                        "注：此数据为估算值，仅供参考"
                    ]
                },
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "is_estimated": True
            }

        except Exception as e:
            logger.error(f"备用资金流向估算失败: {str(e)}")
            return {
                "symbol": symbol,
                "days": days,
                "main_net_inflow": 0,
                "main_inflow": 0,
                "main_outflow": 0,
                "retail_net_inflow": 0,
                "control_ratio": 0,
                "trend": "数据不足",
                "strength": "未知",
                "daily_flow": [],
                "analysis": {
                    "conclusion": "暂无资金流向数据",
                    "details": ["数据获取失败，请稍后重试"]
                },
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e)
            }

    @staticmethod
    def _analyze_money_flow_trend(df: pd.DataFrame) -> Dict[str, Any]:
        """
        分析资金流向趋势

        Args:
            df: 资金流向数据

        Returns:
            趋势分析结果
        """
        if df.empty:
            return {
                "conclusion": "数据不足",
                "details": []
            }

        details = []

        try:
            # 分析主力连续流入/流出天数
            main_flow = df['主力净流入-净额'].values if '主力净流入-净额' in df.columns else []

            if len(main_flow) > 0:
                # 连续流入天数
                continuous_days = 0
                for flow in main_flow:
                    if flow > 0:
                        continuous_days += 1
                    else:
                        break

                if continuous_days >= 3:
                    details.append(f"✓ 主力连续{continuous_days}日净流入，资金持续看好")
                elif continuous_days == 0:
                    # 计算连续流出
                    continuous_out = 0
                    for flow in main_flow:
                        if flow < 0:
                            continuous_out += 1
                        else:
                            break
                    if continuous_out >= 3:
                        details.append(f"✗ 主力连续{continuous_out}日净流出，需警惕")

                # 计算平均流入
                avg_flow = sum(main_flow) / len(main_flow)
                if avg_flow > 0:
                    details.append(f"✓ 近期平均主力净流入 {avg_flow/100000000:.2f}亿元")
                else:
                    details.append(f"✗ 近期平均主力净流出 {abs(avg_flow)/100000000:.2f}亿元")

            # 分析大单、中单、小单
            if '大单净流入-净额' in df.columns:
                big_order = df['大单净流入-净额'].sum()
                if big_order > 0:
                    details.append(f"✓ 大单净流入 {big_order/100000000:.2f}亿元，大资金看好")
                else:
                    details.append(f"✗ 大单净流出 {abs(big_order)/100000000:.2f}亿元")

            # 综合结论
            if len(details) == 0:
                conclusion = "资金流向数据不足"
            elif sum(1 for d in details if d.startswith('✓')) > len(details) / 2:
                conclusion = "资金面偏多，主力资金积极介入"
            else:
                conclusion = "资金面偏空，主力资金流出明显"

        except Exception as e:
            logger.error(f"分析资金流向趋势失败: {str(e)}")
            conclusion = "分析失败"
            details = [str(e)]

        return {
            "conclusion": conclusion,
            "details": details
        }

    @staticmethod
    def get_market_money_flow() -> Dict[str, Any]:
        """
        获取市场整体资金流向

        Returns:
            市场资金流向数据
        """
        try:
            # 获取沪深两市资金流向
            df = ak.stock_market_fund_flow()

            if df.empty:
                raise ValueError("未获取到市场资金流向数据")

            latest = df.iloc[0]

            return {
                "date": str(latest['日期']),
                "market_net_inflow": float(latest.get('主力净流入-净额', 0)),
                "sh_net_inflow": float(latest.get('沪市-主力净流入', 0)),
                "sz_net_inflow": float(latest.get('深市-主力净流入', 0)),
                "market_trend": "整体流入" if latest.get('主力净流入-净额', 0) > 0 else "整体流出",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            logger.error(f"获取市场资金流向失败: {str(e)}")
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "market_net_inflow": 0,
                "sh_net_inflow": 0,
                "sz_net_inflow": 0,
                "market_trend": "数据不足",
                "error": str(e),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    @staticmethod
    def get_sector_money_flow() -> List[Dict[str, Any]]:
        """
        获取板块资金流向排行

        Returns:
            板块资金流向列表
        """
        try:
            # 获取板块资金流向
            df = ak.stock_sector_fund_flow_rank(indicator="今日")

            if df.empty:
                raise ValueError("未获取到板块资金流向数据")

            # 取前10个板块
            top_sectors = df.head(10)

            result = []
            for _, row in top_sectors.iterrows():
                result.append({
                    "name": row['名称'],
                    "net_inflow": float(row.get('净额', 0)),
                    "net_inflow_ratio": float(row.get('净占比', 0)),
                    "rank": len(result) + 1
                })

            return result

        except Exception as e:
            logger.error(f"获取板块资金流向失败: {str(e)}")
            return []

    @staticmethod
    def analyze_money_flow_signal(money_flow: Dict[str, Any]) -> Dict[str, Any]:
        """
        基于资金流向生成交易信号

        Args:
            money_flow: 资金流向数据

        Returns:
            交易信号
        """
        signals = []
        score = 0

        # 主力净流入分析
        main_net = money_flow.get('main_net_inflow', 0)
        control_ratio = money_flow.get('control_ratio', 0)

        if main_net > 0:
            if control_ratio > 10:
                signals.append("✓ 主力大幅净流入，控盘力度强")
                score += 30
            elif control_ratio > 5:
                signals.append("✓ 主力净流入，资金面向好")
                score += 20
            else:
                signals.append("○ 主力小幅流入")
                score += 10
        else:
            if control_ratio > 10:
                signals.append("✗ 主力大幅流出，需警惕")
                score -= 30
            elif control_ratio > 5:
                signals.append("✗ 主力净流出，资金面承压")
                score -= 20
            else:
                signals.append("○ 主力小幅流出")
                score -= 10

        # 趋势和强度分析
        trend = money_flow.get('trend', '')
        strength = money_flow.get('strength', '')

        if '流入' in trend and strength == '强':
            signals.append("✓ 资金流入趋势强劲")
            score += 15
        elif '流出' in trend and strength == '强':
            signals.append("✗ 资金流出趋势明显")
            score -= 15

        # 综合判断
        if score > 30:
            overall = "资金面强烈看多"
        elif score > 15:
            overall = "资金面偏多"
        elif score > 0:
            overall = "资金面中性偏多"
        elif score > -15:
            overall = "资金面中性偏空"
        elif score > -30:
            overall = "资金面偏空"
        else:
            overall = "资金面强烈看空"

        return {
            "overall": overall,
            "score": score,
            "signals": signals
        }
