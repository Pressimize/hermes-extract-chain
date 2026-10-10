import asyncio
import logging
import re

import pytest

from extract_chain.chain import (
    NOTE_FIRECRAWL,
    NOTE_KEENABLE,
    NOTE_PAYWALL,
    NOTE_PDF,
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
        ("x" * 20, None, "ok"),
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
