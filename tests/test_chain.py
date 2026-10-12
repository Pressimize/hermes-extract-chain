import asyncio
import logging
import re

import pytest

from extract_chain.chain import (
    NOTE_CHECK,
    NOTE_FIRECRAWL,
    NOTE_KEENABLE,
    NOTE_PAYWALL,
    NOTE_PDF,
    NOTE_REDIRECT,
    NOTE_THIN,
    NOTE_THIN_ALONE,
    NOTE_THIN_BOTH,
    NOTE_WALL,
    PAYWALL,
    PAYWALL_DEFINITE,
    WALL,
    classify,
    run_chain,
)

ARTICLE = "Ein ganz normaler Artikeltext mit mehreren Sätzen. " * 20
WALL_TEXT = "Cookies zustimmen oder PUR-Abo abschließen. Einwilligung erteilen."
PAYWALL_TEXT = ARTICLE + "Das war die Leseprobe."
URL = "https://news.example/artikel"


def doc(content="", error=None, code=None, title="T"):
    d = {"title": title, "content": content, "error": error}
    if code:
        d["code"] = code
    return d


def tf_error(code):
    return doc(error=f"TinyFish: {code}", code=code)


# --- E1-E5 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "error", "expected"),
    [
        ("anything", "TinyFish: bot_blocked", "error"),  # E1 wins over content
        ("x" * 19, None, "empty"),  # E2 boundary
        ("x" * 20, None, "thin"),  # E8: 20 characters is no longer ok
        ("<!DOCTYPE html><html><head></head><body></body></html>", None, "empty"),  # E2 strips tags
        (WALL_TEXT, None, "wall"),  # E3 two markers
        ("Cookies zustimmen. " + ARTICLE, None, "ok"),  # E3 one marker only
        (PAYWALL_TEXT, None, "paywall"),  # E4 definite marker
        (ARTICLE + "SPIEGEL+", None, "ok"),  # E4 one general marker
        (ARTICLE + "SPIEGEL+ Jetzt weiterlesen", None, "paywall"),  # E4 two general markers
        (WALL_TEXT + " Das war die Leseprobe. " + ARTICLE, None, "wall"),  # wall before paywall
    ],
)
def test_classify(content, error, expected):
    assert classify(doc(content, error)) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("I'm not a robot. Please click to confirm.", "challenge"),  # E7 observed: TinyFish, 41 characters
        ("Checking the site connection security. Please wait a moment while we verify.", "challenge"),
        ("Verify you are human by completing the action below.", "challenge"),
        ("Please verify that you are human.", "challenge"),
        ("Enable JavaScript and cookies to continue", "challenge"),
        ("Click the button below to continue shopping", "challenge"),
        ("A required part of this site couldn’t load. Try again.", "challenge"),  # typographic apostrophe
        ("Access Denied. You do not have permission.", "challenge"),
        ("<div><b>Just a moment... checking</b></div>", "challenge"),  # case-insensitive, tags removed first
        ("A footer with imprint and links only. " * 3, "thin"),  # E8 observed: footer text
        ("a" * 499, "thin"),
        ("a" * 500, "ok"),
        ("<p>" + "a" * 499 + "</p>" * 20, "thin"),  # tags do not count
        ("<p>" + "a" * 500 + "</p>", "ok"),
        ("captcha " + "a" * 1491, "challenge"),  # 1,499 visible characters
        ("captcha " + "a" * 1492, "ok"),  # 1,500: the cap
        (ARTICLE * 3 + " The captcha on this site is explained here.", "ok"),  # long article that mentions a marker
        (WALL_TEXT, "wall"),  # wall and paywall keep their place before thin
        ("Das war die Leseprobe.", "paywall"),
    ],
)
def test_classify_challenge_and_thin(content, expected):  # E7, E8
    assert classify(doc(content)) == expected


def test_challenge_wins_over_wall():  # E7 before E3
    assert classify(doc("Just a moment. " + WALL_TEXT)) == "challenge"


def test_each_marker_is_in_one_list_only():  # E6
    markers = WALL + PAYWALL_DEFINITE + PAYWALL
    assert len(markers) == len(set(markers))


@pytest.mark.parametrize("markers", [WALL, PAYWALL])
def test_no_marker_lies_inside_another_marker_of_its_list(markers):  # E6
    plain = [m for m in markers if not set(m) & set("\\[](|?+")]  # markers that are their own example text
    assert [(m, text) for text in plain for m in markers if m != text and re.search(m, text, re.IGNORECASE)] == []


