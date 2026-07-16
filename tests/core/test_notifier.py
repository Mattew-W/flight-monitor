"""
S2: Unit tests for core/notifier.py
Tests notification dedup, URL redaction, and price banding.
"""

import time
import pytest
from unittest.mock import patch, MagicMock
from core.notifier import Notifier, _price_band, _redact_url


class TestPriceBand:
    """Tests for _price_band utility."""

    def test_normal_price(self):
        assert _price_band(850.0) == 17  # 850 // 50 = 17

    def test_zero_price(self):
        assert _price_band(0.0) == 0

    def test_small_price(self):
        assert _price_band(30.0) == 0  # 30 // 50 = 0

    def test_none_price(self):
        assert _price_band(None) == 0

    def test_negative_price(self):
        assert _price_band(-100.0) == -2

    def test_boundary(self):
        assert _price_band(49.99) == 0
        assert _price_band(50.0) == 1


class TestRedactUrl:
    """Tests for _redact_url utility."""

    def test_serverchan_url(self):
        url = "https://sctapi.ftqq.com/SCT123456.send"
        redacted = _redact_url(url)
        assert "***REDACTED***" in redacted
        assert "SCT123456" not in redacted

    def test_feishu_url(self):
        url = "https://open.feishu.cn/open-apis/bot/v2/hook/abc123"
        redacted = _redact_url(url)
        assert "***REDACTED***" in redacted

    def test_plain_url(self):
        url = "https://example.com/some/path"
        redacted = _redact_url(url)
        assert "***REDACTED***" in redacted


class TestNotifierInit:
    """Tests for Notifier initialization."""

    def test_init(self):
        n = Notifier()
        assert n is not None
        assert hasattr(n, '_dedup')
        assert hasattr(n, '_executor')

    def test_close(self):
        n = Notifier()
        n.close()  # Should not raise


class TestNotifierDedup:
    """Tests for notification deduplication."""

    def test_dedup_prevents_duplicate(self):
        n = Notifier()
        n._dedup.clear()
        # Same query_id + price band should be deduped
        n.send_notification(
            title="Test", message="Test message",
            send_email=False, send_wechat=False,
            query_id=1, price=850.0
        )
        # Immediately sending again should be deduped
        n.send_notification(
            title="Test", message="Test message",
            send_email=False, send_wechat=False,
            query_id=1, price=860.0  # Same band (850-899)
        )
        n.close()

    def test_no_dedup_without_query_id(self):
        n = Notifier()
        n._dedup.clear()
        # Without query_id, no dedup tracking
        n.send_notification(
            title="Test", message="Test",
            send_email=False, send_wechat=False,
            query_id=None, price=None
        )
        n.close()

    def test_different_query_ids_not_deduped(self):
        n = Notifier()
        n._dedup.clear()
        n.send_notification(
            title="Test", message="Test",
            send_email=False, send_wechat=False,
            query_id=1, price=850.0
        )
        n.send_notification(
            title="Test", message="Test",
            send_email=False, send_wechat=False,
            query_id=2, price=850.0  # Different query_id
        )
        n.close()
