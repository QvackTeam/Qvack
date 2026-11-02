"""ТЗ Ф4 §8.9 T-TT3 (pure part): the holdback buffer of the body stream (Т-§12.2 stage 3,
WP13.4). The `reset` frame and the retry are the turn graph (WP13.2); removing the sentence
after the retries is `remove_spoiler_sentences` of Phase 3."""

from __future__ import annotations

import pytest

from quack.session.holdback import HoldbackBuffer, SpoilerDetected

ANSWER = "1234"


def _has_spoiler(text: str) -> bool:
    return ANSWER in text


def test_last_chars_wait_for_the_check() -> None:
    buffer = HoldbackBuffer(5, _has_spoiler)
    assert buffer.feed("abc") == ""
    assert buffer.feed("defgh") == "abc"
    assert buffer.feed("ij") == "de"
    assert buffer.finish() == "fghij"
    assert buffer.released == "abcdefghij"


def test_spoiler_stops_and_nothing_shown_contained_it() -> None:
    text = "The result is x = " + ANSWER + " exactly."
    buffer = HoldbackBuffer(len(ANSWER) * 2, _has_spoiler)
    with pytest.raises(SpoilerDetected):
        for char in text:
            buffer.feed(char)
    assert ANSWER[:-1] not in buffer.released
    assert ANSWER not in buffer.released


def test_spoiler_found_only_at_the_end() -> None:
    buffer = HoldbackBuffer(100, _has_spoiler)
    assert buffer.feed("x = 12") == ""
    assert buffer.feed("34") == ""
    with pytest.raises(SpoilerDetected):
        buffer.finish()
    assert buffer.released == ""


def test_zero_holdback_releases_each_checked_chunk() -> None:
    buffer = HoldbackBuffer(0, _has_spoiler)
    assert buffer.feed("ab") == "ab"
    assert buffer.feed("c") == "c"
    assert buffer.finish() == ""
