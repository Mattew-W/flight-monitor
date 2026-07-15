"""
Flight Monitor - Session Manager v2 (with AES encryption)
____________________________________________________________

Stores login sessions encrypted with AES-256-GCM.
Key: SESSION_SECRET_KEY env var (auto-generated if unset).
Fallback: base64 + XOR obfuscation (cryptography not installed).
"""
import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"

# ── Crypto backend selection ────────────────────────────────────
_HAS_CRYPTO = False
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTO = True
except ImportError:
    pass


# ── Key management ──────────────────────────────────────────────

def _derive_key() -> bytes:
    """Get or generate the encryption key from env var."""
    raw = os.environ.get("SESSION_SECRET_KEY", "")
    if not raw:
        # Generate a persistent key the first time, store in env hint file
        key_file = SESSIONS_DIR / ".key_hint"
        if key_file.exists():
            raw = key_file.read_text().strip()
        else:
            raw = secrets.token_hex(32)
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(raw)
            os.chmod(key_file, 0o600)
            logger.info("SessionManager: generated new encryption key")
    return hashlib.sha256(raw.encode()).digest()  # 32 bytes for AES-256


# ── AES-GCM encrypt/decrypt ─────────────────────────────────────

def _encrypt_aes(plaintext: str, key: bytes) -> bytes:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return nonce + ct  # prepend nonce


def _decrypt_aes(ciphertext: bytes, key: bytes) -> str:
    nonce, ct = ciphertext[:12], ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()


# ── XOR + base64 fallback ───────────────────────────────────────

def _xor_encrypt(plaintext: str, key: bytes) -> bytes:
    pt = plaintext.encode()
    # XOR with key, cycling through key bytes
    ct = bytes(pt[i] ^ key[i % len(key)] for i in range(len(pt)))
    return base64.b64encode(ct)


def _xor_decrypt(ciphertext: bytes, key: bytes) -> str:
    ct = base64.b64decode(ciphertext)
    pt = bytes(ct[i] ^ key[i % len(key)] for i in range(len(ct)))
    return pt.decode()


# ── Session Manager ─────────────────────────────────────────────

class SessionManager:
    """Manages persisted login sessions with encryption."""

    def __init__(self):
        SESSIONS_DIR.mkdir(exist_ok=True)
        self._key = _derive_key()

    def _encrypt(self, plaintext: str) -> bytes:
        if _HAS_CRYPTO:
            return _encrypt_aes(plaintext, self._key)
        return _xor_encrypt(plaintext, self._key)

    def _decrypt(self, ciphertext: bytes) -> str:
        if _HAS_CRYPTO:
            return _decrypt_aes(ciphertext, self._key)
        return _xor_decrypt(ciphertext, self._key)

    def save(self, platform: str, session: Dict):
        """Save encrypted session to disk (atomic write via tmpfile + rename)."""
        path = SESSIONS_DIR / f"{platform}.enc"
        plaintext = json.dumps(session, ensure_ascii=False)
        encrypted = self._encrypt(plaintext)
        # Atomic write: write to temp file then rename to prevent corruption
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(encrypted)
        tmp_path.replace(path)  # atomic on same filesystem
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        logger.info(f"SessionManager: saved encrypted session for '{platform}'")

    def load(self, platform: str) -> Optional[Dict]:
        """Load and decrypt session."""
        path = SESSIONS_DIR / f"{platform}.enc"
        if not path.exists():
            # Backward compat: try old .json format
            old_path = SESSIONS_DIR / f"{platform}.json"
            if old_path.exists():
                try:
                    with open(old_path, "r", encoding="utf-8") as f:
                        s = json.load(f)
                    # Auto-migrate to encrypted format
                    self.save(platform, s)
                    old_path.unlink()
                    logger.info(f"SessionManager: migrated '{platform}' to encrypted format")
                    return self._check_expiry(platform, s)
                except Exception:
                    pass
            return None
        try:
            with open(path, "rb") as f:
                ciphertext = f.read()
            plaintext = self._decrypt(ciphertext)
            s = json.loads(plaintext)
            return self._check_expiry(platform, s)
        except Exception as e:
            logger.warning(f"SessionManager: decrypt failed for '{platform}': {e}")
            return None

    def _check_expiry(self, platform: str, s: Dict) -> Optional[Dict]:
        exp_str = s.get("expires_at")
        if not exp_str:
            return None
        try:
            exp = datetime.fromisoformat(exp_str)
        except (ValueError, TypeError):
            return None
        if exp < datetime.now():
            logger.info(f"SessionManager: '{platform}' expired at {exp}")
            return None
        return s

    def get_cookies(self, platform: str) -> Optional[List[Dict]]:
        s = self.load(platform)
        return s.get("cookies", []) if s else None

    def is_valid(self, platform: str) -> bool:
        return self.load(platform) is not None

    def list_platforms(self) -> List[str]:
        if not SESSIONS_DIR.exists():
            return []
        platforms = set()
        for p in SESSIONS_DIR.glob("*.enc"):
            platforms.add(p.stem)
        for p in SESSIONS_DIR.glob("*.json"):
            platforms.add(p.stem)
        return sorted(platforms)


_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
