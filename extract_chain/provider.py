"""Hermes web extract provider for the fallback chain (design section 4)."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import logging
import math
import time
from collections.abc import Callable
from functools import partial
from typing import Any

import httpx
from agent.web_search_provider import WebSearchProvider, get_provider_env

from . import fetchers
from .chain import MIN_STAGE, URL_BUDGET_MAX, Fetch, Stage, failure, run_chain

NAME = "extract-chain"
# N2, D-1 (Andre 2026-10-18): Jina first (benchmark set 3: 170 against 160 complete with Bright Data first; several
# agents share one Jina rate limit, Bright Data then catches its 429s); Tavily only on request (no effect measured).
DEFAULT_ORDER = ("jina", "brightdata", "firecrawl", "keenable")
ORDER_ENV = "EXTRACT_CHAIN_ORDER"
NAMES = {
    "brightdata": "Bright Data",
    "jina": "Jina",
    "firecrawl": "Firecrawl",
    "tavily": "Tavily",
    "keenable": "Keenable",
}
KEYS = {
    "brightdata": "BRIGHTDATA_API_KEY",
    "jina": "JINA_API_KEY",  # optional: Jina runs without a key (N3)
    "firecrawl": "FIRECRAWL_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "keenable": "KEENABLE_API_KEY",
}
ZONE_ENV = "BRIGHTDATA_UNLOCKER_ZONE"
DAY = 86400  # K7: a used-up quota pauses a stage for 24 hours
BUDGET_MARGIN = 10.0  # N9: the URL budget stays this far below web.extract_timeout
BUDGET_FALLBACK = 110.0  # N9: Hermes' default of 120 s minus the margin, when the setting cannot be read
TIMEOUT_LOW = 180.0  # Z1, L3: below this, a warning once per process (I2 recommends 180 s)
log = logging.getLogger(__name__)

# S7: Hermes applies its website blocklist inside each provider, not centrally, so the plugin calls it itself.
try:
    from tools.website_policy import check_website_access
except ImportError:  # an incompatible Hermes version: extract() then refuses every URL
    check_website_access = None
# Hermes' keyless rescue leaves entries alone whose error contains "blocked by website policy".
NO_POLICY = (
    "Blocked by website policy: extract-chain cannot load Hermes' website blocklist and fetches nothing without it "
    "(the plugin does not match this Hermes version). Update the plugin or set web.extract_backend to another provider."
)
NOT_A_URL = "extract-chain: not a URL"  # S6: an entry of urls that is no string
# S8: same convention as Hermes' built-in providers for /stop and new user messages.
try:
    from tools.interrupt import is_interrupted
except ImportError:

    def is_interrupted() -> bool:
        return False


_warned: set[str] = set()  # N2, N9: warnings once per process


def _warn_once(topic: str, message: str, *args: object) -> None:
    if topic not in _warned:
        _warned.add(topic)
        log.warning(message, *args)


def _env(name: str) -> str:
    try:
        return get_provider_env(name)
    except Exception:  # S3: e.g. UnscopedSecretError counts as a missing key
        return ""


def stage_order(value: str) -> list[str]:
    """N2: stage ids from EXTRACT_CHAIN_ORDER; unknown names and duplicates are dropped, Keenable goes last."""
    if not value.strip():
        return list(DEFAULT_ORDER)
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    known = [n for n in dict.fromkeys(names) if n in NAMES and n != "keenable"]
    invalid = len(set(names)) != len(names) or any(n not in NAMES for n in names)  # duplicates, Keenable included
    if invalid or not known:
        _warn_once("order", "extract-chain: %s has unknown or repeated names; using %s", ORDER_ENV,
                   ",".join(known + ["keenable"]) if known else ",".join(DEFAULT_ORDER))  # fmt: skip
    return known + ["keenable"] if known else list(DEFAULT_ORDER)


def url_budget() -> float:
    """N9: time per URL, from Hermes' web.extract_timeout (0 or below: no cap in Hermes)."""
    try:
        from tools.web_tools import _load_web_config

        value = float(_load_web_config().get("extract_timeout", 120))
    except Exception:  # an incompatible Hermes version or an unreadable setting
        return BUDGET_FALLBACK
    if value <= 0:
        return URL_BUDGET_MAX
    if value < TIMEOUT_LOW:
        _warn_once("timeout", "extract-chain: web.extract_timeout is %.0f s; 180 s are recommended", value)
    return max(MIN_STAGE, min(URL_BUDGET_MAX, value - BUDGET_MARGIN))