def test_cookie_zustimmung_counts_once():
    assert classify(doc("Cookie-Zustimmung. " + ARTICLE)) == "ok"
    assert classify(doc("Cookie-Zustimmung. Ihre Zustimmung fehlt. " + ARTICLE)) == "wall"


def test_wall_window_short_text_checked_completely():
    text = "a" * (3999 - len(WALL_TEXT)) + WALL_TEXT
    assert len(text) == 3999
    assert classify(doc(text)) == "wall"


def test_paywall_area_full_page_ignores_last_quarter():
    footer = " SPIEGEL+ Jetzt weiterlesen"
    page = "a" * (8000 - len(footer)) + footer  # markers in the last 25 %: footer of a whole page
    assert classify(doc(page), full_page=True) == "ok"
    assert classify(doc(page)) == "paywall"  # main-content providers: whole text counts
    early = "a" * 5000 + footer + "a" * 2000  # markers at about 63 %
    assert classify(doc(early), full_page=True) == "paywall"
    short = "a" * 3000 + footer  # below 4000 characters the whole text counts
    assert classify(doc(short), full_page=True) == "paywall"


def test_firecrawl_footer_markers_no_paywall_note():
    page = ARTICLE * 10 + " SPIEGEL+ Jetzt weiterlesen Mehrfachnutzung erkannt"
    out = run(tf_error("bot_blocked"), Fake(doc(page)), Fake())
    assert out["content"] == NOTE_FIRECRAWL.format(reason="TinyFish: bot_blocked") + "\n\n" + page


def test_wall_window_long_text_only_start():
    text = "a" * (4000 - len(WALL_TEXT)) + WALL_TEXT
    assert len(text) == 4000
    assert classify(doc(text)) == "ok"
    assert classify(doc("a" * 1990 + WALL_TEXT + "a" * 3000)) == "ok"  # second marker beyond 2000
    assert classify(doc(WALL_TEXT + "a" * 5000)) == "wall"


# --- K2-K5, V1-V6 ------------------------------------------------------------------------------------


class Fake:
    """Async fetch stand-in that counts calls (K5)."""

    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    async def __call__(self):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def run(tinyfish, firecrawl=None, keenable=None):
    return asyncio.run(run_chain(URL, tinyfish, firecrawl, keenable))


def test_tinyfish_ok_no_note_no_fallback():
    fc, ke = Fake(doc(ARTICLE)), Fake(doc(ARTICLE))
    out = run(doc(ARTICLE), fc, ke)
    assert out == {"url": URL, "title": "T", "content": ARTICLE, "error": None, "metadata": {"sourceURL": URL}}
    assert fc.calls == ke.calls == 0


def test_tinyfish_paywall_note_only():
    fc, ke = Fake(doc(ARTICLE)), Fake(doc(ARTICLE))
    out = run(doc(PAYWALL_TEXT), fc, ke)
    assert out["content"] == f"{NOTE_PAYWALL}\n\n{PAYWALL_TEXT}"
    assert fc.calls == ke.calls == 0


@pytest.mark.parametrize(
    "code", ["page_not_found", "login_required", "invalid_url", "invalid_redirect_url", "content_too_large"]
)
def test_tinyfish_final_codes_pass_through(code):
    fc, ke = Fake(doc(ARTICLE)), Fake(doc(ARTICLE))
    out = run(tf_error(code), fc, ke)
    assert out["error"] == f"TinyFish: {code}" and out["content"] == ""
    assert fc.calls == ke.calls == 0


def test_firecrawl_after_tinyfish_error():
    fc, ke = Fake(doc(ARTICLE, title="FC")), Fake(doc(ARTICLE))
    out = run(tf_error("bot_blocked"), fc, ke)
    assert out["content"] == NOTE_FIRECRAWL.format(reason="TinyFish: bot_blocked") + "\n\n" + ARTICLE
    assert out["title"] == "FC" and out["error"] is None
    assert (fc.calls, ke.calls) == (1, 0)


def test_firecrawl_after_tinyfish_empty():
    out = run(doc(""), Fake(doc(ARTICLE)), Fake())
    assert out["content"].startswith(NOTE_FIRECRAWL.format(reason="TinyFish: empty page"))


