import asyncio
import random
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx

REGISTRY = "https://registry.npmjs.org"
SEARCH_PAGE = 250


@dataclass(frozen=True)
class SearchHit:
    version: str
    weekly_downloads: int


class NpmClient:
    def __init__(self, concurrency: int = 8) -> None:
        self._client = httpx.AsyncClient(
            timeout=60,
            follow_redirects=True,
            headers={"User-Agent": "backstage-plugin-catalog"},
        )
        self._sem = asyncio.Semaphore(concurrency)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        """GET JSON with retries. Returns None on 404."""
        last: int | str = ""
        for attempt in range(8):
            async with self._sem:
                try:
                    resp: httpx.Response | None = await self._client.get(url, params=params)
                except httpx.TransportError:
                    resp = None
            if resp is not None:
                if resp.status_code == 404:
                    return None
                if resp.is_success:
                    return resp.json()
                if resp.status_code != 429 and resp.status_code < 500:
                    resp.raise_for_status()
            retry_after = resp.headers.get("retry-after", "") if resp is not None else ""
            backoff = 2**attempt + random.random()
            delay = max(float(retry_after), backoff) if retry_after.isdigit() else backoff
            last = resp.status_code if resp is not None else "transport error"
            await asyncio.sleep(min(delay, 120))
        raise RuntimeError(f"giving up on {url} {params}: {last}")

    async def search(self, text: str) -> dict[str, SearchHit]:
        hits: dict[str, SearchHit] = {}
        offset = 0
        while True:
            page = await self._get(
                f"{REGISTRY}/-/v1/search",
                {"text": text, "size": SEARCH_PAGE, "from": offset},
            )
            objects = page["objects"] if page else []
            for obj in objects:
                weekly = int((obj.get("downloads") or {}).get("weekly") or 0)
                hits[obj["package"]["name"]] = SearchHit(obj["package"]["version"], weekly)
            offset += SEARCH_PAGE
            if page is None or not objects or offset >= page["total"]:
                return hits

    async def packument(self, name: str) -> dict[str, Any] | None:
        """Full metadata: every version, times, README. Can weigh several MB."""
        result: dict[str, Any] | None = await self._get(f"{REGISTRY}/{quote(name, safe='@')}")
        return result

    async def latest(self, name: str) -> dict[str, Any] | None:
        """Manifest of the latest version only: a few KB."""
        result: dict[str, Any] | None = await self._get(f"{REGISTRY}/{quote(name, safe='@')}/latest")
        return result
