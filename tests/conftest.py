"""Stand-ins for the Hermes modules the plugin needs, so it imports and runs without Hermes installed."""

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

# Hermes' website policy with nothing blocked; tests replace provider.check_website_access (S7).
_policy = types.ModuleType("tools.website_policy")
_policy.check_website_access = lambda url: None
sys.modules.setdefault("tools", types.ModuleType("tools"))
sys.modules["tools.website_policy"] = _policy

KEYS = {"TINYFISH_API_KEY": "tf-SECRET", "FIRECRAWL_API_KEY": "fc-SECRET", "KEENABLE_API_KEY": "ke-SECRET"}


@pytest.fixture
def env():
    """All three keys set; tests may delete or replace entries."""
    ENV.clear()
    ENV.update(KEYS)
    yield ENV
    ENV.clear()
