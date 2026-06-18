"""Tests for round lifecycle, persistence, and the draw safety check."""

import pytest

from node_raffle import draw
from node_raffle.registry import RaffleRound, Store, Status


BLOCK = "00000000000000001e4118adcfbb02364bc13c41c210d8811e4f39aeb3687e36"


def make_round():
    rnd = RaffleRound(round_id="t1", draw_block_height=920000)
    for n in ["npub1c", "npub1a", "npub1b"]:
        rnd.add_entry(n)
    return rnd


def test_dedup_on_entry():
    rnd = make_round()
    assert rnd.add_entry("npub1a") is False
    assert len(rnd.entries) == 3


def test_close_canonicalizes_and_commits():
    rnd = make_round()
    commitment = rnd.close()
    assert rnd.entries == ["npub1a", "npub1b", "npub1c"]  # sorted
    assert rnd.status is Status.CLOSED
    assert commitment == draw.commitment(rnd.entries)


def test_cannot_enter_after_close():
    rnd = make_round()
    rnd.close()
    with pytest.raises(RuntimeError):
        rnd.add_entry("npub1d")


def test_full_lifecycle_and_persistence(tmp_path):
    store = Store(tmp_path / "state.json")
    rnd = make_round()
    store.save(rnd)

    loaded = store.load("t1")
    assert loaded.status is Status.OPEN
    assert len(loaded.entries) == 3

    loaded.close()
    loaded.mark_published("event123", ["wss://relay.example"])
    store.save(loaded)

    again = store.load("t1")
    assert again.status is Status.PUBLISHED
    assert again.entry_event_id == "event123"

    result = draw.pick_winner(again.entries, [BLOCK])
    again.record_draw(result)
    store.save(again)

    final = store.load("t1")
    assert final.status is Status.DRAWN
    assert final.winner == result.winner
    assert final.winner_index == result.index


def test_draw_rejects_tampered_entry_list(tmp_path):
    rnd = make_round()
    rnd.close()
    rnd.mark_published("evt", ["wss://r"])

    # Simulate the entry set being altered after sealing.
    tampered = list(rnd.entries) + ["npub1sneaky"]
    bad_result = draw.pick_winner(tampered, [BLOCK])

    with pytest.raises(RuntimeError, match="commitment changed"):
        rnd.record_draw(bad_result)


def test_status_order_enforced():
    rnd = make_round()
    # can't publish before closing
    with pytest.raises(RuntimeError):
        rnd.mark_published("x", [])
    rnd.close()
    # can't draw before publishing
    result = draw.pick_winner(rnd.entries, [BLOCK])
    with pytest.raises(RuntimeError):
        rnd.record_draw(result)
