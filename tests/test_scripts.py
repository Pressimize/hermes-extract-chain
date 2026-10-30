"""Developer scripts in scripts/ (not shipped with the plugin): replay (N23) and live check (N24)."""

import re
from pathlib import Path

import live_check
import pytest
import replay

from sift import chain, fetchers

ARTICLE = "Ein ganz normaler Artikeltext mit mehreren Sätzen. " * 20


# --- N23 replay.as_fetched -----------------------------------------------------------------------------


def test_as_fetched_without_stored_result():
    assert replay.as_fetched("brightdata", None) == {"error": "Bright Data: no stored result", "code": "no_result"}


@pytest.mark.parametrize(("code", "status"), [("target_404", 404), ("target_410", 410), ("target_502", 502)])
def test_as_fetched_target_status_from_the_code(code, status):  # target_status for the log and the reasons
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


def test_as_fetched_brightdata_pdf_as_the_fetcher():  # A1, D39
    pdf = "%PDF-1.7\n binary"
    expected = {"error": "Bright Data: PDF file, not text", "code": "pdf"}
    assert replay.as_fetched("brightdata", {"content": pdf}) == expected
    assert replay.as_fetched("jina", {"content": pdf})["content"] == pdf  # only Bright Data passes the raw file on


def test_as_fetched_legacy_text_reply_gets_text_at():  # E2, D37, T2: stored text replies stay readable
    text = "Title: x\n\nMarkdown Content:\n" + ARTICLE
    assert replay.jina_text_at(text) == 27
    assert replay.as_fetched("jina", {"content": text})["text_at"] == 27
    assert replay.jina_text_at("x" * 3983 + "Markdown Content:") == 4000  # still inside the header block
    assert replay.jina_text_at("x" * 3984 + "Markdown Content:") is None
    assert "text_at" not in replay.as_fetched("jina", {"content": ARTICLE})
    assert "links" not in replay.as_fetched("jina", {"content": text})  # no link list: V16b later
    assert "text_at" not in replay.as_fetched("keenable", {"content": text})  # only Jina has header lines


LINKS = [["Ein ganz normaler", "https://h.example/1"], ["Sätzen", "https://h.example/2"]]


def test_as_fetched_json_row_goes_through_jina_doc():  # A7, T2: a stored JSON reply (a row with links)
    row = {"id": "c1", "title": "Ein Titel", "content": ARTICLE, "links": LINKS}
    expected = fetchers.jina_doc({"data": {"title": "Ein Titel", "text": ARTICLE, "links": LINKS}})
    out = replay.as_fetched("jina", row)
    assert out == expected
    assert out["content"] == "Title: Ein Titel\n\n" + ARTICLE and out["text_at"] == len("Title: Ein Titel\n\n")
    assert out["links"] == [(t, u) for t, u in LINKS]


def test_as_fetched_json_row_without_title_and_with_empty_links():  # A7
    out = replay.as_fetched("jina", {"content": ARTICLE, "links": []})
    assert out == {"title": "", "content": ARTICLE, "final_url": None, "links": []}


def test_as_fetched_json_row_with_http_status_is_a_target_error():  # A7
    out = replay.as_fetched("jina", {"content": "Nicht gefunden", "links": [], "httpStatus": 404})
    assert out == {"error": "Jina: target HTTP 404", "code": "target_404", "target_status": 404}
    assert "error" not in replay.as_fetched("jina", {"content": ARTICLE, "links": [], "httpStatus": 399})


def test_as_fetched_json_row_with_non_string_text_is_malformed():  # A7
    assert replay.as_fetched("jina", {"content": 5, "links": []})["code"] == "malformed"


def test_as_fetched_links_key_is_read_for_jina_only():  # T2: other providers keep their rows as they are
    row = {"content": ARTICLE, "links": LINKS}
    assert "links" not in replay.as_fetched("keenable", row)


def test_replay_names_the_source_stage():  # N23
    order = ["brightdata", "jina", "keenable"]
    data = {
        "brightdata": {"c1": {"id": "c1", "error": "Bright Data: target HTTP 403", "code": "target_403"}},
        "jina": {"c1": {"id": "c1", "content": ARTICLE}},
        "keenable": {"c1": {"id": "c1", "content": ARTICLE}},
    }
    source, result = replay.replay(order, data, "c1")
    assert source == "jina" and result["content"].startswith("[sift] Live fetch via Jina")
    assert chain._result.__name__ == "_result"  # the recording stand-in is removed again


# --- N24 live_check -------------------------------------------------------------------------------------

KEENABLE = chain.NOTE_COPY.format(provider="Keenable", reasons="Bright Data: API 500") + "\n\ntext"


def test_live_check_two_urls_of_one_host():  # L1 lines name only the host
    group = [{"id": "a", "url": "https://n.example/1"}, {"id": "b", "url": "https://n.example/2"}]
    results = [{"url": group[0]["url"], "content": "text"}, {"url": group[1]["url"], "content": KEENABLE}]
    lines = [
        (1.0, "sift n.example: brightdata=ok keenable=ref_ok"),
        (2.0, "sift n.example: brightdata=api_500 jina=api_500 keenable=ok"),
    ]
    shown, problems = live_check.check_call(group, results, lines)
    assert problems == [] and shown == ["(2 log lines for this host)"] * 2
    results[1]["content"] = "text"
    assert live_check.check_call(group, results, lines)[1] == ["a, b: Keenable result without note"]


def test_live_check_one_url_per_host():
    group = [{"id": "a", "url": "https://n.example/1"}, {"id": "b", "url": "https://m.example/2"}]
    results = [{"url": group[0]["url"], "content": "text"}, {"url": group[1]["url"], "content": "text"}]
    lines = [
        (1.0, "sift n.example: brightdata=ok keenable=ref_ok"),  # a reference only needs no note
        (2.0, "sift m.example: brightdata=api_500 keenable=paywall"),
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
            fragments = re.split(r"\{[^}]*\}", text.removeprefix("[sift] "))
            assert [f.strip() for f in fragments if f.strip() and f.strip() not in readme] == [], name


def test_replay_json_row_is_shaped_with_addresses():  # A7, V16a, T2: set 3 rows give the text the model sees
    order = ["jina", "keenable"]
    data = {
        "jina": {"c1": {"id": "c1", "title": "T", "content": ARTICLE, "links": LINKS}},
        "keenable": {"c1": {"id": "c1", "content": ARTICLE}},
    }
    source, result = replay.replay(order, data, "c1")
    assert source == "jina"
    assert result["content"].startswith("Title: T\n\n")
    assert "Ein ganz normaler <https://h.example/1>" in result["content"]
    assert "Sätzen <https://h.example/2>" in result["content"]


def test_replay_legacy_text_row_is_shaped_as_markdown():  # V16b, T2: sets 1 and 2 hold Markdown
    text = "Title: x\n\nMarkdown Content:\n" + ARTICLE + " [Apply now](https://x.example/a) ![i](p.png)"
    data = {"jina": {"c1": {"id": "c1", "content": text}}, "keenable": {"c1": {"id": "c1", "content": ARTICLE}}}
    source, result = replay.replay(["jina", "keenable"], data, "c1")
    assert source == "jina" and "Apply now <https://x.example/a>" in result["content"]
    assert "![i]" not in result["content"]