def test_firecrawl_paywall_two_notes():
    out = run(tf_error("timeout"), Fake(doc(PAYWALL_TEXT)), Fake(doc(ARTICLE)))
    note = NOTE_FIRECRAWL.format(reason="TinyFish: timeout")
    assert out["content"] == f"{note}\n{NOTE_PAYWALL}\n\n{PAYWALL_TEXT}"


def test_tinyfish_wall_skips_firecrawl():
    fc, ke = Fake(doc(ARTICLE)), Fake(doc(ARTICLE, title="KE"))
    out = run(doc(WALL_TEXT), fc, ke)
    assert out["content"] == NOTE_KEENABLE.format(reasons="TinyFish: consent wall") + "\n\n" + ARTICLE
    assert out["title"] == "KE"
    assert (fc.calls, ke.calls) == (0, 1)


def test_keenable_after_firecrawl_wall():
    out = run(tf_error("bot_blocked"), Fake(doc(WALL_TEXT)), Fake(doc(ARTICLE)))
    reasons = "TinyFish: bot_blocked; Firecrawl: consent wall"
    assert out["content"].startswith(NOTE_KEENABLE.format(reasons=reasons) + "\n\n")


def test_keenable_paywall_two_notes():
    out = run(doc(WALL_TEXT), Fake(), Fake(doc(PAYWALL_TEXT)))
    note = NOTE_KEENABLE.format(reasons="TinyFish: consent wall")
    assert out["content"] == f"{note}\n{NOTE_PAYWALL}\n\n{PAYWALL_TEXT}"


def test_all_fail_joined_error():
    out = run(
        tf_error("bot_blocked"),
        Fake(doc(error="Firecrawl: target HTTP 403")),
        Fake(doc(error="Keenable: Gateway timeout")),
    )
    assert out["error"] == "TinyFish: bot_blocked; Firecrawl: target HTTP 403; Keenable: Gateway timeout"
    assert out["content"] == ""


def test_wall_without_alternative_returns_wall_page():
    out = run(doc(WALL_TEXT), Fake(), Fake(doc(error="Keenable: The page is behind a login or paywall")))
    reasons = "TinyFish: consent wall; Keenable: The page is behind a login or paywall"
    assert out["content"] == NOTE_WALL.format(reasons=reasons) + "\n\n" + WALL_TEXT
    assert out["error"] is None


def test_firecrawl_wall_page_kept_when_keenable_fails():
    fc_wall = WALL_TEXT + " (Firecrawl)"
    out = run(tf_error("bot_blocked"), Fake(doc(fc_wall)), Fake(doc("")))
    assert out["content"].endswith(fc_wall)
    assert "Keenable: empty page" in out["content"].splitlines()[0]


def test_missing_keys_skip_stages():
    out = run(tf_error("bot_blocked"), None, None)
    assert out["error"] == "TinyFish: bot_blocked; Firecrawl: no API key; Keenable: no API key"


def test_exception_in_stage_becomes_error():
    ke = Fake(doc(ARTICLE))
    out = run(tf_error("bot_blocked"), Fake(exc=RuntimeError("boom")), ke)
    assert "Firecrawl: RuntimeError" in out["content"].splitlines()[0]
    assert ke.calls == 1


def test_log_line(caplog):
    caplog.set_level(logging.INFO, logger="extract_chain.chain")
    run(tf_error("bot_blocked"), Fake(doc(error="Firecrawl: API 429: busy")), Fake(doc(ARTICLE)))
    run(doc(ARTICLE))
    lines = [r.getMessage() for r in caplog.records]
    assert lines == [
        "extract-chain news.example: tinyfish=bot_blocked firecrawl=error keenable=ok",
        "extract-chain news.example: tinyfish=ok",
    ]


def test_log_line_never_raises_or_shows_full_url(caplog):
    caplog.set_level(logging.INFO, logger="extract_chain.chain")
    out = asyncio.run(run_chain("http://[::1", doc(ARTICLE), None, None))  # urlsplit raises ValueError here
    asyncio.run(run_chain("file:///tmp/x?token=abc", doc(ARTICLE), None, None))
    asyncio.run(run_chain(123, doc(ARTICLE), None, None))  # urlsplit raises another class for a non-string
    assert out["error"] is None
    assert [r.getMessage() for r in caplog.records] == [
        "extract-chain <invalid url>: tinyfish=ok",
        "extract-chain <no host>: tinyfish=ok",
        "extract-chain <invalid url>: tinyfish=ok",
    ]


