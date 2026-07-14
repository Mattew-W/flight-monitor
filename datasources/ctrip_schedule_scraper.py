"""
Ctrip Schedule Scraper v3 — 务实方案

L1+L2 用 requests（能正常访问），建立航线连通数据库。
航班详情数据由已有的 H5 价格 API 和 flight_schedules.py 提供。

产出:
  - route_map.json: 每个出发机场到哪些目的地有航班
  - 机场数量统计、航线总数等

用法:
    python ctrip_schedule_scraper.py              # 爬取所有航线连通关系
    python ctrip_schedule_scraper.py --top 30     # 只爬前30个出发城市
"""
import json
import os
import re
import sys
import time
import logging
import argparse
from typing import Dict, List, Set, Tuple

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ctrip_schedule")

BASE_URL = "https://flights.ctrip.com/schedule/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# IATA code -> Chinese city name mapping (built from Luke's data)
# We'll fill this as we scrape


def fetch_airports() -> Dict[str, str]:
    """Fetch all departure airports: {IATA_code: city_name}."""
    logger.info("Fetching airport list...")
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    resp.encoding = "utf-8"
    
    # Pattern: <a href="/schedule/bjs..html">北京航班</a>
    pattern = re.compile(
        r'<a[^>]*href="?/schedule/([a-z0-9]+)\.\.html"?[^>]*>(.*?)航班</a>',
        re.IGNORECASE
    )
    
    airports = {}
    for m in pattern.finditer(resp.text):
        code = m.group(1).upper()
        city = m.group(2).strip()
        if code and city:
            airports[code] = city
    
    logger.info(f"Found {len(airports)} departure airports")
    return airports


def fetch_destinations(dep_code: str) -> Dict[str, str]:
    """From a departure airport page, get all destinations: {IATA: city_name}."""
    url = f"{BASE_URL}{dep_code.lower()}..html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.encoding = "utf-8"
    except requests.RequestException as e:
        logger.warning(f"  {dep_code}: request failed: {e}")
        return {}
    
    # Pattern: <a href="/schedule/{dep}.{arr}.html">上海航班</a>
    pattern = re.compile(
        rf'<a[^>]*href="?/schedule/{dep_code.lower()}\.([a-z0-9]+)\.html"?[^>]*>(.*?)航班</a>',
        re.IGNORECASE
    )
    
    destinations = {}
    for m in pattern.finditer(resp.text):
        code = m.group(1).upper()
        city = m.group(2).strip()
        if code and city and code != dep_code:
            destinations[code] = city
    
    return destinations


def build_route_map(
    top_n: int = 0,
    departure_filter: str = "",
    delay: float = 0.3,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Build complete route connectivity map.
    
    Returns:
      (airports, route_map)
      airports: {IATA: city_name} for all airports
      route_map: {dep_IATA: {arr_IATA: city_name}}
    """
    airports = fetch_airports()
    
    if departure_filter:
        target = departure_filter.upper()
        airports = {k: v for k, v in airports.items() if k == target}
    
    airport_list = list(airports.items())
    if top_n > 0:
        airport_list = airport_list[:top_n]
    
    route_map = {}
    total_routes = 0
    
    for dep_code, dep_city in airport_list:
        logger.info(f"Processing: {dep_city} ({dep_code})")
        destinations = fetch_destinations(dep_code)
        route_map[dep_code] = destinations
        total_routes += len(destinations)
        logger.info(f"  {len(destinations)} destinations")
        
        if delay > 0 and len(airport_list) > 1:
            time.sleep(delay)
    
    logger.info(f"Done: {len(route_map)} airports, {total_routes} route pairs")
    return airports, route_map


def generate_flight_schedule_py(
    airports: Dict[str, str],
    route_map: Dict[str, Dict[str, str]],
    output_path: str,
):
    """Generate an updated flight_schedules.py with the route connectivity data.
    This supplements (not replaces) the existing static schedule data."""
    
    lines = [
        '"""',
        'Flight Schedule Database — Auto-generated from Ctrip schedule scraper',
        f'Generated: {time.strftime("%Y-%m-%d %H:%M")}',
        f'Airports: {len(airports)}, Routes: {sum(len(v) for v in route_map.values())}',
        '',
        'This file supplements the static flight schedule data with',
        'live route connectivity information scraped from flights.ctrip.com/schedule/.',
        '"""',
        '',
        '# Airport IATA codes to Chinese city names',
        'AIRPORT_NAMES = {',
    ]
    
    for code, city in sorted(airports.items()):
        lines.append(f'    "{code}": "{city}",')
    lines.append('}')
    lines.append('')
    
    lines.append('# Route connectivity: departure IATA -> {arrival IATA: city_name}')
    lines.append('ROUTE_MAP = {')
    for dep_code in sorted(route_map.keys()):
        dests = route_map[dep_code]
        if dests:
            lines.append(f'    "{dep_code}": {{')
            for arr_code, arr_city in sorted(dests.items()):
                lines.append(f'        "{arr_code}": "{arr_city}",')
            lines.append('    },')
    lines.append('}')
    lines.append('')
    
    lines.append('')
    lines.append('def get_destinations(departure_code: str) -> dict:')
    lines.append('    """Get all destinations from a departure airport."""')
    lines.append('    return ROUTE_MAP.get(departure_code.upper(), {})')
    lines.append('')
    lines.append('def get_airport_name(code: str) -> str:')
    lines.append('    """Get Chinese city name for an IATA code."""')
    lines.append('    return AIRPORT_NAMES.get(code.upper(), code)')
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    logger.info(f"Generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Ctrip Route Map Scraper")
    parser.add_argument("--top", type=int, default=0, help="Only first N airports")
    parser.add_argument("--departure", type=str, default="", help="Only from IATA code")
    parser.add_argument("--output", type=str, default="datasources/route_map.py",
                        help="Output Python module path")
    parser.add_argument("--json", type=str, default="",
                        help="Also output as JSON")
    parser.add_argument("--delay", type=float, default=0.3, help="Request delay")
    args = parser.parse_args()

    airports, route_map = build_route_map(
        top_n=args.top,
        departure_filter=args.departure or "",
        delay=args.delay,
    )

    if airports and route_map:
        generate_flight_schedule_py(airports, route_map, args.output)
        
        total_routes = sum(len(v) for v in route_map.values())
        print(f"\n{'='*50}")
        print(f"Airports: {len(airports)}")
        print(f"Route pairs: {total_routes}")
        print(f"Output: {args.output}")
        
        if args.json:
            data = {"airports": airports, "routes": route_map}
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"JSON: {args.json}")
    else:
        print("No data collected.")


if __name__ == "__main__":
    main()
