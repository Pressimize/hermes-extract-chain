"""Hermes plugin: web_extract fallback chain TinyFish -> Firecrawl -> Keenable."""


def register(ctx) -> None:
    # Imported here so chain.py and fetchers.py stay usable without Hermes (tests, scripts/replay.py).
    from .provider import ExtractChainProvider

    ctx.register_web_search_provider(ExtractChainProvider())
