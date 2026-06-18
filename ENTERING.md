# How to enter the raffle

This guide is for **Bitcoin full-node operators** who want to enter.  
You do not need to trust the organiser — every step is independently verifiable.

---

## What you need

| Requirement | Why |
|-------------|-----|
| A Bitcoin full node reachable on the public internet | We do a live P2P handshake to confirm your node is real |
| Port **8333** open (or your custom port) | The handshake connects to that port |
| A **Nostr public key** (npub) | This is your pseudonymous identity in the entry list — your IP is never published |

Don't have an npub yet? Any Nostr client ([Damus](https://damus.io), [Primal](https://primal.net), [Amethyst](https://github.com/vitorpamplona/amethyst)) will generate one for free in under a minute.

---

## How to enter

### Option A — web form (easiest)

The organiser will share a link like:

```
http://<organiser-host>/enter/<round-id>
```

Open it, paste your **npub** and your **node's public IP address**, and click  
**"Verify node & enter"**. The page will confirm whether your node passed the check.

### Option B — contact the organiser directly

Send the organiser your **npub** and **node IP**. They will run the node check  
and add your entry via the operator dashboard or CLI.

---

## What happens after you submit

1. **Node check** — a Bitcoin P2P handshake is performed against your IP. This takes a few seconds. It confirms your node is listening; it does not reveal your IP to anyone else.
2. **Entry counted** — your npub is appended to the round's entry list. One entry per IP address.
3. **List sealed** — when the organiser closes entries, the full list is hashed (SHA-256) and published as a signed Nostr event across multiple independent relays. After this point the list cannot be changed without detection.
4. **Draw** — once the announced Bitcoin block is mined, its hash is used to pick the winner: `entries[block_hash mod N]`. This is computed publicly and anyone can recheck it.

---

## Verifying the draw yourself

You don't need to take anyone's word for it. Once the draw block is mined:

**In a browser (no install needed):**  
Open `verify.html` (the organiser will share a link, or you can [open it directly](verify.html)).  
Paste the published entry list and the block hash — it recomputes the winner client-side.

**From the command line:**

```bash
# Download the standalone verifier (depends only on requests, and only when using --height)
python verify.py \
  --entries entries.txt \
  --block-hash 00000000000000001e4118adcfbb02364bc13c41c210d8811e4f39aeb3687e36

# Or let it fetch the block hash from mempool.space by height:
python verify.py --entries entries.txt --height 920000
```

If the winner your script prints matches the announced winner, the draw was honest.

---

## Privacy notes

- Your **IP address** is used only for the one-time node handshake. It is not stored in the public entry list.
- Only your **npub** appears in the sealed, published list.
- The organiser sees your IP during verification. If you prefer not to reveal it directly, you can ask the organiser to accept a Bitnodes-verified entry instead (they can check [bitnodes.io](https://bitnodes.io) and skip the live handshake).

---

## Known limitations

- The node check is **one-shot and clearnet-only** — it confirms your node is reachable at the moment of entry, not continuously. .onion nodes are not supported yet.
- **One entry per IP** — multiple entries from the same IP are rejected automatically.
- Payout is manual multisig (Caravan). The organiser publishes the funding transaction ID before the round opens so you can confirm the prize is real and reserved.

---

## Questions?

Reach the organiser via Nostr or the contact method they published with the round announcement.
