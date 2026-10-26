"""REST calls of the five stages (N11-N16, A0-A5); no network, httpx.MockTransport only."""

import asyncio
import json

import httpx
import pytest

from extract_chain import chain, fetchers

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


# A1, D38: error headers a target page sent itself; Bright Data passes them on (probe 2026-10-19)
FORGED = {"x-brd-error": "probe-target", "x-brd-error-code": "client_10002", "x-brd-err-code": "client_10020"}


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


def test_brightdata_target_headers_with_a_body_are_no_error():  # A1, D38: the target page sent them (probe 2026-10-19)
    out = call(fetchers.brightdata, reply(bd_reply(200, "# Text", headers=FORGED)), U, "bd-key", "z")
    assert out == {"title": "", "content": "# Text", "final_url": None}


def test_brightdata_target_headers_do_not_hide_the_target_status():  # A1, D38
    out = call(fetchers.brightdata, reply(bd_reply(404, "<html>gone</html>", headers=FORGED)), U, "bd-key", "z")
    assert out["code"] == "target_404" and "quota" not in out


@pytest.mark.parametrize("body", ["", " \n ", None])
def test_brightdata_inner_headers_count_with_an_empty_body(body):  # A1, D38: an Unlocker error has no body
    brd = {"x-brd-error": "Could not resolve host", "x-brd-error-code": "proxy_error"}
    out = call(fetchers.brightdata, reply(bd_reply(502, body, headers=brd)), U, "bd-key", "z")
    assert out["code"] == "brd_proxy_error"


def test_brightdata_outer_headers_count_with_a_body():  # A1: outer headers come from Bright Data itself
    brd = {"x-brd-error": "blocked", "x-brd-error-code": "proxy_error"}
    out = call(fetchers.brightdata, reply(bd_reply(200, "# Text", outer_headers=brd)), U, "bd-key", "z")
    assert out["code"] == "brd_proxy_error"


@pytest.mark.parametrize(
    ("outer", "code", "expected", "quota"),
    [
        (500, "client_10100", "brd_client_10100", True),  # a quota code
        (402, "foo", "brd_foo", True),  # the outer status means a quota
        (500, "proxy_error", "brd_proxy_error", False),
        (429, "sr_rate_limit", "brd_sr_rate_limit", False),
    ],
)
def test_brightdata_error_headers_with_an_outer_error_status(outer, code, expected, quota):  # A1, K7
    response = httpx.Response(outer, text="error", headers={"x-brd-error": "text", "x-brd-error-code": code})
    out = call(fetchers.brightdata, reply(response), U, "bd-key", "z")
    assert out["code"] == expected and out.get("quota", False) is quota


def test_brightdata_unknown_zone_is_an_api_error():  # A1, K7: probe 2026-10-19, no x-brd headers, no pause
    out = call(fetchers.brightdata, reply(httpx.Response(400, text='zone "zz" not found')), U, "bd-key", "z")
    assert out == {"error": 'Bright Data: API 400: zone "zz" not found', "code": "api_400"}


@pytest.mark.parametrize("body", ["%PDF-1.7\n%\ufffd\ufffd binary", "\n  %PDF-1.5 x"])
def test_brightdata_raw_pdf_is_an_error(body):  # A1, D39: Bright Data passes PDF files on as raw bytes
    out = call(fetchers.brightdata, reply(bd_reply(200, body)), U, "bd-key", "z")
    assert out == {"error": "Bright Data: PDF file, not text", "code": "pdf"}


@pytest.mark.parametrize(
    ("text", "pdf"),
    [
        ("%PDF-1.4", True),
        ("%PDFx", False),
        (" %PDF-", True),
        ("PDF-1.4", False),
        ("# A text about %PDF-1.4 files", False),
        ("%pdf-1.4", False),
        ("", False),
    ],
)
def test_is_pdf(text, pdf):  # A1, D39: only the file header at the start
    assert fetchers.is_pdf(text) is pdf


# --- N12 Jina --------------------------------------------------------------------------------------


def jina_reply(text="Der Artikeltext.", status=200, **data):
    return httpx.Response(status, json={"code": 200, "status": 20000, "data": {"text": text, **data}})


def jina_fetch(response, key="jn-key"):
    return call(fetchers.jina, reply(response), U, key)


def test_jina_request():  # N12, A7: query string appended unchanged, JSON with text and link list
    handler, seen = recorder(jina_reply())
    url = "https://a.example/x?q=a%20b&page=2"
    call(fetchers.jina, handler, url, "jn-key")
    request = seen[0]
    assert (request.method, str(request.url)) == ("GET", "https://r.jina.ai/" + url)
    assert request.headers["accept"] == "application/json" and request.headers["x-return-format"] == "text"
    assert request.headers["x-with-links-summary"] == "all"
    assert request.headers["authorization"] == "Bearer jn-key"


