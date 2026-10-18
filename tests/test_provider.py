"""The Hermes provider (S1-S8, N1-N5, N9, N10, N16, K5, K7, L2) with all five services behind one MockTransport."""

import asyncio
import json
import logging
import sys
import time
import tomllib
from pathlib import Path

import httpx
import pytest
import yaml

import extract_chain
from extract_chain import chain, provider
from extract_chain.chain import NOTE_COPY, NOTE_LIVE, NOTE_PAYWALL
from extract_chain.provider import ExtractChainProvider

ARTICLE = "Ein ganz normaler Artikeltext mit mehreren Sätzen. " * 20
PAYWALL_TEXT = ARTICLE + "Das war die Leseprobe."
URL = "https://a.example/"
HOSTS = {
    "api.brightdata.com": "brightdata",
    "r.jina.ai": "jina",
    "api.firecrawl.dev": "firecrawl",
    "api.tavily.com": "tavily",
    "api.keenable.ai": "keenable",
}
NOON = 20_000 * 86400 + 12 * 3600


@pytest.fixture(autouse=True)
def fresh_warnings(monkeypatch):
    """N2, N9: warnings once per process; each test starts as a new process."""
    monkeypatch.setattr(provider, "_warned", set())


def down(request):
    return httpx.Response(500, json={"success": False, "error": "down"})


def bd_ok(content=ARTICLE, status=200, headers=None):
    return lambda r: httpx.Response(200, json={"status_code": status, "headers": headers or {}, "body": content})


def jina_ok(content=ARTICLE):
    return lambda r: httpx.Response(200, text=f"Title: J\nURL Source: {URL}\n\nMarkdown Content:\n{content}")


def fc_ok(content=ARTICLE, **meta):
    page = {"success": True, "data": {"markdown": content, "metadata": {"statusCode": 200, **meta}}}
    return lambda r: httpx.Response(200, json=page)


def tavily_ok(content=ARTICLE):
    return lambda r: httpx.Response(200, json={"results": [{"url": URL, "raw_content": content}]})


def ke_ok(content=ARTICLE, url=URL):
    return lambda r: httpx.Response(200, json={"url": url, "title": "K", "content": content})


class Api:
    """MockTransport handler for the five services (500 unless given); records requests."""

    def __init__(self, **handlers):
        self.handlers = {name: handlers.get(name, down) for name in HOSTS.values()}
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        result = self.handlers[HOSTS[request.url.host]](request)
        return await result if asyncio.iscoroutine(result) else result

    def asked(self, since=0):
        """Stages asked, in order; Keenable runs in parallel, so it is left out (see keenable())."""
        return [HOSTS[r.url.host] for r in self.requests[since:] if HOSTS[r.url.host] != "keenable"]

    def keenable(self, since=0):
        return sum(HOSTS[r.url.host] == "keenable" for r in self.requests[since:])


def extract(api, urls, **kwargs):
    return asyncio.run(ExtractChainProvider(httpx.MockTransport(api)).extract(urls, **kwargs))


def failed(url, error):
    return {"url": url, "title": "", "content": "", "error": error, "metadata": {"sourceURL": url}}


def chain_lines(caplog):
    caplog.set_level(logging.INFO)
    return lambda: [r.getMessage() for r in caplog.records if r.name == "extract_chain.chain"]


# --- S1, N1, N4: manifest, version, display name -------------------------------------------------------


def manifest():
    return yaml.safe_load((Path(extract_chain.__file__).parent / "plugin.yaml").read_text(encoding="utf-8"))


def test_manifest_and_register():  # S1, N4
    m = manifest()
    assert m["name"] == "extract-chain" and m["kind"] == "backend"
    assert m["provides_web_providers"] == ["extract-chain"]
    assert [e["name"] for e in m["requires_env"]] == [
        "BRIGHTDATA_API_KEY",
        "BRIGHTDATA_UNLOCKER_ZONE",
        "FIRECRAWL_API_KEY",
        "TAVILY_API_KEY",
        "KEENABLE_API_KEY",
    ]
    assert [e["name"] for e in m["optional_env"]] == ["JINA_API_KEY", "EXTRACT_CHAIN_ORDER"]
    for entry in m["requires_env"] + m["optional_env"]:  # N4: names on _KEY are secrets, the others not
        assert bool(entry.get("secret")) is entry["name"].endswith("_KEY"), entry["name"]
    assert "tinyfish" not in json.dumps(m).lower()  # N1

    registered = []

    class Ctx:
        def register_web_search_provider(self, p):
            registered.append(p)

    extract_chain.register(Ctx())
    assert len(registered) == 1 and registered[0].name == "extract-chain"


