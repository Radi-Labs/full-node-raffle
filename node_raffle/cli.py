"""
Command-line driver for the raffle loop.

    python -m node_raffle.cli init   --round-id 2026-07 --draw-height 920000
    python -m node_raffle.cli enter  --round-id 2026-07 --npub npub1... --ip 1.2.3.4
    python -m node_raffle.cli status --round-id 2026-07
    python -m node_raffle.cli close  --round-id 2026-07
    python -m node_raffle.cli publish --round-id 2026-07 --nsec nsec1...
    python -m node_raffle.cli draw   --round-id 2026-07

Each stage persists to a JSON state file (default raffle_state.json) so the
round can be inspected and resumed at any point.
"""

from __future__ import annotations

import argparse
import sys

from . import draw
from .check_node import check_node
from .registry import RaffleRound, Store, Status


def _store(args) -> Store:
    return Store(args.state)


def cmd_init(args):
    store = _store(args)
    if args.round_id in store.list_rounds():
        print(f"round {args.round_id!r} already exists", file=sys.stderr)
        return 1
    rnd = RaffleRound(
        round_id=args.round_id,
        draw_block_height=args.draw_height,
        extra_blocks=args.extra_blocks,
    )
    store.save(rnd)
    seed_desc = ("single-block seed" if args.extra_blocks == 0
                 else f"{args.extra_blocks + 1}-block hardened seed")
    print(f"Created round {args.round_id!r}")
    print(f"  draw block height: {args.draw_height} ({seed_desc})")
    print(f"  announce this height publicly NOW, before entries close.")
    return 0


def cmd_enter(args):
    store = _store(args)
    rnd = store.load(args.round_id)

    if not args.skip_check:
        result = check_node(args.ip, args.port, timeout=args.timeout)
        print(result)
        if not result.reachable:
            print("not counted: node did not complete a handshake", file=sys.stderr)
            return 1

    added = rnd.add_entry(args.npub)
    store.save(rnd)
    if added:
        print(f"entry counted: {args.npub}  (total: {len(rnd.entries)})")
    else:
        print(f"already entered: {args.npub}  (total: {len(rnd.entries)})")
    return 0


def cmd_status(args):
    store = _store(args)
    rnd = store.load(args.round_id)
    print(f"Round:            {rnd.round_id}")
    print(f"Status:           {rnd.status.value}")
    print(f"Draw block:       {rnd.draw_block_height}"
          + (f" (+{rnd.extra_blocks} more)" if rnd.extra_blocks else ""))
    print(f"Entries:          {len(rnd.entries)}")
    if rnd.commitment:
        print(f"Commitment:       {rnd.commitment}")
    if rnd.entry_event_id:
        print(f"Nostr event id:   {rnd.entry_event_id}")
        print(f"Relays:           {', '.join(rnd.relays)}")
    if rnd.status == Status.DRAWN:
        print(f"Winning index:    {rnd.winner_index}")
        print(f"Winner:           {rnd.winner}")
        print(f"Seed (hex):       {rnd.seed_hex}")
    return 0


def cmd_close(args):
    store = _store(args)
    rnd = store.load(args.round_id)
    commitment = rnd.close()
    store.save(rnd)
    print(f"Sealed {len(rnd.entries)} entries.")
    print(f"Entry commitment (SHA-256): {commitment}")
    print("Next: publish the sealed list to Nostr before the draw block is mined.")
    return 0


def cmd_publish(args):
    store = _store(args)
    rnd = store.load(args.round_id)
    if rnd.status != Status.CLOSED:
        print(f"round must be 'closed' first (is {rnd.status.value})", file=sys.stderr)
        return 1

    from .nostr_publish import publish_entry_list, DEFAULT_RELAYS
    relays = args.relay or DEFAULT_RELAYS
    serialized = draw.serialize(rnd.entries)
    event_id = publish_entry_list(serialized, args.nsec, rnd.round_id, relays)

    rnd.mark_published(event_id, relays)
    store.save(rnd)
    print(f"Published entry list as Nostr event: {event_id}")
    print(f"Relays: {', '.join(relays)}")
    print("Announce this event id alongside the draw block height.")
    return 0


def cmd_draw(args):
    store = _store(args)
    rnd = store.load(args.round_id)
    if rnd.status != Status.PUBLISHED:
        print(f"round must be 'published' first (is {rnd.status.value})", file=sys.stderr)
        return 1

    if args.block_hash:
        hashes = args.block_hash
    else:
        from .blockchain import Mempool, BitcoinCoreRPC
        src = BitcoinCoreRPC(args.rpc) if args.rpc else Mempool()
        tip = src.tip_height()
        last_needed = rnd.draw_block_height + rnd.extra_blocks
        if tip < last_needed:
            print(f"draw block(s) not mined yet: tip={tip}, need {last_needed}",
                  file=sys.stderr)
            return 1
        hashes = src.block_hashes(rnd.draw_block_height, rnd.extra_blocks + 1)

    result = draw.pick_winner(rnd.entries, hashes)
    rnd.record_draw(result)
    store.save(rnd)
    print(result.explain())
    print("Anyone can reproduce this with verify.py and the published entry list.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="node_raffle", description="Node-runner raffle loop")
    p.add_argument("--state", default="raffle_state.json", help="state file path")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="create a round and announce the draw block")
    pi.add_argument("--round-id", required=True)
    pi.add_argument("--draw-height", type=int, required=True)
    pi.add_argument("--extra-blocks", type=int, default=0,
                    help="extra consecutive blocks to harden the seed (default 0)")
    pi.set_defaults(func=cmd_init)

    pe = sub.add_parser("enter", help="verify a node and count an entry")
    pe.add_argument("--round-id", required=True)
    pe.add_argument("--npub", required=True)
    pe.add_argument("--ip", default="")
    pe.add_argument("--port", type=int, default=8333)
    pe.add_argument("--timeout", type=float, default=5.0)
    pe.add_argument("--skip-check", action="store_true",
                    help="skip the P2P check (e.g. node already verified elsewhere)")
    pe.set_defaults(func=cmd_enter)

    ps = sub.add_parser("status", help="show round state")
    ps.add_argument("--round-id", required=True)
    ps.set_defaults(func=cmd_status)

    pc = sub.add_parser("close", help="seal the entry list and commit to it")
    pc.add_argument("--round-id", required=True)
    pc.set_defaults(func=cmd_close)

    pp = sub.add_parser("publish", help="broadcast the sealed list to Nostr")
    pp.add_argument("--round-id", required=True)
    pp.add_argument("--nsec", required=True, help="organizer Nostr secret key (nsec or hex)")
    pp.add_argument("--relay", action="append", help="relay url (repeatable)")
    pp.set_defaults(func=cmd_publish)

    pd = sub.add_parser("draw", help="select the winner from the draw block hash")
    pd.add_argument("--round-id", required=True)
    pd.add_argument("--block-hash", action="append",
                    help="supply block hash(es) directly instead of fetching")
    pd.add_argument("--rpc", help="Bitcoin Core RPC url (else mempool.space)")
    pd.set_defaults(func=cmd_draw)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
