import asyncio
import json
import logging
import tomllib
from pathlib import Path

import httpx
import pytest
import yaml

import extract_chain
from extract_chain import chain, provider
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
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert manifest["version"] == project["version"]  # the version is kept in both files

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
    # TinyFish named no final_url: the URL of its entry counts (A1)
    assert all(r["error"] is None and r["metadata"] == {"sourceURL": r["url"], "finalURL": r["url"]} for r in out)
    assert out[0] is not out[2] and out[0]["metadata"] is not out[2]["metadata"]  # duplicates share nothing
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


@pytest.mark.parametrize("reply", [{"message": "blocked"}, {"host": "a.example"}, "blocked"])
def test_policy_block_of_unexpected_shape_still_blocks(env, monkeypatch, reply):
    monkeypatch.setattr(provider, "check_website_access", lambda url: reply)  # e.g. a later Hermes version
    api = Api(tinyfish=tinyfish_echo)
    out = extract(api, ["https://a.example/"])
    assert api.requests == [] and out[0]["content"] == ""
    assert out[0]["error"] in ("blocked", "Blocked by website policy")
    assert set(out[0]["blocked_by_policy"]) == {"host", "rule", "source"}


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


@pytest.mark.parametrize("stage", ["firecrawl", "keenable"])
def test_policy_checked_on_final_url_of_later_stages(env, monkeypatch, stage):
    monkeypatch.setattr(provider, "check_website_access", block_host("evil.example"))
    final = "https://evil.example/x"
    page = {"success": True, "data": {"markdown": ARTICLE, "metadata": {"statusCode": 200, "url": final}}}
    api = Api(
        tinyfish=tinyfish_blocked,
        firecrawl=lambda r: httpx.Response(200, json=page) if stage == "firecrawl" else httpx.Response(500),
        keenable=lambda r: httpx.Response(200, json={"url": final, "title": "K", "content": ARTICLE}),
    )
    out = extract(api, ["https://a.example/"])
    assert api.hosts()[-1].split(".")[1] == stage
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


@pytest.mark.parametrize("fails_for", ["a.example", "final.example"])  # the input URL, the final URL
def test_policy_check_error_blocks(env, monkeypatch, fails_for):
    def broken(url):
        if fails_for in url:
            raise ValueError("Invalid IPv6 URL")

    def redirected(request):
        result = {"url": "https://a.example/", "final_url": "https://final.example/x", "text": ARTICLE}
        return httpx.Response(200, json={"results": [result]})

    monkeypatch.setattr(provider, "check_website_access", broken)
    api = Api(tinyfish=redirected)
    out = extract(api, ["https://a.example/"])
    assert out[0]["url"] == "https://a.example/" and out[0]["content"] == ""
    assert out[0]["error"] == "Blocked by website policy: the check failed for this URL (ValueError)"
    assert len(api.requests) == (0 if fails_for == "a.example" else 1)  # an input URL is not even fetched


def test_entries_that_are_no_strings_fail_alone(env):
    api = Api(tinyfish=tinyfish_echo)
    urls = [123, {"x": 1}, "https://a.example/", None]
    out = extract(api, urls)
    assert [r["url"] for r in out] == urls
    assert [r["error"] for r in out] == ["extract-chain: not a URL"] * 2 + [None, "extract-chain: not a URL"]
    assert json.loads(api.requests[0].content)["urls"] == ["https://a.example/"]


def test_redirect_of_a_provider_api_is_not_followed(env):
    def moved(request):
        return httpx.Response(307, headers={"Location": "https://elsewhere.example/"})

    api = Api(tinyfish=moved)
    out = extract(api, ["https://a.example/"])
    assert api.hosts() == ["api.fetch.tinyfish.ai", "api.firecrawl.dev"]  # the key went to no other host (A5)
    assert out[0]["content"].startswith(NOTE_FIRECRAWL.format(reason="TinyFish: HTTP 307"))