def test_version_is_the_same_in_both_files():  # N21, P1
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert manifest()["version"] == project["version"] == "0.3.0"


def test_display_name_names_the_chain():  # N1
    assert ExtractChainProvider().display_name == "Extract chain (Bright Data, Jina, Firecrawl, Tavily, Keenable)"


# --- S2, N3: availability ----------------------------------------------------------------------------------


def test_capabilities(env):  # S2
    p = ExtractChainProvider()
    assert (p.name, p.supports_search(), p.supports_extract()) == ("extract-chain", False, True)


@pytest.mark.parametrize(
    ("keys", "available"),
    [
        ({"BRIGHTDATA_API_KEY": "bd-SECRET", "BRIGHTDATA_UNLOCKER_ZONE": "z"}, True),
        ({"BRIGHTDATA_API_KEY": "bd-SECRET"}, False),  # N3: Bright Data needs its zone
        ({"BRIGHTDATA_UNLOCKER_ZONE": "z"}, False),
        ({"JINA_API_KEY": "jn-SECRET"}, False),  # N3: Jina alone does not count
        ({"FIRECRAWL_API_KEY": "fc-SECRET"}, True),
        ({"TAVILY_API_KEY": "tv-SECRET"}, True),
        ({"KEENABLE_API_KEY": "ke-SECRET"}, True),
        ({}, False),
    ],
)
def test_is_available(env, keys, available):  # N3
    env.clear()
    env.update(keys)
    assert ExtractChainProvider().is_available() is available


def test_key_that_cannot_be_read_counts_as_missing(env):  # S3: e.g. UnscopedSecretError
    env.clear()
    env["FIRECRAWL_API_KEY"] = RuntimeError("UnscopedSecretError")
    assert not ExtractChainProvider().is_available()


# --- N2 stage order -----------------------------------------------------------------------------------------

DEFAULT = ["brightdata", "jina", "firecrawl", "tavily", "keenable"]


@pytest.mark.parametrize(
    ("value", "order"),
    [
        ("", DEFAULT),
        ("   ", DEFAULT),
        ("jina,brightdata,firecrawl,tavily,keenable", ["jina", "brightdata", "firecrawl", "tavily", "keenable"]),
        ("Jina, BRIGHTDATA ,firecrawl", ["jina", "brightdata", "firecrawl", "keenable"]),  # case and spaces
        ("keenable,jina,tavily", ["jina", "tavily", "keenable"]),  # Keenable always last
        ("firecrawl,tavily", ["firecrawl", "tavily", "keenable"]),  # without Keenable
    ],
)
def test_stage_order(value, order, caplog):  # N2
    assert provider.stage_order(value) == order
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    ("value", "order"),
    [
        ("jina,jina,brightdata", ["jina", "brightdata", "keenable"]),  # duplicates dropped
        ("jina,tinyfish,exa", ["jina", "keenable"]),  # unknown names dropped
        ("keenable", DEFAULT),  # nothing but Keenable: the default
        ("tinyfish", DEFAULT),
    ],
)
def test_invalid_stage_order_warns(value, order, caplog):  # N2
    assert provider.stage_order(value) == order
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "EXTRACT_CHAIN_ORDER" in caplog.records[0].getMessage()


def test_order_warning_once_per_process(caplog):  # N2
    provider.stage_order("jina,nope")
    provider.stage_order("tinyfish")
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_order_from_the_environment(env):  # N2
    env["EXTRACT_CHAIN_ORDER"] = "firecrawl,jina"
    api = Api(firecrawl=down, jina=jina_ok())
    out = extract(api, [URL])
    assert api.asked() == ["firecrawl", "jina"]
    assert out[0]["content"].startswith(NOTE_LIVE.format(provider="Jina", reasons="Firecrawl: API 500: down"))


# --- N9 budget ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("config", "budget"), [({"extract_timeout": 180}, 170.0), ({"extract_timeout": 300}, 170.0)])
def test_url_budget_from_the_setting(web_config, config, budget, caplog):  # N9: at most 170 s
    web_config["config"] = config
    assert provider.url_budget() == budget
    assert not caplog.records


