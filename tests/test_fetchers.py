"""REST calls of the five stages (N11-N16, A0-A5); no network, httpx.MockTransport only."""

import asyncio
import json

import httpx
import pytest

from extract_chain import fetchers

U = "https://a.example/x"


def call(fetch, handler, *args, deadline=40.0):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch(client, *args, deadline=deadline)

    return asyncio.run(go())


def reply(response):
    return lambda request: response


def recorder(response):
    seen = []

    def handler(request):
        seen.append(request)
        return response

    return handler, seen


# The five fetchers with the arguments after the client (Bright Data also takes its zone).
FETCHES = {
    "Bright Data": (fetchers.brightdata, (U, "bd-SECRET", "zone1")),
    "Jina": (fetchers.jina, (U, "jn-SECRET")),
    "Firecrawl": (fetchers.firecrawl, (U, "fc-SECRET")),
    "Tavily": (fetchers.tavily, (U, "tv-SECRET")),
    "Keenable": (fetchers.keenable, (U, "ke-SECRET")),
}


def fetch_of(provider, handler, key=None, deadline=40.0):
    fetch, args = FETCHES[provider]
    if key is not None:
        args = (args[0], key, *args[2:])
    return call(fetch, handler, *args, deadline=deadline)


# --- N11 Bright Data -------------------------------------------------------------------------------


def bd_reply(status_code=200, body="# Text", headers=None, outer_headers=None, outer=200):
    payload = {"status_code": status_code, "headers": headers or {}, "body": body}
    return httpx.Response(outer, json=payload, headers=outer_headers or {})


def test_brightdata_request_and_success():  # N11
    handler, seen = recorder(bd_reply())
    out = call(fetchers.brightdata, handler, U, "bd-key", "zone1")
    request = seen[0]
    assert (request.method, str(request.url)) == ("POST", "https://api.brightdata.com/request")
    assert request.headers["authorization"] == "Bearer bd-key"
    assert json.loads(request.content) == {"zone": "zone1", "url": U, "format": "json", "data_format": "markdown"}
    assert out == {"title": "", "content": "# Text", "final_url": None}  # N11: no final URL in the reply


def test_brightdata_api_error_keeps_api_status():  # N11 (a)
    out = call(fetchers.brightdata, reply(httpx.Response(401, text="Invalid key")), U, "bd-key", "z")
    assert out == {"error": "Bright Data: API 401: Invalid key", "code": "api_401"}


@pytest.mark.parametrize("where", ["outer", "inner"])
def test_brightdata_unlocker_error(where):  # N11 (b): x-brd-error outside or in the JSON field headers
    brd = {"x-brd-error": "Proxy error: blocked", "x-brd-error-code": "proxy_error"}
    response = bd_reply(502, "", **({"outer_headers": brd} if where == "outer" else {"headers": brd}))
    out = call(fetchers.brightdata, reply(response), U, "bd-key", "z")
    assert out == {"error": "Bright Data: proxy_error Proxy error: blocked", "code": "brd_proxy_error"}  # no target


def test_brightdata_unlocker_code_that_is_no_code():  # L1: the log line only gets a short code
    brd = {"x-brd-error": "bad", "x-brd-error-code": "Not A Code!\nforged"}
    out = call(fetchers.brightdata, reply(bd_reply(502, "", headers=brd)), U, "bd-key", "z")
    assert out["code"] == "brd_unlocker"


@pytest.mark.parametrize("status", [402, 403, 404, 502])
def test_brightdata_target_status(status):  # N11 (c): status_code is the target page; no API status, no quota
    out = call(fetchers.brightdata, reply(bd_reply(status, "<html>Not here</html>")), U, "bd-key", "z")
    assert out == {"error": f"Bright Data: target HTTP {status}", "code": f"target_{status}", "target_status": status}


def test_brightdata_malformed_reply():
    out = call(fetchers.brightdata, reply(httpx.Response(200, text="<html>")), U, "bd-key", "z")
    assert out == {"error": "Bright Data: malformed reply", "code": "malformed"}


@pytest.mark.parametrize("code", ["client_10020", "client_10100", "client_10002"])
@pytest.mark.parametrize("where", ["outer", "inner"])
def test_brightdata_quota_codes(code, where):  # N16
    brd = {"x-brd-error": "account problem", "x-brd-error-code": code}
    response = bd_reply(502, "", **({"outer_headers": brd} if where == "outer" else {"headers": brd}))
    out = call(fetchers.brightdata, reply(response), U, "bd-key", "z")
    assert out["code"] == f"brd_{code}" and out["quota"] is True


