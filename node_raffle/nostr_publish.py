"""
Publishing the sealed entry list to Nostr, and fetching it back.

Publishing the full entry list as a signed event across several independent
relays is the v1 "can't be quietly edited later" guarantee: altering it after
the fact would mean colluding with every relay that holds a copy.

Uses nostr-sdk (rust-nostr Python bindings), MIT licensed:
https://github.com/rust-nostr/nostr  --  docs: https://rust-nostr.org/sdk
    pip install nostr-sdk

Verified against nostr-sdk 0.44.2. nostr-sdk is explicitly alpha and its API
has changed across releases; if a method name below is rejected, check the
docs for the version you pinned.
"""

from __future__ import annotations

import asyncio

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
    "wss://relay.primal.net",
]

ROUND_TAG = "noderaffle"


def _set_event_loop():
    # nostr-sdk needs the running loop registered (see rust-nostr install docs)
    try:
        from nostr_sdk import uniffi_set_event_loop
        uniffi_set_event_loop(asyncio.get_running_loop())
    except Exception:
        pass


async def _publish(entries_serialized: str, nsec: str, relays: list[str],
                   round_id: str) -> str:
    from nostr_sdk import Keys, Client, NostrSigner, EventBuilder, Kind, Tag
    _set_event_loop()

    keys = Keys.parse(nsec)
    client = Client(NostrSigner.keys(keys))
    for relay in relays:
        await client.add_relay(relay)
    await client.connect()

    tags = [
        Tag.identifier(round_id),                       # d tag: which round
        Tag.hashtag(ROUND_TAG),                         # t tag: discoverability
        Tag.alt(f"Node-runner raffle entry list, round {round_id}"),
    ]
    builder = EventBuilder(Kind(1), entries_serialized).tags(tags)
    event = builder.sign_with_keys(keys)
    await client.send_event(event)
    event_id = event.id().to_hex()
    await client.shutdown()
    return event_id


async def _fetch(event_id_hex: str, relays: list[str], timeout_secs: float = 10.0) -> str | None:
    from nostr_sdk import Client, Filter, EventId
    from datetime import timedelta
    _set_event_loop()

    client = Client()
    for relay in relays:
        await client.add_relay(relay)
    await client.connect()

    flt = Filter().id(EventId.parse(event_id_hex))
    events = await client.fetch_events(flt, timedelta(seconds=timeout_secs))
    await client.shutdown()

    vec = events.to_vec()
    return vec[0].content() if vec else None


def publish_entry_list(entries_serialized: str, nsec: str, round_id: str,
                       relays: list[str] | None = None) -> str:
    """Publish the sealed list; returns the Nostr event id (hex). Announce this id."""
    relays = relays or DEFAULT_RELAYS
    return asyncio.run(_publish(entries_serialized, nsec, relays, round_id))


def fetch_entry_list(event_id_hex: str, relays: list[str] | None = None) -> str | None:
    """Fetch a published entry list back from relays, for independent verification."""
    relays = relays or DEFAULT_RELAYS
    return asyncio.run(_fetch(event_id_hex, relays))