@pytest.mark.parametrize("value", [0, -5])
def test_url_budget_without_limit_in_hermes(web_config, value):  # N9: 0 or below means no limit in Hermes
    web_config["config"] = {"extract_timeout": value}
    assert provider.url_budget() == 170.0


def test_url_budget_below_120_warns_once(web_config, caplog):  # N9
    web_config["config"] = {"extract_timeout": 100}
    assert provider.url_budget() == 90.0
    provider.url_budget()
    assert [r.getMessage() for r in caplog.records] == [
        "extract-chain: web.extract_timeout is 100 s; 180 s are recommended"
    ]


def test_url_budget_default_setting(web_config):  # N9: Hermes' default of 120 s
    web_config["config"] = {}
    assert provider.url_budget() == 110.0


@pytest.mark.parametrize("config", [RuntimeError("broken yaml"), {"extract_timeout": "abc"}, None])
def test_url_budget_when_the_setting_cannot_be_read(web_config, config):  # N9: 110 s
    web_config["config"] = config
    assert provider.url_budget() == 110.0


def test_url_budget_without_hermes_module(monkeypatch):  # N9: an incompatible Hermes version
    monkeypatch.delitem(sys.modules, "tools.web_tools")
    assert provider.url_budget() == 110.0


def test_budget_and_clock_reach_the_chain(env, web_config, caplog):  # N9: monotonic clock from the start of a URL
    lines = chain_lines(caplog)
    web_config["config"] = {"extract_timeout": 100}  # 90 s per URL
    now = [0.0]

    def slow_brightdata(request):
        now[0] += 81  # 9 s left
        return httpx.Response(500)

    api = Api(brightdata=slow_brightdata, keenable=ke_ok())
    p = ExtractChainProvider(httpx.MockTransport(api), monotonic=lambda: now[0])
    asyncio.run(p.extract([URL]))
    assert api.asked() == ["brightdata"]
    assert lines() == [
        "extract-chain a.example: brightdata=api_500 jina=no_time firecrawl=no_time tavily=no_time keenable=ok"
    ]


# --- S3, N3: keys and stages -------------------------------------------------------------------------------


def test_each_stage_gets_its_url_and_its_key(env):  # S3, N11-N13, A3
    api = Api(keenable=down)
    urls = ["https://a.example/", "https://b.example/"]
    extract(api, urls)
    by = {name: [r for r in api.requests if HOSTS[r.url.host] == name] for name in HOSTS.values()}
    assert sorted(json.loads(r.content)["url"] for r in by["brightdata"]) == urls
    assert {json.loads(r.content)["zone"] for r in by["brightdata"]} == {"unlocker1"}
    assert sorted(str(r.url).removeprefix("https://r.jina.ai/") for r in by["jina"]) == urls
    assert sorted(json.loads(r.content)["url"] for r in by["firecrawl"]) == urls
    assert sorted(json.loads(r.content)["urls"][0] for r in by["tavily"]) == urls
    assert sorted(r.url.params["url"] for r in by["keenable"]) == urls
    keys = {name: {r.headers.get("authorization") for r in reqs} for name, reqs in by.items()}
    assert keys == {
        "brightdata": {"Bearer bd-SECRET"},
        "jina": {"Bearer jn-SECRET"},
        "firecrawl": {"Bearer fc-SECRET"},
        "tavily": {"Bearer tv-SECRET"},
        "keenable": {"Bearer ke-SECRET"},
    }


def test_each_provider_is_asked_once_per_url(env):  # K5
    api = Api()
    extract(api, [URL])
    assert api.asked() == ["brightdata", "jina", "firecrawl", "tavily"] and api.keenable() == 1


def test_jina_runs_without_key(env):  # N3
    del env["JINA_API_KEY"]
    api = Api(brightdata=down, jina=jina_ok())
    out = extract(api, [URL])
    jina = [r for r in api.requests if r.url.host == "r.jina.ai"]
    assert len(jina) == 1 and "authorization" not in jina[0].headers
    assert out[0]["content"].startswith(NOTE_LIVE.format(provider="Jina", reasons="Bright Data: API 500: down"))


