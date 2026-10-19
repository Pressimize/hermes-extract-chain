"""Classification (E1-E8), checks (N7) and the chain of one URL (N5-N9, N17-N20, V3-V11, L1)."""

import asyncio
import logging
import re
import time

import pytest

from extract_chain import chain
from extract_chain.chain import (
    NOTE_CHECK,
    NOTE_COPY,
    NOTE_LIVE,
    NOTE_LONGEST,
    NOTE_LONGEST_COPY,
    NOTE_PAYWALL,
    NOTE_PDF,
    NOTE_REDIRECT,
    NOTE_WALL,
    PAYWALL,
    PAYWALL_DEFINITE,
    SUSPECT_CHECK,
    SUSPECT_JS,
    SUSPECT_PRINT,
    WALL,
    Stage,
    classify,
    run_chain,
    suspect,
)

ARTICLE = "Ein ganz normaler Artikeltext mit mehreren Sätzen. " * 20
LONG = ARTICLE * 3  # a reference copy at least 1.5 times as long as ARTICLE
WALL_TEXT = "Cookies zustimmen oder PUR-Abo abschließen. Einwilligung erteilen."
PAYWALL_TEXT = ARTICLE + "Das war die Leseprobe."
BOT = "Please verify you are human."
URL = "https://news.example/artikel"
OTHER = "https://other.example/x"
NAMES = {"brightdata": "Bright Data", "jina": "Jina", "firecrawl": "Firecrawl", "tavily": "Tavily"}


def doc(content="", error=None, code=None, title="T", **extra):
    d = {"title": title, "content": content, "error": error, **extra}
    if code:
        d["code"] = code
    return d


def err(provider, detail, code="error", **extra):
    return doc(error=f"{provider}: {detail}", code=code, **extra)


def gone(provider, status):
    return err(provider, f"target HTTP {status}", f"target_{status}", target_status=status)


def n(text):
    return len(text.strip())


# --- E1-E8 classify ----------------------------------------------------------------------------------


def test_error_wins_over_content():  # E1
    assert classify(doc("anything", "Jina: target HTTP 403")) == "error"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("x" * 19, "empty"),  # E2 boundary
        ("x" * 20, "thin"),  # E8
        ("<!DOCTYPE html><html><head></head><body></body></html>", "empty"),  # E2 strips tags
        (WALL_TEXT, "wall"),  # E3 two markers
        ("Cookies zustimmen. " + ARTICLE, "ok"),  # E3 one marker only
        (PAYWALL_TEXT, "paywall"),  # E4 definite marker
        (ARTICLE + "SPIEGEL+", "ok"),  # E4 one general marker
        (ARTICLE + "SPIEGEL+ Jetzt weiterlesen", "paywall"),  # E4 two general markers
        (WALL_TEXT + " Das war die Leseprobe. " + ARTICLE, "wall"),  # wall before paywall
        ("I'm not a robot. Please click to confirm.", "challenge"),  # E7
        ("Checking the site connection security. Please wait a moment while we verify.", "challenge"),
        ("Verify you are human by completing the action below.", "challenge"),
        ("Please verify that you are human.", "challenge"),
        ("Enable JavaScript and cookies to continue", "challenge"),
        ("Click the button below to continue shopping", "challenge"),
        ("A required part of this site couldn’t load. Try again.", "challenge"),  # typographic apostrophe
        ("Access Denied. You do not have permission.", "challenge"),
        ("<div><b>Just a moment... checking</b></div>", "challenge"),  # case-insensitive, tags removed first
        ("A footer with imprint and links only. " * 3, "thin"),  # E8
        ("a" * 499, "thin"),
        ("a" * 500, "ok"),
        ("<p>" + "a" * 499 + "</p>" * 20, "thin"),  # tags do not count
        ("<p>" + "a" * 500 + "</p>", "ok"),
        ("captcha " + "a" * 1491, "challenge"),  # 1,499 visible characters
        ("captcha " + "a" * 1492, "ok"),  # 1,500: the cap
        (ARTICLE * 3 + " The captcha on this site is explained here.", "ok"),
        ("Das war die Leseprobe.", "paywall"),  # paywall keeps its place before thin
    ],
)
def test_classify(content, expected):
    assert classify(doc(content)) == expected


def test_less_than_sign_is_no_tag():  # E2
    assert classify(doc("Wenn x < 10 ist, " + ARTICLE + " gilt x -> y.")) == "ok"
    code = "Der Ausdruck `a < b` ist wahr, wenn a kleiner ist.\n\n" + ARTICLE + "\n\n```\n>>> 1 < 2\nTrue\n```\n"
    assert classify(doc(code)) == "ok"
    assert classify(doc("<p>" + ARTICLE + "</p><br/><!-- c --><div class='a'></div>")) == "ok"
    assert classify(doc("<p class='x'> " + "y" * 10 + " </p>")) == "empty"
    assert classify(doc("<p\nclass='x'>" + "y" * 10 + "</p><!DOCTYPE html>")) == "empty"
    assert classify(doc("for (i = 0; i<n; i++) " + ARTICLE + " p->next")) == "ok"
    assert classify(doc("List<String> " + ARTICLE)) == "ok"


def test_many_less_than_signs_classify_in_linear_time():  # E2
    start = time.perf_counter()
    assert classify(doc("a<b " * 80_000), full_page=True) == "ok"
    assert time.perf_counter() - start < 2


def test_challenge_wins_over_wall():  # E7 before E3
    assert classify(doc("Just a moment. " + WALL_TEXT)) == "challenge"


def test_each_marker_is_in_one_list_only():  # E6
    markers = WALL + PAYWALL_DEFINITE + PAYWALL
    assert len(markers) == len(set(markers))


@pytest.mark.parametrize("markers", [WALL, PAYWALL])
def test_no_marker_lies_inside_another_marker_of_its_list(markers):  # E6
    plain = [m for m in markers if not set(m) & set("\\[](|?+")]
    assert [(m, text) for text in plain for m in markers if m != text and re.search(m, text, re.IGNORECASE)] == []


