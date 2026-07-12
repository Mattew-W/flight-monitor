"""
Flight Monitor - Notifier
Handles price alert notifications via multiple channels.
"""
import html
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO,
    SERVERCHAN_KEY, FEISHU_WEBHOOK,
)

logger = logging.getLogger(__name__)


class Notifier:
    """Multi-channel notification sender."""

    def __init__(self):
        self._requests = None
        try:
            import requests
            self._requests = requests
        except ImportError:
            pass

    def send_notification(
        self,
        title: str,
        message: str,
        send_email: bool = True,
        send_wechat: bool = False,
    ):
        """Send notification via configured channels."""
        if send_email:
            self._send_email(title, message)
        if send_wechat:
            self._send_serverchan(title, message)
        if FEISHU_WEBHOOK:
            self._send_feishu(title, message)

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
            msg.attach(MIMEText(html, "html", "utf-8"))

            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
            logger.info(f"Email notification sent: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")

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
            logger.error(f"Failed to send WeChat notification: {e}")

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
            logger.error(f"Failed to send Feishu notification: {e}")