@pytest.mark.parametrize(
    ("missing", "reason"),
    [("BRIGHTDATA_UNLOCKER_ZONE", "Bright Data: no zone"), ("BRIGHTDATA_API_KEY", "Bright Data: no API key")],
)
def test_brightdata_without_key_or_zone_is_skipped(env, caplog, missing, reason):  # N3
    lines = chain_lines(caplog)
    del env[missing]
    api = Api(jina=jina_ok())
    out = extract(api, [URL])
    assert api.asked() == ["jina"]
    assert out[0]["content"].startswith(NOTE_LIVE.format(provider="Jina", reasons=reason))
    assert lines() == ["extract-chain a.example: brightdata=no_key jina=ok keenable=ref_http_500"]


def test_missing_keys_skip_stages(env, caplog):  # N3, L1
    lines = chain_lines(caplog)
    for name in ("FIRECRAWL_API_KEY", "TAVILY_API_KEY", "KEENABLE_API_KEY"):
        env[name] = ""
    api = Api()
    out = extract(api, [URL])
    assert api.asked() == ["brightdata", "jina"] and api.keenable() == 0
    assert out[0]["error"] == (
        "Bright Data: API 500: down; Jina: API 500: down; Firecrawl: no API key; Tavily: no API key; "
        "Keenable: no API key"
    )
    assert lines() == [
        "extract-chain a.example: brightdata=api_500 jina=api_500 firecrawl=no_key tavily=no_key keenable=no_key"
    ]


def test_keys_never_leak(env, caplog):  # S3
    caplog.set_level(logging.DEBUG)

    def fail(request):
        return httpx.Response(401, text=f"invalid key {request.headers.get('authorization')}")

    out = extract(Api(**dict.fromkeys(HOSTS.values(), fail)), [URL])
    assert out[0]["error"].startswith("Bright Data: API 401: invalid key Bearer [key]; Jina: API 401")
    dump = json.dumps(out) + caplog.text
    assert not [v for k, v in env.items() if k.endswith("_KEY") and v in dump]


def test_key_that_cannot_be_encoded_fails_only_its_stage(env):  # S6, K7: the pause table digests any key
    env["BRIGHTDATA_API_KEY"] = "bd-" + chr(0xDCFF) + "SECRET"
    api = Api(jina=jina_ok())
    out = extract(api, [URL])
    assert api.asked() == ["jina"]
    assert out[0]["content"].startswith(NOTE_LIVE.format(provider="Jina", reasons="Bright Data: UnicodeEncodeError"))


# --- S4, S5, S6, N10 ----------------------------------------------------------------------------------------


def test_order_and_duplicates(env):  # S4, S5
    api = Api(brightdata=lambda r: bd_ok(json.loads(r.content)["url"] + " " + ARTICLE)(r))
    urls = ["https://a.example/", "https://b.example/", "https://a.example/"]
    out = extract(api, urls, format="html", unknown=1)
    assert [r["url"] for r in out] == urls
    assert [r["content"].split(" ", 1)[0] for r in out] == urls
    assert all(r["error"] is None and r["metadata"] == {"sourceURL": r["url"]} for r in out)  # N11: no final URL
    assert out[0] is not out[2] and out[0]["metadata"] is not out[2]["metadata"]  # duplicates share nothing
    assert api.asked() == ["brightdata", "brightdata"]  # each URL once


def test_empty_list(env):
    assert extract(Api(), []) == []


def test_entries_that_are_no_strings_fail_alone(env):  # S6
    api = Api(brightdata=bd_ok(), keenable=ke_ok())
    urls = [123, {"x": 1}, URL, None]
    out = extract(api, urls)
    assert [r["url"] for r in out] == urls
    assert [r["error"] for r in out] == ["extract-chain: not a URL"] * 2 + [None, "extract-chain: not a URL"]


def test_urls_run_concurrently(env):  # N10, K6
    started, both = [], asyncio.Event()

    async def barrier(request):
        started.append(request)
        if len(started) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 2)  # times out if the URLs ran one after another
        return bd_ok()(request)

    out = extract(Api(brightdata=barrier, keenable=ke_ok()), ["https://a.example/", "https://b.example/"])
    assert [r["content"] for r in out] == [ARTICLE, ARTICLE]


