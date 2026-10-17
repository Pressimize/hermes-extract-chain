"""Developer scripts in scripts/ (not shipped with the plugin)."""

import re
from pathlib import Path

import live_check
import pytest
import replay

from extract_chain import chain


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ('Keenable fetch failed: {"message": "behind a paywall"}', "Keenable: behind a paywall"),
        ("Keenable fetch failed: Gateway timeout", "Keenable: Gateway timeout"),
        ("Keenable fetch failed: 402", "Keenable: 402"),  # N04: JSON that is no object ended the replay
        ("Keenable fetch failed: null", "Keenable: null"),
    ],
)
def test_replay_error_detail(stored, expected):
    assert replay.other_doc("Keenable", {"error": stored}) == {"error": expected}


KEENABLE = live_check.KEENABLE_NOTE + "; it may be older than the live page (live fetch: …).\n\ntext"


def test_live_check_two_urls_of_one_host():  # N05: L1 lines name only the host
    group = [{"id": "a", "url": "https://n.example/1"}, {"id": "b", "url": "https://n.example/2"}]
    results = [{"url": group[0]["url"], "content": "text"}, {"url": group[1]["url"], "content": KEENABLE}]
    lines = [(1.0, "extract-chain n.example: tinyfish=ok"), (2.0, "extract-chain n.example: tinyfish=wall keenable=ok")]
    shown, problems = live_check.check_call(group, results, lines)
    assert problems == []  # before, "a" was checked against b's line and reported without note
    assert shown == ["(2 log lines for this host)"] * 2
    results[1]["content"] = "text"
    assert live_check.check_call(group, results, lines)[1] == ["a, b: Keenable result without note"]


def test_live_check_one_url_per_host():
    group = [{"id": "a", "url": "https://n.example/1"}, {"id": "b", "url": "https://m.example/2"}]
    results = [{"url": group[0]["url"], "content": "text"}, {"url": group[1]["url"], "content": "text"}]
    lines = [(1.0, "extract-chain n.example: tinyfish=ok"), (2.0, "extract-chain m.example: tinyfish=wall keenable=ok")]
    shown, problems = live_check.check_call(group, results, lines)
    assert shown == [lines[0][1], lines[1][1]]
    assert problems == ["b: Keenable result without note"]


def test_live_check_keenable_note_follows_the_plugin():  # the script copies the start of V4 on purpose
    assert chain.NOTE_KEENABLE.startswith(live_check.KEENABLE_NOTE)


def test_readme_lists_every_note():  # V2-V11: the README table must follow chain.NOTE_*
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for name, text in vars(chain).items():
        if name.startswith("NOTE_") and isinstance(text, str):
            fragments = re.split(r"\{[^}]*\}", text.removeprefix("[extract-chain] "))
            assert [f.strip() for f in fragments if f.strip() and f.strip() not in readme] == [], name
