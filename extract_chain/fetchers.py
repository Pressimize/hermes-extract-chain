"""REST calls to Bright Data Web Unlocker, Jina Reader, Firecrawl scrape v2, Tavily Extract and Keenable fetch
(design section 8).

Every function fetches one URL, takes the time it may use (``deadline``, seconds) and never raises. A result is
``{"title", "content", "final_url"}`` plus optional ``target_status`` (int, status of the target page) and
``pdf_pages``. A failure is ``{"error": "<Provider>: <detail>", "code": "<short code>"}``; the code appears in the log
line (L1). ``target_status`` is set on failures of the target page, ``quota: True`` when the provider's own API
reports a used-up quota or a blocked account (K7: only that starts a pause, never the status of a target page).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

import httpx

BRIGHTDATA_URL = "https://api.brightdata.com/request"
JINA_URL = "https://r.jina.ai/"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"
TAVILY_URL = "https://api.tavily.com/extract"
KEENABLE_URL = "https://api.keenable.ai/v1/fetch"

# A0: hard total time per request in seconds (httpx timeouts only bound single phases). The chain passes less when
# the time budget of the URL (Z1) has less left.
BRIGHTDATA_DEADLINE = 90.0
JINA_DEADLINE = 35.0
FIRECRAWL_DEADLINE = 40.0
TAVILY_DEADLINE = 30.0
KEENABLE_DEADLINE = 25.0
ERROR_MAX = 200  # A4
KEY_MIN = 8  # S3: a shorter value is not masked as a key
FIRECRAWL_PDF_MAX_PAGES = 30  # Firecrawl bills one credit per PDF page
SERVER_MARGIN = 5.0  # seconds a provider gets less than the request, so that it answers before the deadline

# D7: Firecrawl accepts cached copies of at most one hour.
FIRECRAWL_BODY = {
    "formats": ["markdown"],
    "onlyMainContent": True,
    "maxAge": 3_600_000,
    "parsers": [{"type": "pdf", "maxPages": FIRECRAWL_PDF_MAX_PAGES}],
}
# A6: as measured in the benchmark of 2026-10-18 (format json carries the status of the target page).
BRIGHTDATA_BODY = {"format": "json", "data_format": "markdown"}
TAVILY_BODY = {"extract_depth": "advanced", "format": "markdown"}
TAVILY_TIMEOUT_MAX = 30  # Tavily accepts 1-60 s; 30 s is its default for "advanced"
# K7: replies of the provider's API that mean a used-up quota or a blocked account.
QUOTA_STATUS = frozenset({402})
TAVILY_QUOTA_STATUS = frozenset({402, 432, 433})  # 432: plan limit, 433: pay-as-you-go limit
BRIGHTDATA_QUOTA_CODES = frozenset({"client_10020", "client_10100", "client_10002"})  # account, zone limit, zone

_JINA_HEAD_END = "Markdown Content:"
_JINA_HEAD_MAX = 4000  # the header block is short; nothing after this is read as a header
_JINA_WARNING = re.compile(r"^Warning: Target URL returned error (\d{3})", re.MULTILINE)
_JINA_TITLE = re.compile(r"^Title: ?(.*)$", re.MULTILINE)
_CODE = re.compile(r"[a-z0-9_]{1,40}")


def _redact(detail: object, key: str) -> str:
    """A reply that echoes the key must not carry it into the result or the log (S3); one line (V1)."""
    text = str(detail)
    forms = {key, quote(key, safe="", errors="surrogatepass")} if len(key) >= KEY_MIN else ()
    for form in forms:  # as sent and percent-encoded, in any case
        text = re.sub(re.escape(form), "[key]", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _error(provider: str, detail: object, code: str, key: str = "", **extra: Any) -> dict:
    """extra: target_status (int) or quota (True)."""
    text = _redact(detail, key)[:ERROR_MAX]
    text = " ".join("".join(c if c.isprintable() else " " for c in text).split())  # A4: no control characters
    return {"error": f"{provider}: {text}", "code": code, **extra}


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


def _detail(response: httpx.Response) -> str:
    """The provider's own reason in a JSON error body, else the response text."""
    body = _json(response)
    for field in ("message", "error", "detail"):
        value = body.get(field)
        if isinstance(value, dict):
            value = value.get("message") or value.get("error")
        if value:
            return str(value)
    return response.text.strip()