def test_transport_failures_become_errors(env):  # S6
    def refused(request):
        raise httpx.ConnectError("down")

    out = extract(Api(**dict.fromkeys(HOSTS.values(), refused)), [URL])
    assert out[0]["error"] == (
        "Bright Data: ConnectError; Jina: ConnectError; Firecrawl: ConnectError; Tavily: ConnectError; "
        "Keenable: ConnectError"
    )


@pytest.mark.parametrize("stage", list(HOSTS.values()))
def test_redirect_of_a_provider_api_is_not_followed(env, stage):  # A5: every stage sends a key
    def moved(request):
        return httpx.Response(307, headers={"Location": "https://elsewhere.example/"})

    api = Api(**{stage: moved})
    out = extract(api, [URL])
    assert {r.url.host for r in api.requests} <= set(HOSTS)  # and no other host
    assert "307" in out[0]["error"]


def test_unexpected_failure_becomes_error_entries(env, monkeypatch, caplog):  # S6
    def broken_client(*args, **kwargs):
        raise ValueError("Unknown scheme for proxy URL")

    monkeypatch.setattr(provider.httpx, "AsyncClient", broken_client)
    urls = ["https://a.example/", "https://b.example/"]
    assert extract(Api(), urls) == [failed(u, "extract-chain: ValueError") for u in urls]
    assert caplog.messages == ["extract-chain: call failed: ValueError"]


def test_unexpected_failure_in_one_chain_spares_the_other_urls(env, monkeypatch, caplog):  # S6
    real = chain.classify

    def classify(doc, full_page=False):
        if doc.get("content") == "BOOM":
            raise KeyError("bug")
        return real(doc, full_page)

    monkeypatch.setattr(chain, "classify", classify)
    urls = ["https://a.example/", "https://b.example/"]
    api = Api(brightdata=lambda r: bd_ok("BOOM" if "a.example" in r.content.decode() else ARTICLE)(r), keenable=ke_ok())
    out = extract(api, urls)
    assert out[0] == failed(urls[0], "extract-chain: KeyError")
    assert out[1]["error"] is None and out[1]["content"] == ARTICLE
    assert "extract-chain a.example: chain failed: KeyError" in caplog.messages


# --- N5 the Keenable task -----------------------------------------------------------------------------------


def run_with_tasks(api, urls):
    """extract() plus the tasks still running once it has returned (N5: none)."""

    async def go():
        out = await ExtractChainProvider(httpx.MockTransport(api)).extract(urls)
        return out, [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    return asyncio.run(go())


def slow_keenable(state, seconds=5.0):
    async def handler(request):
        state["started"] = True
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        state["finished"] = True
        return ke_ok()(request)

    return handler


def test_keenable_runs_in_parallel_with_the_first_stage(env):  # N5
    started, both = [], asyncio.Event()

    async def meet(request):
        started.append(HOSTS[request.url.host])
        if len(started) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 2)  # times out if Keenable waited for Bright Data
        return bd_ok()(request) if request.url.host == "api.brightdata.com" else ke_ok()(request)

    out = extract(Api(brightdata=meet, keenable=meet), [URL])
    assert sorted(started) == ["brightdata", "keenable"] and out[0]["content"] == ARTICLE


def after_a_moment(handler):
    """A reply that comes once the Keenable request is under way."""

    async def later(request):
        await asyncio.sleep(0.05)
        return handler(request)

    return later


def test_keenable_task_is_cancelled_on_early_end(env):  # N5, A5: a paywall ends before Keenable is needed
    state = {}
    start = time.monotonic()
    api = Api(brightdata=after_a_moment(bd_ok(PAYWALL_TEXT)), keenable=slow_keenable(state))
    out, running = run_with_tasks(api, [URL])
    assert out[0]["content"] == f"{NOTE_PAYWALL}\n\n{PAYWALL_TEXT}"
    assert state == {"started": True, "cancelled": True} and running == []
    assert time.monotonic() - start < 2


def test_keenable_task_is_cancelled_on_an_unexpected_failure(env, monkeypatch):  # N5, S6
    real = chain.classify

    def classify(doc, full_page=False):
        if doc.get("content") == "BOOM":
            raise KeyError("bug")
        return real(doc, full_page)

    monkeypatch.setattr(chain, "classify", classify)
    state = {}
    api = Api(brightdata=after_a_moment(bd_ok("BOOM")), keenable=slow_keenable(state))
    out, running = run_with_tasks(api, [URL])
    assert out[0]["error"] == "extract-chain: KeyError"
    assert state.get("cancelled") and running == []


