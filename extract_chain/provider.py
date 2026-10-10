"""Hermes web extract provider for the fallback chain (design section 4)."""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import time
from collections.abc import Callable
from functools import partial
from typing import Any

import httpx
from agent.web_search_provider import WebSearchProvider, get_provider_env

from . import fetchers
from .chain import Fetch, failure, run_chain

NAME = "extract-chain"
KEYS = ("TINYFISH_API_KEY", "FIRECRAWL_API_KEY", "KEENABLE_API_KEY")
PAUSE_STATUS = 402  # K7: the provider's API says the quota or the credits are used up
DAY = 86400
TINYFISH_RESET_GRACE = 300  # K7: clocks differ, so TinyFish is asked again five minutes after its daily renewal
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
# S8: same convention as Hermes' built-in providers for /stop and new user messages.
try:
    from tools.interrupt import is_interrupted
except ImportError:

    def is_interrupted() -> bool:
        return False


def _env(name: str) -> str:
    try:
        return get_provider_env(name)
    except Exception:  # S3: e.g. UnscopedSecretError counts as a missing key
        return ""


def _pause_seconds(provider: str, now: float) -> float:
    """K7: 24 h; TinyFish only until 00:05 UTC, just after its daily allowance renews."""
    return DAY - (now - TINYFISH_RESET_GRACE) % DAY if provider == "TinyFish" else DAY


def _left(seconds: float) -> str:
    """Remaining pause for the error text, rounded up."""
    return f"{math.ceil(seconds / 3600)} h" if seconds > 3600 else f"{math.ceil(seconds / 60)} min"


def _blocked(url: str, entry_url: str | None = None) -> dict | None:
    """Hermes' error entry if the website policy blocks ``url``, else None. A failing check allows, as in Hermes."""
    try:
        blocked = check_website_access(url)
    except Exception as exc:  # e.g. ValueError from urlparse on a malformed final URL (S6)
        log.warning("extract-chain: website policy check failed for a URL (allowed): %s", type(exc).__name__)
        return None
    if not blocked:
        return None
    entry_url = entry_url or url
    return {
        "url": entry_url,
        "title": "",
        "content": "",
        "error": blocked["message"],
        "blocked_by_policy": {k: blocked[k] for k in ("host", "rule", "source")},
        "metadata": {"sourceURL": entry_url},
    }


class ExtractChainProvider(WebSearchProvider):
    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        self._transport = transport  # tests only; Hermes instantiates without arguments
        self._clock = clock  # wall clock, because TinyFish's pause ends at 00:05 UTC
        self._paused: dict[tuple[str, str], tuple[float, str]] = {}  # K7: (provider, key) -> (until, reason)

    @property
    def name(self) -> str:
        return NAME

    @property
    def display_name(self) -> str:
        return "Extract chain (TinyFish, Firecrawl, Keenable)"

    def is_available(self) -> bool:
        return bool(_env("TINYFISH_API_KEY"))

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def extract(self, urls: list[str], **kwargs: Any) -> list[dict]:
        """One entry per input URL, in input order (S5). kwargs such as ``format`` are ignored (S4)."""
        if check_website_access is None:  # S7: never fetch without the blocklist
            log.warning("extract-chain: tools.website_policy not importable; every URL refused")
            return [failure(url, NO_POLICY) for url in urls]
        unique = list(dict.fromkeys(urls))
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
        return [copy.deepcopy(done[url]) for url in urls]  # duplicates get entries of their own (S5)

    async def _chain(self, urls: list[str]) -> dict[str, dict]:
        tf_key, fc_key, ke_key = (_env(k) for k in KEYS)
        async with httpx.AsyncClient(transport=self._transport) as client:
            if not tf_key:
                first = {url: {"error": "TinyFish: no API key", "code": "no_key"} for url in urls}
            elif paused := self._paused_doc("TinyFish", tf_key):
                first = {url: dict(paused) for url in urls}
            else:
                first = await fetchers.tinyfish(client, urls, tf_key)
                for doc in first.values():
                    self._watch("TinyFish", tf_key, doc)
            done = await asyncio.gather(
                *(
                    run_chain(
                        url,
                        first[url],
                        self._stage("Firecrawl", partial(fetchers.firecrawl, client, url, fc_key), fc_key),
                        self._stage("Keenable", partial(fetchers.keenable, client, url, ke_key), ke_key),
                    )
                    for url in urls
                )
            )
        results = {}
        for url, result in zip(urls, done, strict=True):
            final = result["metadata"].get("finalURL")  # S7: a redirect may end on a blocked site
            results[url] = (final and final != url and _blocked(final, entry_url=url)) or result
        return results

    def _stage(self, provider: str, fetch: Fetch, key: str) -> Fetch | None:
        """Stage call for run_chain, or None without a key (K3, K4). No request on interrupt (S8) or pause (K7)."""
        if not key:
            return None

        async def run() -> dict:
            if is_interrupted():
                return {"error": f"{provider}: interrupted", "code": "interrupted"}
            return self._paused_doc(provider, key) or self._watch(provider, key, await fetch())

        return run

    def _paused_doc(self, provider: str, key: str) -> dict | None:
        """K7: the error of a stage that is skipped after a used-up quota, or None."""
        until, reason = self._paused.get((provider, key), (0.0, ""))
        left = until - self._clock()
        if not 0 < left <= DAY:  # more than a day left: the clock was set back, so the pause is dropped
            return None
        return {"error": f"{reason} (paused for another {_left(left)})", "code": "paused"}

    def _watch(self, provider: str, key: str, doc: dict) -> dict:
        """K7: start a pause when the provider's API reports a used-up quota. Returns doc."""
        if doc.get("status") == PAUSE_STATUS and not self._paused_doc(provider, key):
            now = self._clock()
            seconds = _pause_seconds(provider, now)
            self._paused[(provider, key)] = (now + seconds, doc["error"])
            log.warning("extract-chain: %s paused for %d s (%s)", provider, math.ceil(seconds), doc["code"])  # L2
        return doc
