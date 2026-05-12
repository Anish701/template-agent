"""SSO token authentication for httpx clients.

Implements an httpx.Auth handler that attaches a Bearer token on every
request in the chain (surviving redirects), and optionally refreshes
the token via the gateway when a 401 is received.
"""

from typing import AsyncGenerator, Generator

import httpx

from template_agent.utils.pylogger import get_python_logger

logger = get_python_logger()


class SSOTokenAuth(httpx.Auth):
    """httpx Auth handler that re-applies Bearer token on every request.

    Unlike static headers, this survives cross-origin redirects because
    httpx.Auth.auth_flow is invoked for each request in the chain.
    """

    requires_response_body = False

    def __init__(self, token: str, gateway_url: str = ""):
        self._token = token
        self._gateway_url = gateway_url.rstrip("/") if gateway_url else ""

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == 401 and self._gateway_url:
            refreshed = self._sync_refresh()
            if refreshed:
                self._token = refreshed
                request.headers["Authorization"] = f"Bearer {self._token}"
                yield request

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == 401 and self._gateway_url:
            refreshed = await self._async_refresh()
            if refreshed:
                self._token = refreshed
                request.headers["Authorization"] = f"Bearer {self._token}"
                yield request

    def _sync_refresh(self) -> str | None:
        """Attempt a synchronous token refresh via the gateway."""
        try:
            resp = httpx.get(
                f"{self._gateway_url}/internal/token/refresh",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                new_token = resp.json().get("access_token", "")
                if new_token:
                    logger.info("SSO token refreshed via gateway (sync)")
                    return new_token
        except Exception as exc:
            logger.warning(f"Token refresh failed (sync): {exc}")
        return None

    async def _async_refresh(self) -> str | None:
        """Attempt an async token refresh via the gateway."""
        try:
            async with httpx.AsyncClient(verify=False) as client:  # nosec B501
                resp = await client.get(
                    f"{self._gateway_url}/internal/token/refresh",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    new_token = resp.json().get("access_token", "")
                    if new_token:
                        logger.info("SSO token refreshed via gateway (async)")
                        return new_token
        except Exception as exc:
            logger.warning(f"Token refresh failed (async): {exc}")
        return None