def test_interrupt_stops_before_requests(env, monkeypatch):  # S8
    monkeypatch.setattr(provider, "is_interrupted", lambda: True)
    monkeypatch.setattr(provider, "check_website_access", block_host("b.example"))
    api = Api()
    out = extract(api, ["https://a.example/", "https://b.example/"])
    assert out[0] == failed("https://a.example/", "Interrupted") and api.requests == []
    assert out[1]["error"] == "Blocked by website policy: b.example"  # a policy block keeps its entry


def test_interrupt_between_stages_skips_the_live_stages(env, monkeypatch, caplog):  # S8, N20
    lines = chain_lines(caplog)

    def brightdata_then_interrupt(request):
        monkeypatch.setattr(provider, "is_interrupted", lambda: True)
        return httpx.Response(500)

    api = Api(brightdata=brightdata_then_interrupt)
    out = extract(api, [URL])
    assert api.asked() == ["brightdata"]
    assert out[0]["error"] == "Bright Data: API 500: HTTP 500; Jina: interrupted; Keenable: interrupted"
    assert lines() == ["extract-chain a.example: brightdata=api_500 jina=interrupted keenable=interrupted"]


def test_interrupt_between_stages_cancels_the_running_keenable_task(env, monkeypatch):  # N5, S8
    state = {}

    def brightdata_then_interrupt(request):
        monkeypatch.setattr(provider, "is_interrupted", lambda: True)
        return httpx.Response(500)

    start = time.monotonic()
    api = Api(brightdata=after_a_moment(brightdata_then_interrupt), keenable=slow_keenable(state, 1.0))
    out, running = run_with_tasks(api, [URL])
    assert state.get("cancelled") and not state.get("finished") and running == []
    assert out[0]["content"] == "" and time.monotonic() - start < 0.8


# --- K7, N16 pauses ----------------------------------------------------------------------------------------


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def calls(api, clock):
    """extract() of one provider object, so pauses survive from call to call; returns (entry, stages asked)."""
    p = ExtractChainProvider(httpx.MockTransport(api), clock=clock)

    def call():
        before = len(api.requests)
        out = asyncio.run(p.extract([URL]))
        return out[0], [HOSTS[r.url.host] for r in api.requests[before:]]

    return call


@pytest.mark.parametrize(
    ("seconds", "text"), [(1, "1 min"), (3599, "60 min"), (3600, "1 h"), (5399, "1 h"), (5400, "2 h"), (86400, "24 h")]
)
def test_remaining_pause_is_rounded(seconds, text):  # K7
    assert provider._left(seconds) == text


def test_quota_pauses_the_stage_for_24_hours(env, caplog):  # N16, K7, L2
    lines = chain_lines(caplog)
    clock = Clock(NOON)
    plan_limit = lambda r: httpx.Response(432, json={"detail": {"error": "plan limit"}})  # noqa: E731
    call = calls(Api(tavily=plan_limit, keenable=ke_ok()), clock)

    out, asked = call()
    assert "tavily" in asked
    assert "extract-chain: Tavily paused for 86400 s (api_432)" in caplog.messages

    clock.now += 3600
    out, asked = call()
    assert "tavily" not in asked
    assert "Tavily: API 432: plan limit (paused for another 23 h)" in out["content"].split("\n", 1)[0]
    assert "tavily=paused" in lines()[-1]
    assert caplog.text.count("paused for 86400 s") == 1  # the running pause is not announced again

    clock.now = NOON + 86400 - 0.5
    assert "tavily" not in call()[1]
    clock.now = NOON + 86400
    assert "tavily" in call()[1]


BD_QUOTA = {"x-brd-error": "Account suspended", "x-brd-error-code": "client_10020"}


