"""SSO access token lifecycle management.

Provides pre-flight JWT expiry checking and on-demand refresh via the
gateway's ``/internal/token/refresh`` endpoint.  Works alongside
``SSOTokenAuth`` (transport-level 401 retry) to give two layers of
token-freshness protection:

1. **Application layer** (this module): proactively refreshes *before*
   the token expires so most requests never see a 401.
2. **Transport layer** (``token_auth.SSOTokenAuth``): catches any 401
   that still leaks through and retries once with a freshened token.
"""

from __future__ import annotations

import base64
import json
import time

import httpx

from template_agent.src.settings import settings
from template_agent.utils.pylogger import get_python_logger

logger = get_python_logger(log_level=settings.PYTHON_LOG_LEVEL)


class TokenManager:
    """Refresh SSO bearer tokens using the gateway internal refresh endpoint."""

    @staticmethod
    def _normalize_token(raw: str | None) -> str | None:
        """Strip whitespace and optional ``Bearer `` prefix."""
        if not raw:
            return None
        t = raw.strip()
        if t.lower().startswith("bearer "):
            t = t[7:].strip()
        return t or None

    def __init__(self, initial_token: str | None) -> None:
        self._token = self._normalize_token(initial_token)
        self._gateway_url = settings.GATEWAY_INTERNAL_URL.rstrip("/")
        self._buffer_seconds = settings.TOKEN_REFRESH_BUFFER_SECONDS

    @property
    def current_token(self) -> str | None:
        return self._token

    async def get_valid_token(self) -> str | None:
        """Return the current token, refreshing first if near expiry."""
        if not self._token:
            return None
        if self._is_near_expiry():
            await self.force_refresh()
        return self._token

    async def force_refresh(self) -> str | None:
        """Call the gateway to obtain a fresh token unconditionally."""
        if not self._token:
            return None
        if not self._gateway_url:
            logger.debug("No GATEWAY_INTERNAL_URL configured — skipping token refresh")
            return self._token
        logger.info("sso_token_refresh_attempt", extra={"gateway_url": self._gateway_url})
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:  # nosec B501
                resp = await client.get(
                    f"{self._gateway_url}/internal/token/refresh",
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                resp.raise_for_status()
                data = resp.json()
                new_token = data.get("access_token")
                if new_token:
                    self._token = self._normalize_token(str(new_token))
                    logger.info(
                        "sso_token_refresh_outcome",
                        extra={"outcome": "success", "gateway_url": self._gateway_url},
                    )
                else:
                    logger.warning(
                        "sso_token_refresh_outcome",
                        extra={"outcome": "missing_access_token", "gateway_url": self._gateway_url},
                    )
        except Exception as e:
            logger.warning(
                "sso_token_refresh_outcome",
                extra={"outcome": "failure", "gateway_url": self._gateway_url, "error": str(e)},
            )
        return self._token

    @classmethod
    def _decode_exp(cls, token: str | None) -> float | None:
        """Decode JWT and return the ``exp`` claim as a Unix timestamp."""
        if not token:
            return None
        try:
            payload = cls._decode_jwt_payload(token)
            exp = payload.get("exp")
            if exp is None:
                return None
            return float(exp)
        except Exception:
            return None

    def _is_near_expiry(self) -> bool:
        exp = self._decode_exp(self._token)
        if exp is None:
            return True
        return time.time() >= (exp - self._buffer_seconds)

    @staticmethod
    def _decode_jwt_payload(token: str) -> dict[str, object]:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        raw = json.loads(payload_bytes)
        if not isinstance(raw, dict):
            raise ValueError("JWT payload must be a JSON object")
        return raw
