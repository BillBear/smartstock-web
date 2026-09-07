"""
腾讯数据服务
作为AKShare不可用时的真实数据备用源（实时行情 + 日线K线）
"""
from datetime import datetime
from datetime import timedelta, timezone
import hashlib
import logging
import math
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
        if symbol.startswith("6"):
            return f"sh{symbol}"
        return f"sz{symbol}"

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

    def _parse_quote_payload(self, symbol: str, raw: Optional[str]) -> Optional[dict]:
        if not isinstance(raw, str):
            return None
        parts = raw.split("~")
        if len(parts) < 37:
            return None

        def number(value):
            try:
                numeric = float(value or 0)
            except (TypeError, ValueError, OverflowError):
                return None
            return numeric if math.isfinite(numeric) else None

        segments = parts[35].split("/")
        amount = number(segments[2]) if len(segments) >= 3 else 0.0
        update_time = parts[30]
        if len(update_time) != 14 or not update_time.isdigit():
            return None
        try:
            update_time = datetime.strptime(update_time, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

        price = number(parts[3])
        change = number(parts[31])
        pct_change = number(parts[32])
        open_price = number(parts[5])
        high = number(parts[33])
        low = number(parts[34])
        volume = number(parts[36] or parts[6])
        if None in (amount, price, change, pct_change, open_price, high, low, volume):
            return None

        return {
            "code": symbol,
            "name": parts[1] or symbol,
            "price": price,
            "change": change,
            "pct_change": pct_change,
            "open": open_price,
            "high": high,
            "low": low,
            "volume": volume,
            "amount": amount,
            "update_time": update_time,
        }

    @staticmethod
    def parse_quote_contract(symbol: str, raw: str, *, unit_assumption=None) -> dict:
        """Pure research contract; deliberately not used by live getters.

        Position semantics follow the captured A-share layout. Volume/amount
        normalization requires an explicit, unverified research assumption;
        internal price consistency is supporting evidence, not provider proof.
        """
        if unit_assumption not in (None, "volume_lots_amount_yuan_v1"):
            raise ValueError("unsupported unit assumption")
        if not isinstance(raw, str) or not isinstance(symbol, str) or len(symbol) != 6 or not symbol.isdigit():
            raise ValueError("invalid payload or symbol")
        result = {"schema_version": "tencent-quote-contract-v1", "symbol": symbol,
                  "source": "tencent", "status": "rejected", "values": {}, "raw_values": {},
                  "source_time": None, "trade_date": None, "issues": [],
                  "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                  "unit_assumption": unit_assumption, "official_unit_contract_verified": False,
                  "production_enabled": False, "consistency": {"average_price": None},
                  "positions": {"price": 3, "open": 5, "change": 31, "pct_change": 32,
                                "high": 33, "low": 34, "volume": 36, "amount": "35/2", "source_time": 30}}
        parts = raw.split("~")
        if len(parts) < 37:
            result["issues"].append("short_payload")
            return result
        if parts[2] != symbol:
            result["issues"].append("symbol_mismatch")
            return result
        issues = result["issues"]

        def number(text, field):
            if not text.strip():
                issues.append("missing:" + field)
                return None
            try:
                value = float(text)
                if math.isfinite(value):
                    return value
            except (ValueError, OverflowError):
                pass
            issues.append("invalid:" + field)
            return None

        values = result["values"]
        for field in ("price", "open", "change", "pct_change", "high", "low"):
            values[field] = number(parts[result["positions"][field]], field)
        amount_parts = parts[35].split("/")
        volume = number(parts[36], "volume")
        amount = number(amount_parts[2] if len(amount_parts) == 3 else "", "amount")
        result["raw_values"].update(values, volume=volume, amount=amount)
        for text in (parts[6], amount_parts[1] if len(amount_parts) == 3 else ""):
            if text.strip():
                alternate = number(text, "volume_alternate")
                if alternate is not None and volume is not None and alternate != volume:
                    issues.append("conflicting_volume")
        for field, value in (("volume", volume), ("amount", amount)):
            if value is not None and value < 0:
                issues.append("negative:" + field)
        if len(parts[30]) == 14 and parts[30].isdigit():
            try:
                timestamp = datetime.strptime(parts[30], "%Y%m%d%H%M%S")
                result["source_time"] = timestamp.replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
                result["trade_date"] = timestamp.strftime("%Y%m%d")
            except ValueError:
                issues.append("invalid_source_time")
        else:
            issues.append("missing_or_invalid_source_time")
        low, high = values["low"], values["high"]
        price = values["price"]
        rejected = price is None or price <= 0
        if low is not None and high is not None:
            if low <= 0 or high < low or any(value is not None and not low <= value <= high for value in (price, values["open"])):
                issues.append("invalid_price_range")
                rejected = True
        values.update(volume=None, amount=None)
        result["units"] = {"price": "yuan_per_share", "volume": "unknown", "amount": "unknown"}
        if unit_assumption is None:
            issues.append("unverified_units")
        else:
            values["volume"] = volume * 100 if volume is not None else None
            values["amount"] = amount
            result["units"].update(volume="shares_under_assumption", amount="yuan_under_assumption")
            if values["volume"] is not None and not math.isfinite(values["volume"]):
                issues.append("invalid:converted_volume")
                values["volume"] = None
            if values["volume"] and values["volume"] > 0 and amount is not None and low is not None and high is not None:
                average = amount / values["volume"]
                if math.isfinite(average):
                    result["consistency"]["average_price"] = average
                    if not low - 0.01 <= average <= high + 0.01:
                        issues.append("amount_volume_outside_price_range")
                else:
                    issues.append("invalid:average_price")
            else:
                issues.append("unit_consistency_unavailable")
        result["issues"] = sorted(set(issues))
        result["status"] = "rejected" if rejected else "partial" if issues else "complete_under_assumption"
        return result

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
                    try:
                        quote = self._parse_quote_payload(symbol, raw)
                    except (IndexError, TypeError, ValueError, OverflowError):
                        logger.warning("Tencent批量行情解析失败 symbol=%s", symbol)
                        continue
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