def test_cookie_zustimmung_counts_once():  # E3
    assert classify(doc("Cookie-Zustimmung. " + ARTICLE)) == "ok"
    assert classify(doc("Cookie-Zustimmung. Ihre Zustimmung fehlt. " + ARTICLE)) == "wall"


def test_wall_window():  # E3: the whole text below 4,000 characters, otherwise the first 2,000
    assert classify(doc("a" * (3999 - len(WALL_TEXT)) + WALL_TEXT)) == "wall"
    assert classify(doc("a" * (4000 - len(WALL_TEXT)) + WALL_TEXT)) == "ok"
    assert classify(doc("a" * 1990 + WALL_TEXT + "a" * 3000)) == "ok"
    assert classify(doc(WALL_TEXT + "a" * 5000)) == "wall"


def test_paywall_area_full_page_ignores_last_quarter():  # E4
    footer = " SPIEGEL+ Jetzt weiterlesen"
    page = "a" * (8000 - len(footer)) + footer
    assert classify(doc(page), full_page=True) == "ok"
    assert classify(doc(page)) == "paywall"
    assert classify(doc("a" * 5000 + footer + "a" * 2000), full_page=True) == "paywall"
    assert classify(doc("a" * 3000 + footer), full_page=True) == "paywall"


# --- N7 suspect ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("length", "rule"), [(499, "thin"), (500, None)])
def test_suspect_thin(length, rule):  # N7.1: 500 characters
    assert suspect(doc("a" * length), None) == rule


def test_suspect_thin_counts_visible_text():  # N7, E2
    assert suspect(doc("<p>" + "a" * 499 + "</p>" * 50), None) == "thin"


@pytest.mark.parametrize("marker", ["Dieser Ausdruck wurde am", "AUSDRUCK ERSTELLT"])
def test_suspect_print_in_the_first_5000_characters(marker):  # N7.2, case-insensitive
    assert suspect(doc("a" * (5000 - len(marker)) + marker + "b" * 100), None) == "print"
    assert suspect(doc("a" * (5001 - len(marker)) + marker + "b" * 100), None) is None


@pytest.mark.parametrize(
    "hint",
    [
        "Turn on JavaScript",
        "enable javascript",
        "JavaScript is disabled",
        "javascript required",
        "Aktivieren Sie JavaScript",
        "Just a moment",
        "Nur einen Moment",
        "verify you are human",
        "CAPTCHA",
        "Access denied",
        "Pardon our interruption",
        "Zugriff verweigert",
        "Sicherheitsüberprüfung",
        "Security check",
        "Checking your browser",
    ],
)
def test_suspect_check_below_3000(hint):  # N7.3
    assert suspect(doc(hint + " " + "a" * (2999 - len(hint) - 1)), None) == "check"
    assert suspect(doc(hint + " " + "a" * (3000 - len(hint) - 1)), None) is None


def test_suspect_check_lists_are_covered():  # N7.3: the hints above are the whole lists
    assert len(SUSPECT_JS) == 4 and len(SUSPECT_CHECK) == 10 and len(SUSPECT_PRINT) == 2


def test_suspect_consent_counts_occurrences():  # N7.4: two occurrences of one marker, below 1,500
    text = "Cookie hier, noch ein Cookie. "
    assert suspect(doc(text + "a" * (1499 - len(text))), None) == "consent"
    assert suspect(doc(text + "a" * (1500 - len(text))), None) is None
    assert suspect(doc("Zustimmung. " + "a" * 1000), None) is None  # one occurrence
    assert suspect(doc("Consent und Einwilligung. " + "a" * 1000), None) == "consent"  # two markers count as well


@pytest.mark.parametrize(("reference", "rule"), [(1499, None), (1500, "shorter"), (1501, "shorter"), (None, None)])
def test_suspect_shorter_than_the_reference(reference, rule):  # N7.5: factor 1.5, none without a reference
    assert suspect(doc("a" * 1000), reference) == rule


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        ("Dieser Ausdruck wurde am 1.1. erstellt. " + "a" * 300, "thin"),  # thin before print
        ("Ausdruck erstellt. Enable JavaScript. " + "a" * 1000, "print"),  # print before check
        ("Enable JavaScript. Cookie, cookie. " + "a" * 1000, "check"),  # check before consent
        ("Cookie, cookie. " + "a" * 1000, "consent"),  # consent before shorter
        ("Ausdruck erstellt. " + "a" * 4000, "print"),  # print before shorter
    ],
)
def test_suspect_rule_order(content, rule):  # N7: the first rule that applies wins
    assert suspect(doc(content), 100_000) == rule


# --- run_chain helpers -------------------------------------------------------------------------------


class Fake:
    """Fetch stand-in: counts calls (K5) and records the deadline it got (N9)."""

    def __init__(self, result=None, exc=None, then=None):
        self.result, self.exc, self.then, self.deadlines = result, exc, then, []

    @property
    def calls(self):
        return len(self.deadlines)

    async def __call__(self, deadline):
        self.deadlines.append(deadline)
        if self.then:
            self.then()
        if self.exc:
            raise self.exc
        return self.result


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def stages(*results, order=("brightdata", "jina", "firecrawl", "tavily")):
    """Stages with Fake fetches; a result of None means a stage without a key (N3)."""
    fakes = [r if isinstance(r, Fake) else Fake(r) for r in results]
    built = [
        Stage(sid, NAMES[sid], None if r is None else fake) for sid, r, fake in zip(order, results, fakes, strict=False)
    ]
    return built, fakes


REFERENCE = doc(ARTICLE)  # Keenable's copy as long as ARTICLE: rule N7.5 does not apply