def test_brightdata_proxy_network_error_headers():  # N11 (b): x-brd-err-code / x-brd-err-msg as well
    brd = {"x-brd-err-code": "client_10020", "x-brd-err-msg": "Account suspended"}
    out = call(fetchers.brightdata, reply(bd_reply(502, "", headers=brd)), U, "bd-key", "z")
    assert out == {"error": "Bright Data: client_10020 Account suspended", "code": "brd_client_10020", "quota": True}


def test_brightdata_unlocker_code_wins_and_either_code_pauses():  # N11 (b), N16
    brd = {"x-brd-error": "Proxy error", "x-brd-error-code": "proxy_error", "x-brd-err-code": "client_10100"}
    out = call(fetchers.brightdata, reply(bd_reply(502, "", headers=brd)), U, "bd-key", "z")
    assert out == {"error": "Bright Data: proxy_error Proxy error", "code": "brd_proxy_error", "quota": True}


@pytest.mark.parametrize("code", ["client_10110", "sr_rate_limit", "proxy_error"])
def test_brightdata_other_codes_do_not_pause(code):  # N16: rate limits never pause
    brd = {"x-brd-error": "slow down", "x-brd-error-code": code}
    out = call(fetchers.brightdata, reply(bd_reply(502, "", headers=brd)), U, "bd-key", "z")
    assert "quota" not in out


def test_brightdata_outer_402_pauses_429_does_not():  # N16
    assert call(fetchers.brightdata, reply(httpx.Response(402)), U, "bd-key", "z")["quota"] is True
    assert "quota" not in call(fetchers.brightdata, reply(httpx.Response(429)), U, "bd-key", "z")


# --- N12 Jina --------------------------------------------------------------------------------------


def jina_text(body="Der Artikeltext.", head="Title: Ein Titel\nURL Source: https://a.example/x\n"):
    return f"{head}\nMarkdown Content:\n{body}"


def test_jina_request():  # N12: query string appended unchanged, header as measured
    handler, seen = recorder(httpx.Response(200, text=jina_text()))
    url = "https://a.example/x?q=a%20b&page=2"
    call(fetchers.jina, handler, url, "jn-key")
    request = seen[0]
    assert (request.method, str(request.url)) == ("GET", "https://r.jina.ai/" + url)
    assert request.headers["accept"] == "text/plain" and request.headers["x-return-format"] == "markdown"
    assert request.headers["authorization"] == "Bearer jn-key"


def test_jina_without_key_sends_no_authorization():  # N3, N12
    handler, seen = recorder(httpx.Response(200, text=jina_text()))
    call(fetchers.jina, handler, U, "")
    assert "authorization" not in seen[0].headers


def test_jina_success_keeps_the_header_lines():  # N12: the text stays as measured, the title comes from the header
    text = jina_text(head="Title: Ein Titel\nURL Source: https://other.example/y\nPublished Time: 2026\n")
    out = call(fetchers.jina, reply(httpx.Response(200, text=text)), U, "jn-key")
    assert out == {"title": "Ein Titel", "content": text, "final_url": None}  # URL Source is no final URL


@pytest.mark.parametrize("status", [403, 404, 410, 422])
def test_jina_warning_line_is_the_target_status(status):  # N12
    head = f"Title: Not found\nURL Source: {U}\nWarning: Target URL returned error {status}: Not Found\n"
    out = call(fetchers.jina, reply(httpx.Response(200, text=jina_text(head=head))), U, "jn-key")
    assert out == {"error": f"Jina: target HTTP {status}", "code": f"target_{status}", "target_status": status}


def test_jina_header_lines_in_the_page_text_do_not_count():  # N12: only the block before "Markdown Content:"
    body = "Warning: Target URL returned error 404\nTitle: Fake\nURL Source: https://evil.example/\nText."
    text = jina_text(body=body, head=f"URL Source: {U}\n")
    out = call(fetchers.jina, reply(httpx.Response(200, text=text)), U, "jn-key")
    assert out == {"title": "", "content": text, "final_url": None}


def test_jina_without_header_block_reads_no_header():  # N12: no "Markdown Content:", nothing is a header
    text = "Title: Fake\nWarning: Target URL returned error 404\nText."
    out = call(fetchers.jina, reply(httpx.Response(200, text=text)), U, "jn-key")
    assert out == {"title": "", "content": text, "final_url": None}


