"""
Flight Monitor - Session Manager
Loads persisted login sessions and applies them to browser contexts.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"


class SessionManager:
    """Manages persisted login sessions for various platforms."""

    def __init__(self):
        SESSIONS_DIR.mkdir(exist_ok=True)

    def load(self, platform: str) -> Optional[Dict]:
        """Load session for a platform, return None if not found or expired."""
        path = SESSIONS_DIR / f"{platform}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            exp_str = s.get("expires_at")
            if not exp_str:
                return None
            try:
                exp = datetime.fromisoformat(exp_str)
            except (ValueError, TypeError):
                return None
            if exp < datetime.now():
                logger.info(f"Session[{platform}] expired at {exp}")
                return None
            return s
        except Exception as e:
            logger.warning(f"Session[{platform}] load error: {e}")
            return None

    def get_cookies(self, platform: str) -> Optional[List[Dict]]:
        s = self.load(platform)
        if s:
            return s.get("cookies", [])
        return None

    def is_valid(self, platform: str) -> bool:
        return self.load(platform) is not None

    def list_platforms(self) -> List[str]:
        """List all platforms that have saved sessions."""
        if not SESSIONS_DIR.exists():
            return []
        return [p.stem for p in SESSIONS_DIR.glob("*.json")]


_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