def test_pdf_cap_note_and_final_url():
    page = doc(ARTICLE)
    page.update(pdf_pages=(30, 120), final_url="https://news.example/final")
    out = run(tf_error("timeout"), Fake(page), Fake())
    lines = out["content"].splitlines()
    assert lines[1] == NOTE_PDF.format(shown=30, total=120)
    assert out["metadata"] == {"sourceURL": URL, "finalURL": "https://news.example/final"}


# --- E7, E8 in the chain (K2, K3, K4), V8-V9 ------------------------------------------------------------

SHORT = ("Eine kurze Seite mit etwas Inhalt, aber unter fünfhundert Zeichen. " * 3).strip()
SHORTER = "Noch kürzer, aber echt, und auch noch lesbar."
BOT = "Please verify you are human."
THIN_REASON = f"TinyFish: very short page ({len(SHORT)} characters)"
OTHER = "https://other.example/x"


def test_tinyfish_thin_firecrawl_ok():
    fc, ke = Fake(doc(ARTICLE, title="FC")), Fake(doc(ARTICLE))
    out = run(doc(SHORT), fc, ke)
    assert out["content"] == NOTE_FIRECRAWL.format(reason=THIN_REASON) + "\n\n" + ARTICLE
    assert (fc.calls, ke.calls) == (1, 0)


def test_tinyfish_thin_firecrawl_paywall():
    out = run(doc(SHORT), Fake(doc(PAYWALL_TEXT)), Fake())
    assert out["content"] == f"{NOTE_FIRECRAWL.format(reason=THIN_REASON)}\n{NOTE_PAYWALL}\n\n{PAYWALL_TEXT}"


def test_both_thin_longer_page_wins_with_source_note():  # V8, V2
    longer = SHORT + " Und noch ein Satz."
    ke = Fake(doc(ARTICLE))
    out = run(doc(SHORT), Fake(doc(longer, title="FC")), ke)
    note = NOTE_THIN_BOTH.format(n=len(longer))
    assert out["content"] == f"{NOTE_FIRECRAWL.format(reason=THIN_REASON)}\n{note}\n\n{longer}"
    assert out["title"] == "FC" and ke.calls == 0


@pytest.mark.parametrize("firecrawl_text", [SHORT, SHORTER])
def test_both_thin_tinyfish_page_when_shorter_or_equal(firecrawl_text):  # V8, a tie goes to TinyFish
    ke = Fake(doc(ARTICLE))
    out = run(doc(SHORT, title="TF"), Fake(doc(firecrawl_text, title="FC")), ke)
    assert out["content"] == NOTE_THIN_BOTH.format(n=len(SHORT)) + "\n\n" + SHORT
    assert out["title"] == "TF" and ke.calls == 0


@pytest.mark.parametrize(
    ("firecrawl", "reason"),
    [
        (Fake(doc(error="Firecrawl: target HTTP 403")), "Firecrawl: target HTTP 403"),
        (None, "Firecrawl: no API key"),
        (Fake(doc("")), "Firecrawl: empty page"),
        (Fake(doc(BOT)), "Firecrawl: bot check page"),
        (Fake(doc(error="Firecrawl: API 402: no credits (paused for another 3 h)", code="paused")), None),
    ],
)
def test_thin_without_second_opinion_returns_tinyfish_page(firecrawl, reason):  # V9, D23
    ke = Fake(doc(ARTICLE))
    out = run(doc(SHORT), firecrawl, ke)
    reason = reason or firecrawl.result["error"]
    assert out["content"] == NOTE_THIN_ALONE.format(n=len(SHORT), reason=reason) + "\n\n" + SHORT
    assert out["error"] is None and ke.calls == 0


def test_thin_then_firecrawl_wall_returns_tinyfish_page():  # K3, D23: a short page is never dropped for a wall
    ke = Fake(doc(ARTICLE))
    out = run(doc(SHORT), Fake(doc(WALL_TEXT)), ke)
    assert out["content"] == NOTE_THIN_ALONE.format(n=len(SHORT), reason="Firecrawl: consent wall") + "\n\n" + SHORT
    assert out["error"] is None and ke.calls == 0