def test_jina_api_errors():  # N12, N16: 402 is the API's empty balance, 429 its rate limit
    out = call(fetchers.jina, reply(httpx.Response(402, json={"message": "Insufficient balance"})), U, "jn-key")
    assert out == {"error": "Jina: API 402: Insufficient balance", "code": "api_402", "quota": True}
    out = call(fetchers.jina, reply(httpx.Response(429, text="Too many requests")), U, "")
    assert out == {"error": "Jina: API 429: Too many requests", "code": "api_429"}


# --- A2, N14 Firecrawl -----------------------------------------------------------------------------


def firecrawl_reply(status=200, markdown="# Text", **meta):
    return {
        "success": True,
        "data": {"markdown": markdown, "metadata": {"title": "Titel", "statusCode": status, **meta}},
    }


def test_firecrawl_request_and_success():  # A2, N14
    handler, seen = recorder(httpx.Response(200, json=firecrawl_reply(url="https://a.example/final")))
    out = call(fetchers.firecrawl, handler, U, "fc-key")
    assert seen[0].method == "POST" and seen[0].headers["authorization"] == "Bearer fc-key"
    assert json.loads(seen[0].content) == {
        "url": U,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "maxAge": 3600000,
        "timeout": 35000,
        "parsers": [{"type": "pdf", "maxPages": 30}],
    }
    assert out == {"title": "Titel", "content": "# Text", "final_url": "https://a.example/final"}


@pytest.mark.parametrize(("deadline", "timeout"), [(40.0, 35000), (12.5, 7500), (3.0, 1000)])
def test_firecrawl_body_timeout_follows_the_deadline(deadline, timeout):  # N9, P2
    handler, seen = recorder(httpx.Response(200, json=firecrawl_reply()))
    call(fetchers.firecrawl, handler, U, "k", deadline=deadline)
    assert json.loads(seen[0].content)["timeout"] == timeout


def test_firecrawl_final_url_falls_back_to_source_url():  # A2
    out = call(fetchers.firecrawl, reply(httpx.Response(200, json=firecrawl_reply(sourceURL=U))), U, "k")
    assert out["final_url"] == U


def test_firecrawl_pdf_page_cap_reported():  # V7
    capped = firecrawl_reply(numPages=30, totalPages=120)
    assert call(fetchers.firecrawl, reply(httpx.Response(200, json=capped)), U, "k")["pdf_pages"] == (30, 120)
    whole = firecrawl_reply(numPages=12, totalPages=12)
    assert "pdf_pages" not in call(fetchers.firecrawl, reply(httpx.Response(200, json=whole)), U, "k")


@pytest.mark.parametrize(("status", "ok"), [(200, True), (304, True), (300, False), (402, False), (404, False)])
def test_firecrawl_target_status(status, ok):  # D9, N6: target_status; a target 402 is no quota (N16)
    out = call(fetchers.firecrawl, reply(httpx.Response(200, json=firecrawl_reply(status, ""))), U, "k")
    if ok:
        assert "error" not in out
    else:
        assert out == {"error": f"Firecrawl: target HTTP {status}", "code": f"target_{status}", "target_status": status}


def test_firecrawl_api_402_is_quota():  # N16
    response = httpx.Response(402, json={"success": False, "error": "Payment Required: Insufficient credits"})
    out = call(fetchers.firecrawl, reply(response), U, "k")
    assert out == {
        "error": "Firecrawl: API 402: Payment Required: Insufficient credits",
        "code": "api_402",
        "quota": True,
    }


def test_firecrawl_429_and_success_false_are_no_quota():  # N16, A2: HTTP 200 with "success": false is an API error
    out = call(fetchers.firecrawl, reply(httpx.Response(429, json={"success": False, "error": "busy"})), U, "k")
    assert out == {"error": "Firecrawl: API 429: busy", "code": "api_429"}
    response = httpx.Response(200, json={"success": False, "error": "402 Payment Required"})
    out = call(fetchers.firecrawl, reply(response), U, "k")
    assert out == {"error": "Firecrawl: API 200: 402 Payment Required", "code": "api_200"}


@pytest.mark.parametrize("data", ["markdown text", [{"markdown": "x"}], {"markdown": "x" * 600, "metadata": "nope"}])
def test_firecrawl_data_that_is_no_object_is_malformed(data):  # N02 of v0.2
    out = call(fetchers.firecrawl, reply(httpx.Response(200, json={"success": True, "data": data})), U, "k")
    assert out == {"error": "Firecrawl: malformed reply", "code": "malformed"}


def test_firecrawl_missing_title_and_text_give_empty_strings():  # E2: the chain sees an empty page
    page = {"success": True, "data": {"metadata": {"statusCode": 200}}}
    assert call(fetchers.firecrawl, reply(httpx.Response(200, json=page)), U, "k") == {
        "title": "",
        "content": "",
        "final_url": None,
    }


