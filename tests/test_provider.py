import asyncio
import json
import logging
from pathlib import Path

import httpx
import yaml

import extract_chain
from extract_chain import provider
from extract_chain.chain import NOTE_FIRECRAWL
from extract_chain.provider import ExtractChainProvider

ARTICLE = "Ein ganz normaler Artikeltext mit mehreren Sätzen. " * 20


def firecrawl_ok(request):
    return httpx.Response(200, json={"success": True, "data": {"markdown": ARTICLE, "metadata": {"statusCode": 200}}})


class Api:
    """MockTransport handler for all three services; records requests."""

    def __init__(self, tinyfish=None, firecrawl=firecrawl_ok, keenable=None):
        self.handlers = {"api.fetch.tinyfish.ai": tinyfish, "api.firecrawl.dev": firecrawl, "api.keenable.ai": keenable}
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        result = self.handlers[request.url.host](request)
        return await result if asyncio.iscoroutine(result) else result

    def hosts(self):
        return [r.url.host for r in self.requests]


def tinyfish_echo(request):
    urls = json.loads(request.content)["urls"]
    return httpx.Response(200, json={"results": [{"url": u, "title": u, "text": ARTICLE} for u in urls]})


def tinyfish_blocked(request):
    urls = json.loads(request.content)["urls"]
    return httpx.Response(200, json={"results": [], "errors": [{"url": u, "error": "bot_blocked"} for u in urls]})


def extract(api, urls, **kwargs):
    return asyncio.run(ExtractChainProvider(httpx.MockTransport(api)).extract(urls, **kwargs))


# --- S1, S2 ---------------------------------------------------------------------------------------


