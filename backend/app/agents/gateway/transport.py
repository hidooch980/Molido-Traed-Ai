"""How a request leaves the process. Injected, so tests never touch a network."""

from __future__ import annotations

from typing import Any, Protocol


class Transport(Protocol):
    async def post(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
    ) -> tuple[int, dict[str, Any]]: ...


class HttpxTransport:
    """The real one. Imported lazily so a disabled gateway costs nothing."""

    async def post(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
    ) -> tuple[int, dict[str, Any]]:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload if isinstance(payload, dict) else {}
