"""
Reading block hashes for the draw.

Two sources, both supported:

1. mempool.space REST API (default) -- "The Mempool Open Source Project":
   https://mempool.space/docs/api/rest  (self-host: github.com/mempool/mempool)
2. Your own Bitcoin Core node over RPC -- the no-third-party path. Prefer
   this for the real draw: depending on a block explorer reintroduces a
   trusted party for the single most important input.

A future block height is announced before entries close; once that block is
mined, its hash becomes the public seed. `tip_height` lets the caller check
whether the draw block exists yet.
"""

from __future__ import annotations

import requests

DEFAULT_MEMPOOL = "https://mempool.space/api"


class Mempool:
    def __init__(self, base_url: str = DEFAULT_MEMPOOL, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def block_hash(self, height: int) -> str:
        r = requests.get(f"{self.base_url}/block-height/{height}", timeout=self.timeout)
        r.raise_for_status()
        return r.text.strip()

    def tip_height(self) -> int:
        r = requests.get(f"{self.base_url}/blocks/tip/height", timeout=self.timeout)
        r.raise_for_status()
        return int(r.text.strip())

    def block_hashes(self, start_height: int, count: int = 1) -> list[str]:
        return [self.block_hash(start_height + i) for i in range(count)]


class BitcoinCoreRPC:
    """Minimal JSON-RPC client for `getblockhash` / `getblockcount`.

    Point this at your own node instead of a public explorer:
        rpc = BitcoinCoreRPC("http://user:pass@127.0.0.1:8332")
    """

    def __init__(self, url: str, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout

    def _call(self, method: str, params: list | None = None):
        payload = {"jsonrpc": "1.0", "id": "raffle", "method": method, "params": params or []}
        r = requests.post(self.url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data["result"]

    def block_hash(self, height: int) -> str:
        return self._call("getblockhash", [height])

    def tip_height(self) -> int:
        return int(self._call("getblockcount"))

    def block_hashes(self, start_height: int, count: int = 1) -> list[str]:
        return [self.block_hash(start_height + i) for i in range(count)]