def run(stage_list, reference=REFERENCE, *, budget=170.0, clock=None, interrupted=None):
    """reference: Keenable's result (dict), None (no key), an exception, "pending", or a function(loop, future).
    interrupted: the interrupt flag check (S8), never set by default."""

    async def go():
        loop = asyncio.get_running_loop()
        task = None
        if reference is not None:
            task = loop.create_future()
            if isinstance(reference, dict):
                task.set_result(reference)
            elif isinstance(reference, Exception):
                task.set_exception(reference)
            elif callable(reference):
                reference(loop, task)
        out = await run_chain(
            URL, stage_list, task, budget=budget, clock=clock or Clock(), is_interrupted=interrupted or (lambda: False)
        )
        assert out["url"] == URL and out["metadata"]["sourceURL"] == URL  # S5
        return out

    return asyncio.run(go())


def notes(out):
    return out["content"].split("\n\n", 1)[0].splitlines()


def logged(caplog):
    caplog.set_level(logging.INFO, logger="extract_chain.chain")
    return lambda: [r.getMessage() for r in caplog.records if r.name == "extract_chain.chain"]


# --- N6, N17: stages in order ------------------------------------------------------------------------


def test_first_stage_ok_is_taken_without_note():  # N6, N17: no note from the first stage
    s, fakes = stages(doc(ARTICLE), doc(ARTICLE), doc(ARTICLE), doc(ARTICLE))
    out = run(s, doc(ARTICLE))
    assert out == {"url": URL, "title": "T", "content": ARTICLE, "error": None, "metadata": {"sourceURL": URL}}
    assert [f.calls for f in fakes] == [1, 0, 0, 0]


def test_stage_gets_the_time_left():  # N9: each stage at most the remaining budget
    clock = Clock()
    s, fakes = stages(Fake(err("Bright Data", "x"), then=lambda: setattr(clock, "now", clock.now + 30)), doc(ARTICLE))
    run(s, doc(ARTICLE), budget=170.0, clock=clock)
    assert [f.deadlines for f in fakes] == [[170.0], [140.0]]


def test_no_title_is_an_empty_one():  # S5
    s, _ = stages(doc(ARTICLE, title=None))
    assert run(s, doc(ARTICLE))["title"] == ""


@pytest.mark.parametrize(
    ("first", "reason"),
    [
        (err("Bright Data", "target HTTP 403", "target_403"), "Bright Data: target HTTP 403"),
        (doc(""), "Bright Data: empty page"),
        (doc(WALL_TEXT), "Bright Data: consent wall"),
        (doc(BOT), "Bright Data: bot check page"),
        (doc("a" * 312), "Bright Data: very short page (312 characters)"),
        (doc("Dieser Ausdruck wurde am 1.1. erstellt. " + ARTICLE), "Bright Data: print view"),
        (doc("Please enable JavaScript. " + ARTICLE), "Bright Data: JavaScript or bot-check hint"),
        (doc("Cookie und Cookie. " + ARTICLE), "Bright Data: consent text"),
        (doc(ARTICLE[:600]), "Bright Data: shorter than the reference copy"),
    ],
)
def test_passed_over_stage_gives_live_note_with_reason(first, reason):  # N6, N7, N17
    s, fakes = stages(first, doc(ARTICLE, title="J"))
    out = run(s, doc(ARTICLE))
    assert out["content"] == NOTE_LIVE.format(provider="Jina", reasons=reason) + "\n\n" + ARTICLE
    assert out["title"] == "J" and [f.calls for f in fakes] == [1, 1]


def test_reasons_of_all_passed_over_stages():  # N17: joined with "; "
    s, _ = stages(err("Bright Data", "API 401: bad"), doc("a" * 300), doc(WALL_TEXT), doc(ARTICLE))
    out = run(s, doc(ARTICLE))
    reasons = "Bright Data: API 401: bad; Jina: very short page (300 characters); Firecrawl: consent wall"
    assert notes(out) == [NOTE_COPY.format(provider="Tavily", reasons=reasons)]  # Tavily is a copy (N17)


def test_keenable_as_last_stage_gives_copy_note():  # N5, N17
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    out = run(s, doc(ARTICLE, title="KE"))
    reasons = "Bright Data: API 500; Jina: API 500; Firecrawl: API 500; Tavily: API 500"
    assert out["content"] == NOTE_COPY.format(provider="Keenable", reasons=reasons) + "\n\n" + ARTICLE
    assert out["title"] == "KE"


def test_keenable_suspect_is_checked_without_reference():  # N7: thin, print, check, consent apply to Keenable too
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    out = run(s, doc("k" * 300))
    reasons = "Bright Data: API 500; Jina: API 500; Firecrawl: API 500; Tavily: API 500"
    reasons += "; Keenable: very short page (300 characters)"
    assert notes(out) == [NOTE_LONGEST_COPY.format(provider="Keenable", n=300, reasons=reasons)]  # V15: a copy


def test_longest_result_from_tavily_is_a_copy():  # V15: Tavily is a copy as well
    s, _ = stages(doc("a" * 300), None, None, doc("t" * 400, title="TV"))
    out = run(s, None)
    reasons = "Bright Data: very short page (300 characters); Jina: no API key; Firecrawl: no API key; "
    reasons += "Tavily: very short page (400 characters); Keenable: no API key"
    assert notes(out) == [NOTE_LONGEST_COPY.format(provider="Tavily", n=400, reasons=reasons)]


def test_keenable_paywall_ends_with_copy_note_and_v3():  # N6, V3
    s, _ = stages(doc(WALL_TEXT), None, None, None)
    out = run(s, doc(PAYWALL_TEXT))
    reasons = "Bright Data: consent wall; Jina: no API key; Firecrawl: no API key; Tavily: no API key"
    assert notes(out) == [NOTE_COPY.format(provider="Keenable", reasons=reasons), NOTE_PAYWALL]


def test_keenable_is_never_used_for_the_shorter_rule_against_itself():  # N7.5
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    assert run(s, doc(ARTICLE))["content"].endswith("\n\n" + ARTICLE)  # Keenable taken, not kept as suspect


# --- V3 paywall, V5 wall, V11 bot check ----------------------------------------------------------------


