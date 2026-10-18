"""Developer scripts in scripts/ (not shipped with the plugin): replay (N23) and live check (N24)."""

import re
from pathlib import Path

import live_check
import pytest
import replay

from extract_chain import chain

ARTICLE = "Ein ganz normaler Artikeltext mit mehreren Sätzen. " * 20


# --- N23 replay.as_fetched -----------------------------------------------------------------------------


def test_as_fetched_without_stored_result():
    assert replay.as_fetched("brightdata", None) == {"error": "Bright Data: no stored result", "code": "no_result"}


@pytest.mark.parametrize(("code", "status"), [("target_404", 404), ("target_410", 410), ("target_502", 502)])
def test_as_fetched_target_status_from_the_code(code, status):  # N6: target_status for the 404/410 rule
    out = replay.as_fetched("firecrawl", {"error": f"Firecrawl: target HTTP {status}", "code": code})
    assert out == {"error": f"Firecrawl: target HTTP {status}", "code": code, "target_status": status}


@pytest.mark.parametrize(
    ("code", "expected"), [("api_500", "api_500"), ("target_4044", "target_4044"), (None, "error")]
)
def test_as_fetched_other_errors_have_no_target_status(code, expected):
    out = replay.as_fetched("tavily", {"error": "Tavily:\n  failed " + "x" * 300, "code": code})
    assert out["code"] == expected and "target_status" not in out
    assert "\n" not in out["error"] and len(out["error"]) == 220  # one line, cut


@pytest.mark.parametrize(("provider", "final"), [("brightdata", None), ("jina", None), ("tavily", None)])
def test_as_fetched_no_final_url_where_the_provider_gives_none(provider, final):  # N11-N13
    row = {"title": "T", "content": ARTICLE, "final_url": "https://other.example/"}
    assert replay.as_fetched(provider, row) == {"title": "T", "content": ARTICLE, "final_url": final}


@pytest.mark.parametrize("provider", ["firecrawl", "keenable"])
def test_as_fetched_keeps_the_final_url_of_firecrawl_and_keenable(provider):
    row = {"content": ARTICLE, "final_url": "https://other.example/"}
    assert replay.as_fetched(provider, row)["final_url"] == "https://other.example/"


def test_as_fetched_jina_warning_line_is_a_target_error():  # N12
    head = "Title: x\nURL Source: https://a.example/\nWarning: Target URL returned error 404: Not Found\n"
    out = replay.as_fetched("jina", {"content": head + "\nMarkdown Content:\nNot found"})
    assert out == {"error": "Jina: target HTTP 404", "code": "target_404", "target_status": 404}


def test_as_fetched_jina_warning_in_the_page_text_does_not_count():  # N12
    text = "Title: x\n\nMarkdown Content:\nWarning: Target URL returned error 404\n" + ARTICLE
    assert replay.as_fetched("jina", {"content": text})["content"] == text


def test_replay_names_the_source_stage():  # N23
    order = ["brightdata", "jina", "keenable"]
    data = {
        "brightdata": {"c1": {"id": "c1", "error": "Bright Data: target HTTP 403", "code": "target_403"}},
        "jina": {"c1": {"id": "c1", "content": ARTICLE}},
        "keenable": {"c1": {"id": "c1", "content": ARTICLE}},
    }
    source, result = replay.replay(order, data, "c1")
    assert source == "jina" and result["content"].startswith("[extract-chain] Live fetch via Jina")
    assert chain._result.__name__ == "_result"  # the recording stand-in is removed again


# --- N24 live_check -------------------------------------------------------------------------------------

KEENABLE = chain.NOTE_COPY.format(provider="Keenable", reasons="Bright Data: API 500") + "\n\ntext"


def test_live_check_two_urls_of_one_host():  # L1 lines name only the host
    group = [{"id": "a", "url": "https://n.example/1"}, {"id": "b", "url": "https://n.example/2"}]
    results = [{"url": group[0]["url"], "content": "text"}, {"url": group[1]["url"], "content": KEENABLE}]
    lines = [
        (1.0, "extract-chain n.example: brightdata=ok keenable=ref_ok"),
        (2.0, "extract-chain n.example: brightdata=api_500 jina=api_500 keenable=ok"),
    ]
    shown, problems = live_check.check_call(group, results, lines)
    assert problems == [] and shown == ["(2 log lines for this host)"] * 2
    results[1]["content"] = "text"
    assert live_check.check_call(group, results, lines)[1] == ["a, b: Keenable result without note"]


def test_live_check_one_url_per_host():
    group = [{"id": "a", "url": "https://n.example/1"}, {"id": "b", "url": "https://m.example/2"}]
    results = [{"url": group[0]["url"], "content": "text"}, {"url": group[1]["url"], "content": "text"}]
    lines = [
        (1.0, "extract-chain n.example: brightdata=ok keenable=ref_ok"),  # a reference only needs no note
        (2.0, "extract-chain m.example: brightdata=api_500 keenable=paywall"),
    ]
    shown, problems = live_check.check_call(group, results, lines)
    assert shown == [lines[0][1], lines[1][1]]
    assert problems == ["b: Keenable result without note"]


def test_live_check_keenable_note_follows_the_plugin():  # N17: the script copies the start of NOTE_COPY
    assert chain.NOTE_COPY.format(provider="Keenable", reasons="x").startswith(live_check.KEENABLE_NOTE)


def test_readme_lists_every_note():  # N17-N19: the README table must follow chain.NOTE_*
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for name, text in vars(chain).items():
        if name.startswith("NOTE_") and isinstance(text, str):
            fragments = re.split(r"\{[^}]*\}", text.removeprefix("[extract-chain] "))
            assert [f.strip() for f in fragments if f.strip() and f.strip() not in readme] == [], name
