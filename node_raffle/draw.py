"""
Deterministic draw core.

This module is the trust anchor of the whole system. It has no network
access and no side effects: given the same entry list and the same block
hash(es), it always produces the same winner. That is what lets anyone --
not just the organizer -- recompute the result and confirm it wasn't rigged.

Everything here is intentionally simple enough to reimplement in any
language. The single-block path reduces to `int(block_hash, 16) % N`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def canonical_entries(entries: list[str]) -> list[str]:
    """Strip, drop blanks, de-duplicate, and sort.

    Sorting makes the list order-independent: the commitment and the winner
    depend only on the *set* of entries, not the order they were collected.
    """
    cleaned = {e.strip() for e in entries if e and e.strip()}
    return sorted(cleaned)


def serialize(entries: list[str]) -> str:
    """Canonical wire form: one entry per line, newline-joined, no trailing newline."""
    return "\n".join(canonical_entries(entries))


def commitment(entries: list[str]) -> str:
    """SHA-256 hex of the canonical serialization.

    A lightweight commitment to the exact entry set. Publish this (it's in
    the Nostr note content already, but the hash is a convenient fingerprint)
    so the list can't be quietly altered after the fact.
    """
    return hashlib.sha256(serialize(entries).encode("utf-8")).hexdigest()


def derive_seed(block_hashes: list[str]) -> int:
    """Turn one or more Bitcoin block hashes into a single integer seed.

    - One block hash: read it directly as a big integer (`int(h, 16)`).
      This is the simple, hand-checkable default.
    - Several block hashes: SHA-256 over the concatenated raw hash bytes,
      read as an integer. Manipulating the outcome then requires controlling
      *every* block in the set, which raises the bar against a miner grinding
      for a favorable result.
    """
    if not block_hashes:
        raise ValueError("need at least one block hash")
    if len(block_hashes) == 1:
        return int(block_hashes[0].strip(), 16)
    raw = b"".join(bytes.fromhex(h.strip()) for h in block_hashes)
    return int.from_bytes(hashlib.sha256(raw).digest(), "big")


@dataclass
class DrawResult:
    winner: str
    index: int
    n: int
    seed_hex: str
    block_hashes: list[str]
    commitment: str
    entries: list[str] = field(default_factory=list)

    def explain(self) -> str:
        blocks = "\n".join(f"    - {h}" for h in self.block_hashes)
        return (
            "Draw verification trail\n"
            "-----------------------\n"
            f"Entries (N):        {self.n}\n"
            f"Entry commitment:   {self.commitment}\n"
            f"Draw block hash(es):\n{blocks}\n"
            f"Seed (hex):         {self.seed_hex}\n"
            f"Winning index:      seed mod {self.n} = {self.index}\n"
            f"Winner:             {self.winner}\n"
        )


def pick_winner(entries: list[str], block_hashes: list[str]) -> DrawResult:
    """Select the winning entry deterministically from the block hash(es)."""
    canonical = canonical_entries(entries)
    n = len(canonical)
    if n == 0:
        raise ValueError("no entries")

    seed = derive_seed(block_hashes)
    index = seed % n

    return DrawResult(
        winner=canonical[index],
        index=index,
        n=n,
        seed_hex=hex(seed)[2:],
        block_hashes=[h.strip() for h in block_hashes],
        commitment=commitment(canonical),
        entries=canonical,
    )