def test_first_stage_paywall_ends_with_v3_only():  # N6, V3, D4
    s, fakes = stages(doc(PAYWALL_TEXT), doc(ARTICLE))
    out = run(s, "pending")  # no wait for the reference either
    assert out["content"] == f"{NOTE_PAYWALL}\n\n{PAYWALL_TEXT}"
    assert fakes[1].calls == 0


def test_later_paywall_ends_with_source_note_and_v3():  # N6, N18 order
    s, fakes = stages(doc("a" * 300), doc(PAYWALL_TEXT), doc(ARTICLE))
    out = run(s, doc(ARTICLE))
    assert notes(out) == [
        NOTE_LIVE.format(provider="Jina", reasons="Bright Data: very short page (300 characters)"),
        NOTE_PAYWALL,
    ]
    assert fakes[2].calls == 0


def test_whole_page_footer_is_no_paywall_for_live_stages():  # N6: full_page for the four stages, E4
    footer = " SPIEGEL+ Jetzt weiterlesen"
    page = "Ein Satz. " * 800 + footer
    s, _ = stages(doc(page))
    assert run(s, doc(page))["content"] == page
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    assert notes(run(s, doc(page)))[-1] == NOTE_PAYWALL  # Keenable: no whole page


def test_wall_without_alternative_returns_first_wall_page():  # N6, N8 (c), V5
    s, _ = stages(doc(WALL_TEXT + " (BD)"), doc(WALL_TEXT + " (J)"), None, None)
    out = run(s, err("Keenable", "Gateway timeout", "http_504"))
    reasons = "Bright Data: consent wall; Jina: consent wall; Firecrawl: no API key; Tavily: no API key"
    reasons += "; Keenable: Gateway timeout"
    assert out["content"] == NOTE_WALL.format(reasons=reasons) + "\n\n" + WALL_TEXT + " (BD)"
    assert out["error"] is None


def test_wall_before_bot_check_page():  # N8 (c) before (d), V5 before V11
    s, _ = stages(doc(BOT), doc(WALL_TEXT), None, None)
    out = run(s, err("Keenable", "HTTP 500", "http_500"))
    assert out["content"].endswith("\n\n" + WALL_TEXT) and notes(out)[0].startswith(NOTE_WALL.split("(")[0])


def test_bot_check_page_without_alternative():  # N8 (d), V11
    s, _ = stages(doc(BOT, title="BD"), doc(BOT + " (J)"), None, None)
    out = run(s, None)
    reasons = (
        "Bright Data: bot check page; Jina: bot check page; Firecrawl: no API key; Tavily: no API key; "
        "Keenable: no API key"
    )
    assert out["content"] == NOTE_CHECK.format(reasons=reasons) + "\n\n" + BOT and out["title"] == "BD"


def test_keenable_wall_or_bot_check_is_never_kept():  # as in v0.2.6 (K4)
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    out = run(s, doc(BOT))
    assert out["error"].endswith("Tavily: API 500; Keenable: bot check page") and out["content"] == ""


def test_all_fail_joined_error():  # N8 (e), S5
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    out = run(s, err("Keenable", "HTTP 404", "http_404"))
    error = "Bright Data: API 500; Jina: API 500; Firecrawl: API 500; Tavily: API 500; Keenable: HTTP 404"
    assert out == {"url": URL, "title": "", "content": "", "error": error, "metadata": {"sourceURL": URL}}


# --- N8 fallback order ------------------------------------------------------------------------------------


def test_longest_suspect_result_is_returned():  # N8 (a), N18
    s, _ = stages(doc("a" * 300), doc("b" * 400, title="J"), doc("c" * 200), err("Tavily", "failed"))
    out = run(s, err("Keenable", "HTTP 500"))
    reasons = (
        "Bright Data: very short page (300 characters); Jina: very short page (400 characters); "
        "Firecrawl: very short page (200 characters); Tavily: failed; Keenable: HTTP 500"
    )
    assert out["content"] == NOTE_LONGEST.format(provider="Jina", n=400, reasons=reasons) + "\n\n" + "b" * 400
    assert out["title"] == "J"


def test_longest_tie_goes_to_the_earlier_stage():  # N8 (a): equal length, earlier position
    s, _ = stages(doc("a" * 300, title="BD"), doc("b" * 300, title="J"), None, None)
    out = run(s, None)
    assert out["title"] == "BD" and notes(out)[0].startswith("[extract-chain] No source passed the checks")


def test_longest_result_may_be_keenables():  # N8 (a): Keenable's suspect result is a candidate as well
    s, _ = stages(doc("a" * 300), None, None, None)
    out = run(s, doc("k" * 400, title="KE"))
    assert out["title"] == "KE" and "(Keenable, 400 characters;" in notes(out)[0]


def test_check_candidates_only_when_nothing_else():  # N8 (a) leaves out results with check
    hinted = "Please enable JavaScript. " + "a" * 2000
    s, _ = stages(doc(hinted, title="BD"), doc("b" * 300, title="J"), None, None)
    out = run(s, None)
    assert out["title"] == "J"  # the shorter result without the hint


def test_longest_check_candidate_with_v11():  # N8 (b)
    short_hint = "Please enable JavaScript. " + "a" * 1000
    long_hint = "Please enable JavaScript. " + "a" * 2000
    s, _ = stages(doc(short_hint, title="BD"), doc(long_hint, title="J"), doc(WALL_TEXT), None)
    out = run(s, None)
    reasons = (
        "Bright Data: JavaScript or bot-check hint; Jina: JavaScript or bot-check hint; Firecrawl: consent wall; "
        "Tavily: no API key; Keenable: no API key"
    )
    assert out["content"] == NOTE_CHECK.format(reasons=reasons) + "\n\n" + long_hint  # before the wall (c)
    assert out["title"] == "J"


# --- N9 reference and time budget -------------------------------------------------------------------------


def test_first_ok_stage_waits_for_the_reference():  # N9: the reference arrives while the chain waits
    s, fakes = stages(doc(ARTICLE), doc(LONG, title="J"))
    out = run(s, lambda loop, ref: loop.call_later(0.05, ref.set_result, doc(LONG)))
    assert notes(out) == [NOTE_LIVE.format(provider="Jina", reasons="Bright Data: shorter than the reference copy")]
    assert fakes[1].calls == 1


