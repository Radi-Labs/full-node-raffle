"""
Raffle round state and persistence.

One JSON file holds the full lifecycle of a round so every stage leaves an
auditable record: which block decides the draw, who entered, when the list
was sealed, the Nostr event it was published as, and the final result.

Lifecycle:  OPEN -> CLOSED -> PUBLISHED -> DRAWN
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

from . import draw


class Status(str, Enum):
    OPEN = "open"          # accepting verified entries
    CLOSED = "closed"      # entry list frozen + committed
    PUBLISHED = "published"  # sealed list broadcast to Nostr
    DRAWN = "drawn"        # winner selected from the block hash


@dataclass
class RaffleRound:
    round_id: str
    draw_block_height: int
    extra_blocks: int = 0          # 0 => single-block seed; >0 => hardened multi-block
    status: Status = Status.OPEN
    entries: list[str] = field(default_factory=list)
    relays: list[str] = field(default_factory=list)
    opened_at: float = field(default_factory=lambda: time.time())
    closed_at: float | None = None
    commitment: str | None = None
    entry_event_id: str | None = None
    draw_block_hashes: list[str] = field(default_factory=list)
    winner: str | None = None
    winner_index: int | None = None
    seed_hex: str | None = None

    # --- entry stage ---
    def add_entry(self, npub: str) -> bool:
        """Add a verified entry. Returns False if the round is closed or it's a dup."""
        if self.status != Status.OPEN:
            raise RuntimeError(f"round is {self.status.value}, not accepting entries")
        npub = npub.strip()
        if npub in self.entries:
            return False
        self.entries.append(npub)
        return True

    # --- seal stage ---
    def close(self) -> str:
        if self.status != Status.OPEN:
            raise RuntimeError(f"round already {self.status.value}")
        if not self.entries:
            raise RuntimeError("no entries to seal")
        self.entries = draw.canonical_entries(self.entries)
        self.commitment = draw.commitment(self.entries)
        self.closed_at = time.time()
        self.status = Status.CLOSED
        return self.commitment

    def mark_published(self, event_id: str, relays: list[str]) -> None:
        if self.status != Status.CLOSED:
            raise RuntimeError(f"can only publish a closed round (is {self.status.value})")
        self.entry_event_id = event_id
        self.relays = relays
        self.status = Status.PUBLISHED

    # --- draw stage ---
    def record_draw(self, result: draw.DrawResult) -> None:
        if self.status != Status.PUBLISHED:
            raise RuntimeError(f"can only draw a published round (is {self.status.value})")
        if result.commitment != self.commitment:
            raise RuntimeError(
                "entry commitment changed between publish and draw -- refusing. "
                f"sealed={self.commitment} now={result.commitment}"
            )
        self.draw_block_hashes = result.block_hashes
        self.winner = result.winner
        self.winner_index = result.index
        self.seed_hex = result.seed_hex
        self.status = Status.DRAWN

    # --- (de)serialization ---
    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RaffleRound":
        d = dict(d)
        d["status"] = Status(d["status"])
        return cls(**d)


class Store:
    """Trivial single-file store keyed by round_id."""

    def __init__(self, path: str | Path = "raffle_state.json"):
        self.path = Path(path)

    def _load_all(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def save(self, round_obj: RaffleRound) -> None:
        data = self._load_all()
        data[round_obj.round_id] = round_obj.to_dict()
        self.path.write_text(json.dumps(data, indent=2))

    def load(self, round_id: str) -> RaffleRound:
        data = self._load_all()
        if round_id not in data:
            raise KeyError(f"no round {round_id!r} in {self.path}")
        return RaffleRound.from_dict(data[round_id])

    def list_rounds(self) -> list[str]:
        return sorted(self._load_all().keys())