@pytest.mark.parametrize(
    ("stage", "handler"),
    [
        ("brightdata", lambda r: httpx.Response(402)),
        ("brightdata", lambda r: httpx.Response(200, headers=BD_QUOTA, json={"status_code": 502, "body": ""})),
        ("brightdata", bd_ok("", 502, {**BD_QUOTA, "x-brd-error-code": "client_10100"})),
        ("brightdata", bd_ok("", 502, {**BD_QUOTA, "x-brd-error-code": "client_10002"})),
        ("jina", lambda r: httpx.Response(402)),
        ("firecrawl", lambda r: httpx.Response(402, json={"success": False, "error": "credits"})),
        ("tavily", lambda r: httpx.Response(402)),
        ("tavily", lambda r: httpx.Response(433)),
        ("keenable", lambda r: httpx.Response(402)),
    ],
)
def test_api_quota_replies_pause(env, stage, handler):  # N16
    call = calls(Api(**{stage: handler}), Clock(NOON))
    assert stage in call()[1]
    out, asked = call()
    assert stage not in asked and "(paused for another 24 h)" in (out["error"] or out["content"])


@pytest.mark.parametrize(
    ("stage", "handler"),
    [
        ("brightdata", lambda r: httpx.Response(429)),
        ("brightdata", bd_ok("", 402)),  # the target page answers 402, not Bright Data's API
        ("brightdata", bd_ok("", 502, {"x-brd-error": "slow", "x-brd-error-code": "client_10110"})),
        ("jina", lambda r: httpx.Response(429)),
        ("firecrawl", lambda r: httpx.Response(429)),
        ("firecrawl", fc_ok("", statusCode=402)),  # the target page answers 402
        ("tavily", lambda r: httpx.Response(429)),
        ("keenable", lambda r: httpx.Response(429)),
    ],
)
def test_no_pause_for_429_or_a_target_402(env, stage, handler):  # N16, N10
    call = calls(Api(**{stage: handler}), Clock(NOON))
    assert stage in call()[1] and stage in call()[1]  # the second call would skip a paused stage


def test_pause_per_key(env):  # K7: another key (profile, or a corrected one) is not paused
    call = calls(Api(keenable=lambda r: httpx.Response(402)), Clock(NOON))
    call()
    out, asked = call()
    assert "keenable" not in asked and out["error"].endswith("Keenable: HTTP 402 (paused for another 24 h)")
    env["KEENABLE_API_KEY"] = "ke-OTHER-KEY"
    assert "keenable" in call()[1]


def test_pause_is_dropped_when_the_clock_was_set_back(env):  # K7
    clock = Clock(NOON)
    call = calls(Api(firecrawl=lambda r: httpx.Response(402)), clock)
    call()
    clock.now -= 3 * 86400
    assert "firecrawl" in call()[1]


def test_pause_table_holds_no_key(env):  # K7, S3
    p = ExtractChainProvider(httpx.MockTransport(Api(firecrawl=lambda r: httpx.Response(402))), clock=Clock(NOON))
    asyncio.run(p.extract([URL]))
    assert p._paused and "SECRET" not in repr(p._paused)


def test_several_quota_replies_in_one_call_start_one_pause(env, caplog):  # L2: announced once
    started, all_in = [], asyncio.Event()

    async def credits_gone_for_all(request):
        started.append(request)
        if len(started) == 3:
            all_in.set()
        await asyncio.wait_for(all_in.wait(), 2)
        return httpx.Response(402, json={"success": False, "error": "credits"})

    urls = [f"https://{name}.example/" for name in "abc"]
    api = Api(firecrawl=credits_gone_for_all, keenable=ke_ok())
    asyncio.run(ExtractChainProvider(httpx.MockTransport(api), clock=Clock(NOON)).extract(urls))
    assert len(started) == 3
    assert [m for m in caplog.messages if "paused for" in m] == [
        "extract-chain: Firecrawl paused for 86400 s (api_402)"
    ]


# --- S7 website policy ---------------------------------------------------------------------------------------


def block_host(host):
    def check(url):
        if host in url:
            return {"host": host, "rule": host, "source": "config", "message": f"Blocked by website policy: {host}"}
        return None

    return check


def test_policy_blocks_before_any_request(env, monkeypatch):  # S7
    monkeypatch.setattr(provider, "check_website_access", block_host("b.example"))
    api = Api(brightdata=bd_ok(), keenable=ke_ok())
    out = extract(api, ["https://a.example/", "https://b.example/"])
    assert out[1] == {
        "url": "https://b.example/",
        "title": "",
        "content": "",
        "error": "Blocked by website policy: b.example",
        "blocked_by_policy": {"host": "b.example", "rule": "b.example", "source": "config"},
        "metadata": {"sourceURL": "https://b.example/"},
    }
    assert {json.loads(r.content)["url"] for r in api.requests if r.url.host == "api.brightdata.com"} == {URL}