def test_jina_without_key_sends_no_authorization():  # N3, A7: the other headers stay
    handler, seen = recorder(jina_reply())
    call(fetchers.jina, handler, U, "")
    assert "authorization" not in seen[0].headers
    assert seen[0].headers["accept"] == "application/json" and seen[0].headers["x-with-links-summary"] == "all"


def test_jina_headers_constant_is_not_changed_by_a_key():  # A7: the key goes into a copy
    call(fetchers.jina, reply(jina_reply()), U, "jn-key")
    assert "Authorization" not in fetchers.JINA_HEADERS


def test_jina_success_without_title():  # A7: the content is the page text alone, no text_at
    out = jina_fetch(jina_reply("Der Artikeltext.", title=""))
    assert out == {"title": "", "content": "Der Artikeltext.", "final_url": None, "links": []}


def test_jina_title_line_in_front_and_text_at():  # A7, E2, D37
    out = jina_fetch(jina_reply("Der Artikeltext.", title="Ein Titel"))
    head = "Title: Ein Titel\n\n"
    assert out == {
        "title": "Ein Titel",
        "content": head + "Der Artikeltext.",
        "final_url": None,  # data.url is the requested URL, not a final URL
        "links": [],
        "text_at": len(head),
    }


def test_jina_final_url_is_not_taken_from_data_url():  # A7
    assert jina_fetch(jina_reply(url="https://other.example/y"))["final_url"] is None


def test_jina_title_whitespace_is_collapsed_to_one_line():  # A7
    out = jina_fetch(jina_reply("Text", title="  Ein \n\n Titel\t mit   Raum "))
    assert out["title"] == "Ein Titel mit Raum" and out["content"] == "Title: Ein Titel mit Raum\n\nText"
    assert out["text_at"] == len("Title: Ein Titel mit Raum\n\n")


@pytest.mark.parametrize("title", ["", "  \n\t ", None, 5, ["T"], {"a": 1}])
def test_jina_no_usable_title_gives_no_text_at(title):  # A7: a blank or non-string title is no title
    out = jina_fetch(jina_reply("Text", title=title))
    assert out["title"] == "" and out["content"] == "Text" and "text_at" not in out


def test_jina_missing_title_gives_no_text_at():  # A7
    assert "text_at" not in jina_fetch(jina_reply("Text"))


@pytest.mark.parametrize("data", [{"text": None}, {}])
def test_jina_text_none_or_missing_is_an_empty_page(data):  # A7, E2
    out = jina_fetch(httpx.Response(200, json={"data": data}))
    assert out == {"title": "", "content": "", "final_url": None, "links": []}


def test_jina_empty_page_with_title_keeps_the_title_line():  # A7, E2: text_at at the end, the page is empty
    out = jina_fetch(httpx.Response(200, json={"data": {"title": "T", "text": None}}))
    assert out["content"] == "Title: T\n\n" and out["text_at"] == len(out["content"])
    assert chain.classify(out, full_page=True) == "empty"


@pytest.mark.parametrize("text", [5, True, ["a"], {"a": "b"}, 1.5])
def test_jina_text_that_is_no_string_is_malformed(text):  # A7
    out = jina_fetch(httpx.Response(200, json={"data": {"title": "T", "text": text}}))
    assert out == {"error": "Jina: malformed reply", "code": "malformed"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"data": "text"}),
        httpx.Response(200, json={"data": [1]}),
        httpx.Response(200, json={"data": None}),
        httpx.Response(200, json={}),
        httpx.Response(200, json=["data"]),
        httpx.Response(200, json="text"),
        httpx.Response(200, text="Title: x\n\nMarkdown Content:\nText"),  # the old text reply is no JSON
        httpx.Response(200, text=""),
    ],
)
def test_jina_reply_without_a_data_object_is_malformed(response):  # A7
    assert jina_fetch(response) == {"error": "Jina: malformed reply", "code": "malformed"}


@pytest.mark.parametrize("status", [403, 404, 410, 422, 500])
def test_jina_http_status_is_the_target_status(status):  # A7
    out = jina_fetch(jina_reply("Not found text", title="Not found", httpStatus=status))
    assert out == {"error": f"Jina: target HTTP {status}", "code": f"target_{status}", "target_status": status}


@pytest.mark.parametrize(("status", "failed"), [(200, False), (301, False), (399, False), (400, True)])
def test_jina_http_status_boundary(status, failed):  # A7: from 400 on the target page failed
    assert bool(jina_fetch(jina_reply(httpStatus=status)).get("error")) is failed


@pytest.mark.parametrize("status", [True, False, "404", "400", 404.0, None, [404], {"a": 404}])
def test_jina_http_status_that_is_no_integer_is_no_status(status):  # A7: bool and strings are not a status
    out = jina_fetch(jina_reply(httpStatus=status))
    assert "error" not in out and out["content"] == "Der Artikeltext."


def test_jina_http_status_is_checked_before_the_text():  # A7
    out = jina_fetch(jina_reply(5, httpStatus=404))
    assert out == {"error": "Jina: target HTTP 404", "code": "target_404", "target_status": 404}


