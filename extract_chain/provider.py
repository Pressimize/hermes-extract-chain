"""Hermes web extract provider for the fallback chain (design section 4)."""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

import httpx
from agent.web_search_provider import WebSearchProvider, get_provider_env

from . import fetchers
from .chain import run_chain

NAME = "extract-chain"
KEYS = ("TINYFISH_API_KEY", "FIRECRAWL_API_KEY", "KEENABLE_API_KEY")
log = logging.getLogger(__name__)

# S7: Hermes applies its website blocklist inside each provider, not centrally, so the plugin calls it itself.
try:
    from tools.website_policy import check_website_access
except ImportError:  # outside Hermes (tests) or after an incompatible Hermes change; warned in extract()
    check_website_access = None
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


def _failed(url: str, error: str) -> dict:
    return {"url": url, "title": "", "content": "", "error": error, "metadata": {"sourceURL": url}}


def _blocked(url: str, entry_url: str | None = None) -> dict | None:
    """Hermes' error entry if the website policy blocks ``url``, else None. Fails open, as Hermes does."""
    if check_website_access is None:
        return None
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
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests only; Hermes instantiates without arguments
        self._warned_policy = False

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
        if check_website_access is None and not self._warned_policy:
            log.warning("extract-chain: tools.website_policy not importable; website blocklist not applied")
            self._warned_policy = True
        unique = list(dict.fromkeys(urls))
        done = {url: entry for url in unique if (entry := _blocked(url))}
        todo = [url for url in unique if url not in done]
        if todo and is_interrupted():
            done.update({url: _failed(url, "Interrupted") for url in todo})
        elif todo:
            try:
                done.update(await self._chain(todo))
            except Exception as exc:  # S6: e.g. httpx.AsyncClient rejecting a malformed proxy variable
                log.warning("extract-chain: call failed: %s", type(exc).__name__)
                done.update({url: _failed(url, f"extract-chain: {type(exc).__name__}") for url in todo})
        return [dict(done[url]) for url in urls]

    async def _chain(self, urls: list[str]) -> dict[str, dict]:
        tf_key, fc_key, ke_key = (_env(k) for k in KEYS)
        async with httpx.AsyncClient(transport=self._transport) as client:
            if tf_key:
                first = await fetchers.tinyfish(client, urls, tf_key)
            else:
                first = {url: {"error": "TinyFish: no API key", "code": "no_key"} for url in urls}
            done = await asyncio.gather(
                *(
                    run_chain(
                        url,
                        first[url],
                        _stage("Firecrawl", partial(fetchers.firecrawl, client, url, fc_key), fc_key),
                        _stage("Keenable", partial(fetchers.keenable, client, url, ke_key), ke_key),
                    )
                    for url in urls
                )
            )
        results = {}
        for url, result in zip(urls, done, strict=True):
            final = result["metadata"].get("finalURL")  # S7: a redirect may end on a blocked site
            results[url] = (final and final != url and _blocked(final, entry_url=url)) or result
        return results


def _stage(provider: str, fetch, key: str):
    """Stage call for run_chain, or None without a key (K3, K4). Stops before the request on interrupt (S8)."""
    if not key:
        return None

    async def run() -> dict:
        if is_interrupted():
            return {"error": f"{provider}: interrupted", "code": "interrupted"}
        return await fetch()

    return run