class Script:
    """Clock with given readings, then the last one forever (for one reading inside run_chain)."""

    def __init__(self, *readings):
        self.readings = list(readings)

    def __call__(self):
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


def test_reference_is_awaited_only_once():  # N9: later stages never wait, N7.5 stays off
    holder = {}
    s, fakes = stages(doc("a" * 300), Fake(doc(ARTICLE, title="J"), then=lambda: holder["ref"].set_result(doc(LONG))))
    # readings: start, left() of stage 1, left() for the wait (0.05 s left), left() of stage 2
    clock = Script(0.0, 0.0, 169.95, 0.0)
    out = run(s, lambda loop, ref: holder.update(ref=ref), clock=clock)
    assert out["title"] == "J"  # stage 2 did not see the reference that arrived after the wait
    assert notes(out) == [NOTE_LIVE.format(provider="Jina", reasons="Bright Data: very short page (300 characters)")]


@pytest.mark.parametrize("reference", [RuntimeError("boom"), err("Keenable", "HTTP 500", "http_500"), None])
def test_without_reference_rule_shorter_is_off(reference):  # N7.5, N9
    s, fakes = stages(doc(ARTICLE[:600]), doc(LONG))
    out = run(s, reference)
    assert out["content"] == ARTICLE[:600] and fakes[1].calls == 0


def test_keenable_exception_is_its_error():  # S6: the reference task raised
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    assert run(s, RuntimeError("boom"))["error"].endswith("Tavily: API 500; Keenable: RuntimeError")


@pytest.mark.parametrize(("used", "runs"), [(160.0, True), (160.01, False)])
def test_stage_skipped_below_10_seconds(used, runs):  # N9: 10 s left still runs
    clock = Clock()
    first = Fake(doc("a" * 300), then=lambda: setattr(clock, "now", clock.now + used))
    s, fakes = stages(first, doc(ARTICLE), None, None)
    out = run(s, None, budget=170.0, clock=clock)
    assert fakes[1].calls == int(runs)
    if not runs:  # N8 then applies; the reason names the skipped stage
        assert "Jina: no time left" in notes(out)[0] and out["content"].endswith("a" * 300)


def test_keenable_without_time_left():  # N9: the last stage does not wait beyond the budget
    clock = Clock()
    first = Fake(err("Bright Data", "API 500"), then=lambda: setattr(clock, "now", clock.now + 200))
    s, _ = stages(first, doc(ARTICLE), doc(ARTICLE), doc(ARTICLE))
    out = run(s, "pending", clock=clock)
    assert out["error"] == (
        "Bright Data: API 500; Jina: no time left; Firecrawl: no time left; Tavily: no time left; "
        "Keenable: no time left"
    )


# --- 404/410: an ordinary error (K9 removed in 0.3.1, D36) ----------------------------------------------


def test_two_live_404_410_go_on_to_the_later_stages():  # K4, D36
    s, fakes = stages(gone("Bright Data", 404), gone("Jina", 410), doc(ARTICLE, title="FC"), doc(ARTICLE))
    out = run(s, doc(ARTICLE))
    reasons = "Bright Data: target HTTP 404; Jina: target HTTP 410"
    assert notes(out) == [NOTE_LIVE.format(provider="Firecrawl", reasons=reasons)] and out["title"] == "FC"
    assert [f.calls for f in fakes] == [1, 1, 1, 0]


def test_keenables_copy_after_404s_gets_the_copy_note(caplog):  # K4, V13, D36
    lines = logged(caplog)
    s, fakes = stages(gone("Bright Data", 404), gone("Jina", 404), gone("Firecrawl", 404), err("Tavily", "failed"))
    out = run(s, doc(ARTICLE, title="KE"))
    reasons = "Bright Data: target HTTP 404; Jina: target HTTP 404; Firecrawl: target HTTP 404; Tavily: failed"
    assert out["content"] == NOTE_COPY.format(provider="Keenable", reasons=reasons) + "\n\n" + ARTICLE
    assert [f.calls for f in fakes] == [1, 1, 1, 1]
    assert lines() == [
        "extract-chain news.example: brightdata=target_404 jina=target_404 firecrawl=target_404 tavily=error "
        "keenable=ok"
    ]


def test_404s_keep_an_earlier_kept_result():  # K8, D36: before 0.3.1 two 404s discarded it (F8)
    order = ("tavily", "brightdata", "jina", "firecrawl")
    s, fakes = stages(doc("a" * 300, title="TV"), gone("Bright Data", 404), gone("Jina", 404), None, order=order)
    out = run(s, err("Keenable", "HTTP 404", "http_404"))
    assert out["title"] == "TV" and notes(out)[0].startswith(NOTE_LONGEST_COPY.split("(")[0])


@pytest.mark.parametrize("reference", [err("Keenable", "HTTP 404", "http_404"), None])
def test_only_404s_end_in_an_error(reference):  # K8 (e)
    s, fakes = stages(gone("Bright Data", 404), gone("Jina", 410), gone("Firecrawl", 404), None)
    out = run(s, reference)
    tail = "Keenable: HTTP 404" if reference else "Keenable: no API key"
    assert out["error"] == (
        "Bright Data: target HTTP 404; Jina: target HTTP 410; Firecrawl: target HTTP 404; Tavily: no API key; " + tail
    )


# --- S8 interrupt ----------------------------------------------------------------------------------------


def test_interrupted_stage_ends_the_chain_without_waiting_for_keenable(caplog):  # S8, N5, N20
    lines = logged(caplog)
    s, fakes = stages(err("Bright Data", "API 500", "api_500"), err("Jina", "interrupted", "interrupted"), doc(ARTICLE))
    out = run(s, "pending")  # a running Keenable request is not awaited
    assert out["error"] == "Bright Data: API 500; Jina: interrupted; Keenable: interrupted"
    assert fakes[2].calls == 0
    assert lines() == ["extract-chain news.example: brightdata=api_500 jina=interrupted keenable=interrupted"]


