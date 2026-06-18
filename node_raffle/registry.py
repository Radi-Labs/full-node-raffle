"""
Raffle round state and persistence.

One JSON file holds the full lifecycle of a round so every stage leaves an
auditable record: which block decides the draw, who entered, when the list
was sealed, the Nostr event it was published as, and the final result.

Lifecycle:  OPEN -> CLOSED -> PUBLISHED -> DRAWN
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

from . import draw

# Default max entries allowed per source IP address.
# Override via MAX_ENTRIES_PER_IP env var or the max_entries_per_ip parameter.
_DEFAULT_MAX_PER_IP = int(os.environ.get("MAX_ENTRIES_PER_IP", "1"))


class Status(str, Enum):
    OPEN = "open"            # accepting verified entries
    CLOSED = "closed"        # entry list frozen + committed
    PUBLISHED = "published"  # sealed list broadcast to Nostr
    DRAWN = "drawn"          # winner selected from the block hash


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
    max_entries_per_ip: int = _DEFAULT_MAX_PER_IP
    prize_address: str = ""   # Bitcoin address for the prize pool
    # Maps IP address -> list of npubs entered from that IP. Not part of the
    # public entry list; used only for Sybil gating before entries close.
    ip_map: dict[str, list[str]] = field(default_factory=dict)

    # --- entry stage ---
    def add_entry(self, npub: str, source_ip: str = "") -> bool:
        """Add a verified entry. Returns False if it's a duplicate.

        Raises RuntimeError if:
        - the round is not OPEN
        - source_ip has already reached max_entries_per_ip for this round
        """
        if self.status != Status.OPEN:
            raise RuntimeError(f"round is {self.status.value}, not accepting entries")
        npub = npub.strip()
        if npub in self.entries:
            return False

        if source_ip:
            seen_from_ip = self.ip_map.get(source_ip, [])
            if len(seen_from_ip) >= self.max_entries_per_ip:
                raise RuntimeError(
                    f"IP {source_ip} already has {len(seen_from_ip)} "
                    f"entr{'y' if len(seen_from_ip) == 1 else 'ies'} "
                    f"(max {self.max_entries_per_ip} per IP)"
                )
            seen_from_ip.append(npub)
            self.ip_map[source_ip] = seen_from_ip

        self.entries.append(npub)
        return True

    def ip_entry_count(self, ip: str) -> int:
        """How many entries have been submitted from this IP."""
        return len(self.ip_map.get(ip, []))

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
        # ip_map may be absent in state files created before this field was added
        d.setdefault("ip_map", {})
        d.setdefault("max_entries_per_ip", _DEFAULT_MAX_PER_IP)
        d.setdefault("prize_address", "")
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