# --- N13 Tavily ------------------------------------------------------------------------------------


def tavily_reply(content="Der Artikeltext.", url="https://a.example/source"):
    return httpx.Response(200, json={"results": [{"url": url, "raw_content": content}], "failed_results": []})


def test_tavily_request_and_success():  # N13
    handler, seen = recorder(tavily_reply())
    out = call(fetchers.tavily, handler, U, "tv-key")
    request = seen[0]
    assert (request.method, str(request.url)) == ("POST", "https://api.tavily.com/extract")
    assert request.headers["authorization"] == "Bearer tv-key"
    assert json.loads(request.content) == {
        "urls": [U],
        "extract_depth": "advanced",
        "format": "markdown",
        "timeout": 30,
    }
    assert out == {"title": "", "content": "Der Artikeltext.", "final_url": None}  # results[0].url is no final URL


@pytest.mark.parametrize(("deadline", "timeout"), [(40.0, 30), (35.0, 30), (30.0, 25), (20.9, 15), (6.0, 1), (3.0, 1)])
def test_tavily_body_timeout(deadline, timeout):  # N9: min(30, deadline - 5), at least 1
    handler, seen = recorder(tavily_reply())
    call(fetchers.tavily, handler, U, "k", deadline=deadline)
    assert json.loads(seen[0].content)["timeout"] == timeout


def test_tavily_failed_result_is_an_error_with_tavilys_text():  # N13
    response = httpx.Response(200, json={"results": [], "failed_results": [{"url": U, "error": "Failed to fetch"}]})
    out = call(fetchers.tavily, reply(response), U, "k")
    assert out == {"error": "Tavily: Failed to fetch", "code": "failed"}


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, json={"results": []}), {"error": "Tavily: no result", "code": "no_result"}),
        (httpx.Response(200, json={"results": ["x"]}), {"error": "Tavily: no result", "code": "no_result"}),
        (httpx.Response(200, text="<html>"), {"error": "Tavily: malformed reply", "code": "malformed"}),
    ],
)
def test_tavily_no_result(response, expected):
    assert call(fetchers.tavily, reply(response), U, "k") == expected


@pytest.mark.parametrize("status", [402, 432, 433])
def test_tavily_quota_status(status):  # N16: 432 plan limit, 433 pay-as-you-go limit
    out = call(fetchers.tavily, reply(httpx.Response(status, json={"detail": {"error": "limit"}})), U, "k")
    assert out == {"error": f"Tavily: API {status}: limit", "code": f"api_{status}", "quota": True}


def test_tavily_429_is_no_quota():  # N16
    out = call(fetchers.tavily, reply(httpx.Response(429, json={"detail": {"error": "rate limit"}})), U, "k")
    assert out == {"error": "Tavily: API 429: rate limit", "code": "api_429"}


# --- A3 Keenable -----------------------------------------------------------------------------------


def test_keenable_request_and_success():  # A3
    handler, seen = recorder(httpx.Response(200, json={"url": "https://a.example/", "title": "K", "content": "Kopie"}))
    out = call(fetchers.keenable, handler, "https://a.example/?q=1", "ke-key")
    request = seen[0]
    assert request.method == "GET" and request.url.params["url"] == "https://a.example/?q=1"
    assert request.headers["authorization"] == "Bearer ke-key"
    assert request.headers["x-keenable-title"] == "hermes-extract-chain"
    assert out == {"title": "K", "content": "Kopie", "final_url": "https://a.example/"}


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(422, json={"error": "Unprocessable entity", "message": "The page is behind a login"}),
            {"error": "Keenable: The page is behind a login", "code": "http_422"},
        ),
        (httpx.Response(504, text="Gateway timeout"), {"error": "Keenable: Gateway timeout", "code": "http_504"}),
        (httpx.Response(500), {"error": "Keenable: HTTP 500", "code": "http_500"}),
        (httpx.Response(429), {"error": "Keenable: HTTP 429", "code": "http_429"}),  # N16: no quota
        (httpx.Response(402), {"error": "Keenable: HTTP 402", "code": "http_402", "quota": True}),
        (httpx.Response(200, text="<html>"), {"error": "Keenable: malformed reply", "code": "malformed"}),
        (httpx.Response(200, json=["no", "dict"]), {"error": "Keenable: malformed reply", "code": "malformed"}),
    ],
)
def test_keenable_errors(response, expected):
    assert call(fetchers.keenable, reply(response), U, "k") == expected