@pytest.mark.parametrize("reply", [{"message": "blocked"}, {"host": "a.example"}, "blocked"])
def test_policy_block_of_unexpected_shape_still_blocks(env, monkeypatch, reply):  # S6, S7
    monkeypatch.setattr(provider, "check_website_access", lambda url: reply)
    api = Api()
    out = extract(api, [URL])
    assert api.requests == [] and out[0]["content"] == ""
    assert out[0]["error"] in ("blocked", "Blocked by website policy")
    assert set(out[0]["blocked_by_policy"]) == {"host", "rule", "source"}


@pytest.mark.parametrize("stage", ["firecrawl", "keenable"])
def test_policy_checked_on_the_final_url(env, monkeypatch, stage):  # S7, N8
    monkeypatch.setattr(provider, "check_website_access", block_host("evil.example"))
    final = "https://evil.example/x"
    handlers = {"firecrawl": fc_ok(url=final)} if stage == "firecrawl" else {"keenable": ke_ok(url=final)}
    out = extract(Api(**handlers), [URL])
    assert out[0]["url"] == URL and out[0]["content"] == ""
    assert out[0]["blocked_by_policy"]["host"] == "evil.example"


def test_policy_checked_on_the_final_url_of_an_earlier_stage(env, monkeypatch):  # S7, N8 (a): the longest result
    monkeypatch.setattr(provider, "check_website_access", block_host("evil.example"))
    out = extract(Api(firecrawl=fc_ok("f" * 400, url="https://evil.example/x"), tavily=tavily_ok("t" * 300)), [URL])
    assert out[0]["blocked_by_policy"]["host"] == "evil.example" and out[0]["content"] == ""


def test_policy_is_asked_about_a_final_url_only_when_there_is_another_one(env, monkeypatch):  # S7
    seen = []
    monkeypatch.setattr(provider, "check_website_access", lambda url: seen.append(url))
    extract(Api(brightdata=bd_ok(), keenable=ke_ok()), [URL])  # Bright Data names no final URL (N11)
    assert seen == [URL]
    seen.clear()
    extract(Api(firecrawl=fc_ok(url=URL)), [URL])  # the final URL is the requested one
    assert seen == [URL]


@pytest.mark.parametrize("fails_for", ["a.example", "final.example"])
def test_policy_check_error_blocks(env, monkeypatch, caplog, fails_for):  # S7
    def broken(url):
        if fails_for in url:
            raise ValueError("Invalid IPv6 URL")

    monkeypatch.setattr(provider, "check_website_access", broken)
    api = Api(firecrawl=fc_ok(url="https://final.example/x"))
    out = extract(api, [URL])
    assert out[0]["url"] == URL and out[0]["content"] == ""
    assert out[0]["error"] == "Blocked by website policy: the check failed for this URL (ValueError)"
    assert bool(api.requests) is (fails_for != "a.example")  # an input URL is not even fetched
    assert "extract-chain: website policy check failed for a URL (blocked): ValueError" in caplog.messages


def test_missing_policy_module_refuses_every_url(env, monkeypatch, caplog):  # S7, D15
    monkeypatch.setattr(provider, "check_website_access", None)
    api = Api()
    urls = ["https://a.example/", "https://b.example/", "https://a.example/"]
    out = extract(api, urls)
    assert api.requests == [] and [r["url"] for r in out] == urls
    assert all("blocked by website policy" in r["error"].lower() and r["content"] == "" for r in out)
    assert "extract-chain: tools.website_policy not importable; every URL refused" in caplog.messages
    assert extract(api, [5])[0]["error"] == "extract-chain: not a URL"
    assert ExtractChainProvider().is_available()


# --- N17 through the provider --------------------------------------------------------------------------------


def test_tavily_copy_note_through_the_provider(env):  # N17, N13
    out = extract(Api(tavily=tavily_ok()), [URL])
    reasons = "Bright Data: API 500: down; Jina: API 500: down; Firecrawl: API 500: down"
    assert out[0]["content"] == NOTE_COPY.format(provider="Tavily", reasons=reasons) + "\n\n" + ARTICLE
