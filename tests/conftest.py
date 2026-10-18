"""Stand-ins for the Hermes modules the plugin needs, so it imports and runs without Hermes installed."""

import sys
import types

import pytest

ENV: dict[str, str] = {}
WEB: dict[str, object] = {}


class WebSearchProvider:
    """Minimal stand-in for the Hermes base class (only what the plugin relies on)."""


def get_provider_env(name: str) -> str:
    value = ENV.get(name, "")
    if isinstance(value, Exception):
        raise value
    return value


def _load_web_config() -> dict:
    """Hermes' web section of config.yaml (N9); a test sets WEB["config"] to a dict or to an exception."""
    config = WEB["config"]
    if isinstance(config, Exception):
        raise config
    return config


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

_web = types.ModuleType("tools.web_tools")
_web._load_web_config = _load_web_config
sys.modules["tools.web_tools"] = _web

KEYS = {
    "BRIGHTDATA_API_KEY": "bd-SECRET",
    "BRIGHTDATA_UNLOCKER_ZONE": "unlocker1",
    "JINA_API_KEY": "jn-SECRET",
    "FIRECRAWL_API_KEY": "fc-SECRET",
    "TAVILY_API_KEY": "tv-SECRET",
    "KEENABLE_API_KEY": "ke-SECRET",
}


@pytest.fixture
def env():
    """All keys and the Bright Data zone set; tests may delete or replace entries."""
    ENV.clear()
    ENV.update(KEYS)
    yield ENV
    ENV.clear()


@pytest.fixture(autouse=True)
def web_config():
    """web.extract_timeout 180 (I2), i.e. 170 s per URL; tests may set WEB["config"]."""
    WEB["config"] = {"extract_timeout": 180}
    yield WEB
    WEB["config"] = {"extract_timeout": 180}