def test_challenge_then_firecrawl_ok():
    out = run(doc(BOT), Fake(doc(ARTICLE)), Fake())
    assert out["content"] == NOTE_FIRECRAWL.format(reason="TinyFish: bot check page") + "\n\n" + ARTICLE


@pytest.mark.parametrize(
    ("first", "reason"),
    [(tf_error("bot_blocked"), "TinyFish: bot_blocked"), (doc(BOT), "TinyFish: bot check page")],
)
def test_error_then_firecrawl_thin_returns_firecrawl_page(first, reason):  # V2, V8a
    ke = Fake(doc(ARTICLE))
    out = run(first, Fake(doc(SHORT)), ke)
    expected = NOTE_FIRECRAWL.format(reason=reason) + "\n" + NOTE_THIN.format(n=len(SHORT)) + "\n\n" + SHORT
    assert out["content"] == expected
    assert ke.calls == 0


def test_challenge_without_alternative_is_returned_with_note():  # V11
    reasons = "TinyFish: bot check page; Firecrawl: no API key; Keenable: no API key"
    out = run(doc(BOT), None, None)
    assert out["content"] == NOTE_CHECK.format(reasons=reasons) + "\n\n" + BOT and out["error"] is None
    reasons = "TinyFish: bot check page; Firecrawl: bot check page; Keenable: Gateway timeout"
    out = run(doc(BOT, title="TF"), Fake(doc(BOT + " (FC)", title="FC")), Fake(doc(error="Keenable: Gateway timeout")))
    assert out["content"] == NOTE_CHECK.format(reasons=reasons) + "\n\n" + BOT and out["title"] == "TF"


def test_firecrawl_challenge_page_kept_with_source_note():  # V2, V11
    fc = BOT + " (FC)"
    out = run(tf_error("bot_blocked"), Fake(doc(fc)), Fake(doc(error="Keenable: Gateway timeout")))
    reasons = "TinyFish: bot_blocked; Firecrawl: bot check page; Keenable: Gateway timeout"
    note = NOTE_FIRECRAWL.format(reason="TinyFish: bot_blocked")
    assert out["content"] == f"{note}\n{NOTE_CHECK.format(reasons=reasons)}\n\n{fc}"


def test_challenge_all_stages_without_a_page_is_still_an_error():
    out = run(
        tf_error("bot_blocked"), Fake(doc(error="Firecrawl: API 500")), Fake(doc(error="Keenable: Gateway timeout"))
    )
    assert out["error"] == "TinyFish: bot_blocked; Firecrawl: API 500; Keenable: Gateway timeout"
    out = run(tf_error("bot_blocked"), Fake(doc(error="Firecrawl: API 500")), Fake(doc(BOT)))
    assert out["error"] == "TinyFish: bot_blocked; Firecrawl: API 500; Keenable: bot check page"  # never kept


def test_wall_wins_over_challenge_page():  # V5 before V11
    out = run(doc(WALL_TEXT), Fake(), Fake(doc(BOT)))
    reasons = "TinyFish: consent wall; Keenable: bot check page"
    assert out["content"] == NOTE_WALL.format(reasons=reasons) + "\n\n" + WALL_TEXT
    out = run(doc(BOT), Fake(doc(WALL_TEXT)), Fake(doc(error="Keenable: Gateway timeout")))
    assert out["content"].startswith(
        NOTE_WALL.format(reasons="TinyFish: bot check page; Firecrawl: consent wall; Keenable: Gateway timeout")
    )


def test_keenable_thin_counts_as_ok_and_challenge_as_error():  # K4
    out = run(doc(WALL_TEXT), Fake(), Fake(doc(SHORT)))
    assert out["content"] == NOTE_KEENABLE.format(reasons="TinyFish: consent wall") + "\n\n" + SHORT
    out = run(tf_error("bot_blocked"), Fake(doc(error="Firecrawl: API 500")), Fake(doc(BOT)))
    assert out["error"] == "TinyFish: bot_blocked; Firecrawl: API 500; Keenable: bot check page"


def test_log_line_new_kinds(caplog):  # L1
    caplog.set_level(logging.INFO, logger="extract_chain.chain")
    run(doc(SHORT), Fake(doc(ARTICLE)))
    run(doc(BOT), Fake(doc(BOT)), Fake(doc(error="Keenable: HTTP 404", code="http_404")))
    assert [r.getMessage() for r in caplog.records] == [
        "extract-chain news.example: tinyfish=thin firecrawl=ok",
        "extract-chain news.example: tinyfish=challenge firecrawl=challenge keenable=http_404",
    ]