def test_interrupt_falls_back_to_the_kept_result(short_wait):  # S8, N8 (a)
    s, _ = stages(doc("a" * 300), err("Jina", "interrupted", "interrupted"), doc(ARTICLE))
    out = run(s, "pending")
    reasons = "Bright Data: very short page (300 characters); Jina: interrupted; Keenable: interrupted"
    assert notes(out) == [NOTE_LONGEST.format(provider="Bright Data", n=300, reasons=reasons)]


def test_interrupt_uses_a_copy_that_has_arrived(caplog):  # S8: an arrived copy is the last stage, as usual
    lines = logged(caplog)
    s, fakes = stages(doc("a" * 259), err("Jina", "interrupted", "interrupted"), doc(ARTICLE))
    out = run(s, doc(ARTICLE, title="KE"))
    reasons = "Bright Data: very short page (259 characters); Jina: interrupted"
    assert out["content"] == NOTE_COPY.format(provider="Keenable", reasons=reasons) + "\n\n" + ARTICLE
    assert fakes[2].calls == 0
    assert lines() == ["extract-chain news.example: brightdata=suspect_thin jina=interrupted keenable=ok"]


def test_interrupt_without_keenable_key_logs_no_key(caplog):  # S8, L1: not "interrupted"
    lines = logged(caplog)
    s, _ = stages(err("Bright Data", "API 500", "api_500"), err("Jina", "interrupted", "interrupted"))
    out = run(s, None)
    assert out["error"] == "Bright Data: API 500; Jina: interrupted; Keenable: no API key"
    assert lines() == ["extract-chain news.example: brightdata=api_500 jina=interrupted keenable=no_key"]


# --- K3, D35: the wait for the reference ------------------------------------------------------------------


@pytest.fixture
def short_wait(monkeypatch):
    """K3, D35 scaled down: the first stage that looks fine waits 0.2 s instead of 8 s, polling every 0.02 s."""
    monkeypatch.setattr(chain, "REFERENCE_WAIT", 0.2)
    monkeypatch.setattr(chain, "POLL", 0.02)


def test_reference_wait_is_capped(short_wait):  # K3, D35: a later reference does not count, C5 stays off
    s, fakes = stages(doc(ARTICLE, title="BD"), doc(LONG))
    started = time.monotonic()
    out = run(s, lambda loop, ref: loop.call_later(1.0, ref.set_result, doc(LONG)))
    assert out["title"] == "BD" and fakes[1].calls == 0
    assert time.monotonic() - started < 0.9


def test_reference_wait_cap_is_eight_seconds():  # K3, D35
    assert chain.REFERENCE_WAIT == 8.0 and chain.POLL <= 1.0


def test_reference_wait_ends_on_interrupt(short_wait, monkeypatch):  # S8: the wait ends at once
    monkeypatch.setattr(chain, "REFERENCE_WAIT", 5.0)
    flag = {"set": False}
    s, fakes = stages(doc(ARTICLE, title="BD"), doc(LONG))

    def reference(loop, ref):
        loop.call_later(0.05, flag.update, {"set": True})

    started = time.monotonic()
    out = run(s, reference, interrupted=lambda: flag["set"])
    assert time.monotonic() - started < 1.0  # not the 5 s of the wait
    assert out["title"] == "BD" and fakes[1].calls == 0  # no reference, so nothing to compare: the result is taken


def test_last_stage_wait_ends_on_interrupt(short_wait, caplog):  # S8: Keenable as the last stage
    lines = logged(caplog)
    flag = {"set": False}
    s, _ = stages(err("Bright Data", "API 500", "api_500"), None, None, None)

    def reference(loop, ref):
        loop.call_later(0.05, flag.update, {"set": True})

    started = time.monotonic()
    out = run(s, reference, interrupted=lambda: flag["set"])
    assert time.monotonic() - started < 1.0
    assert out["error"].endswith("Tavily: no API key; Keenable: interrupted")
    assert lines()[0].endswith("keenable=interrupted")


def test_reference_wait_is_capped_by_the_time_left(short_wait, monkeypatch):  # K3, Z1: never beyond the budget
    monkeypatch.setattr(chain, "REFERENCE_WAIT", 5.0)
    clock = Clock()
    first = Fake(doc(ARTICLE, title="BD"), then=lambda: setattr(clock, "now", clock.now + 169.9))  # 0.1 s left
    s, _ = stages(first, doc(LONG))
    started = time.monotonic()
    out = run(s, "pending", budget=170.0, clock=clock)
    assert time.monotonic() - started < 1.0 and out["title"] == "BD"


def test_failing_interrupt_check_counts_as_none(short_wait):  # S6
    s, fakes = stages(doc(ARTICLE[:600], title="BD"), doc(LONG, title="J"))

    def boom():
        raise RuntimeError("flag")

    out = run(s, lambda loop, ref: loop.call_later(0.05, ref.set_result, doc(LONG)), interrupted=boom)
    assert out["title"] == "J"  # the reference arrived within the wait and made Bright Data suspect (C5)


# --- E2, D37: Jina's header lines do not count towards lengths ------------------------------------------


JINA_HEAD = "Title: Some page\nURL Source: https://news.example/artikel\nPublished Time: 2026\n\nMarkdown Content:\n"


def jina_doc(body, head=JINA_HEAD):
    return doc(head + body, text_at=len(head))


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("", "empty"),  # header lines only: empty, not thin
        ("x" * 19, "empty"),
        ("x" * 20, "thin"),
        ("x" * 499, "thin"),  # the header lines would have lifted this above 500
        ("x" * 500, "ok"),
    ],
)
def test_jina_lengths_without_header_lines(body, expected):  # E2, E8, D37
    assert classify(jina_doc(body), full_page=True) == expected


def test_jina_markers_in_the_header_still_count():  # D37: the title of a bot check says "Just a moment"
    page = jina_doc("Checking connection, please wait. " * 2, head=JINA_HEAD.replace("Some page", "Just a moment..."))
    assert classify(page, full_page=True) == "challenge"