def test_jina_links_as_a_list_of_pairs():  # A7
    links = [["Erster Link", "https://h.example/1"], ["Zweiter Link", "https://h.example/2"]]
    assert jina_fetch(jina_reply(links=links))["links"] == [(t, u) for t, u in links]


def test_jina_links_as_an_object_from_text_to_url():  # A7: the older form
    out = jina_fetch(jina_reply(links={"Erster Link": "https://h.example/1", "Zweiter": "https://h.example/2", "x": 1}))
    assert out["links"] == [("Erster Link", "https://h.example/1"), ("Zweiter", "https://h.example/2")]


def test_jina_links_with_broken_entries_skip_only_those():  # A7: entries that are no pair of strings
    links = [
        ["Gut", "https://h.example/1"],
        "text",
        None,
        5,
        ["nur eins"],
        ["a", "b", "c"],
        [1, "https://h.example/2"],
        ["Text", 2],
        ["Text", None],
        [],
        {"a": "b"},
        ["Auch gut", "https://h.example/3"],
    ]
    out = jina_fetch(jina_reply(links=links))
    assert out["links"] == [("Gut", "https://h.example/1"), ("Auch gut", "https://h.example/3")]


@pytest.mark.parametrize("links", [None, "text", 5, True])
def test_jina_links_missing_or_other_value_is_an_empty_list(links):  # A7
    assert jina_fetch(jina_reply(links=links))["links"] == []
    assert jina_fetch(jina_reply())["links"] == []


def test_jina_links_are_not_filtered_by_the_fetcher():  # A7: V16a filters, the fetcher returns them as sent
    links = [["ab", "ftp://h.example/"], ["Text", U], ["Text", U]]
    assert jina_fetch(jina_reply(links=links))["links"] == [(t, u) for t, u in links]


def test_jina_api_errors():  # N12, N16: 402 is the API's empty balance, 429 its rate limit
    out = call(fetchers.jina, reply(httpx.Response(402, json={"message": "Insufficient balance"})), U, "jn-key")
    assert out == {"error": "Jina: API 402: Insufficient balance", "code": "api_402", "quota": True}
    out = call(fetchers.jina, reply(httpx.Response(429, text="Too many requests")), U, "")
    assert out == {"error": "Jina: API 429: Too many requests", "code": "api_429"}
    assert "quota" not in out


def test_jina_title_marker_still_classifies_and_lengths_start_at_text_at():  # A7, E2, D37
    out = jina_fetch(jina_reply("Checking connection, please wait. " * 2, title="Just a moment..."))
    assert chain.classify(out, full_page=True) == "challenge"  # the marker stands in the title line only
    body = jina_fetch(jina_reply("x" * 450, title="T" * 100))
    assert chain._length(body) == 450 and chain.classify(body, full_page=True) == "thin"
    body = jina_fetch(jina_reply("x" * 19, title="T" * 100))
    assert chain.classify(body, full_page=True) == "empty"


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


def test_key_in_an_unlocker_error_with_an_outer_error_status_is_masked():  # S3, A1
    response = httpx.Response(500, headers={"x-brd-error": "bad bd-SECRET", "x-brd-error-code": "proxy_error"})
    out = call(fetchers.brightdata, reply(response), U, "bd-SECRET", "z")
    assert out["error"] == "Bright Data: proxy_error bad [key]"


def test_key_as_an_unlocker_code_is_no_code():  # S3, L1: the code goes into the log line unmasked
    brd = {"x-brd-error": "bad", "x-brd-error-code": "bd_secret_key_1"}
    out = call(fetchers.brightdata, reply(bd_reply(502, "", headers=brd)), U, "bd_secret_key_1", "z")
    assert out["code"] == "brd_unlocker" and "secret" not in str(out)


def test_brightdata_null_header_value_is_no_error():  # A1: JSON null in the field headers
    out = call(fetchers.brightdata, reply(bd_reply(200, "", headers={"x-brd-error": None})), U, "bd-key", "z")
    assert "error" not in out and out["content"] == ""


def test_brightdata_target_status_before_pdf():  # A1: a failing target page stays a target status
    out = call(fetchers.brightdata, reply(bd_reply(404, "%PDF-1.7 x")), U, "bd-key", "z")
    assert out["code"] == "target_404"


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


def test_brightdata_status_code_as_text():  # N11 (c): documented as a number; a string is read as well
    out = call(fetchers.brightdata, reply(bd_reply("404", "")), U, "bd-key", "z")
    assert out["code"] == "target_404" and out["target_status"] == 404


def test_brightdata_empty_error_header_is_no_error():  # N11 (b): only a header with a value is an Unlocker error
    out = call(fetchers.brightdata, reply(bd_reply(200, "# Text", headers={"x-brd-error-code": ""})), U, "bd-key", "z")
    assert out == {"title": "", "content": "# Text", "final_url": None}
