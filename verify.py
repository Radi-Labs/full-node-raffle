#!/usr/bin/env python3
"""
Standalone draw verifier -- the script a sceptic runs.

You do NOT need the rest of this project to check a draw. You need:
  1. the entry list exactly as published on Nostr (one npub per line), and
  2. the hash of the announced draw block (from any explorer or your node).

Then this recomputes the winner. If it matches the announced result, the
draw was honest. If it doesn't, it wasn't.

Examples
--------
# You already have the block hash (no network needed at all):
  python verify.py --entries entries.txt \
      --block-hash 0000000000000000000245f...e1b

# Let it look the hash up by height from mempool.space:
  python verify.py --entries entries.txt --height 920000

# Hardened multi-block draw (block 920000 plus the next two):
  python verify.py --entries entries.txt --height 920000 --extra-blocks 2

The only optional dependency is `requests`, and only when you pass --height
instead of --block-hash.
"""

import argparse
import hashlib
import sys


def canonical_entries(lines):
    cleaned = {ln.strip() for ln in lines if ln and ln.strip()}
    return sorted(cleaned)


def commitment(entries):
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def derive_seed(block_hashes):
    if len(block_hashes) == 1:
        return int(block_hashes[0].strip(), 16)
    raw = b"".join(bytes.fromhex(h.strip()) for h in block_hashes)
    return int.from_bytes(hashlib.sha256(raw).digest(), "big")


def fetch_hashes(height, count):
    import requests
    base = "https://mempool.space/api"
    out = []
    for h in range(height, height + count):
        r = requests.get(f"{base}/block-height/{h}", timeout=15)
        r.raise_for_status()
        out.append(r.text.strip())
    return out


def main():
    ap = argparse.ArgumentParser(description="Independently verify a raffle draw")
    ap.add_argument("--entries", required=True,
                    help="file with the published entry list, one npub per line")
    ap.add_argument("--block-hash", action="append",
                    help="draw block hash (repeatable); skips network")
    ap.add_argument("--height", type=int, help="draw block height to look up")
    ap.add_argument("--extra-blocks", type=int, default=0,
                    help="extra consecutive blocks in a hardened seed")
    args = ap.parse_args()

    with open(args.entries) as f:
        entries = canonical_entries(f.readlines())
    if not entries:
        print("no entries found", file=sys.stderr)
        return 2

    if args.block_hash:
        hashes = args.block_hash
    elif args.height is not None:
        hashes = fetch_hashes(args.height, args.extra_blocks + 1)
    else:
        print("provide either --block-hash or --height", file=sys.stderr)
        return 2

    seed = derive_seed(hashes)
    index = seed % len(entries)

    print(f"Entries (N):       {len(entries)}")
    print(f"Entry commitment:  {commitment(entries)}")
    print("Block hash(es):")
    for h in hashes:
        print(f"  - {h.strip()}")
    print(f"Seed (hex):        {hex(seed)[2:]}")
    print(f"Winning index:     {index}")
    print(f"Winner:            {entries[index]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
