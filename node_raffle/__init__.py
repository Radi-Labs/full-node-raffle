"""Node-runner raffle -- reference implementation.

A provably fair, privacy-preserving Bitcoin raffle for full node operators.
See the accompanying whitepaper for the architecture this implements.
"""

from .draw import (
    canonical_entries,
    serialize,
    commitment,
    derive_seed,
    pick_winner,
    DrawResult,
)
from .check_node import check_node, NodeCheck
from .registry import RaffleRound, Store, Status

__all__ = [
    "canonical_entries",
    "serialize",
    "commitment",
    "derive_seed",
    "pick_winner",
    "DrawResult",
    "check_node",
    "NodeCheck",
    "RaffleRound",
    "Store",
    "Status",
]

__version__ = "0.1.0"
