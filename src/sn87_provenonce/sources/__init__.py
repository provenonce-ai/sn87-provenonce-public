"""Permitted source configurations: a source, a permission, a mapping version, a profile.

``mapping`` turns a permitted source export into IC capsules plus a disclosure; ``execution``
runs the existing bundle evaluation over them. Nothing here scores, and nothing here is a new
bundle schema: it is plumbing around ``bundle.evaluate``.
"""
