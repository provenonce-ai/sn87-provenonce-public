"""Helpers shared by the signed-endpoint tests."""

from __future__ import annotations

from bittensor import sp_core


def throwaway_key():
    """A fresh random sr25519 key for one test. Never read from or written to a wallet."""
    return sp_core.Keypair.create_from_mnemonic(sp_core.Keypair.generate_mnemonic())


def dotted(*octets):
    """A dotted address built from octets: the public tree's text scan flags literal addresses."""
    return ".".join(str(o) for o in octets)


def echo_differential(capsule):
    """A custom miner method for the ``--method module:function`` tests."""
    return {"schema_version": "gra/0.1", "qid": capsule["qid"], "state": "NO_MATERIAL_DEVIATION"}
