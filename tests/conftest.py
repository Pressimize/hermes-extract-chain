"""Stand-in for Hermes' ``agent.web_search_provider`` so the plugin imports without Hermes installed."""

import sys
import types

import pytest

ENV: dict[str, str] = {}


class WebSearchProvider:
    """Minimal stand-in for the Hermes base class (only what the plugin relies on)."""


def get_provider_env(name: str) -> str:
    value = ENV.get(name, "")
    if isinstance(value, Exception):
        raise value
    return value


_module = types.ModuleType("agent.web_search_provider")
_module.WebSearchProvider = WebSearchProvider
_module.get_provider_env = get_provider_env
sys.modules.setdefault("agent", types.ModuleType("agent"))
sys.modules["agent.web_search_provider"] = _module

KEYS = {"TINYFISH_API_KEY": "tf-SECRET", "FIRECRAWL_API_KEY": "fc-SECRET", "KEENABLE_API_KEY": "ke-SECRET"}


@pytest.fixture
def env():
    """All three keys set; tests may delete or replace entries."""
    ENV.clear()
    ENV.update(KEYS)
    yield ENV
    ENV.clear()