async def _request(client: httpx.AsyncClient, deadline: float, method: str, url: str, **kw: Any) -> httpx.Response:
    async with asyncio.timeout(deadline):
        return await client.request(method, url, timeout=deadline, **kw)


def _api_error(provider: str, response: httpx.Response, key: str, quota_status: frozenset[int]) -> dict:
    status = response.status_code
    detail = _detail(response) or f"HTTP {status}"
    extra = {"quota": True} if status in quota_status else {}
    return _error(provider, f"API {status}: {detail}", f"api_{status}", key, **extra)


def _target(provider: str, status: int) -> dict:
    """A failing target page: the page text is dropped, the status is kept for N6 (404/410)."""
    return _error(provider, f"target HTTP {status}", f"target_{status}", target_status=status)


async def brightdata(client: httpx.AsyncClient, url: str, key: str, zone: str, *, deadline: float) -> dict:
    """N11: Web Unlocker. Unlocker errors arrive with HTTP 200 and x-brd-error in the headers (outside or, with
    format json, inside the JSON field headers); otherwise status_code is the status of the target page."""
    try:
        response = await _request(
            client,
            deadline,
            "POST",
            BRIGHTDATA_URL,
            json={"zone": zone, "url": url, **BRIGHTDATA_BODY},
            headers={"Authorization": f"Bearer {key}"},
        )
        if response.status_code >= 300:
            return _api_error("Bright Data", response, key, QUOTA_STATUS)
        data = _json(response)
        inner = data.get("headers") if isinstance(data.get("headers"), dict) else {}
        headers = {k.lower(): str(v) for k, v in [*response.headers.items(), *inner.items()]}
        if "x-brd-error" in headers or "x-brd-error-code" in headers:
            code = headers.get("x-brd-error-code", "").lower()
            code = code if _CODE.fullmatch(code) else "unlocker"
            detail = f"{code} {headers.get('x-brd-error', '')}".strip()
            extra = {"quota": True} if code in BRIGHTDATA_QUOTA_CODES else {}
            return _error("Bright Data", detail, f"brd_{code}", key, **extra)
        if not data:
            return _error("Bright Data", "malformed reply", "malformed")
        status = data.get("status_code")
        if isinstance(status, int) and status >= 400:
            return _target("Bright Data", status)
        body = data.get("body")
        return {"title": "", "content": body if isinstance(body, str) else "", "final_url": None}
    except Exception as exc:
        return _error("Bright Data", _describe(exc), _describe(exc))


def _jina_head(text: str) -> str:
    end = text.find(_JINA_HEAD_END, 0, _JINA_HEAD_MAX)
    return text[:end] if end >= 0 else ""