# --- V10 -----------------------------------------------------------------------------------------------


def redirected(requested, final):
    """Returns the content of a TinyFish page with the given final URL."""
    return asyncio.run(run_chain(requested, {**doc(ARTICLE), "final_url": final}, None, None))["content"]


@pytest.mark.parametrize(
    ("requested", "final"),
    [
        ("https://news.example/artikel", "https://other.example/artikel"),  # other host
        ("https://news.example/jobs", "https://www.other.example/jobs"),
        ("https://news.example/jobs?q=x", "https://news.example/"),  # path to root
        ("https://news.example/jobs?q=x", "https://news.example"),
        ("https://news.example/jobs", "https://news.example/de/"),  # path to locale root
        ("https://news.example/jobs", "https://news.example/en-US/"),
    ],
)
def test_redirect_note_added(requested, final):
    assert redirected(requested, final) == NOTE_REDIRECT.format(final=final) + "\n\n" + ARTICLE


@pytest.mark.parametrize(
    ("requested", "final"),
    [
        ("https://news.example/artikel", "https://www.news.example/artikel"),  # www only
        ("https://www.news.example/artikel", "https://news.example/artikel"),
        ("https://news.example/artikel", "http://news.example/artikel"),  # scheme only
        ("https://news.example/artikel", "https://news.example/artikel/"),  # trailing slash
        ("https://news.example/de", "https://news.example/de/"),  # same page, although a locale path
        ("https://news.example/artikel", "https://news.example/artikel?utm=1"),  # query
        ("https://news.example/artikel", "https://news.example/artikel#top"),  # fragment
        ("https://News.Example/Artikel", "https://news.example/artikel"),  # letter case
        ("https://news.example/", "https://news.example/de/"),  # requested path has no segment
        ("https://news.example/jobs", "https://news.example/jobs/list"),  # deeper path
        ("https://news.example/jobs", "https://news.example/deutsch/"),  # not locale-like
        ("https://news.example/jobs", None),  # no final URL
        ("https://news.example/jobs", ""),
        ("https://news.example/jobs", "/relative"),
        ("https://news.example/jobs", 123),  # not a string
        ("https://news.example/jobs", ["https://other.example/"]),
        ("http://[::1", OTHER),  # invalid requested URL
    ],
)
def test_no_redirect_note(requested, final):
    assert redirected(requested, final) == ARTICLE


def test_redirect_url_cut_to_200_characters_and_one_line():
    final = "https://other.example/" + "a" * 300
    assert redirected(URL, final).splitlines()[0] == NOTE_REDIRECT.format(final=final[:200])
    assert redirected(URL, "https://other.example/a\nb c").splitlines()[0] == NOTE_REDIRECT.format(
        final="https://other.example/a b c"
    )


def test_redirect_note_comes_after_the_other_notes():
    page = {**doc(ARTICLE), "final_url": OTHER, "pdf_pages": (30, 120)}
    lines = run(tf_error("timeout"), Fake(page), Fake())["content"].splitlines()
    assert lines[:3] == [
        NOTE_FIRECRAWL.format(reason="TinyFish: timeout"),
        NOTE_PDF.format(shown=30, total=120),
        NOTE_REDIRECT.format(final=OTHER),
    ]
    lines = asyncio.run(run_chain(URL, {**doc(PAYWALL_TEXT), "final_url": OTHER}, None, None))["content"].splitlines()
    assert lines[:2] == [NOTE_PAYWALL, NOTE_REDIRECT.format(final=OTHER)]
    thin = {**doc(SHORT), "final_url": OTHER}
    lines = run(thin, Fake(doc(error="Firecrawl: API 500")))["content"].splitlines()
    assert lines[:2] == [
        NOTE_THIN_ALONE.format(n=len(SHORT), reason="Firecrawl: API 500"),
        NOTE_REDIRECT.format(final=OTHER),
    ]
    keenable = {**doc(ARTICLE), "final_url": OTHER}
    lines = run(doc(WALL_TEXT), None, Fake(keenable))["content"].splitlines()
    assert lines[:2] == [NOTE_KEENABLE.format(reasons="TinyFish: consent wall"), NOTE_REDIRECT.format(final=OTHER)]