def test_manifest_and_register():
    manifest = yaml.safe_load((Path(extract_chain.__file__).parent / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "extract-chain" and manifest["kind"] == "backend"
    assert manifest["provides_web_providers"] == ["extract-chain"]
    assert [e["name"] for e in manifest["requires_env"]] == [
        "TINYFISH_API_KEY",
        "FIRECRAWL_API_KEY",
        "KEENABLE_API_KEY",
    ]
    assert all(e["secret"] for e in manifest["requires_env"])

    registered = []

    class Ctx:
        def register_web_search_provider(self, provider):
            registered.append(provider)

    extract_chain.register(Ctx())
    assert len(registered) == 1 and registered[0].name == "extract-chain"


def test_capabilities_and_availability(env):
    provider = ExtractChainProvider()
    assert (provider.supports_search(), provider.supports_extract()) == (False, True)
    assert provider.is_available()
    env["TINYFISH_API_KEY"] = ""
    assert not provider.is_available()
    env["TINYFISH_API_KEY"] = RuntimeError("UnscopedSecretError")
    assert not provider.is_available()


# --- S4, S5, K1, K6 -------------------------------------------------------------------------------


def test_order_duplicates_and_single_batch(env):
    api = Api(tinyfish=tinyfish_echo)
    urls = ["https://a.example/", "https://b.example/", "https://a.example/"]
    out = extract(api, urls, format="html", unknown=1)
    assert [r["url"] for r in out] == urls
    assert [r["title"] for r in out] == urls
    assert all(r["error"] is None and r["metadata"] == {"sourceURL": r["url"]} for r in out)
    assert api.hosts() == ["api.fetch.tinyfish.ai"]
    assert json.loads(api.requests[0].content)["urls"] == ["https://a.example/", "https://b.example/"]


def test_empty_list(env):
    assert extract(Api(), []) == []


def test_fallback_runs_concurrently(env):
    started, both = [], asyncio.Event()

    async def firecrawl_barrier(request):
        started.append(request)
        if len(started) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 2)  # times out if the URLs ran one after another
        return firecrawl_ok(request)

    api = Api(tinyfish=tinyfish_blocked, firecrawl=firecrawl_barrier)
    out = extract(api, ["https://a.example/", "https://b.example/"])
    assert all(r["content"].startswith(NOTE_FIRECRAWL.format(reason="TinyFish: bot_blocked")) for r in out)


def test_missing_tinyfish_key_goes_to_firecrawl(env):
    env["TINYFISH_API_KEY"] = ""
    api = Api()
    out = extract(api, ["https://a.example/"])
    assert api.hosts() == ["api.firecrawl.dev"]
    assert out[0]["content"].startswith(NOTE_FIRECRAWL.format(reason="TinyFish: no API key"))


# --- S3, S6 ---------------------------------------------------------------------------------------


def test_keys_never_leak(env, caplog):
    caplog.set_level(logging.DEBUG)

    def fail(request):
        return httpx.Response(401, text="invalid key")

    out = extract(Api(tinyfish=fail, firecrawl=fail, keenable=fail), ["https://a.example/"])
    assert out[0]["error"].startswith("TinyFish: HTTP 401; Firecrawl: API 401")
    dump = json.dumps(out) + caplog.text
    assert not any(secret in dump for secret in env.values())


def test_transport_failures_become_errors(env):
    def down(request):
        raise httpx.ConnectError("down")

    out = extract(Api(tinyfish=down, firecrawl=down, keenable=down), ["https://a.example/"])
    assert out[0]["error"] == "TinyFish: ConnectError; Firecrawl: ConnectError; Keenable: ConnectError"


# --- S7 website policy, S8 interrupt, L1 codes ----------------------------------------------------


def block_host(host):
    def check(url):
        if host in url:
            return {"host": host, "rule": host, "source": "config", "message": f"Blocked by website policy: {host}"}
        return None

    return check


def test_policy_blocks_before_any_request(env, monkeypatch):
    monkeypatch.setattr(provider, "check_website_access", block_host("b.example"))
    api = Api(tinyfish=tinyfish_echo)
    out = extract(api, ["https://a.example/", "https://b.example/"])
    assert out[1]["error"] == "Blocked by website policy: b.example"
    assert out[1]["blocked_by_policy"] == {"host": "b.example", "rule": "b.example", "source": "config"}
    assert json.loads(api.requests[0].content)["urls"] == ["https://a.example/"]


def test_policy_checked_on_redirect_target(env, monkeypatch):
    monkeypatch.setattr(provider, "check_website_access", block_host("evil.example"))

    def redirected(request):
        return httpx.Response(
            200,
            json={"results": [{"url": "https://a.example/", "final_url": "https://evil.example/x", "text": ARTICLE}]},
        )

    out = extract(Api(tinyfish=redirected), ["https://a.example/"])
    assert out[0]["url"] == "https://a.example/" and out[0]["content"] == ""
    assert out[0]["blocked_by_policy"]["host"] == "evil.example"


def test_interrupt_stops_before_requests(env, monkeypatch):
    monkeypatch.setattr(provider, "is_interrupted", lambda: True)
    api = Api()
    out = extract(api, ["https://a.example/"])
    assert out[0]["error"] == "Interrupted" and api.requests == []


def test_interrupt_between_stages(env, monkeypatch):
    calls = []

    def tinyfish_then_interrupt(request):
        monkeypatch.setattr(provider, "is_interrupted", lambda: True)
        calls.append(request)
        return tinyfish_blocked(request)

    api = Api(tinyfish=tinyfish_then_interrupt)
    out = extract(api, ["https://a.example/"])
    assert api.hosts() == ["api.fetch.tinyfish.ai"]
    assert out[0]["error"] == "TinyFish: bot_blocked; Firecrawl: interrupted; Keenable: interrupted"


def test_log_line_shows_error_codes(env, caplog):
    caplog.set_level(logging.INFO, logger="extract_chain.chain")

    def fail(request):
        return httpx.Response(402 if request.url.host == "api.firecrawl.dev" else 401, json={"error": "no"})

    extract(Api(tinyfish=fail, firecrawl=fail, keenable=fail), ["https://a.example/"])
    assert (
        caplog.records[-1].getMessage()
        == "extract-chain a.example: tinyfish=http_401 firecrawl=api_402 keenable=http_401"
    )


def test_policy_check_error_fails_open(env, monkeypatch):
    def broken(url):
        raise ValueError("Invalid IPv6 URL")

    monkeypatch.setattr(provider, "check_website_access", broken)
    out = extract(Api(tinyfish=tinyfish_echo), ["https://a.example/"])
    assert out[0]["error"] is None and out[0]["content"] == ARTICLE


def test_unexpected_failure_becomes_error_entries(env, monkeypatch):
    def broken_client(*args, **kwargs):
        raise ValueError("Unknown scheme for proxy URL")

    monkeypatch.setattr(provider.httpx, "AsyncClient", broken_client)
    out = extract(Api(), ["https://a.example/", "https://b.example/"])
    assert [r["error"] for r in out] == ["extract-chain: ValueError"] * 2