def test_missing_policy_module_refuses_every_url(env, monkeypatch, caplog):
    monkeypatch.setattr(provider, "check_website_access", None)  # as after an incompatible Hermes update
    api = Api(tinyfish=tinyfish_echo)
    urls = ["https://a.example/", "https://b.example/", "https://a.example/"]
    out = extract(api, urls)
    assert api.requests == [] and [r["url"] for r in out] == urls
    # Hermes' keyless rescue must leave these entries alone; it recognises them by this phrase
    assert all("blocked by website policy" in r["error"].lower() and r["content"] == "" for r in out)
    assert "extract-chain: tools.website_policy not importable; every URL refused" in caplog.text


def test_unexpected_failure_becomes_error_entries(env, monkeypatch):
    def broken_client(*args, **kwargs):
        raise ValueError("Unknown scheme for proxy URL")

    monkeypatch.setattr(provider.httpx, "AsyncClient", broken_client)
    out = extract(Api(), ["https://a.example/", "https://b.example/"])
    assert [r["error"] for r in out] == ["extract-chain: ValueError"] * 2


def test_unexpected_failure_in_one_chain_spares_the_other_urls(env, monkeypatch, caplog):
    def classify(doc, full_page=False):
        if doc.get("content") == "BOOM":
            raise KeyError("bug")
        return "ok"

    monkeypatch.setattr(chain, "classify", classify)
    urls = ["https://a.example/", "https://b.example/"]
    reply = {"results": [{"url": urls[0], "text": "BOOM"}, {"url": urls[1], "text": ARTICLE}]}
    out = extract(Api(tinyfish=lambda r: httpx.Response(200, json=reply)), urls)
    assert out[0]["error"] == "extract-chain: KeyError" and out[0]["content"] == ""
    assert out[1]["error"] is None and out[1]["content"] == ARTICLE
    assert "extract-chain a.example: chain failed: KeyError" in caplog.text


# --- K7 pauses ------------------------------------------------------------------------------------

URL = "https://a.example/"
NOON = 20_000 * 86400 + 12 * 3600  # 12:00 UTC of some day


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def out_of_credits(request):
    error = f"Insufficient credits for {request.headers['authorization']}"
    return httpx.Response(402, json={"success": False, "error": error})


def keenable_ok(request):
    return httpx.Response(200, json={"url": URL, "title": "K", "content": ARTICLE})


def calls(api, clock):
    """extract() of one provider object, so pauses survive from call to call; returns the hosts asked."""
    chain_provider = ExtractChainProvider(httpx.MockTransport(api), clock=clock)

    def call():
        before = len(api.requests)
        out = asyncio.run(chain_provider.extract([URL]))
        return out[0], [host.split(".")[-2] for host in api.hosts()[before:]]

    return call


def test_pause_after_402_skips_the_stage_for_24_hours(env, caplog):
    caplog.set_level(logging.INFO)
    clock = Clock(NOON)
    call = calls(Api(tinyfish=tinyfish_blocked, firecrawl=out_of_credits, keenable=keenable_ok), clock)

    out, asked = call()
    assert asked == ["tinyfish", "firecrawl", "keenable"]
    reason = "Firecrawl: API 402: Insufficient credits for Bearer [key]"
    assert f"{reason})" in out["content"].split("\n", 1)[0]
    assert "extract-chain: Firecrawl paused for 86400 s (api_402)" in caplog.text  # L2

    clock.now += 3600
    out, asked = call()
    assert asked == ["tinyfish", "keenable"]
    assert f"{reason} (paused for another 23 h))" in out["content"].split("\n", 1)[0]
    assert (
        caplog.records[-1].getMessage() == "extract-chain a.example: tinyfish=bot_blocked firecrawl=paused keenable=ok"
    )
    assert caplog.text.count("paused for 86400 s") == 1  # the running pause is not announced again
    assert "fc-SECRET" not in json.dumps(out) + caplog.text  # S3 holds for the repeated reason too

    clock.now = NOON + 86400
    assert call()[1] == ["tinyfish", "firecrawl", "keenable"]


def tinyfish_allowance_used(request):
    return httpx.Response(402, json={"error": {"code": "INSUFFICIENT_CREDITS"}})


