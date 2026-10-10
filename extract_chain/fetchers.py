"""REST calls to TinyFish Fetch, Firecrawl scrape v2 and Keenable fetch (design section 8).

Every function returns result dicts and never raises. A failure becomes
``{"error": "<Provider>: <detail>", "code": "<short code>"}``; the code appears in the log line (L1).
"""

from __future__ import annotations

import asyncio

import httpx

TINYFISH_URL = "https://api.fetch.tinyfish.ai"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"
KEENABLE_URL = "https://api.keenable.ai/v1/fetch"

# A0: hard total time per request in seconds (httpx timeouts only bound single phases).
TINYFISH_DEADLINE = 40.0
FIRECRAWL_DEADLINE = 40.0
KEENABLE_DEADLINE = 25.0
ERROR_MAX = 200  # A4
TINYFISH_MAX_URLS = 10  # per request (TinyFish limit)
FIRECRAWL_PDF_MAX_PAGES = 30  # Firecrawl bills one credit per PDF page

# D7: accept cached copies of at most one hour.
TINYFISH_BODY = {"format": "markdown", "per_url_timeout_ms": 30_000, "ttl": 3600}
FIRECRAWL_BODY = {
    "formats": ["markdown"],
    "onlyMainContent": True,
    "maxAge": 3_600_000,
    "timeout": 30_000,
    "parsers": [{"type": "pdf", "maxPages": FIRECRAWL_PDF_MAX_PAGES}],
}


def _error(provider: str, detail: object, code: str, key: str = "") -> dict:
    text = str(detail).strip()
    if key:  # S3: a reply that echoes the key must not carry it into the result
        text = text.replace(key, "[key]")
    return {"error": f"{provider}: {text[:ERROR_MAX]}", "code": code}


def _describe(exc: Exception) -> str:
    if isinstance(exc, TimeoutError | httpx.TimeoutException):
        return "timeout"
    return type(exc).__name__


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _request(client: httpx.AsyncClient, deadline: float, method: str, url: str, **kw) -> httpx.Response:
    async with asyncio.timeout(deadline):
        return await client.request(method, url, timeout=deadline, **kw)


def _key(url: object) -> str:
    return str(url or "").rstrip("/")


async def tinyfish(client: httpx.AsyncClient, urls: list[str], key: str) -> dict[str, dict]:
    """A1: batch request(s); result per input URL. Errors carry TinyFish's code in ``code``."""
    if len(urls) > TINYFISH_MAX_URLS:
        parts = await asyncio.gather(
            *(tinyfish(client, urls[i : i + TINYFISH_MAX_URLS], key) for i in range(0, len(urls), TINYFISH_MAX_URLS))
        )
        return {url: doc for part in parts for url, doc in part.items()}
    try:
        response = await _request(
            client,
            TINYFISH_DEADLINE,
            "POST",
            TINYFISH_URL,
            json={"urls": urls, **TINYFISH_BODY},
            headers={"X-API-Key": key, "Accept": "application/json"},
        )
        if response.status_code >= 300:
            failed = _error("TinyFish", f"HTTP {response.status_code}", f"http_{response.status_code}")
            return {url: dict(failed) for url in urls}
        data = response.json()
        found = {}
        for item in data.get("results") or []:
            found[_key(item.get("url"))] = {
                "title": str(item.get("title") or ""),
                "content": str(item.get("text") or ""),
                "final_url": item.get("final_url"),
            }
        for item in data.get("errors") or []:
            code = str(item.get("error") or "fetch failed")
            found[_key(item.get("url"))] = _error("TinyFish", code, code)
        if len(urls) == 1 and len(found) == 1 and _key(urls[0]) not in found:
            found = {_key(urls[0]): next(iter(found.values()))}  # reply names another URL (e.g. after a redirect)
    except Exception as exc:  # transport errors, deadline, malformed reply
        failed = _error("TinyFish", _describe(exc), _describe(exc))
        return {url: dict(failed) for url in urls}
    return {url: found.get(_key(url)) or _error("TinyFish", "no result", "no_result") for url in urls}


async def firecrawl(client: httpx.AsyncClient, url: str, key: str) -> dict:
    """A2: scrape one URL; a non-2xx status of the target page counts as an error (D9)."""
    try:
        response = await _request(
            client,
            FIRECRAWL_DEADLINE,
            "POST",
            FIRECRAWL_URL,
            json={"url": url, **FIRECRAWL_BODY},
            headers={"Authorization": f"Bearer {key}"},
        )
        payload = _json(response)
        if response.status_code >= 300 or not payload.get("success"):
            detail = f"API {response.status_code}: {payload.get('error') or response.text}"
            return _error("Firecrawl", detail, f"api_{response.status_code}", key)
        data = payload.get("data") or {}
        meta = data.get("metadata") or {}
        status = meta.get("statusCode")
        if isinstance(status, int) and not (200 <= status < 300 or status == 304):
            return _error("Firecrawl", f"target HTTP {status}", f"target_{status}")
        doc = {
            "title": str(meta.get("title") or ""),
            "content": str(data.get("markdown") or ""),
            "final_url": meta.get("url") or meta.get("sourceURL"),
        }
        shown, total = meta.get("numPages"), meta.get("totalPages")
        if isinstance(shown, int) and isinstance(total, int) and total > shown:
            doc["pdf_pages"] = (shown, total)  # V7
        return doc
    except Exception as exc:
        return _error("Firecrawl", _describe(exc), _describe(exc))


async def keenable(client: httpx.AsyncClient, url: str, key: str) -> dict:
    """A3: indexed copy of one URL (no ``live`` fetch)."""
    try:
        response = await _request(
            client,
            KEENABLE_DEADLINE,
            "GET",
            KEENABLE_URL,
            params={"url": url},
            headers={"Authorization": f"Bearer {key}", "X-Keenable-Title": "hermes-extract-chain"},
        )
        if response.status_code >= 300:
            body = _json(response)
            detail = body.get("message") or body.get("error") or response.text.strip()
            return _error("Keenable", detail or f"HTTP {response.status_code}", f"http_{response.status_code}", key)
        data = response.json()
        return {
            "title": str(data.get("title") or ""),
            "content": str(data.get("content") or ""),
            "final_url": data.get("url"),
        }
    except Exception as exc:
        return _error("Keenable", _describe(exc), _describe(exc))
