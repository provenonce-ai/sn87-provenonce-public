"""A minimal READ-ONLY chain client for the SN87 testnet attestation verifier.

It answers exactly the reads ``verify_attestation.py`` needs, through the public ``bittensor``
SDK (the ``transport`` extra), and nothing else:

- ``last_weights_block(netuid, uid, at_block=None)``: ``LastUpdate[uid]`` of the subnet, from the
  state at ``at_block`` (or the current state).
- ``weight_row(netuid, mecid, uid, at_block=None)``: the uid's weight row, as
  ``{"dests": [...], "weights": [...]}``, from the state at ``at_block``.
- ``current_block()``.

This module has no write path of any kind: it never builds a transaction, holds no key or
account object, reads no home directory and no environment variable. It talks to one endpoint
(``ENDPOINT`` by default, or the one the caller names) and refuses to answer until that
endpoint's genesis hash equals the testnet genesis, so a wrong or hostile node cannot pose as
the testnet. Importing the SDK is deferred until the first read.

Run the verifier under a scratch HOME (it does this itself): the SDK may keep a small cache
under the HOME it is given.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

NETWORK = "test"
ENDPOINT = "wss://test.chain.opentensor.ai:443"
GENESIS = "0x8f9cf856bf558a14440e75569c9e58594757048d7b3a84b5d25f6bd978263105"
GLOBAL_MAX_SUBNET_COUNT = 4096  # SDK constant: storage index of mechanism m is m * 4096 + netuid


class ChainRefused(RuntimeError):
    """The endpoint is not the testnet (its genesis hash differs)."""


class ChainReadError(RuntimeError):
    """A read did not produce a usable value."""


def _default_subtensor_factory(endpoint: str) -> Any:
    """Build the SDK client, pinned to one endpoint (no fallback pool)."""
    import bittensor as bt  # noqa: PLC0415 - deferred so importing this module never loads it

    return bt.Subtensor(endpoint, fallback_endpoints=[], archive_endpoints=[])


def _storage() -> Any:
    import bittensor as bt  # noqa: PLC0415

    return bt.storage.SubtensorModule


class ChainReader:
    """Reads of testnet state. Every method is a storage query or a block-number read."""

    def __init__(self, endpoint: str = ENDPOINT, *,
                 subtensor_factory: Callable[[str], Any] | None = None) -> None:
        self._endpoint = endpoint
        self._factory = subtensor_factory or _default_subtensor_factory
        self._sub: Any = None
        self._verified = False
        self.read_count = 0  # every chain request made through this client

    # ------------------------------------------------------------------------- plumbing
    def _connect(self) -> Any:
        if self._sub is None:
            self._sub = self._factory(self._endpoint)
        if not self._verified:
            if self._raw_genesis() != GENESIS:
                self._sub = None
                raise ChainRefused("genesis hash does not match the testnet genesis")
            self._verified = True
        return self._sub

    def _raw_genesis(self) -> str:
        sub = self._sub
        self.read_count += 1
        # The SDK has no public genesis accessor on the blocking client: block 0's hash is it.
        return sub._call(sub._client._substrate.block_hash(0))

    def _query(self, name: str, params: list[int], *, block: int | None = None) -> Any:
        sub = self._connect()
        descriptor = getattr(_storage(), name)
        self.read_count += 1
        return sub.query(descriptor, params, block=block)

    @staticmethod
    def _index(mecid: int, netuid: int) -> int:
        return mecid * GLOBAL_MAX_SUBNET_COUNT + netuid

    # ----------------------------------------------------------------------- the reads
    def endpoint(self) -> str:
        return self._endpoint

    def current_block(self) -> int:
        sub = self._connect()
        self.read_count += 1
        block = sub.block
        if type(block) is not int:
            raise ChainReadError("current_block: not an integer")
        return block

    def last_weights_block(self, netuid: int, uid: int, at_block: int | None = None) -> int:
        """``LastUpdate[uid]``; with ``at_block`` it is read from that block's state."""
        updates = self._query("LastUpdate", [self._index(0, netuid)], block=at_block)
        if not isinstance(updates, list) or not 0 <= uid < len(updates):
            raise ChainReadError("last_weights_block: uid outside the LastUpdate vector")
        return int(updates[uid])

    def weight_row(self, netuid: int, mecid: int, uid: int,
                   at_block: int | None = None) -> dict[str, list[int]]:
        row = self._query("Weights", [self._index(mecid, netuid), uid], block=at_block) or []
        return {"dests": [int(dest) for dest, _ in row], "weights": [int(w) for _, w in row]}
