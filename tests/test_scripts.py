"""Developer scripts in scripts/ (not shipped with the plugin)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replay  # noqa: E402


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
