"""Miner node: one launcher for the signed endpoint, the loopback development server, and the
signed endpoint announcement record.

The base package imports nothing from the chain SDK. Modules that need it (``keys``,
``launcher``, ``announcement``) import it lazily, inside functions, so the unsigned loopback
development server keeps working with only the base install.
"""
