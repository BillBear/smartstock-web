"""
免费官方资讯因子服务（V1）
来源：
- gov.cn 最新政策 JSON
- pbc.gov.cn 新闻发布页
- miit.gov.cn 工信动态
- cninfo.com.cn 公告查询接口

仅保存结构化事件，控制存储成本，并为智能选股/市场全景提供可解释的资讯因子。
"""
from __future__ import annotations

import hashlib
import html
import re
from collections import Counter
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.services.coach_store import CoachStore


class NewsFactorService:
    GOV_POLICY_JSON_URL = "https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json"
    GOV_BASE_URL = "https://www.gov.cn/"
    PBC_NEWS_URL = "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html"
    PBC_BASE_URL = "https://www.pbc.gov.cn/"
    CSRC_HOME_URL = "https://www.csrc.gov.cn/"
    CSRC_BASE_URL = "https://www.csrc.gov.cn"
    CSRC_NEWS_LIST_URL = "https://www.csrc.gov.cn/csrc/c100028/common_xq_list.shtml"
    NDRC_NEWS_URL = "https://www.ndrc.gov.cn/xwdt/xwfb/"
    NDRC_BASE_URL = "https://www.ndrc.gov.cn"
    MIIT_NEWS_URL = "https://www.miit.gov.cn/xwdt/gxdt/ldhd/index.html"
    MIIT_BASE_URL = "https://www.miit.gov.cn"
    MIIT_UNIT_BUILD_URL = "https://www.miit.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"
    FMPRC_QA_URL = "https://www.fmprc.gov.cn/web/fyrbt_673021/dhdw_673027/"
    FMPRC_BASE_URL = "https://www.fmprc.gov.cn"
    SSE_NEWS_URL = "https://www.sse.com.cn/aboutus/mediacenter/hotandd/"
    SSE_BASE_URL = "https://www.sse.com.cn"
    SZSE_NEWS_URL = "https://www.szse.cn/aboutus/trends/news/"
    SZSE_BASE_URL = "https://www.szse.cn"
    CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    CNINFO_REFERER = "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice"
    MIIT_UNIT_PARAMS: Dict[str, str] = {
        "parseType": "buildstatic",
        "webId": "8d828e408d90447786ddbe128d495e9e",
        "tplSetId": "209741b2109044b5b7695700b2bec37e",
        "pageType": "column",
        "tagId": "右侧内容",
        "editType": "null",
        "pageId": "d3e2bede1bc045e2875fc7161c01db7d",
    }

    INDUSTRY_KEYWORDS: Dict[str, List[str]] = {
        "银行金融": ["银行", "保险", "证券", "资本市场", "货币政策", "金融稳定", "支付", "征信"],
        "半导体": ["半导体", "芯片", "集成电路", "晶圆", "算力", "服务器"],
        "人工智能": ["人工智能", "大模型", "AIGC", "算力", "数据要素", "云计算"],
        "新能源": ["新能源", "光伏", "风电", "储能", "锂电", "新能源汽车", "充电桩"],
        "高端制造": ["制造业", "工业母机", "机器人", "航空", "航天", "智能制造"],
        "医药": ["医药", "创新药", "器械", "生物制品", "中药"],
        "消费": ["消费", "零售", "家电", "汽车消费", "文旅", "餐饮"],
        "地产基建": ["地产", "房地产", "保障房", "基建", "城中村", "水利", "交通"],
        "资源周期": ["煤炭", "钢铁", "有色", "铜", "铝", "化工", "油气"],
        "军工": ["军工", "国防", "装备", "军贸"],
        "传媒互联网": ["传媒", "广告", "游戏", "互联网", "短剧", "出版"],
    }

    MACRO_POSITIVE_KEYWORDS: List[str] = [
        "支持", "促进", "提振", "稳增长", "扩大内需", "降准", "降息", "工具创新",
        "并购重组", "科技创新", "设备更新", "消费补贴", "以旧换新", "民营经济",
    ]
    MACRO_NEGATIVE_KEYWORDS: List[str] = [
        "风险提示", "整顿", "从严", "处罚", "约谈", "制裁", "冲突", "出口管制", "加征关税",
        "收紧", "下调", "暂停", "违规", "战争", "军事打击", "袭击", "爆炸", "遇害",
        "局势升级", "停火", "雷达照射", "核设施", "边境冲突",
    ]
    STOCK_POSITIVE_KEYWORDS: List[str] = [
        "业绩预增", "业绩快报", "回购", "增持", "中标", "签署", "重大合同", "订单",
        "获批", "通过", "股权激励", "盈利", "产销快报", "分红",
    ]
    STOCK_NEGATIVE_KEYWORDS: List[str] = [
        "减持", "业绩预亏", "亏损", "处罚", "问询函", "关注函", "诉讼", "立案", "终止",
        "异常波动", "风险提示", "质押", "延期", "退市", "违规",
    ]

    def __init__(
        self,
        store: CoachStore,
        refresh_seconds: int = 900,
        symbol_refresh_seconds: int = 1800,
    ):
        self.store = store
        self.refresh_seconds = max(120, int(refresh_seconds or 900))
        self.symbol_refresh_seconds = max(300, int(symbol_refresh_seconds or 1800))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self._lock = RLock()
        self._last_refresh_ts = 0.0
        self._last_refresh_at: Optional[str] = None
        self._symbol_refresh_ts: Dict[str, float] = {}

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = html.unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _format_time(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 10_000_000_000:
                ts = ts / 1000.0
            try:
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("年", "-").replace("月", "-").replace("日", "")
        text = text.replace("/", "-").replace(".", "-")
        if re.fullmatch(r"\d{8,14}", text):
            if len(text) >= 8:
                return f"{text[:4]}-{text[4:6]}-{text[6:8]} 00:00:00"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
        return None

    @staticmethod
    def _score_to_display(net_score: float) -> float:
        return max(0.0, min(100.0, 50.0 + net_score))

    @staticmethod
    def _make_hash(source: str, title: str, url: str, publish_time: str) -> str:
        raw = f"{source}|{title}|{url}|{publish_time}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _extract_industry_tags(self, text: str) -> List[str]:
        tags = []
        title = self._clean_text(text)
        for tag, keywords in self.INDUSTRY_KEYWORDS.items():
            if any(keyword in title for keyword in keywords):
                tags.append(tag)
        return tags[:4]

    def _freshness_decay(self, publish_time: Optional[str], horizon_hours: float = 168.0) -> float:
        if not publish_time:
            return 0.45
        try:
            dt = datetime.strptime(publish_time, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return 0.45
        age_hours = max((datetime.now() - dt).total_seconds() / 3600.0, 0.0)
        if age_hours <= 12:
            return 1.0
        if age_hours <= 24:
            return 0.88
        if age_hours <= 72:
            return 0.72
        if age_hours <= horizon_hours:
            return 0.52
        if age_hours <= 24 * 30:
            return 0.28
        return 0.12

    def _build_event(
        self,
        *,
        source: str,
        source_type: str,
        event_level: str,
        event_type: str,
        title: str,
        summary: str,
        url: str,
        publish_time: str,
        direction: str,
        impact_score: float,
        confidence_score: float,
        symbol: Optional[str] = None,
        symbol_name: Optional[str] = None,
        industry_tags: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        title = self._clean_text(title)
        summary = self._clean_text(summary)
        if not title or not url or not publish_time:
            return None
        sign = 1.0 if direction == "positive" else (-1.0 if direction == "negative" else 0.0)
        event_score = sign * impact_score * confidence_score * 10.0
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "source": source,
            "source_type": source_type,
            "event_level": event_level,
            "event_type": event_type,
            "title": title,
            "summary": summary,
            "url": url,
            "publish_time": publish_time,
            "symbol": symbol,
            "symbol_name": self._clean_text(symbol_name),
            "industry_tags": industry_tags or [],
            "direction": direction,
            "impact_score": round(float(impact_score), 4),
            "confidence_score": round(float(confidence_score), 4),
            "event_score": round(float(event_score), 4),
            "content_hash": self._make_hash(source, title, url, publish_time),
            "meta": meta or {},
            "created_at": created_at,
        }

    def _classify_macro_title(self, title: str, source: str) -> Dict[str, Any]:
        text = self._clean_text(title)
        pos_hits = sum(1 for word in self.MACRO_POSITIVE_KEYWORDS if word in text)
        neg_hits = sum(1 for word in self.MACRO_NEGATIVE_KEYWORDS if word in text)
        direction = "neutral"
        if pos_hits > neg_hits:
            direction = "positive"
        elif neg_hits > pos_hits:
            direction = "negative"

        impact = 2.2 + min(2.5, pos_hits * 0.55 + neg_hits * 0.65)
        if any(word in text for word in ["降准", "降息", "资本市场", "并购重组", "房地产", "专项债"]):
            impact += 0.8
        industry_tags = self._extract_industry_tags(text)
        event_type = "macro_policy"
        if source == "pbc":
            event_type = "monetary_policy"
        if industry_tags:
            event_type = "industry_policy"
        return {
            "direction": direction,
            "impact_score": max(1.0, min(5.0, impact)),
            "industry_tags": industry_tags,
            "event_type": event_type,
        }

    def _classify_announcement_title(self, title: str) -> Dict[str, Any]:
        text = self._clean_text(title)
        pos_hits = sum(1 for word in self.STOCK_POSITIVE_KEYWORDS if word in text)
        neg_hits = sum(1 for word in self.STOCK_NEGATIVE_KEYWORDS if word in text)
        direction = "neutral"
        if pos_hits > neg_hits:
            direction = "positive"
        elif neg_hits > pos_hits:
            direction = "negative"

        impact = 2.0 + min(2.6, pos_hits * 0.6 + neg_hits * 0.7)
        event_type = "announcement"
        if any(word in text for word in ["业绩", "快报", "预告"]):
            event_type = "earnings_notice"
            impact += 0.5
        elif any(word in text for word in ["减持", "增持", "回购"]):
            event_type = "capital_action"
            impact += 0.4
        elif any(word in text for word in ["合同", "订单", "中标"]):
            event_type = "business_order"
            impact += 0.5
        elif any(word in text for word in ["处罚", "诉讼", "立案"]):
            event_type = "regulatory_risk"
            impact += 0.8
        return {
            "direction": direction,
            "impact_score": max(1.0, min(5.0, impact)),
            "event_type": event_type,
        }

    def _fetch_json(self, url: str) -> Any:
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _fetch_gov_events(self) -> List[Dict[str, Any]]:
        items = self._fetch_json(self.GOV_POLICY_JSON_URL) or []
        events: List[Dict[str, Any]] = []
        for item in items[:60]:
            title = item.get("TITLE") or item.get("title")
            publish_time = self._format_time(item.get("DOCRELPUBTIME") or item.get("pubtime"))
            url = urljoin(self.GOV_BASE_URL, str(item.get("URL") or item.get("url") or ""))
            meta = self._classify_macro_title(str(title or ""), "gov")
            event = self._build_event(
                source="gov",
                source_type="official_policy",
                event_level="macro" if not meta.get("industry_tags") else "industry",
                event_type=meta.get("event_type", "macro_policy"),
                title=str(title or ""),
                summary=str(item.get("ABSTRACT") or item.get("CHANNEL") or ""),
                url=url,
                publish_time=publish_time or "",
                direction=meta.get("direction", "neutral"),
                impact_score=meta.get("impact_score", 2.5),
                confidence_score=0.98,
                industry_tags=meta.get("industry_tags", []),
                meta={"channel": item.get("CHANNEL"), "docpuburl": item.get("DOCPUBURL")},
            )
            if event:
                events.append(event)
        return events

    def _fetch_pbc_events(self) -> List[Dict[str, Any]]:
        resp = self.session.get(self.PBC_NEWS_URL, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Dict[str, Any]] = []
        seen = set()
        for anchor in soup.select("#r_con a[istitle='true'], #r_con .newslist_style a[href]"):
            href = str(anchor.get("href") or "").strip()
            title = self._clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            if len(title) < 8 or "/goutongjiaoliu/113456/113469/" not in href or title in seen:
                continue
            row = anchor.find_parent("td") or anchor.parent
            date_node = row.find("span", class_="hui12") if row else None
            publish_time = self._format_time(date_node.get_text(" ", strip=True) if date_node else None)
            if not publish_time:
                match = re.search(r"/(20\d{6,14})/", href)
                publish_time = self._format_time(match.group(1)) if match else None
            if not publish_time:
                continue
            url = urljoin(self.PBC_BASE_URL, href)
            seen.add(title)
            meta = self._classify_macro_title(title, "pbc")
            event = self._build_event(
                source="pbc",
                source_type="official_policy",
                event_level="macro" if not meta.get("industry_tags") else "industry",
                event_type=meta.get("event_type", "monetary_policy"),
                title=title,
                summary="中国人民银行公开发布信息",
                url=url,
                publish_time=publish_time,
                direction=meta.get("direction", "neutral"),
                impact_score=meta.get("impact_score", 2.8),
                confidence_score=0.98,
                industry_tags=meta.get("industry_tags", []),
            )
            if event:
                events.append(event)
            if len(events) >= 40:
                break
        return events

    def _fetch_csrc_events(self) -> List[Dict[str, Any]]:
        resp = self.session.get(self.CSRC_NEWS_LIST_URL, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        channel_meta = soup.find("meta", attrs={"name": "channelid"})
        channel_id = (channel_meta.get("content") if channel_meta else "") or "a1a078ee0bc54721ab6b148884c784a8"
        search_url = (
            f"{self.CSRC_BASE_URL}/searchList/{channel_id}"
            "?_isAgg=true&_isJson=true&_pageSize=20&_template=index&_rangeTimeGte=&_channelName=&page=1"
        )
        data = self._fetch_json(search_url) or {}
        rows = (((data.get("data") or {}).get("results")) or [])
        events: List[Dict[str, Any]] = []
        for item in rows:
            title = self._clean_text(item.get("title"))
            url = urljoin(self.CSRC_BASE_URL, str(item.get("url") or ""))
            publish_time = self._format_time(item.get("publishedTimeStr")) or ""
            if len(title) < 10 or not publish_time:
                continue
            meta = self._classify_macro_title(title, "csrc")
            event = self._build_event(
                source="csrc",
                source_type="official_regulation",
                event_level="macro",
                event_type="market_regulation",
                title=title,
                summary="中国证监会公开发布信息",
                url=url,
                publish_time=publish_time,
                direction=meta.get("direction", "neutral"),
                impact_score=max(2.2, self._safe_float(meta.get("impact_score"), 2.8)),
                confidence_score=0.99,
                industry_tags=meta.get("industry_tags", []),
            )
            if event:
                events.append(event)
            if len(events) >= 25:
                break
        return events

    def _fetch_ndrc_events(self) -> List[Dict[str, Any]]:
        resp = self.session.get(self.NDRC_NEWS_URL, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Dict[str, Any]] = []
        seen = set()
        for li in soup.select(".list .u-list li"):
            anchor = li.find("a", href=True)
            date_node = li.find("span")
            if not anchor or not date_node:
                continue
            href = str(anchor.get("href") or "").strip()
            title = self._clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            publish_time = self._format_time(date_node.get_text(" ", strip=True))
            if len(title) < 10 or href.startswith("javascript") or href == "#" or not publish_time:
                continue
            url = urljoin(self.NDRC_NEWS_URL, href)
            if "/xwdt/xwfb/" not in url or title in seen:
                continue
            seen.add(title)
            meta = self._classify_macro_title(title, "ndrc")
            event_level = "industry" if meta.get("industry_tags") else "macro"
            event = self._build_event(
                source="ndrc",
                source_type="official_policy",
                event_level=event_level,
                event_type=meta.get("event_type", "industry_policy"),
                title=title,
                summary="国家发展改革委公开发布信息",
                url=url,
                publish_time=publish_time,
                direction=meta.get("direction", "neutral"),
                impact_score=max(2.0, self._safe_float(meta.get("impact_score"), 2.5)),
                confidence_score=0.98,
                industry_tags=meta.get("industry_tags", []),
            )
            if event:
                events.append(event)
            if len(events) >= 25:
                break
        return events

    def _fetch_miit_events(self) -> List[Dict[str, Any]]:
        resp = self.session.get(
            self.MIIT_UNIT_BUILD_URL,
            params=self.MIIT_UNIT_PARAMS,
            headers={"Referer": self.MIIT_NEWS_URL},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        html_block = (((data.get("data") or {}).get("html")) or "").strip()
        if not html_block:
            return []

        soup = BeautifulSoup(html_block, "html.parser")
        events: List[Dict[str, Any]] = []
        seen = set()
        for li in soup.select("li.cf, li"):
            anchor = li.find("a", href=True)
            date_node = li.find("span")
            if not anchor or not date_node:
                continue
            title = self._clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            href = str(anchor.get("href") or "").strip()
            publish_time = self._format_time(date_node.get_text(" ", strip=True))
            if len(title) < 8 or not href or not publish_time or title in seen:
                continue
            url = urljoin(self.MIIT_BASE_URL, href)
            seen.add(title)
            meta = self._classify_macro_title(title, "miit")
            event_level = "industry" if meta.get("industry_tags") else "macro"
            event = self._build_event(
                source="miit",
                source_type="official_policy",
                event_level=event_level,
                event_type=meta.get("event_type", "industry_policy"),
                title=title,
                summary="工业和信息化部公开发布信息",
                url=url,
                publish_time=publish_time,
                direction=meta.get("direction", "neutral"),
                impact_score=max(2.0, self._safe_float(meta.get("impact_score"), 2.4)),
                confidence_score=0.98,
                industry_tags=meta.get("industry_tags", []),
            )
            if event:
                events.append(event)
            if len(events) >= 25:
                break
        return events

    def _fetch_fmprc_events(self) -> List[Dict[str, Any]]:
        resp = self.session.get(self.FMPRC_QA_URL, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Dict[str, Any]] = []
        seen = set()
        for anchor in soup.select(".newsBd ul.list1 li a[href]"):
            title = self._clean_text(anchor.get_text(" ", strip=True))
            href = str(anchor.get("href") or "").strip()
            if len(title) < 10 or not href or title in seen:
                continue
            date_match = re.search(r"[（(]\s*(20\d{2}-\d{2}-\d{2})\s*[）)]", title)
            publish_time = self._format_time(date_match.group(1)) if date_match else None
            if not publish_time:
                href_match = re.search(r"/(20\d{2})(\d{2})/", href)
                publish_time = self._format_time(f"{href_match.group(1)}-{href_match.group(2)}-01") if href_match else None
            if not publish_time:
                continue

            url = urljoin(self.FMPRC_QA_URL, href)
            seen.add(title)
            meta = self._classify_macro_title(title, "fmprc")
            geo_keywords = ["伊朗", "以色列", "中东", "乌克兰", "美国", "巴基斯坦", "南海", "边境", "冲突", "打击"]
            if meta.get("direction") == "neutral" and any(word in title for word in geo_keywords):
                meta["direction"] = "negative"
                meta["impact_score"] = max(3.0, self._safe_float(meta.get("impact_score"), 2.8) + 0.9)
            event = self._build_event(
                source="fmprc",
                source_type="official_diplomacy",
                event_level="macro",
                event_type="geopolitical_event",
                title=title,
                summary="外交部发言人表态和电话答问",
                url=url,
                publish_time=publish_time,
                direction=meta.get("direction", "neutral"),
                impact_score=max(2.6, self._safe_float(meta.get("impact_score"), 3.0)),
                confidence_score=0.98,
                industry_tags=meta.get("industry_tags", []),
            )
            if event:
                events.append(event)
            if len(events) >= 30:
                break
        return events

    def _fetch_sse_events(self) -> List[Dict[str, Any]]:
        resp = self.session.get(self.SSE_NEWS_URL, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Dict[str, Any]] = []
        seen = set()
        for row in soup.select(".sse_list_1 dd"):
            anchor = row.find("a", href=True)
            date_node = row.find("span")
            if not anchor or not date_node:
                continue
            title = self._clean_text(anchor.get_text(" ", strip=True))
            href = str(anchor.get("href") or "").strip()
            publish_time = self._format_time(date_node.get_text(" ", strip=True))
            if len(title) < 10 or not publish_time:
                continue
            if "发行上市一件事" in title or "招聘" in title:
                continue
            url = urljoin(self.SSE_BASE_URL, href)
            if "/aboutus/mediacenter/hotandd/" not in url or title in seen:
                continue
            seen.add(title)
            meta = self._classify_macro_title(title, "sse")
            event = self._build_event(
                source="sse",
                source_type="exchange_regulation",
                event_level="macro",
                event_type="exchange_action",
                title=title,
                summary="上海证券交易所公开发布信息",
                url=url,
                publish_time=publish_time,
                direction=meta.get("direction", "neutral"),
                impact_score=max(2.0, self._safe_float(meta.get("impact_score"), 2.3)),
                confidence_score=0.97,
                industry_tags=meta.get("industry_tags", []),
            )
            if event:
                events.append(event)
            if len(events) >= 20:
                break
        return events

    def _fetch_szse_events(self) -> List[Dict[str, Any]]:
        resp = self.session.get(self.SZSE_NEWS_URL, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Dict[str, Any]] = []
        seen = set()
        for li in soup.select("ul.newslist.date-right li"):
            anchor = li.find("a", class_="art-list-link", href=True)
            title = self._clean_text(anchor.get("title") or anchor.get_text(" ", strip=True)) if anchor else ""
            href = str(anchor.get("href") or "").strip() if anchor else ""
            if not anchor:
                script = li.find("script")
                script_text = script.get_text("\n", strip=True) if script else ""
                href_match = re.search(r"var\s+curHref\s*=\s*['\"]([^'\"]+)['\"]", script_text)
                title_match = re.search(r"var\s+curTitle\s*=\s*['\"]([^'\"]+)['\"]", script_text)
                href = href_match.group(1).strip() if href_match else ""
                title = self._clean_text(title_match.group(1)) if title_match else ""
            date_node = li.find("span", class_="time")
            publish_time = self._format_time(date_node.get_text(" ", strip=True) if date_node else None)
            if len(title) < 10 or not href or not publish_time:
                continue
            url = urljoin(self.SZSE_NEWS_URL, href)
            if "/aboutus/trends/news/" not in url or title in seen:
                continue
            seen.add(title)
            meta = self._classify_macro_title(title, "szse")
            event = self._build_event(
                source="szse",
                source_type="exchange_regulation",
                event_level="macro",
                event_type="exchange_action",
                title=title,
                summary="深圳证券交易所公开发布信息",
                url=url,
                publish_time=publish_time,
                direction=meta.get("direction", "neutral"),
                impact_score=max(2.0, self._safe_float(meta.get("impact_score"), 2.3)),
                confidence_score=0.97,
                industry_tags=meta.get("industry_tags", []),
            )
            if event:
                events.append(event)
            if len(events) >= 20:
                break
        return events

    def _fetch_cninfo_page(self, page_num: int = 1, page_size: int = 40, search_key: str = "") -> List[Dict[str, Any]]:
        payload = {
            "pageNum": page_num,
            "pageSize": page_size,
            "tabName": "fulltext",
            "plate": "",
            "category": "",
            "searchkey": search_key,
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.CNINFO_REFERER,
        }
        resp = self.session.post(self.CNINFO_QUERY_URL, data=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json() or {}
        return data.get("announcements") or []

    def _convert_cninfo_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for item in items:
            title = self._clean_text(item.get("announcementTitle"))
            publish_time = self._format_time(item.get("announcementTime"))
            adjunct_url = item.get("adjunctUrl") or ""
            url = urljoin("https://static.cninfo.com.cn/", str(adjunct_url))
            meta = self._classify_announcement_title(title)
            event = self._build_event(
                source="cninfo",
                source_type="official_announcement",
                event_level="stock",
                event_type=meta.get("event_type", "announcement"),
                title=title,
                summary=f"巨潮公告：{item.get('secName') or ''}",
                url=url,
                publish_time=publish_time or "",
                symbol=str(item.get("secCode") or ""),
                symbol_name=str(item.get("secName") or ""),
                direction=meta.get("direction", "neutral"),
                impact_score=meta.get("impact_score", 2.4),
                confidence_score=0.99,
                meta={
                    "announcement_type": item.get("announcementType"),
                    "page_column": item.get("pageColumn"),
                },
            )
            if event:
                events.append(event)
        return events

    def _fetch_cninfo_latest_events(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for page in range(1, 3):
            items.extend(self._fetch_cninfo_page(page_num=page, page_size=30))
        return self._convert_cninfo_items(items[:60])

    def refresh_symbol_announcements(self, symbol: str) -> List[Dict[str, Any]]:
        code = str(symbol or "").strip()
        if len(code) != 6 or not code.isdigit():
            return []
        now_ts = datetime.now().timestamp()
        with self._lock:
            if now_ts - float(self._symbol_refresh_ts.get(code, 0.0)) < self.symbol_refresh_seconds:
                return self.store.list_news_events(event_level="stock", symbol=code, limit=8)

        items = self._fetch_cninfo_page(page_num=1, page_size=8, search_key=code)
        events = self._convert_cninfo_items(items)
        if events:
            self.store.upsert_news_events(events)
        with self._lock:
            self._symbol_refresh_ts[code] = now_ts
        return events

    def refresh_if_needed(self, force: bool = False) -> Dict[str, Any]:
        now_ts = datetime.now().timestamp()
        with self._lock:
            if (not force) and (now_ts - self._last_refresh_ts < self.refresh_seconds):
                return {
                    "updated_at": self._last_refresh_at,
                    "refreshed": False,
                }

        events: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {}
        for source_name, fetcher in [
            ("gov", self._fetch_gov_events),
            ("pbc", self._fetch_pbc_events),
            ("csrc", self._fetch_csrc_events),
            ("ndrc", self._fetch_ndrc_events),
            ("miit", self._fetch_miit_events),
            ("fmprc", self._fetch_fmprc_events),
            ("sse", self._fetch_sse_events),
            ("szse", self._fetch_szse_events),
            ("cninfo", self._fetch_cninfo_latest_events),
        ]:
            try:
                items = fetcher() or []
            except Exception:
                items = []
            events.extend(items)
            source_counts[source_name] = len(items)

        if events:
            self.store.upsert_news_events(events)

        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._last_refresh_ts = now_ts
            self._last_refresh_at = updated_at
        return {
            "updated_at": updated_at,
            "refreshed": True,
            "source_counts": source_counts,
            "event_count": len(events),
        }

    def _aggregate_events(self, events: List[Dict[str, Any]], horizon_hours: float) -> float:
        score = 0.0
        for event in events:
            decay = self._freshness_decay(event.get("publish_time"), horizon_hours=horizon_hours)
            score += self._safe_float(event.get("event_score"), 0.0) * decay
        return score

    @staticmethod
    def _serialize_event(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source": item.get("source"),
            "event_level": item.get("event_level"),
            "event_type": item.get("event_type"),
            "title": item.get("title"),
            "publish_time": item.get("publish_time"),
            "direction": item.get("direction"),
            "industry_tags": item.get("industry_tags") or [],
            "url": item.get("url"),
        }

    def _pick_diverse_events(self, events: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
        picked: List[Dict[str, Any]] = []
        seen_sources = set()
        seen_keys = set()

        for item in events:
            key = (item.get("source"), item.get("title"), item.get("publish_time"))
            source = item.get("source")
            if key in seen_keys or not source or source in seen_sources:
                continue
            picked.append(self._serialize_event(item))
            seen_keys.add(key)
            seen_sources.add(source)
            if len(picked) >= limit:
                return picked

        for item in events:
            key = (item.get("source"), item.get("title"), item.get("publish_time"))
            if key in seen_keys:
                continue
            picked.append(self._serialize_event(item))
            seen_keys.add(key)
            if len(picked) >= limit:
                break
        return picked

    def get_market_news_summary(self) -> Dict[str, Any]:
        self.refresh_if_needed(force=False)
        since_time = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        events = self.store.list_news_events(since_time=since_time, limit=360)
        macro_events = [item for item in events if item.get("event_level") == "macro"]
        industry_events = [item for item in events if item.get("event_level") == "industry"]

        macro_net = self._aggregate_events(macro_events, horizon_hours=240)
        industry_net = self._aggregate_events(industry_events, horizon_hours=168)
        policy_net = max(-50.0, min(50.0, macro_net * 0.22 + industry_net * 0.18))
        policy_score = round(self._score_to_display(policy_net), 2)

        risk_bias = "neutral"
        if policy_net >= 10:
            risk_bias = "positive"
        elif policy_net <= -10:
            risk_bias = "negative"

        context_events = [
            item for item in (macro_events + industry_events)
            if abs(self._safe_float(item.get("event_score"), 0.0)) > 0.01
            or item.get("industry_tags")
            or self._safe_float(item.get("impact_score"), 0.0) >= 2.8
            or item.get("event_type") in {"monetary_policy", "market_regulation", "geopolitical_event", "industry_policy"}
        ]
        latest_events = self._pick_diverse_events(context_events or events, limit=8)
        source_counts = Counter(item.get("source") for item in context_events if item.get("source"))

        reasons = []
        positives = [item for item in latest_events if item.get("direction") == "positive"][:2]
        negatives = [item for item in latest_events if item.get("direction") == "negative"][:2]
        for item in positives:
            reasons.append(f"政策/资讯偏利多：{item.get('title')}")
        for item in negatives:
            reasons.append(f"政策/资讯偏利空：{item.get('title')}")

        return {
            "policy_score": policy_score,
            "policy_net": round(policy_net, 2),
            "risk_bias": risk_bias,
            "latest_events": latest_events,
            "reasons": reasons[:4],
            "source_counts": dict(source_counts),
            "updated_at": self._last_refresh_at,
        }

    def get_symbol_news_summary(self, symbol: str, industry: Optional[str] = None, allow_remote: bool = False) -> Dict[str, Any]:
        code = str(symbol or "").strip()
        if len(code) != 6 or not code.isdigit():
            return {
                "macro_score": 50.0,
                "industry_score": 50.0,
                "stock_score": 50.0,
                "total_score": 50.0,
                "net_score": 0.0,
                "sentiment": "neutral",
                "latest_events": [],
            }

        self.refresh_if_needed(force=False)
        if allow_remote:
            self.refresh_symbol_announcements(code)
        since_macro = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        since_stock = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        all_events = self.store.list_news_events(since_time=since_macro, limit=360)
        stock_events = self.store.list_news_events(event_level="stock", symbol=code, since_time=since_stock, limit=12)

        macro_events = [item for item in all_events if item.get("event_level") == "macro"]
        industry_events = []
        industry_name = str(industry or "").strip()
        for item in all_events:
            if item.get("event_level") != "industry":
                continue
            tags = item.get("industry_tags") or []
            if not industry_name:
                continue
            if industry_name in tags or any(tag in industry_name or industry_name in tag for tag in tags):
                industry_events.append(item)

        macro_net = self._aggregate_events(macro_events, horizon_hours=240) * 0.18
        industry_net = self._aggregate_events(industry_events, horizon_hours=168) * 0.28
        stock_net = self._aggregate_events(stock_events, horizon_hours=24 * 30) * 0.32
        net_score = max(-40.0, min(40.0, macro_net + industry_net + stock_net))

        macro_score = round(self._score_to_display(max(-25.0, min(25.0, macro_net))), 2)
        industry_score = round(self._score_to_display(max(-25.0, min(25.0, industry_net))), 2)
        stock_score = round(self._score_to_display(max(-30.0, min(30.0, stock_net))), 2)
        total_score = round(self._score_to_display(net_score), 2)
        sentiment = "neutral"
        if net_score >= 8:
            sentiment = "positive"
        elif net_score <= -8:
            sentiment = "negative"

        # 个股详情页只展示与该股票直接相关的公告，或明确匹配到该行业的资讯。
        # 宏观事件仍参与资讯分，但不作为“关联资讯”展示，避免把无关政策新闻塞进每只股票。
        latest_events = []
        for item in (stock_events[:4] + industry_events[:2])[:6]:
            latest_events.append(
                {
                    "source": item.get("source"),
                    "event_level": item.get("event_level"),
                    "event_type": item.get("event_type"),
                    "title": item.get("title"),
                    "publish_time": item.get("publish_time"),
                    "direction": item.get("direction"),
                    "url": item.get("url"),
                }
            )

        return {
            "macro_score": macro_score,
            "industry_score": industry_score,
            "stock_score": stock_score,
            "total_score": total_score,
            "net_score": round(net_score, 2),
            "sentiment": sentiment,
            "latest_events": latest_events,
            "updated_at": self._last_refresh_at,
        }