def test_jina_short_body_is_checked_as_short():  # C1, D37: the reason names the length without header lines
    s, fakes = stages(jina_doc("a" * 450), doc(ARTICLE, title="BD"), order=("jina", "brightdata"))
    out = run(s, doc(ARTICLE))
    assert notes(out) == [NOTE_LIVE.format(provider="Bright Data", reasons="Jina: very short page (450 characters)")]


def test_jina_length_against_the_reference_without_header_lines():  # C5, D37
    body = "w" * 600
    s, _ = stages(jina_doc(body), doc(ARTICLE, title="BD"), order=("jina", "brightdata"))
    assert run(s, doc("k" * 900))["title"] == "BD"  # 900 >= 1.5 * 600; with the header lines it would pass


@pytest.mark.parametrize(("other", "winner", "n"), [(480, "Bright Data", 480), (400, "Jina", 450)])
def test_jina_length_in_the_fallback_without_header_lines(other, winner, n):  # K8, V15, D37
    s, _ = stages(jina_doc("a" * 450), doc("b" * other), order=("jina", "brightdata"))
    out = run(s, None)
    assert f"({winner}, {n} characters;" in notes(out)[0]  # with the header lines Jina would have had 540


def test_text_at_out_of_range_is_ignored():  # E2: only a position inside the text counts
    assert classify(doc("x" * 30, text_at=100)) == "thin" and classify(doc("x" * 30, text_at="5")) == "thin"


# --- N3, S6 -------------------------------------------------------------------------------------------------


def test_stage_without_fetch_is_skipped_with_its_reason(caplog):  # N3, L1
    lines = logged(caplog)
    s = [Stage("brightdata", "Bright Data", None, missing="no zone"), Stage("jina", "Jina", Fake(doc(ARTICLE)))]
    out = run(s, doc(ARTICLE))
    assert notes(out) == [NOTE_LIVE.format(provider="Jina", reasons="Bright Data: no zone")]
    assert lines() == ["extract-chain news.example: brightdata=no_key jina=ok keenable=ref_ok"]


def test_exception_in_a_stage_fails_only_that_stage(caplog):  # S6
    lines = logged(caplog)
    s, fakes = stages(Fake(exc=RuntimeError("boom")), doc(ARTICLE))
    out = run(s, doc(ARTICLE))
    assert notes(out) == [NOTE_LIVE.format(provider="Jina", reasons="Bright Data: RuntimeError")]
    assert lines() == ["extract-chain news.example: brightdata=exception jina=ok keenable=ref_ok"]


def broken_for(content):
    real = chain.classify

    def classify(doc, full_page=False):
        if doc.get("content") == content:
            raise KeyError("bug")
        return real(doc, full_page)

    return classify


def test_unexpected_failure_fails_only_this_url(monkeypatch, caplog):  # S6
    monkeypatch.setattr(chain, "classify", broken_for("BOOM"))
    s, _ = stages(doc("BOOM"))
    out = run(s, doc(ARTICLE))
    assert out["error"] == "extract-chain: KeyError" and out["content"] == ""
    assert "extract-chain news.example: chain failed: KeyError" in caplog.messages


def test_unexpected_failure_while_logging_the_reference_does_not_raise(monkeypatch):  # S6: run_chain never raises
    monkeypatch.setattr(chain, "classify", broken_for("REF"))
    s, _ = stages(doc(ARTICLE))
    out = run(s, doc("REF"))
    assert out["url"] == URL


# --- N20 / L1 log line --------------------------------------------------------------------------------------


def test_log_line_with_suspects_and_keenable(caplog):  # N20
    lines = logged(caplog)
    s, _ = stages(doc("a" * 300), doc("Cookie, cookie. " + "a" * 600), err("Firecrawl", "API 500", "api_500"), None)
    run(s, doc(ARTICLE))
    assert lines() == [
        "extract-chain news.example: brightdata=suspect_thin jina=suspect_consent firecrawl=api_500 "
        "tavily=no_key keenable=ok"
    ]


def test_log_line_suspect_print_check_shorter(caplog):  # N20
    lines = logged(caplog)
    s, _ = stages(doc("Ausdruck erstellt. " + ARTICLE), doc("Enable JavaScript. " + ARTICLE), doc(ARTICLE[:600]))
    run(s, doc(ARTICLE))
    assert lines() == [
        "extract-chain news.example: brightdata=suspect_print jina=suspect_check firecrawl=suspect_shorter keenable=ok"
    ]


def test_log_line_no_time(caplog):  # N20
    lines = logged(caplog)
    clock = Clock()
    s, _ = stages(Fake(doc("a" * 300), then=lambda: setattr(clock, "now", clock.now + 165)), doc(ARTICLE))
    run(s, doc("k" * 200), clock=clock)
    assert lines() == ["extract-chain news.example: brightdata=suspect_thin jina=no_time keenable=suspect_thin"]


@pytest.mark.parametrize(
    ("reference", "outcome"),
    [
        (doc(ARTICLE), "ref_ok"),  # the reference was there, Keenable was not needed as a stage
        (err("Keenable", "HTTP 500", "http_500"), "ref_http_500"),
        ("pending", "pending"),
        (None, "no_key"),
    ],
)
def test_log_line_always_names_keenable(caplog, reference, outcome):  # N20: Keenable is always listed
    lines = logged(caplog)
    first = doc(ARTICLE) if reference != "pending" else doc(PAYWALL_TEXT)
    run(stages(first)[0], reference)
    assert lines()[-1].endswith(f" keenable={outcome}")


def test_log_line_never_raises_or_shows_full_url(caplog):  # L1
    lines = logged(caplog)

    async def go(url):
        return await run_chain(url, stages(doc(ARTICLE))[0], None, budget=170.0, clock=Clock())

    out = asyncio.run(go("http://[::1"))
    asyncio.run(go("file:///tmp/x?token=abc"))
    asyncio.run(go(123))
    assert out["error"] is None
    assert lines() == [
        "extract-chain <invalid url>: brightdata=ok keenable=no_key",
        "extract-chain <no host>: brightdata=ok keenable=no_key",
        "extract-chain <invalid url>: brightdata=ok keenable=no_key",
    ]


