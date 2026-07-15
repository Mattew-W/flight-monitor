"""
Flight Monitor - Bing Search Data Source
Uses Bing search engine to find real-time flight prices from the web.
Falls back gracefully if search is blocked or returns no results.
"""
import json
import logging
import os
import re
import time
from typing import List, Optional
from datetime import datetime
from urllib.parse import quote, urlencode

from .base import BaseDataSource
from core.models import FlightPrice, SearchQuery

logger = logging.getLogger(__name__)

# Try to import requests
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class BingSearchSource(BaseDataSource):
    """Bing search-based flight price data source.

    Searches Bing for flight prices and extracts price information
    from search results. This provides real-time pricing data from
    various flight booking platforms indexed by Bing.
    """

    name = "bing"

    # Bing search URL (cn.bing.com works better for Chinese queries)
    BING_SEARCH_URL = "https://cn.bing.com/search"

    # Headers to mimic a real browser
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://cn.bing.com/",
    }

    def __init__(self):
        self._session = None
        if HAS_REQUESTS:
            self._session = requests.Session()
            self._session.headers.update(self.HEADERS)
        # In-memory cache for route lookups (flight_no -> result)
        self._route_cache: dict = {}
        # Negative results cache (flight_no -> True) to skip slow re-searches
        self._route_negative_cache: set = set()
        self._route_cache_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "bing_route_cache.json"
        )
        self._load_route_cache()

    def is_available(self) -> bool:
        return HAS_REQUESTS

    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Search Bing for flight prices."""
        if not self.is_available():
            return []

        results = []
        search_queries = self._build_search_queries(query)

        for sq in search_queries:
            try:
                flights = self._search_and_parse(sq, query)
                results.extend(flights)
                if len(results) >= 20:
                    break
                time.sleep(1.5)  # Be polite to Bing
            except Exception as e:
                logger.warning(f"Bing search failed for '{sq}': {e}")
                continue

        # Deduplicate by flight_no + price
        seen = set()
        unique = []
        for f in results:
            key = f"{f.flight_no}_{f.price}"
            if key not in seen:
                seen.add(key)
                unique.append(f)

        logger.info(f"[bing] Found {len(unique)} flights for {query.departure}->{query.destination}")
        return unique

    def lookup_flight_route(self, flight_no: str) -> dict:
        """Search Bing for flight route info (with caching).

        Returns dict with dep_city, arr_city, airline, or empty dict if not found.
        """
        fn = flight_no.strip().upper()

        # 1. Check in-memory positive cache
        if fn in self._route_cache:
            logger.debug(f"[bing] Route cache hit: {fn}")
            return dict(self._route_cache[fn], _cached=True)

        # 2. Check negative cache (previously not found)
        if fn in self._route_negative_cache:
            logger.debug(f"[bing] Route negative cache hit: {fn}")
            return {}

        # 3. Cache miss: do the actual browser search
        html = self._browser_search(fn)
        if not html:
            self._route_negative_cache.add(fn)
            self._save_route_cache()
            return {}

        result = self._parse_route_html(html, fn)
        if result:
            self._route_cache[fn] = result
        else:
            self._route_negative_cache.add(fn)
        self._save_route_cache()
        return result

    def _load_route_cache(self):
        """Load route cache from disk."""
        if not os.path.exists(self._route_cache_file):
            return
        try:
            with open(self._route_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._route_cache = data.get("positive", {})
            self._route_negative_cache = set(data.get("negative", []))
            logger.info(f"[bing] Loaded {len(self._route_cache)} cached routes "
                        f"({len(self._route_negative_cache)} negative)")
        except Exception as e:
            logger.warning(f"[bing] Cache load failed: {e}")

    def _save_route_cache(self):
        """Persist route cache to disk (best-effort, non-blocking-ish)."""
        try:
            os.makedirs(os.path.dirname(self._route_cache_file), exist_ok=True)
            data = {"positive": self._route_cache, "negative": list(self._route_negative_cache)}
            with open(self._route_cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"[bing] Cache save failed: {e}")

    def _browser_search(self, flight_no: str) -> Optional[str]:
        """Use Playwright headless browser to search Bing and return HTML."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not available for Bing route lookup")
            return None

        query = f"{flight_no} 航班"
        url = f"{self.BING_SEARCH_URL}?q={quote(query)}"
        logger.info(f"[bing] Browser searching: {query}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=8000)
                except Exception:
                    pass
                # Wait briefly for results to render
                try:
                    page.wait_for_selector("#b_results", timeout=4000)
                except Exception:
                    pass
                time.sleep(0.5)  # Reduced from 1.5s
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logger.warning(f"[bing] Browser search failed: {e}")
            return None

    def _parse_route_html(self, html: str, flight_no: str) -> dict:
        """Parse Bing search HTML to extract flight route cities.

        Uses Playwright element-level extraction for precision, then regex
        fallback on cleaned text.
        """
        # --- Approach 1: structured search in DOM-like text ---
        # Remove JS/CSS, extract only visible text
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        # Extract text from between tags
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-z]+;', ' ', text, flags=re.IGNORECASE)  # HTML entities
        text = re.sub(r'\s+', ' ', text).strip()

        # Known Chinese city suffixes for filtering
        city_suffixes = r'(?:市|县|区)?'

        # Pattern: flight_no followed by route within 150 chars
        # e.g. "...ZH9103 航班查询_深圳到北京 飞机..."
        pat = re.escape(flight_no) + r'.{0,150}?'
        pat += r'([\u4e00-\u9fff]{2,4})'  # city 1
        pat += r'\s*[—–→➡到至飞]\s*'       # separator (no plain dash)
        pat += r'([\u4e00-\u9fff]{2,4})'   # city 2

        for m in re.finditer(pat, text):
            c1, c2 = m.group(1), m.group(2)
            if c1 != c2 and not self._is_noise_city(c1) and not self._is_noise_city(c2):
                return self._make_result(flight_no, c1, c2)

        # --- Approach 2: find city cities near any flight_no occurrence ---
        known_cities = [
            "北京", "上海", "广州", "深圳", "成都", "西安", "杭州",
            "南京", "厦门", "武汉", "长沙", "重庆", "昆明", "贵阳",
            "海口", "三亚", "郑州", "天津", "青岛", "大连", "沈阳",
            "哈尔滨", "长春", "济南", "石家庄", "乌鲁木齐", "拉萨",
            "合肥", "南昌", "福州", "南宁", "银川", "西宁", "兰州",
            "呼和浩特", "太原", "香港", "澳门", "台北",
        ]
        # Find flight_no positions
        for m in re.finditer(re.escape(flight_no), text):
            ctx = text[m.start():m.start() + 300]
            found_cities = [c for c in known_cities if c in ctx]
            if len(found_cities) >= 2:
                return self._make_result(flight_no, found_cities[0], found_cities[1])

        return {}

    def _is_noise_city(self, text: str) -> bool:
        """Check if text is a non-city word."""
        noise = {
            "航班", "飞机", "机票", "出发", "到达", "搜索", "查询", "价格",
            "预定", "预订", "信息", "时刻", "动态", "时刻表", "通用",
            "工具", "问题", "结果", "页面", "网站", "首页", "下载", "百度",
            "如何", "怎样", "怎么", "哪个", "哪些", "什么", "以及", "了解",
            "查看", "更多", "全部", "最新", "推荐", "热门", "深圳航空",
            "航空公司", "国际航空", "航班号", "航班查询", "航空有限",
            "责任公司", "有限责任", "详情", "点击", "链接", "携程",
            "途牛", "去哪儿", "飞猪", "达地点", "地点", "方式", "方法",
        }
        if text in noise or len(text) < 2:
            return True
        # Filter: if text contains numbers or ASCII, likely not a city
        if re.search(r'[a-zA-Z0-9]', text):
            return True
        return False

    def _make_result(self, flight_no: str, dep_city: str, arr_city: str) -> dict:
        """Build result dict with airline guessing."""
        airline_map = {
            "CA": "中国国航", "MU": "东方航空", "CZ": "南方航空",
            "HU": "海南航空", "ZH": "深圳航空", "MF": "厦门航空",
            "3U": "四川航空", "9C": "春秋航空", "HO": "吉祥航空",
        }
        prefix = flight_no[:2]
        airline = airline_map.get(prefix, prefix)
        logger.info(f"[bing] Route found: {flight_no} = {dep_city} -> {arr_city}")
        return {"dep_city": dep_city, "arr_city": arr_city, "airline": airline}

    def _build_search_queries(self, query: SearchQuery) -> List[str]:
        """Build multiple search queries for better coverage."""
        dep = query.departure
        arr = query.destination
        date = query.departure_date

        return [
            f"{dep}到{arr}机票价格 {date} 特价",
            f"{dep} {arr} flight price {date}",
            f"机票 {dep}→{arr} {date} 携程 去哪儿",
            f"site:flights.ctrip.com {dep} {arr} {date}",
        ]

    def _search_and_parse(self, search_query: str, original_query: SearchQuery) -> List[FlightPrice]:
        """Execute Bing search and parse results for flight prices."""
        params = {
            "q": search_query,
            "setlang": "zh-CN",
            "count": "30",
        }

        url = f"{self.BING_SEARCH_URL}?{urlencode(params)}"
        logger.info(f"[bing] Searching: {search_query[:60]}...")

        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.warning(f"[bing] Request failed: {e}")
            return []

        return self._parse_bing_results(html, original_query)

    def _parse_bing_results(self, html: str, query: SearchQuery) -> List[FlightPrice]:
        """Parse Bing search HTML to extract flight prices."""
        flights = []
        now = datetime.now().isoformat()

        # Strategy 1: Extract prices with context (flight number + price)
        flight_price_pattern = re.compile(
            r'([A-Z]{2}\d{2,4})[^\d¥]{0,100}?[¥￥]\s*(\d{3,5})',
            re.DOTALL,
        )
        for match in flight_price_pattern.finditer(html):
            flight_no = match.group(1)
            price = float(match.group(2))
            if price < 100 or price > 50000:
                continue
            flights.append(FlightPrice(
                flight_no=flight_no,
                departure=query.departure,
                destination=query.destination,
                departure_date=query.departure_date,
                price=price,
                cabin_class="economy",
                source="bing",
                timestamp=now,
            ))

        # Strategy 2: Extract prices from snippet text
        snippet_pattern = re.compile(
            r'<div[^>]*class="[^"]*b_caption[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )
        price_pattern = re.compile(r'[¥￥]\s*(\d{3,5})')
        flight_pattern = re.compile(r'([A-Z]{2}\d{2,4})')

        for cap_match in snippet_pattern.finditer(html):
            snippet = cap_match.group(1)
            prices = [float(p) for p in price_pattern.findall(snippet) if 100 < float(p) < 50000]
            flight_nums = flight_pattern.findall(snippet)
            for fn in flight_nums:
                for p in prices:
                    flights.append(FlightPrice(
                        flight_no=fn,
                        departure=query.departure,
                        destination=query.destination,
                        departure_date=query.departure_date,
                        price=p,
                        cabin_class="economy",
                        source="bing",
                        timestamp=now,
                    ))

        # Strategy 3: Try JSON-LD structured data
        jsonld_pattern = re.compile(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            re.DOTALL | re.IGNORECASE,
        )
        for match in jsonld_pattern.finditer(html):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict):
                    price = data.get("lowPrice") or data.get("price")
                    if price:
                        flights.append(FlightPrice(
                            flight_no=query.departure + "-" + query.destination,
                            departure=query.departure,
                            destination=query.destination,
                            departure_date=query.departure_date,
                            price=float(price),
                            cabin_class="economy",
                            source="bing_jsonld",
                            timestamp=now,
                        ))
            except (json.JSONDecodeError, ValueError):
                continue

        return flights
