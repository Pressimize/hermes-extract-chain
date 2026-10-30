"""REST calls to Bright Data Web Unlocker, Jina Reader, Firecrawl scrape v2, Tavily Extract and Keenable fetch
(design section 8).

Every function fetches one URL, takes the time it may use (``deadline``, seconds) and never raises. A result is
``{"title", "content", "final_url"}`` plus optional ``target_status`` (int, status of the target page) and
``pdf_pages``, and for Jina ``links`` (the page's link list, V16a) and ``text_at`` (where the page text starts after
the title line, E2). A failure is
``{"error": "<Provider>: <detail>", "code": "<short code>"}``; the code appears in the log line (L1).
``target_status`` is set on failures of the target page, ``quota: True`` when the provider's own API
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
_BRD_ERROR_HEADERS = ("x-brd-error", "x-brd-error-code", "x-brd-err-code")

# A7, D40: text with the page's link list, as measured on 2026-10-26.
JINA_HEADERS = {"Accept": "application/json", "X-Return-Format": "text", "X-With-Links-Summary": "all"}
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


def is_pdf(text: str) -> bool:
    """A1, D39: Bright Data passes a PDF on as the raw file; its bytes are no page text."""
    return text.lstrip().startswith("%PDF-")


def _brd_error(headers: dict[str, str], key: str, quota: bool = False) -> dict | None:
    """A1: Bright Data's error headers (names in lower case) as an error, or None without them. quota: the outer
    status already means a used-up quota (K7)."""
    if not any(headers.get(h, "").strip() for h in _BRD_ERROR_HEADERS):
        return None
    # x-brd-error-code: Unlocker code; x-brd-err-code: code passed on from the proxy network (client_...)
    codes = [headers.get(h, "").lower() for h in ("x-brd-error-code", "x-brd-err-code")]
    code = next((c for c in codes if _CODE.fullmatch(_redact(c, key))), "unlocker")  # S3: a code is no key
    text = headers.get("x-brd-error") or headers.get("x-brd-err-msg") or ""
    extra = {"quota": True} if quota or BRIGHTDATA_QUOTA_CODES & set(codes) else {}
    return _error("Bright Data", f"{code} {text}".strip(), f"brd_{code}", key, **extra)


def _target(provider: str, status: int) -> dict:
    """A failing target page: the page text is dropped, the status is kept in target_status."""
    return _error(provider, f"target HTTP {status}", f"target_{status}", target_status=status)


async def brightdata(client: httpx.AsyncClient, url: str, key: str, zone: str, *, deadline: float) -> dict:
    """N11, A1: Web Unlocker. Unlocker errors arrive with HTTP 200 and x-brd-error in the headers (outside or, with
    format json and an empty body, inside the JSON field headers; D38); otherwise status_code is the status of the
    target page."""
    try:
        response = await _request(
            client,
            deadline,
            "POST",
            BRIGHTDATA_URL,
            json={"zone": zone, "url": url, **BRIGHTDATA_BODY},
            headers={"Authorization": f"Bearer {key}"},
        )
        outer = {k.lower(): str(v) for k, v in response.headers.items()}
        if response.status_code >= 300:
            quota = response.status_code in QUOTA_STATUS
            return _brd_error(outer, key, quota) or _api_error("Bright Data", response, key, QUOTA_STATUS)
        data = _json(response)
        body = data.get("body")
        inner = data.get("headers") if isinstance(data.get("headers"), dict) else {}
        if isinstance(body, str) and body.strip():  # D38: the target page's own headers are passed on as well
            inner = {}
        inner = {k.lower(): str(v) for k, v in inner.items() if v is not None}  # JSON null is no header value
        if failed := _brd_error({**outer, **inner}, key):
            return failed
        if not data:
            return _error("Bright Data", "malformed reply", "malformed")
        status = data.get("status_code")
        if isinstance(status, str) and status.isdigit():  # documented as int; a string is read as well
            status = int(status)
        if isinstance(status, int) and status >= 400:
            return _target("Bright Data", status)
        if isinstance(body, str) and is_pdf(body):
            return _error("Bright Data", "PDF file, not text", "pdf")
        return {"title": "", "content": body if isinstance(body, str) else "", "final_url": None}
    except Exception as exc:
        return _error("Bright Data", _describe(exc), _describe(exc))


def _pairs(links: object) -> list[tuple[str, str]]:
    """A7: Jina's link list as (text, url) pairs; a list of pairs or an object from text to URL (older form)."""
    items = links.items() if isinstance(links, dict) else links if isinstance(links, list) else ()
    return [
        (item[0], item[1])
        for item in items
        if isinstance(item, list | tuple) and len(item) == 2 and all(isinstance(v, str) for v in item)
    ]


def jina_doc(payload: dict) -> dict:
    """A7: the fetcher's result from Jina's JSON reply (also used by the replay). A title goes in front of the text
    as "Title: <title>" and a blank line, so that markers in the title still count (D37); text_at is where the page
    text starts (E2). data.url is the requested URL, not a final URL."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return _error("Jina", "malformed reply", "malformed")
    status = data.get("httpStatus")
    if isinstance(status, int) and not isinstance(status, bool) and status >= 400:
        return _target("Jina", status)
    text = data.get("text")
    if text is None:
        text = ""
    if not isinstance(text, str):
        return _error("Jina", "malformed reply", "malformed")
    title = " ".join(data["title"].split()) if isinstance(data.get("title"), str) else ""
    doc = {"title": title, "content": text, "final_url": None, "links": _pairs(data.get("links"))}
    if title:
        head = f"Title: {title}\n\n"
        doc["content"] = head + text
        doc["text_at"] = len(head)
    return doc


async def jina(client: httpx.AsyncClient, url: str, key: str, *, deadline: float) -> dict:
    """N12, A7: Reader as JSON with text and the page's link list (D40)."""
    headers = dict(JINA_HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = await _request(client, deadline, "GET", JINA_URL + url, headers=headers)
        if response.status_code >= 300:
            return _api_error("Jina", response, key, QUOTA_STATUS)
        return jina_doc(_json(response))
    except Exception as exc:
        return _error("Jina", _describe(exc), _describe(exc))


async def firecrawl(client: httpx.AsyncClient, url: str, key: str, *, deadline: float) -> dict:
    """A2: scrape one URL; a status of the target page outside 2xx, except 304, counts as an error (D9)."""
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
            headers={"Authorization": f"Bearer {key}", "X-Keenable-Title": "hermes-sift"},
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
