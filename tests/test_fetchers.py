import asyncio
import json

import httpx
import pytest

from extract_chain import fetchers


def call(coro_fn, handler, *args):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await coro_fn(client, *args)

    return asyncio.run(go())


# --- A1 TinyFish -----------------------------------------------------------------------------------


def test_tinyfish_request_and_mapping():
    seen = {}

    def handler(request):
        seen["headers"], seen["body"] = request.headers, json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://a.example/x/", "final_url": "https://a.example/y", "title": "A", "text": "T"}
                ],
                "errors": [{"url": "https://b.example/", "error": "bot_blocked"}],
            },
        )

    urls = ["https://a.example/x", "https://b.example/", "https://c.example/"]
    out = call(fetchers.tinyfish, handler, urls, "tf-key")
    assert seen["headers"]["x-api-key"] == "tf-key"
    assert seen["body"] == {"urls": urls, "format": "markdown", "per_url_timeout_ms": 30000, "ttl": 3600}
    # trailing slash tolerated
    assert out["https://a.example/x"] == {"title": "A", "content": "T", "final_url": "https://a.example/y"}
    assert out["https://b.example/"] == {"code": "bot_blocked", "error": "TinyFish: bot_blocked"}
    assert out["https://c.example/"] == {"code": "no_result", "error": "TinyFish: no result"}


def test_tinyfish_single_url_reply_with_other_url():
    reply = {"results": [{"url": "https://www.a.example/x", "title": "A", "text": "T"}]}
    out = call(fetchers.tinyfish, lambda r: httpx.Response(200, json=reply), ["http://a.example/x"], "k")
    # the URL the reply names is kept as final URL, so the website policy sees it (S7)
    assert out == {"http://a.example/x": {"title": "A", "content": "T", "final_url": "https://www.a.example/x"}}


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("BOT_BLOCKED", "bot_blocked"),  # a code, in whatever case
        ("Bad key tf-SECRET\nextract-chain forged: line", "fetch_failed"),  # a text: nothing of it in the log
        ("fetch failed for https://a.example/?token=abc123", "fetch_failed"),  # it may quote the URL
        ("x" * 41, "fetch_failed"),
        (None, "fetch_failed"),
    ],
)
def test_tinyfish_error_code_is_a_code_or_fetch_failed(error, code):  # A1, L1
    reply = {"errors": [{"url": "u", "error": error}]}
    out = call(fetchers.tinyfish, lambda r: httpx.Response(200, json=reply), ["u"], "tf-SECRET")["u"]
    assert out["code"] == code
    assert "tf-SECRET" not in out["error"] and "\n" not in out["error"]  # one line, no key


def test_tinyfish_splits_batches_of_ten():
    sizes = []

    def handler(request):
        urls = json.loads(request.content)["urls"]
        sizes.append(len(urls))
        return httpx.Response(200, json={"results": [{"url": u, "text": u} for u in urls]})

    urls = [f"https://e.example/{i}" for i in range(12)]
    out = call(fetchers.tinyfish, handler, urls, "k")
    assert sorted(sizes) == [2, 10]
    assert [out[u]["content"] for u in urls] == urls


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (
            lambda r: httpx.Response(429, text="slow down"),
            {"error": "TinyFish: HTTP 429", "code": "http_429", "status": 429},
        ),
        (
            lambda r: httpx.Response(200, json=["no", "dict"]),
            {"error": "TinyFish: AttributeError", "code": "AttributeError"},
        ),
        (
            lambda r: httpx.Response(200, text="<html>no JSON</html>"),
            {"error": "TinyFish: JSONDecodeError", "code": "JSONDecodeError"},
        ),
    ],
)
def test_tinyfish_batch_failures_apply_to_all(handler, expected):
    assert call(fetchers.tinyfish, handler, ["u1", "u2"], "k") == {"u1": expected, "u2": expected}


def test_tinyfish_transport_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    out = call(fetchers.tinyfish, handler, ["u"], "k")
    assert out == {"u": {"error": "TinyFish: ConnectError", "code": "ConnectError"}}


def test_tinyfish_urls_differing_only_in_the_trailing_slash_keep_their_own_result():
    def handler(request):
        urls = json.loads(request.content)["urls"]
        return httpx.Response(200, json={"results": [{"url": u, "text": "text for " + u} for u in urls]})

    urls = ["https://a.example/x", "https://a.example/x/"]
    out = call(fetchers.tinyfish, handler, urls, "k")
    assert [out[u]["content"] for u in urls] == ["text for " + u for u in urls]

    only_one = {"results": [{"url": urls[1], "text": "T"}]}  # then that entry counts for both
    out = call(fetchers.tinyfish, lambda r: httpx.Response(200, json=only_one), urls, "k")
    assert [out[u]["content"] for u in urls] == ["T", "T"]
    assert out[urls[0]] is not out[urls[1]]  # as two objects

    twice = {"results": [{"url": urls[1], "text": "T"}], "errors": [{"url": urls[1], "error": "bot_blocked"}]}
    out = call(fetchers.tinyfish, lambda r: httpx.Response(200, json=twice), urls, "tf-key")
    assert [out[u].get("code") for u in urls] == ["bot_blocked", "bot_blocked"]  # the later entry counts