# --- V7, V10 -------------------------------------------------------------------------------------------------


def test_pdf_note_redirect_note_and_final_url():  # V7, V10 after the source note (N18)
    page = doc(ARTICLE, pdf_pages=(30, 120), final_url=OTHER)
    s, _ = stages(err("Bright Data", "API 500"), err("Jina", "API 500"), page)
    out = run(s, doc(ARTICLE))
    assert notes(out) == [
        NOTE_LIVE.format(provider="Firecrawl", reasons="Bright Data: API 500; Jina: API 500"),
        NOTE_PDF.format(shown=30, total=120),
        NOTE_REDIRECT.format(final=OTHER),
    ]
    assert out["metadata"] == {"sourceURL": URL, "finalURL": OTHER}


def test_redirect_note_after_paywall_and_fallback_notes():  # N18: order of notes
    s, _ = stages(doc(PAYWALL_TEXT, final_url=OTHER))
    assert notes(run(s, doc(ARTICLE))) == [NOTE_PAYWALL, NOTE_REDIRECT.format(final=OTHER)]
    s, _ = stages(doc("a" * 300, final_url=OTHER), None, None, None)
    lines = notes(run(s, None))
    assert lines[0].startswith("[extract-chain] No source passed") and lines[1] == NOTE_REDIRECT.format(final=OTHER)
    s, _ = stages(*(err(name, "API 500") for name in NAMES.values()))
    lines = notes(run(s, doc(ARTICLE, final_url=OTHER)))
    assert lines[0].startswith("[extract-chain] Copy via Keenable") and lines[1] == NOTE_REDIRECT.format(final=OTHER)


def redirected(requested, final):
    async def go():
        stage = Stage("firecrawl", "Firecrawl", Fake({**doc(ARTICLE), "final_url": final}))
        return await run_chain(requested, [stage], None, budget=170.0, clock=Clock())

    return asyncio.run(go())["content"]


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
def test_redirect_note_added(requested, final):  # V10
    assert redirected(requested, final) == NOTE_REDIRECT.format(final=final) + "\n\n" + ARTICLE


@pytest.mark.parametrize(
    ("requested", "final"),
    [
        ("https://news.example/artikel", "https://www.news.example/artikel"),  # www only
        ("https://www.news.example/artikel", "https://news.example/artikel"),
        ("https://news.example/artikel", "http://news.example/artikel"),  # scheme only
        ("https://news.example/artikel", "https://news.example/artikel/"),  # trailing slash
        ("https://news.example/de", "https://news.example/de/"),
        ("https://news.example/artikel", "https://news.example/artikel?utm=1"),  # query
        ("https://news.example/artikel", "https://news.example/artikel#top"),  # fragment
        ("https://News.Example/Artikel", "https://news.example/artikel"),  # letter case
        ("https://news.example/", "https://news.example/de/"),  # requested path has no segment
        ("https://news.example/jobs", "https://news.example/jobs/list"),  # deeper path
        ("https://news.example/jobs", "https://news.example/deutsch/"),  # not locale-like
        ("https://news.example/jobs", None),  # no final URL (Bright Data, Jina, Tavily)
        ("https://news.example/jobs", ""),
        ("https://news.example/jobs", "/relative"),
        ("https://news.example/jobs", 123),  # not a string
        ("https://news.example/jobs", ["https://other.example/"]),
        ("http://[::1", OTHER),  # invalid requested URL
    ],
)
def test_no_redirect_note(requested, final):  # V10
    assert redirected(requested, final) == ARTICLE


def test_redirect_url_cut_to_200_characters_and_one_line():  # V10, V1
    final = "https://other.example/" + "a" * 300
    assert redirected(URL, final).splitlines()[0] == NOTE_REDIRECT.format(final=final[:200])
    assert redirected(URL, "https://other.example/a\nb c").splitlines()[0] == NOTE_REDIRECT.format(
        final="https://other.example/a b c"
    )


# --- gaps found in the review against the spec (2026-10-18) -------------------------------------------


def test_no_time_skips_every_stage_but_keenables_copy():  # Z1: below MIN_STAGE every stage is skipped
    order = ("firecrawl", "brightdata", "jina", "tavily")
    s, fakes = stages(doc(ARTICLE), doc(ARTICLE), doc(ARTICLE), doc(ARTICLE), order=order)
    out = run(s, doc(ARTICLE, title="KE"), budget=5.0, clock=Clock())
    assert [f.calls for f in fakes] == [0, 0, 0, 0]
    assert out["title"] == "KE" and "Firecrawl: no time left" in notes(out)[0]  # Keenable's copy, already there


def test_keenable_loses_a_tie_with_a_live_stage():  # N8 (a): Keenable is the last position
    s, _ = stages(doc("a" * 300, title="BD"), None, None, None)
    out = run(s, doc("k" * 300, title="KE"))
    assert out["title"] == "BD"


def test_keenable_consent_page_is_no_reference():  # N7.5, K3: only an ok or thin copy is a reference
    wall = doc("Cookies zustimmen. Alle akzeptieren. " + "Datenschutzeinstellungen " * 400)
    s, fakes = stages(doc(ARTICLE, title="BD"), doc(ARTICLE))
    out = run(s, wall)
    assert out["title"] == "BD" and fakes[1].calls == 0  # the longer consent page does not make Bright Data suspect


def test_keenable_without_answer_is_named():  # N9: the reasons list Keenable when it did not answer
    clock = Clock()

    def used_up():
        clock.now += 20.0  # Jina uses up the budget: no time is left to wait for Keenable

    s, _ = stages(gone("Bright Data", 404), Fake(gone("Jina", 404), then=used_up))
    out = run(s, "pending", budget=20.0, clock=clock)
    assert out["error"].endswith("Keenable: no time left")
