# Node-runner raffle — reference implementation

A provably fair, privacy-preserving Bitcoin raffle for full node operators.
This is the working code for the architecture in the accompanying whitepaper:
a one-shot node check, a Nostr-published sealed entry list, and a draw seeded
by a future Bitcoin block hash that anyone can independently reproduce.

The full design writeup is in [`whitepaper/`](whitepaper/) (`.docx` and `.pdf`).

It is a reference implementation — a skeleton meant to be hardened into
something deployable, not a finished product. See "Known limitations" below.

## The five-stage loop

1. **Announce** a future Bitcoin block height that will decide the draw.
2. **Verify & enter** — each operator's node passes a P2P handshake check and
   is counted under their Nostr pubkey (npub), never their IP.
3. **Seal** — the full entry list is frozen, committed to (SHA-256), and
   published as a signed Nostr event across several independent relays.
4. **Draw** — once the block is mined, `hash mod N` selects the winner.
   Anyone can recompute this.
5. **Pay** — release the prize from a pre-funded multisig and publish the txid.

## Install

```bash
pip install -r requirements.txt        # requests + nostr-sdk
# The draw core, node check, and state management are pure stdlib.
```

## Two user interfaces

**`verify.html` — the public verifier (no server).** A single self-contained
HTML file. Open it in any browser, paste the entry list and the draw block
hash, and it recomputes the winner client-side. It depends on nothing you have
to trust — which is the point, since asking people to trust your server to
check your draw would defeat the exercise. Its JavaScript reproduces
`draw.py` exactly (verified byte-for-byte against the reference vector).

**`webapp/` — the operator dashboard (Flask).** A control panel for running
the loop with a UI instead of CLI flags: open a round, verify nodes and add
entries, seal, publish to Nostr, draw. It wraps the same `node_raffle`
package. Run it locally — the publish step handles your organizer secret key.

```bash
pip install flask
python webapp/app.py            # http://127.0.0.1:5000
```

The dashboard also serves the public verifier at `/verify.html`.

## Use the CLI

```bash
# 1. Open a round and announce the draw block publicly.
python -m node_raffle.cli init --round-id 2026-07 --draw-height 920000

# 2. Verify a node and count an entry (runs the real P2P handshake).
python -m node_raffle.cli enter --round-id 2026-07 --npub npub1... --ip 1.2.3.4

# 3. Seal the list and print its commitment.
python -m node_raffle.cli close --round-id 2026-07

# 4. Broadcast the sealed list to Nostr (needs the organizer nsec).
python -m node_raffle.cli publish --round-id 2026-07 --nsec nsec1...

# 5. After the block is mined, draw the winner.
python -m node_raffle.cli draw --round-id 2026-07

# Inspect state at any point.
python -m node_raffle.cli status --round-id 2026-07
```

For a harder-to-grind draw, seed from several consecutive blocks:
`init ... --draw-height 920000 --extra-blocks 2` uses blocks 920000–920002.

## Verify a draw independently — the whole point

A sceptic does not need this project. They need the published entry list (one
npub per line) and the draw block hash, then:

```bash
python verify.py --entries entries.txt \
    --block-hash 00000000000000001e4118adcfbb02364bc13c41c210d8811e4f39aeb3687e36
# or let it look the hash up by height:
python verify.py --entries entries.txt --height 920000
```

If the recomputed winner matches the announced one, the draw was honest.
`verify.py` depends only on `requests`, and only when you pass `--height`.

## The draw, precisely

So anyone can reimplement it in any language:

- **Canonical entries**: strip each line, drop blanks, de-duplicate, sort.
  The result depends only on the *set* of entries, not collection order.
- **Commitment**: `SHA-256(entries joined by "\n")`, hex.
- **Seed**: one block → `int(block_hash, 16)`. Several blocks →
  `int(SHA-256(raw_hash_bytes_concatenated))`.
- **Winner**: `entries[seed mod N]`.

## Layout

```
node_raffle/
  draw.py           # deterministic core: commitment, seed, winner (no network)
  check_node.py     # Bitcoin P2P handshake reachability check
  blockchain.py     # block hashes via mempool.space or your Bitcoin Core RPC
  nostr_publish.py  # publish / fetch the sealed list (nostr-sdk)
  registry.py       # round lifecycle + JSON persistence
  cli.py            # drives the five-stage loop
verify.html         # standalone public verifier — client-side, no server
webapp/             # Flask operator dashboard wrapping the package
  app.py
  templates/        # base, index, round
  static/app.css
verify.py           # standalone third-party verifier (command line)
tests/              # draw + lifecycle tests  (pytest -q)
```

## Custody is not in this code

Funding and payout are a wallet task, not a script. Use **Caravan**
(github.com/caravan-bitcoin/caravan): build a 2-of-3, fund it before the round
opens, publish the funding txid so entrants can confirm the prize is real and
reserved, and use Caravan again to build the payout transaction after the draw.

## Open-source pieces this builds on

- Bitcoin P2P protocol (public spec) — developer.bitcoin.org/reference/p2p_networking.html
- python-bitcoinlib — github.com/petertodd/python-bitcoinlib (alternative to the hand-rolled handshake)
- Bitnodes — github.com/ayeowch/bitnodes (model for a continuous reachability crawler)
- nostr-sdk / rust-nostr — github.com/rust-nostr/nostr (publishing the sealed list)
- mempool.space API — mempool.space/docs/api/rest (block-hash lookups)
- Caravan — github.com/caravan-bitcoin/caravan (multisig escrow)

## Known limitations (carried over from the whitepaper)

- **Node check is one-shot and clearnet-only.** It confirms a real, listening
  node at that moment — not uptime, not sync, not .onion. Add Tor SOCKS5 and
  continuous tracking (Bitnodes-style) before relying on it against Sybils.
- **No Merkle root / OpenTimestamps in v1.** Publishing across independent
  relays is the only "can't be quietly edited later" guarantee for now. The
  SHA-256 commitment helps but isn't independently timestamped.
- **Payout is manual multisig**, not an automatically executing DLC.
- **nostr-sdk is alpha** (pinned at 0.44.2); its API shifts across releases.
- **Not legal advice.** Cash-equivalent prize draws are regulated differently
  across jurisdictions; check the rules where you and your entrants are based.
```
