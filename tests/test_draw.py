"""Tests for the deterministic draw core -- the part that must be reproducible."""

import hashlib

import pytest

from node_raffle import draw


ENTRIES = [
    "npub1aaa", "npub1bbb", "npub1ccc", "npub1ddd", "npub1eee",
    "npub1fff", "npub1ggg", "npub1hhh", "npub1iii", "npub1jjj",
]
# A real-looking Bitcoin block hash (mainnet block 326148, from public data).
BLOCK = "00000000000000001e4118adcfbb02364bc13c41c210d8811e4f39aeb3687e36"


def test_determinism():
    a = draw.pick_winner(ENTRIES, [BLOCK])
    b = draw.pick_winner(ENTRIES, [BLOCK])
    assert a.winner == b.winner
    assert a.index == b.index
    assert a.seed_hex == b.seed_hex


def test_order_independence():
    forward = draw.pick_winner(ENTRIES, [BLOCK])
    backward = draw.pick_winner(list(reversed(ENTRIES)), [BLOCK])
    assert forward.winner == backward.winner
    assert forward.commitment == backward.commitment


def test_index_matches_hand_calculation():
    n = len(draw.canonical_entries(ENTRIES))
    expected = int(BLOCK, 16) % n
    result = draw.pick_winner(ENTRIES, [BLOCK])
    assert result.index == expected
    assert result.winner == draw.canonical_entries(ENTRIES)[expected]


def test_duplicates_and_whitespace_collapse():
    messy = ["  npub1aaa ", "npub1aaa", "npub1bbb", "", "   "]
    assert draw.canonical_entries(messy) == ["npub1aaa", "npub1bbb"]


def test_commitment_changes_when_entry_changes():
    base = draw.commitment(ENTRIES)
    changed = draw.commitment(ENTRIES + ["npub1zzz"])
    assert base != changed


def test_commitment_is_sha256_of_serialization():
    expected = hashlib.sha256(draw.serialize(ENTRIES).encode()).hexdigest()
    assert draw.commitment(ENTRIES) == expected


def test_multi_block_seed_differs_from_single():
    extra = "00000000000000000004e6a0b4f1b8c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8"
    single = draw.pick_winner(ENTRIES, [BLOCK])
    multi = draw.pick_winner(ENTRIES, [BLOCK, extra])
    assert single.seed_hex != multi.seed_hex


def test_multi_block_seed_is_sha256_concat():
    extra = "00000000000000000004e6a0b4f1b8c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8"
    raw = bytes.fromhex(BLOCK) + bytes.fromhex(extra)
    expected = int.from_bytes(hashlib.sha256(raw).digest(), "big")
    assert draw.derive_seed([BLOCK, extra]) == expected


def test_empty_entries_raises():
    with pytest.raises(ValueError):
        draw.pick_winner([], [BLOCK])


def test_empty_block_hashes_raises():
    with pytest.raises(ValueError):
        draw.derive_seed([])


def test_distribution_is_reasonable():
    """Across many block hashes, winners should spread over all entries."""
    seen = set()
    for i in range(2000):
        h = hashlib.sha256(str(i).encode()).hexdigest()
        seen.add(draw.pick_winner(ENTRIES, [h]).index)
    # With 10 entries and 2000 draws, every index should appear.
    assert seen == set(range(len(ENTRIES)))