@pytest.mark.parametrize(
    ("fetch", "provider", "target"),
    [
        (fetchers.tinyfish, "TinyFish", ["u"]),
        (fetchers.firecrawl, "Firecrawl", "u"),
        (fetchers.keenable, "Keenable", "u"),
    ],
)
def test_deadline(monkeypatch, fetch, provider, target):  # A0: every request, whatever httpx does
    monkeypatch.setattr(fetchers, f"{provider.upper()}_DEADLINE", 0.05)

    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    out = call(fetch, handler, target, "k")
    assert (out["u"] if fetch is fetchers.tinyfish else out) == {"error": f"{provider}: timeout", "code": "timeout"}


# --- A2 Firecrawl ----------------------------------------------------------------------------------


def firecrawl_reply(status=200, markdown="# Text", **meta):
    return {
        "success": True,
        "data": {"markdown": markdown, "metadata": {"title": "Titel", "statusCode": status, **meta}},
    }


def test_firecrawl_request_and_success():
    seen = {}

    def handler(request):
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json=firecrawl_reply(url="https://a.example/final"))

    out = call(fetchers.firecrawl, handler, "https://a.example/", "fc-key")
    assert seen["auth"] == "Bearer fc-key"
    assert seen["body"] == {
        "url": "https://a.example/",
        "formats": ["markdown"],
        "onlyMainContent": True,
        "maxAge": 3600000,
        "timeout": 30000,
        "parsers": [{"type": "pdf", "maxPages": 30}],
    }
    assert out == {"title": "Titel", "content": "# Text", "final_url": "https://a.example/final"}


def test_firecrawl_pdf_page_cap_reported():
    reply = firecrawl_reply(numPages=30, totalPages=120)
    assert call(fetchers.firecrawl, lambda r: httpx.Response(200, json=reply), "u", "k")["pdf_pages"] == (30, 120)
    whole = firecrawl_reply(numPages=12, totalPages=12)
    assert "pdf_pages" not in call(fetchers.firecrawl, lambda r: httpx.Response(200, json=whole), "u", "k")


@pytest.mark.parametrize(("status", "ok"), [(200, True), (304, True), (403, False), (404, False)])
def test_firecrawl_target_status(status, ok):
    out = call(fetchers.firecrawl, lambda r: httpx.Response(200, json=firecrawl_reply(status, "")), "u", "k")
    assert ("error" not in out) is ok
    if not ok:
        assert out == {"error": f"Firecrawl: target HTTP {status}", "code": f"target_{status}"}


def test_firecrawl_api_error():
    reply = httpx.Response(402, json={"success": False, "error": "Payment Required: Insufficient credits"})
    out = call(fetchers.firecrawl, lambda r: reply, "u", "k")
    error = "Firecrawl: API 402: Payment Required: Insufficient credits"
    assert out == {"error": error, "code": "api_402", "status": 402}


# --- A3 Keenable, A4 -------------------------------------------------------------------------------


def test_keenable_request_and_success():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"url": "https://a.example/", "title": "K", "content": "Kopie"})

    out = call(fetchers.keenable, handler, "https://a.example/?q=1", "ke-key")
    request = seen["request"]
    assert request.url.params["url"] == "https://a.example/?q=1"
    assert request.headers["authorization"] == "Bearer ke-key"
    assert request.headers["x-keenable-title"] == "hermes-extract-chain"
    assert out == {"title": "K", "content": "Kopie", "final_url": "https://a.example/"}


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (
            httpx.Response(
                422, json={"error": "Unprocessable entity", "message": "The page is behind a login or paywall"}
            ),
            ("Keenable: The page is behind a login or paywall", "http_422"),
        ),
        (httpx.Response(504, text="Gateway timeout"), ("Keenable: Gateway timeout", "http_504")),
        (httpx.Response(500), ("Keenable: HTTP 500", "http_500")),
        (httpx.Response(200, text="<html>no JSON</html>"), ("Keenable: JSONDecodeError", "JSONDecodeError")),
    ],
)
def test_keenable_errors(reply, expected):
    out = call(fetchers.keenable, lambda r: reply, "u", "k")
    assert (out["error"], out["code"]) == expected
    assert out.get("status") == (reply.status_code if reply.status_code >= 300 else None)  # read by K7


def test_error_detail_truncated():
    out = call(fetchers.keenable, lambda r: httpx.Response(500, text="x" * 500), "u", "k")
    assert out["error"] == "Keenable: " + "x" * 200


def test_key_echoed_by_provider_is_redacted():
    echo = lambda r: httpx.Response(401, text=f"invalid key {r.headers['authorization']}")  # noqa: E731
    assert call(fetchers.keenable, echo, "u", "ke-SECRET")["error"] == "Keenable: invalid key Bearer [key]"
    assert call(fetchers.firecrawl, echo, "u", "fc-SECRET")["error"] == "Firecrawl: API 401: invalid key Bearer [key]"
