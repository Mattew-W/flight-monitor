"""
Flight Monitor - Data Sources Package
"""
from .base import BaseDataSource
from .mock_source import MockDataSource
from .ctrip_source import CtripDataSource
from .ctrip_browser_source import CtripBrowserSource
from .skyscanner_source import SkyscannerSource
from .bing_search_source import BingSearchSource
from .multi_platform_scraper import (
    MultiPlatformScraper, QunarSource, FliggySource, TongchengSource, AirChinaSource,
)

__all__ = [
    "BaseDataSource", "MockDataSource", "CtripDataSource", "CtripBrowserSource",
    "SkyscannerSource", "BingSearchSource",
    "MultiPlatformScraper", "QunarSource", "FliggySource", "TongchengSource", "AirChinaSource",
]
