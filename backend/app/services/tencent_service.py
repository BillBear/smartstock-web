"""
腾讯数据服务
作为AKShare不可用时的真实数据备用源（实时行情 + 日线K线）
"""
from datetime import datetime
import logging
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)


class TencentService:
    """腾讯行情数据服务"""

    QUOTE_API = "https://qt.gtimg.cn/q={market_symbol}"
    KLINE_API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_symbol},day,,,{count},qfq"

    def __init__(self, timeout: int = 4):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            }
        )
        logger.info("Tencent服务初始化成功")

    @staticmethod
    def _to_market_symbol(symbol: str) -> str:
        text = str(symbol or "").strip()
        lowered = text.lower()
        if len(lowered) >= 8 and lowered[:2] in {"sh", "sz", "bj"}:
            return lowered
        upper = text.upper()
        if "." in upper:
            code, market = upper.split(".", 1)
            if market in {"SH", "SZ", "BJ"} and code:
                return f"{market.lower()}{code}"
        if text.startswith("6"):
            return f"sh{text}"
        return f"sz{text}"

    @staticmethod
    def _to_plain_symbol(market_symbol: str) -> str:
        text = str(market_symbol or "").strip()
        if len(text) >= 8 and text[:2] in {"sh", "sz", "bj"}:
            return text[-6:]
        return text

    @staticmethod
    def _safe_float(value):
        """安全浮点转换，遇到非数值（如分红字典）时返回None。"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None
        return None

    def _parse_quote_payload(self, symbol: str, raw: str) -> Optional[dict]:
        parts = raw.split("~")
        if len(parts) < 35:
            return None

        amount = 0.0
        if len(parts) > 35 and "/" in parts[35]:
            segments = parts[35].split("/")
            if len(segments) >= 3:
                amount = float(segments[2] or 0)

        update_time = parts[30] if len(parts) > 30 else ""
        if len(update_time) == 14:
            update_time = datetime.strptime(update_time, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        else:
            update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            "code": symbol,
            "name": parts[1] or symbol,
            "price": float(parts[3] or 0),
            "change": float(parts[31] or 0),
            "pct_change": float(parts[32] or 0),
            "open": float(parts[5] or 0),
            "high": float(parts[33] or 0),
            "low": float(parts[34] or 0),
            "volume": float(parts[36] or parts[6] or 0),
            "amount": amount,
            "update_time": update_time,
        }

    def get_realtime_quote(self, symbol: str) -> Optional[dict]:
        """获取腾讯实时行情。"""
        market_symbol = self._to_market_symbol(symbol)
        url = self.QUOTE_API.format(market_symbol=market_symbol)
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="ignore")
            if "=\"" not in text:
                return None
            raw = text.split("=\"", 1)[1].rsplit("\";", 1)[0]
            return self._parse_quote_payload(symbol, raw)
        except Exception as e:
            logger.error(f"Tencent获取实时行情失败 {symbol}: {str(e)}")
            return None

    def get_realtime_quotes_batch(self, symbols):
        """批量获取腾讯实时行情。"""
        if not symbols:
            return {}

        result = {}
        valid_symbols = [str(s).strip() for s in symbols if str(s).strip()]
        batch_size = 180
        for i in range(0, len(valid_symbols), batch_size):
            batch = valid_symbols[i:i + batch_size]
            market_symbols = [self._to_market_symbol(symbol) for symbol in batch]
            url = self.QUOTE_API.format(market_symbol=",".join(market_symbols))
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                text = resp.content.decode("gbk", errors="ignore")
                lines = [line.strip() for line in text.split(";") if line.strip()]
                for line in lines:
                    if "=\"" not in line:
                        continue
                    prefix, payload = line.split("=\"", 1)
                    market_symbol = prefix.replace("v_", "").strip()
                    symbol = self._to_plain_symbol(market_symbol)
                    raw = payload.rsplit("\"", 1)[0]
                    quote = self._parse_quote_payload(symbol, raw)
                    if quote:
                        result[symbol] = quote
            except Exception as e:
                logger.warning(f"Tencent批量行情失败 batch={i//batch_size + 1}: {str(e)}")
                continue
        return result

    def get_history_data(self, symbol: str, days: int = 120) -> pd.DataFrame:
        """获取腾讯日线历史数据（前复权）。"""
        market_symbol = self._to_market_symbol(symbol)
        count = max(days, 120)
        url = self.KLINE_API.format(market_symbol=market_symbol, count=count)
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            node = (payload.get("data") or {}).get(market_symbol) or {}
            rows = node.get("qfqday") or node.get("day") or []
            if not rows:
                return pd.DataFrame()

            records = []
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    continue
                open_price = self._safe_float(row[1])
                close_price = self._safe_float(row[2])
                high_price = self._safe_float(row[3])
                low_price = self._safe_float(row[4])
                volume = self._safe_float(row[5])
                if None in (open_price, close_price, high_price, low_price, volume):
                    continue

                # 腾讯接口在某些日期会混入分红送配字典，amount字段不稳定，按可解析数值提取。
                amount = 0.0
                for extra in row[6:]:
                    parsed = self._safe_float(extra)
                    if parsed is not None:
                        amount = parsed
                        break

                records.append(
                    {
                        "date": str(row[0]).replace("-", ""),
                        "open": open_price,
                        "close": close_price,
                        "high": high_price,
                        "low": low_price,
                        "volume": volume,
                        "amount": amount,
                    }
                )

            if not records:
                return pd.DataFrame()
            df = pd.DataFrame(records)
            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            logger.error(f"Tencent获取历史数据失败 {symbol}: {str(e)}")
            return pd.DataFrame()