def _slot(provider: str, key: str) -> tuple[str, str]:
    """K7: the pause table is keyed by a digest of the API key (Bright Data: key and zone), so it holds no key."""
    return provider, hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()


def _left(seconds: float) -> str:
    """Remaining pause for the error text: minutes rounded up below one hour, else the nearest hour."""
    return f"{math.floor(seconds / 3600 + 0.5)} h" if seconds >= 3600 else f"{math.ceil(seconds / 60)} min"


def _blocked(url: str, entry_url: str | None = None) -> dict | None:
    """Hermes' error entry if the website policy blocks ``url``, else None. A check that fails blocks (S7)."""
    try:
        blocked = check_website_access(url)
    except Exception as exc:  # e.g. ValueError from urlparse on a final URL that cannot be parsed
        log.warning("extract-chain: website policy check failed for a URL (blocked): %s", type(exc).__name__)
        blocked = {"message": f"Blocked by website policy: the check failed for this URL ({type(exc).__name__})"}
    if not blocked:
        return None
    info = blocked if isinstance(blocked, dict) else {}  # S6: a block of unexpected shape still blocks
    entry_url = entry_url or url
    return {
        "url": entry_url,
        "title": "",
        "content": "",
        "error": str(info.get("message") or "Blocked by website policy"),
        "blocked_by_policy": {k: info.get(k, "") for k in ("host", "rule", "source")},
        "metadata": {"sourceURL": entry_url},
    }


