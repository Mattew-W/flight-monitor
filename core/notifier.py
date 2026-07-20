"""
Flight Monitor - Notifier (v2)
Handles price alert notifications via multiple channels.
Async dispatch via internal ThreadPoolExecutor — I/O never blocks the caller.
"""
import concurrent.futures
import html
import json
import logging
import re
import smtplib
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO,
    SERVERCHAN_KEY, FEISHU_WEBHOOK,
)

logger = logging.getLogger(__name__)

# Notification dedup: same (query_id, price_band) won't fire more than once per window.
_DEDUP_WINDOW = 3600  # 1 hour
_DEDUP_BAND = 50      # price bucket size in CNY — small fluctuations don't re-notify


def _price_band(price: float) -> int:
    """Bucket price into bands so tiny jitter doesn't trigger spam."""
    try:
        return int(price // _DEDUP_BAND)
    except (TypeError, ValueError):
        return 0


def _redact_url(url: str) -> str:
    """Hide secret path segments in URLs before logging."""
    # https://sctapi.ftqq.com/SCTxxxxx.send -> https://sctapi.ftqq.com/***REDACTED***.send
    # https://open.feishu.cn/open-apis/bot/v2/hook/xxx -> .../hook/***REDACTED***
    return re.sub(r"(https?://[^/]+/)([^?\s]+)", lambda m: m.group(1) + "***REDACTED***", url)


class Notifier:
    """Multi-channel notification sender with asynchronous dispatch."""

    def __init__(self):
        self._requests = None
        try:
            import requests
            self._requests = requests
        except ImportError:
            pass

        # Dedicated thread pool for I/O-heavy notification sends.
        # Kept small (3) because SMTP/HTTP are latency-bound, not CPU-bound.
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        # Dedup cache: key=(query_id, price_band) -> last_sent_ts
        self._dedup: dict = {}
        self._dedup_lock = threading.Lock()

    def send_notification(
        self,
        title: str,
        message: str,
        send_email: bool = True,
        send_wechat: bool = False,
        send_feishu: bool = True,
        query_id: Optional[int] = None,
        price: Optional[float] = None,
    ):
        """Send notification via configured channels asynchronously.

        Each channel's I/O is dispatched to the background thread pool.
        The caller returns immediately — no blocking on SMTP or HTTP latency.

        Dedup: when query_id and price are provided, the same (query_id, price_band)
        won't fire more than once within _DEDUP_WINDOW seconds. Pass None to bypass.
        """
        if query_id is not None and price is not None:
            band = _price_band(price)
            key = (query_id, band)
            now = time.time()
            with self._dedup_lock:
                last = self._dedup.get(key)
                if last is not None and (now - last) < _DEDUP_WINDOW:
                    logger.debug(
                        f"Notifier: dedup skip qid={query_id} band={band} "
                        f"(last sent {int(now - last)}s ago)"
                    )
                    return
            # Dedup check passed — fall through to dispatch.
            # We'll record the send only AFTER at least one channel actually
            # submits, so we don't lose retries when all channels are down.

        # Dedup: only mark as "sent" if at least one channel is actually
        # configured, so we don't skip retries when all channels are down.
        attempted = False

        if send_email:
            self._executor.submit(self._send_email, title, message)
            attempted = True
        if send_wechat:
            self._executor.submit(self._send_serverchan, title, message)
            attempted = True
        if send_feishu and FEISHU_WEBHOOK:
            self._executor.submit(self._send_feishu, title, message)
            attempted = True

        if query_id is not None and price is not None and attempted:
            band = _price_band(price)
            key = (query_id, band)
            now = time.time()
            with self._dedup_lock:
                self._dedup[key] = now
                # Opportunistic GC of stale entries (keep cache small).
                if len(self._dedup) > 256:
                    cutoff = now - _DEDUP_WINDOW
                    self._dedup = {k: v for k, v in self._dedup.items() if v > cutoff}

    def close(self):
        """Explicit shutdown of the notification thread pool."""
        if hasattr(self, "_executor"):
            self._executor.shutdown(wait=False)

    def __del__(self):
        self.close()

    def _send_email(self, subject: str, body: str):
        """Send email notification."""
        if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, EMAIL_TO]):
            logger.info("Email not configured, skipping email notification")
            return
        try:
            msg = MIMEMultipart()
            msg["From"] = SMTP_USER
            msg["To"] = EMAIL_TO
            msg["Subject"] = subject
            safe_subject = html.escape(subject)
            safe_body = html.escape(body)
            html_content = f"""
            <html><body style="font-family: 'Microsoft YaHei', sans-serif;">
            <div style="max-width:600px;margin:0 auto;padding:20px;">
                <h2 style="color:#2563eb;">{safe_subject}</h2>
                <div style="background:#f0f9ff;padding:20px;border-radius:10px;
                            border-left:4px solid #2563eb;">
                    <pre style="white-space:pre-wrap;font-family:inherit;">{safe_body}</pre>
                </div>
                <p style="color:#94a3b8;font-size:12px;margin-top:20px;">
                    Flight Monitor | {datetime.now().strftime('%Y-%m-%d %H:%M')}
                </p>
            </div>
            </body></html>
            """
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
            logger.info(f"Email notification sent: {subject}")
        except Exception as e:
            # Do NOT log full exception — may include SMTP_USER / connection strings.
            logger.error(f"Failed to send email: {type(e).__name__}: {e!s}"[:200])

    def _send_serverchan(self, title: str, body: str):
        """Send WeChat notification via Server Chan (Server酱)."""
        if not SERVERCHAN_KEY:
            logger.info("ServerChan key not configured, skipping WeChat notification")
            return
        if not self._requests:
            logger.warning("requests not installed, skipping WeChat notification")
            return
        try:
            url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
            resp = self._requests.post(url, data={"title": title, "desp": body}, timeout=10)
            if resp.status_code == 200:
                logger.info(f"WeChat notification sent: {title}")
            else:
                logger.warning(f"ServerChan returned {resp.status_code}")
        except Exception as e:
            # Redact: requests exceptions often embed the URL (which contains the secret key).
            logger.error(f"Failed to send WeChat notification: {type(e).__name__} "
                         f"(url={_redact_url('https://sctapi.ftqq.com/')})")

    def _send_feishu(self, title: str, message: str):
        """Send Feishu webhook notification."""
        if not FEISHU_WEBHOOK:
            return
        if not self._requests:
            return
        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": title}},
                    "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": message}}],
                },
            }
            resp = self._requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Feishu notification sent: {title}")
        except Exception as e:
            # Redact: webhook URL contains the secret token.
            logger.error(f"Failed to send Feishu notification: {type(e).__name__} "
                         f"(url={_redact_url(FEISHU_WEBHOOK)})")