def test_tinyfish_pause_ends_shortly_after_midnight_utc(env, caplog):
    clock = Clock(NOON + 11 * 3600)  # 23:00 UTC
    call = calls(Api(tinyfish=tinyfish_allowance_used), clock)

    out, asked = call()
    assert asked == ["tinyfish", "firecrawl"] and out["content"].endswith(ARTICLE)
    assert "extract-chain: TinyFish paused for 3900 s (http_402)" in caplog.text

    clock.now += 1800
    out, asked = call()
    assert asked == ["firecrawl"]
    assert out["content"].startswith(NOTE_FIRECRAWL.format(reason="TinyFish: HTTP 402 (paused for another 35 min)"))

    clock.now = NOON + 12 * 3600 + 300  # 00:05 UTC: the daily allowance is back
    assert call()[1] == ["tinyfish", "firecrawl"]


def test_tinyfish_402_just_after_midnight_pauses_for_minutes_only(env, caplog):
    clock = Clock(NOON + 12 * 3600 + 2)  # 00:00:02 UTC: TinyFish's renewal may lag behind this clock
    calls(Api(tinyfish=tinyfish_allowance_used), clock)()
    assert "extract-chain: TinyFish paused for 298 s (http_402)" in caplog.text


def test_pause_is_dropped_when_the_clock_was_set_back(env):
    clock = Clock(NOON)
    call = calls(Api(tinyfish=tinyfish_blocked, firecrawl=out_of_credits, keenable=keenable_ok), clock)
    call()
    clock.now -= 3 * 86400  # otherwise the stage would be paused for four days
    assert call()[1] == ["tinyfish", "firecrawl", "keenable"]


def test_several_402_in_one_call_start_one_pause(env, caplog):
    api = Api(tinyfish=tinyfish_blocked, firecrawl=out_of_credits, keenable=keenable_ok)
    urls = [f"https://{name}.example/" for name in "abc"]
    out = asyncio.run(ExtractChainProvider(httpx.MockTransport(api), clock=Clock(NOON)).extract(urls))
    assert [r["error"] for r in out] == [None] * 3
    assert caplog.text.count("Firecrawl paused for") == 1


def test_keenable_pause_and_pause_per_key(env):
    def down(request):
        return httpx.Response(500, json={"success": False})

    call = calls(Api(tinyfish=tinyfish_blocked, firecrawl=down, keenable=lambda r: httpx.Response(402)), Clock(NOON))
    assert call()[1] == ["tinyfish", "firecrawl", "keenable"]
    out, asked = call()
    assert asked == ["tinyfish", "firecrawl"]
    assert out["error"].endswith("Keenable: HTTP 402 (paused for another 24 h)")
    env["KEENABLE_API_KEY"] = "ke-OTHER"  # another key (profile, or a corrected one) is not paused
    assert call()[1] == ["tinyfish", "firecrawl", "keenable"]


TARGET_402 = {"success": True, "data": {"markdown": "", "metadata": {"statusCode": 402}}}


@pytest.mark.parametrize(
    "firecrawl",
    [
        lambda r: httpx.Response(429),  # rate limit
        lambda r: httpx.Response(200, json={"success": False, "error": "402 Payment Required"}),  # no HTTP 402
        lambda r: httpx.Response(200, json=TARGET_402),  # the target page answers 402, not Firecrawl's API
    ],
)
def test_only_a_402_of_the_api_pauses(env, firecrawl):
    call = calls(Api(tinyfish=tinyfish_blocked, firecrawl=firecrawl, keenable=keenable_ok), Clock(NOON))
    assert call()[1] == call()[1] == ["tinyfish", "firecrawl", "keenable"]


def test_tinyfish_error_for_one_url_does_not_pause(env):
    reply = {"errors": [{"url": URL, "error": "http_402"}]}
    call = calls(Api(tinyfish=lambda r: httpx.Response(200, json=reply)), Clock(NOON))
    assert call()[1] == call()[1] == ["tinyfish", "firecrawl"]