class ExtractChainProvider(WebSearchProvider):
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport  # tests only; Hermes instantiates without arguments
        self._clock = clock  # wall clock for pauses (K7)
        self._monotonic = monotonic  # time budget of a URL (N9)
        self._paused: dict[tuple[str, str], tuple[float, str]] = {}  # K7: _slot(provider, ...) -> (until, reason)

    @property
    def name(self) -> str:
        return NAME

    @property
    def display_name(self) -> str:
        return "Extract chain (Jina, Bright Data, Firecrawl, Keenable)"

    def is_available(self) -> bool:
        """N3: at least one keyed stage of the order can run (Jina alone does not count; Keenable always runs)."""
        order = stage_order(_env(ORDER_ENV))
        bright = "brightdata" in order and bool(_env(KEYS["brightdata"]) and _env(ZONE_ENV))
        return bright or any(s in order and _env(KEYS[s]) for s in ("firecrawl", "tavily", "keenable"))

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def extract(self, urls: list[str], **kwargs: Any) -> list[dict]:
        """One entry per input URL, in input order (S5). kwargs such as ``format`` are ignored (S4)."""
        if check_website_access is None:  # S7: never fetch without the blocklist
            log.warning("extract-chain: tools.website_policy not importable; every URL refused")
            return [failure(u, NO_POLICY if isinstance(u, str) else NOT_A_URL) for u in urls]
        unique = list(dict.fromkeys(url for url in urls if isinstance(url, str)))
        done = {url: entry for url in unique if (entry := _blocked(url))}
        todo = [url for url in unique if url not in done]
        if todo and is_interrupted():
            done.update({url: failure(url, "Interrupted") for url in todo})
        elif todo:
            try:
                done.update(await self._chain(todo))
            except Exception as exc:  # S6: e.g. httpx.AsyncClient rejecting a malformed proxy variable
                log.warning("extract-chain: call failed: %s", type(exc).__name__)
                done.update({url: failure(url, f"extract-chain: {type(exc).__name__}") for url in todo})
        # duplicates get entries of their own (S5); an entry that is no string fails alone (S6)
        return [copy.deepcopy(done[u]) if isinstance(u, str) else failure(u, NOT_A_URL) for u in urls]

    async def _chain(self, urls: list[str]) -> dict[str, dict]:
        keys = {stage: _env(name) for stage, name in KEYS.items()}
        zone = _env(ZONE_ENV)
        order = stage_order(_env(ORDER_ENV))
        budget = url_budget()
        # A5: no redirects, so a key never travels to another host
        async with httpx.AsyncClient(transport=self._transport, follow_redirects=False) as client:
            done = await asyncio.gather(*(self._one(client, url, keys, zone, order, budget) for url in urls))
        results = {}
        for url, result in zip(urls, done, strict=True):
            final = result["metadata"].get("finalURL")
            # S7: a redirect may end on a blocked site; the block entry then replaces the result
            blocked = _blocked(final, entry_url=url) if final and final != url else None
            results[url] = blocked or result
        return results

    async def _one(
        self, client: httpx.AsyncClient, url: str, keys: dict, zone: str, order: list[str], budget: float
    ) -> dict:
        """N5: start Keenable's request, run the other stages, and never leave the Keenable request running."""
        calls = {
            "brightdata": partial(fetchers.brightdata, client, url, keys["brightdata"], zone),
            "jina": partial(fetchers.jina, client, url, keys["jina"]),
            "firecrawl": partial(fetchers.firecrawl, client, url, keys["firecrawl"]),
            "tavily": partial(fetchers.tavily, client, url, keys["tavily"]),
        }
        caps = {
            "brightdata": fetchers.BRIGHTDATA_DEADLINE,
            "jina": fetchers.JINA_DEADLINE,
            "firecrawl": fetchers.FIRECRAWL_DEADLINE,
            "tavily": fetchers.TAVILY_DEADLINE,
        }
        stages = []
        for sid in order:
            if sid == "keenable":
                continue
            needs_key = sid != "jina"
            missing = "no zone" if sid == "brightdata" and keys[sid] and not zone else "no API key"
            runnable = (not needs_key or keys[sid]) and not (sid == "brightdata" and not zone)
            # K7: a Bright Data pause belongs to key and zone, so a corrected zone is used at once
            pause_id = keys[sid] + "\0" + zone if sid == "brightdata" else keys[sid]
            fetch = self._stage(NAMES[sid], calls[sid], pause_id, caps[sid]) if runnable else None
            stages.append(Stage(sid, NAMES[sid], fetch, missing=missing))
        reference = None
        if keys["keenable"]:
            ke = self._stage("Keenable", partial(fetchers.keenable, client, url, keys["keenable"]), keys["keenable"],
                             fetchers.KEENABLE_DEADLINE)  # fmt: skip
            reference = asyncio.ensure_future(_guarded(ke, min(fetchers.KEENABLE_DEADLINE, budget)))
        try:
            return await run_chain(url, stages, reference, budget=budget, clock=self._monotonic,
                                   is_interrupted=lambda: is_interrupted())  # fmt: skip
        finally:
            if reference is not None and not reference.done():
                reference.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await reference

    def _stage(self, provider: str, call: Callable[..., Any], key: str, cap: float) -> Fetch:
        """Stage call for run_chain: no request on interrupt (S8) or pause (K7); the deadline is capped (A0)."""

        async def run(deadline: float) -> dict:
            if is_interrupted():
                return {"error": f"{provider}: interrupted", "code": "interrupted"}
            if paused := self._paused_doc(provider, key):
                return paused
            return self._watch(provider, key, await call(deadline=min(cap, deadline)))

        return run

    def _paused_doc(self, provider: str, key: str) -> dict | None:
        """K7: the error of a stage that is skipped after a used-up quota, or None."""
        until, reason = self._paused.get(_slot(provider, key), (0.0, ""))
        left = until - self._clock()
        if not 0 < left <= DAY:  # more than a day left: the clock was set back, so the pause is dropped
            return None
        return {"error": f"{reason} (paused for another {_left(left)})", "code": "paused"}

    def _watch(self, provider: str, key: str, doc: dict) -> dict:
        """K7, N16: start a pause when the provider's API reports a used-up quota (quota: True). Returns doc."""
        if doc.get("quota") and not self._paused_doc(provider, key):
            self._paused[_slot(provider, key)] = (self._clock() + DAY, doc["error"])
            log.warning("extract-chain: %s paused for %d s (%s)", provider, DAY, doc["code"])  # L2
        return doc


async def _guarded(fetch: Fetch, deadline: float) -> dict:
    """The Keenable request as a task of its own (N5): an unexpected exception fails only this request (S6)."""
    try:
        return await fetch(deadline)
    except Exception as exc:
        return {"error": f"Keenable: {type(exc).__name__}", "code": "exception"}
