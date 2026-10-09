#!/usr/bin/env python3
"""Unsigned loopback development server (compatibility entry point).

  uv run python scripts/miner_serve.py --role candidate|baseline --port N [--host 127.0.0.1]

This script is a thin wrapper. The server lives in ``sn87_provenonce.miner_node.loopback`` and is
the same code that ``sn87-miner serve --unsigned-loopback`` runs. It is UNSIGNED and LOCAL ONLY:
the signed endpoint that validators call (``POST /v1/assurance``, btauth/1, shared replay store)
is ``sn87-miner serve`` (see docs/quickstart/miner.md). Both call the same method interface and
return the same canonical bytes. The full wire description follows (the module docstring of
``miner_node.loopback``).
"""

from __future__ import annotations

import socket  # noqa: F401  (tests patch ``miner_serve.socket``)

from sn87_provenonce.cmt import compile_cmt  # noqa: F401
from sn87_provenonce.miner_node import loopback as _loopback
from sn87_provenonce.miner_node.loopback import (  # noqa: F401
    BASELINE_MINER,
    CANDIDATE,
    LABEL,
    MAX_BODY,
    ROLES,
    Handler,
    MinerServer,
    RefusedHost,
    StagingError,
    main,
    require_loopback,
    role_method,
    serve,
    verify_compiled,
)

__doc__ = (__doc__ or "") + "\n" + (_loopback.__doc__ or "")

if __name__ == "__main__":
    raise SystemExit(main())