# --- A0, A4, A5, N15: all providers ----------------------------------------------------------------


@pytest.mark.parametrize("provider", FETCHES)
def test_deadline(provider):  # A0, N9: the deadline bounds the whole request, whatever httpx does
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    assert fetch_of(provider, slow, deadline=0.05) == {"error": f"{provider}: timeout", "code": "timeout"}


@pytest.mark.parametrize("provider", FETCHES)
def test_transport_error(provider):  # S6
    def down(request):
        raise httpx.ConnectError("refused")

    assert fetch_of(provider, down) == {"error": f"{provider}: ConnectError", "code": "ConnectError"}


@pytest.mark.parametrize("provider", FETCHES)
def test_status_300_is_an_error(provider):  # A5: a redirect of an API is not followed and counts as an error
    out = fetch_of(provider, reply(httpx.Response(307, headers={"Location": "https://elsewhere.example/"})))
    assert out["code"] in ("api_307", "http_307") and "quota" not in out


@pytest.mark.parametrize("provider", FETCHES)
def test_key_is_masked_as_sent_and_percent_encoded(provider):  # N15, S3
    def echo(request):
        return httpx.Response(401, text="keys SE/CRET+KEY1 and se%2Fcret%2Bkey1 and SE%2fCRET%2bKEY1 rejected")

    out = fetch_of(provider, echo, key="se/cret+key1")
    assert out["error"].endswith("keys [key] and [key] and [key] rejected")


@pytest.mark.parametrize("provider", FETCHES)
def test_key_echoed_from_the_authorization_header_is_masked(provider):  # S3
    echo = lambda r: httpx.Response(401, text=f"invalid key {r.headers['authorization']}")  # noqa: E731
    assert fetch_of(provider, echo)["error"].endswith("invalid key Bearer [key]")


def test_key_in_an_unlocker_error_is_masked():  # S3, N11 (b)
    brd = {"x-brd-error": "bad token bd-SECRET", "x-brd-error-code": "client_10000"}
    out = call(fetchers.brightdata, reply(bd_reply(502, "", headers=brd)), U, "bd-SECRET", "z")
    assert out["error"] == "Bright Data: client_10000 bad token [key]"


def test_key_below_eight_characters_is_not_masked():  # S3
    out = call(fetchers.keenable, reply(httpx.Response(401, text="bad key k-12345")), U, "k-12345")
    assert out["error"] == "Keenable: bad key k-12345"


def test_error_detail_truncated():  # A4
    out = call(fetchers.keenable, reply(httpx.Response(500, text="x" * 500)), U, "k")
    assert out["error"] == "Keenable: " + "x" * 200


def test_control_characters_in_an_error_become_spaces():  # A4: one printable line
    out = call(fetchers.keenable, reply(httpx.Response(500, text="a\x1b[31mb\x00c​d\ne")), U, "k")
    assert out["error"] == "Keenable: a [31mb c d e"


def test_megabyte_error_page_gives_a_short_error():  # A4, N15: page excerpts in errors stay short
    page = "<p>error</p>  " * 400_000 + "ke-SECRET"
    out = call(fetchers.keenable, reply(httpx.Response(502, text=page)), U, "ke-SECRET")
    assert out["error"] == ("Keenable: " + "<p>error</p> " * 20)[:210]


# --- gaps found in the review against the spec (2026-10-18) -------------------------------------------


@pytest.mark.parametrize(("status", "failed"), [(399, False), (400, True)])
def test_brightdata_target_status_boundary(status, failed):  # N11 (c): from 400 on the target page failed
    out = call(fetchers.brightdata, reply(bd_reply(status, "# Text")), U, "bd-key", "z")
    assert bool(out.get("error")) is failed


@pytest.mark.parametrize(("status", "failed"), [(399, False), (400, True)])
def test_jina_warning_boundary(status, failed):  # N12: from 400 on the warning is an error of the target page
    head = f"Title: T\nWarning: Target URL returned error {status}: x\n"
    out = call(fetchers.jina, reply(httpx.Response(200, text=jina_text(head=head))), U, "jn-key")
    assert bool(out.get("error")) is failed


def test_jina_header_block_only_in_the_first_4000_characters():  # N12: a late "Markdown Content:" is page text
    text = "Warning: Target URL returned error 404\n" + "x" * 4000 + "\nMarkdown Content:\nText"
    out = call(fetchers.jina, reply(httpx.Response(200, text=text)), U, "jn-key")
    assert out == {"title": "", "content": text, "final_url": None}