async def jina(client: httpx.AsyncClient, url: str, key: str, *, deadline: float) -> dict:
    """N12: Reader. The text keeps the header lines (as measured); only the header block before "Markdown
    Content:" is read: Title, and a Warning about an error status of the target page. URL Source is the requested
    URL, not a final URL."""
    headers = {"X-Return-Format": "markdown", "Accept": "text/plain"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = await _request(client, deadline, "GET", JINA_URL + url, headers=headers)
        if response.status_code >= 300:
            return _api_error("Jina", response, key, QUOTA_STATUS)
        text = response.text
        head = _jina_head(text)
        if warning := _JINA_WARNING.search(head):
            status = int(warning.group(1))
            if status >= 400:
                return _target("Jina", status)
        title = _JINA_TITLE.search(head)
        return {"title": title.group(1).strip() if title else "", "content": text, "final_url": None}
    except Exception as exc:
        return _error("Jina", _describe(exc), _describe(exc))


async def firecrawl(client: httpx.AsyncClient, url: str, key: str, *, deadline: float) -> dict:
    """A2: scrape one URL; a non-2xx status of the target page counts as an error (D9)."""
    timeout_ms = int(max(1.0, deadline - SERVER_MARGIN) * 1000)
    try:
        response = await _request(
            client,
            deadline,
            "POST",
            FIRECRAWL_URL,
            json={"url": url, **FIRECRAWL_BODY, "timeout": timeout_ms},
            headers={"Authorization": f"Bearer {key}"},
        )
        payload = _json(response)
        if response.status_code >= 300 or not payload.get("success"):
            detail = payload.get("error") or response.text
            extra = {"quota": True} if response.status_code in QUOTA_STATUS else {}
            return _error("Firecrawl", f"API {response.status_code}: {detail}", f"api_{response.status_code}", key,
                          **extra)  # fmt: skip
        data = payload.get("data") or {}  # no data at all: an empty page (E2)
        meta = (data.get("metadata") or {}) if isinstance(data, dict) else None
        if not isinstance(meta, dict):  # data or metadata that is no object cannot be read
            return _error("Firecrawl", "malformed reply", "malformed")
        status = meta.get("statusCode")
        if isinstance(status, int) and not (200 <= status < 300 or status == 304):
            return _target("Firecrawl", status)
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


async def tavily(client: httpx.AsyncClient, url: str, key: str, *, deadline: float) -> dict:
    """N13: Extract, one URL. results[0].url is the source URL, not a final URL."""
    timeout = max(1, min(TAVILY_TIMEOUT_MAX, int(deadline - SERVER_MARGIN)))
    try:
        response = await _request(
            client,
            deadline,
            "POST",
            TAVILY_URL,
            json={"urls": [url], **TAVILY_BODY, "timeout": timeout},
            headers={"Authorization": f"Bearer {key}"},
        )
        if response.status_code >= 300:
            return _api_error("Tavily", response, key, TAVILY_QUOTA_STATUS)
        data = _json(response)
        if not data:
            return _error("Tavily", "malformed reply", "malformed")
        failed = data.get("failed_results")
        if isinstance(failed, list) and failed:
            item = failed[0]
            detail = item.get("error") if isinstance(item, dict) else item
            return _error("Tavily", detail or "failed", "failed", key)
        results = data.get("results")
        item = results[0] if isinstance(results, list) and results else None
        if not isinstance(item, dict):
            return _error("Tavily", "no result", "no_result")
        return {"title": "", "content": str(item.get("raw_content") or ""), "final_url": None}
    except Exception as exc:
        return _error("Tavily", _describe(exc), _describe(exc))


async def keenable(client: httpx.AsyncClient, url: str, key: str, *, deadline: float = KEENABLE_DEADLINE) -> dict:
    """A3: indexed copy of one URL (no ``live`` fetch)."""
    try:
        response = await _request(
            client,
            deadline,
            "GET",
            KEENABLE_URL,
            params={"url": url},
            headers={"Authorization": f"Bearer {key}", "X-Keenable-Title": "hermes-extract-chain"},
        )
        if response.status_code >= 300:
            status = response.status_code
            detail = _detail(response) or f"HTTP {status}"
            extra = {"quota": True} if status in QUOTA_STATUS else {}
            return _error("Keenable", detail, f"http_{status}", key, **extra)
        data = _json(response)
        if not data:
            return _error("Keenable", "malformed reply", "malformed")
        return {
            "title": str(data.get("title") or ""),
            "content": str(data.get("content") or ""),
            "final_url": data.get("url"),
        }
    except Exception as exc:
        return _error("Keenable", _describe(exc), _describe(exc))
