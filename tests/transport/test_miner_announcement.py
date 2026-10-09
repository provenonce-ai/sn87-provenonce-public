"""The signed endpoint announcement: a pure data and signature object. No chain, no network."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from transport_support import dotted, throwaway_key

from sn87_provenonce.canonical import canonical_bytes
from sn87_provenonce.miner_node import announcement as ann
from sn87_provenonce.miner_node.launcher import main

NOW = 1_800_000_000_000
DAY = 24 * 3600 * 1000
NETUID = 582
PUBLIC = dotted(93, 184, 216, 34)  # a global address


def record(key, **changes):
    base = ann.Announcement(
        netuid=NETUID, hotkey=key.ss58_address, endpoint="https://example.invalid:8443",
        sequence=5, issued_at_ms=NOW - 1000, expires_at_ms=NOW + DAY)
    return replace(base, **changes)


def signed(key, **changes):
    return ann.sign(record(key, **changes), key)


def verify(raw, **kwargs):
    kwargs.setdefault("last_accepted", None)  # the API requires the argument; None = never seen
    return ann.verify(raw, **kwargs)


def code(error):
    return str(error.value)


def test_a_signed_record_verifies_from_the_hotkey_address_alone():
    key = throwaway_key()
    raw = signed(key)
    result = verify(raw, netuid=NETUID, now_ms=NOW, expected_hotkey=key.ss58_address)
    assert result == record(key)
    assert raw == canonical_bytes(json.loads(raw))  # canonical bytes: what is signed is stable
    assert len(raw) <= ann.MAX_RECORD_BYTES


def test_signing_requires_the_named_hotkey():
    key, other = throwaway_key(), throwaway_key()
    with pytest.raises(ann.AnnouncementError, match="SIGNER_MISMATCH"):
        ann.sign(record(key), other)


@pytest.mark.parametrize("field, value", [
    ("endpoint", "https://example.invalid:9443"),
    ("sequence", 6),
    ("expires_at_ms", NOW + 2 * DAY),
    ("netuid", 583),
])
def test_any_changed_field_breaks_the_signature(field, value):
    key = throwaway_key()
    doc = json.loads(signed(key))
    doc["announcement"][field] = value
    with pytest.raises(ann.AnnouncementError) as error:
        verify(canonical_bytes(doc), netuid=doc["announcement"]["netuid"], now_ms=NOW)
    assert code(error) == "ANNOUNCEMENT_SIGNATURE_INVALID"


def test_a_signature_by_another_key_does_not_verify():
    key, other = throwaway_key(), throwaway_key()
    doc = json.loads(signed(key))
    doc["signature"]["value"] = json.loads(signed(other))["signature"]["value"]
    with pytest.raises(ann.AnnouncementError, match="SIGNATURE_INVALID"):
        verify(canonical_bytes(doc), netuid=NETUID, now_ms=NOW)


def test_signature_is_domain_separated_from_other_signed_bytes():
    key = throwaway_key()
    doc = json.loads(signed(key))
    plain = bytes(key.sign(canonical_bytes(doc["announcement"])))  # no domain prefix
    doc["signature"]["value"] = "0x" + plain.hex()
    with pytest.raises(ann.AnnouncementError, match="SIGNATURE_INVALID"):
        verify(canonical_bytes(doc), netuid=NETUID, now_ms=NOW)


def test_wrong_netuid_and_wrong_hotkey_are_refused():
    key, other = throwaway_key(), throwaway_key()
    raw = signed(key)
    with pytest.raises(ann.AnnouncementError, match="WRONG_NETUID"):
        verify(raw, netuid=1, now_ms=NOW)
    with pytest.raises(ann.AnnouncementError, match="WRONG_HOTKEY"):
        verify(raw, netuid=NETUID, now_ms=NOW, expected_hotkey=other.ss58_address)


def test_freshness_expiry_and_issue_time():
    key = throwaway_key()
    raw = signed(key)
    with pytest.raises(ann.AnnouncementError, match="EXPIRED"):
        verify(raw, netuid=NETUID, now_ms=NOW + DAY)
    with pytest.raises(ann.AnnouncementError, match="ISSUED_IN_FUTURE"):
        verify(raw, netuid=NETUID, now_ms=NOW - 1000 - ann.MAX_FUTURE_SKEW_MS - 1)
    # a little clock skew is tolerated
    verify(raw, netuid=NETUID, now_ms=NOW - 1000 - ann.MAX_FUTURE_SKEW_MS)
    with pytest.raises(ann.AnnouncementError, match="VALIDITY_WINDOW_INVALID"):
        signed(key, expires_at_ms=NOW - 1000 + ann.MAX_VALIDITY_MS + 1)
    with pytest.raises(ann.AnnouncementError, match="VALIDITY_WINDOW_INVALID"):
        signed(key, expires_at_ms=NOW - 1000)


def test_an_older_sequence_cannot_replace_a_newer_one_and_a_conflict_is_refused():
    key = throwaway_key()
    old, new = signed(key, sequence=5), signed(key, sequence=9)
    other_9 = signed(key, sequence=9, endpoint="https://example.invalid:9443")
    state = ann.Accepted(9, ann.record_digest(new))
    verify(new, netuid=NETUID, now_ms=NOW, last_accepted=state)  # the same record again
    with pytest.raises(ann.AnnouncementError, match="SEQUENCE_ROLLBACK"):
        verify(old, netuid=NETUID, now_ms=NOW, last_accepted=state)
    with pytest.raises(ann.AnnouncementError, match="SEQUENCE_CONFLICT"):
        verify(other_9, netuid=NETUID, now_ms=NOW, last_accepted=state)
    with pytest.raises(TypeError):  # last_accepted is mandatory, not optional
        ann.verify(new, netuid=NETUID, now_ms=NOW)
    with pytest.raises(TypeError):
        ann.select([new], netuid=NETUID, hotkey=key.ss58_address, now_ms=NOW)


def test_select_takes_the_highest_sequence_and_refuses_ties_with_different_bytes():
    key = throwaway_key()
    old, new = signed(key, sequence=5), signed(key, sequence=9)
    kwargs = dict(netuid=NETUID, hotkey=key.ss58_address, now_ms=NOW)
    chosen, accepted = ann.select([old, new, b"garbage"], last_accepted=None, **kwargs)
    assert chosen.sequence == 9 and accepted == ann.Accepted(9, ann.record_digest(new))
    assert ann.select([old], last_accepted=accepted, **kwargs) is None
    assert ann.select([new], last_accepted=accepted, **kwargs)[1] == accepted
    assert ann.select([], last_accepted=None, **kwargs) is None
    tie = signed(key, sequence=9, endpoint="https://example.invalid:9443")
    assert ann.select([new, tie], last_accepted=None, **kwargs) is None
    assert ann.select([new, new], last_accepted=None, **kwargs)[0].sequence == 9


def test_select_ignores_records_for_other_hotkeys_and_expired_records():
    key, other = throwaway_key(), throwaway_key()
    assert ann.select([signed(other)], netuid=NETUID, hotkey=key.ss58_address, now_ms=NOW,
                      last_accepted=None) is None
    assert ann.select([signed(key)], netuid=NETUID, hotkey=key.ss58_address,
                      now_ms=NOW + 2 * DAY, last_accepted=None) is None


@pytest.mark.parametrize("endpoint", [
    "http://example.invalid", "ftp://example.invalid", "https://example.invalid/x",
    "https:" + "//user:pw" + chr(64) + "example.invalid", "https://example.invalid?q=1",
    "https://example.invalid#f", "example.invalid", "", "https://",
    "http://127.0.0.1:8787",
])
def test_the_endpoint_must_be_an_https_origin(endpoint):
    with pytest.raises(ann.AnnouncementError, match="ENDPOINT"):
        signed(throwaway_key(), endpoint=endpoint)


def hostile_endpoints():
    d = dotted
    https = "https:" + "//"
    return [
        https + "127.0.0.1", https + d(10, 0, 0, 1) + ":443", https + d(169, 254, 169, 254),
        https + "[::1]", https + "localhost", https + "app.localhost",
        https + d(192, 168, 0, 1), https + d(172, 16, 0, 1), https + d(100, 64, 0, 1),
        https + d(0, 0, 0, 0), https + d(224, 0, 0, 1), https + "[fe80::1]", https + "[fc00::1]",
        https + "[::ffff:" + d(127, 0, 0, 1) + "]", https + "[64:ff9b::" + d(127, 0, 0, 1) + "]",
        https + "example.invalid:0", https + "ex ample.invalid", https + "exa\nmple.invalid",
        https + "exa\tmple.invalid", https + "example.invalid\\.b.invalid",
        https + "2130706433", https + "0x7f.1", https + "0x7f000001", https + "0" + d(10, 0, 0, 1),
        https + "example.invalid:99999", https + "-bad.invalid", https + "bad_.invalid",
        https + "example.123", https + "caf\u00e9.invalid", https + "example.invalid%0a",
        https + "example.invalid\x00", https + "example.invalid:", "HTTPS://example.invalid",
        https + "Example.Invalid",
    ]


@pytest.mark.parametrize("endpoint", hostile_endpoints())
def test_the_endpoint_must_name_a_global_address_and_be_plain_printable_text(endpoint):
    with pytest.raises(ann.AnnouncementError, match="^ANNOUNCEMENT_ENDPOINT"):
        ann.validate_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", [
    "https://example.invalid", "https://example.invalid:8443/",
    "https:" + "//a.b-c.example.invalid",
    f"https://{PUBLIC}:8443", "https://[2606:2800:220:1:248:1893:25c8:1946]:443",
])
def test_ordinary_global_endpoints_are_accepted(endpoint):
    assert ann.validate_endpoint(endpoint) == endpoint.rstrip("/")


def test_loopback_http_is_accepted_only_when_asked():
    key = throwaway_key()
    raw = ann.sign(record(key, endpoint="http://127.0.0.1:8787"), key, allow_loopback=True)
    with pytest.raises(ann.AnnouncementError, match="ENDPOINT_NOT_GLOBAL"):
        verify(raw, netuid=NETUID, now_ms=NOW)
    assert verify(raw, netuid=NETUID, now_ms=NOW, allow_loopback=True).endpoint == (
        "http://127.0.0.1:8787")


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra=1),
    lambda d: d["announcement"].update(extra=1),
    lambda d: d["signature"].update(crypto="ed25519"),
    lambda d: d["announcement"].update(schema_version="other/1"),
    lambda d: d["announcement"].update(transport="gra-transport/9"),
    lambda d: d["announcement"].update(sequence=-1),
    lambda d: d["announcement"].update(netuid=70000),
    lambda d: d["signature"].update(value="0x00"),
])
def test_malformed_records_are_refused_with_a_stable_code(mutate):
    key = throwaway_key()
    doc = json.loads(signed(key))
    mutate(doc)
    with pytest.raises(ann.AnnouncementError, match="^ANNOUNCEMENT_"):
        verify(canonical_bytes(doc), netuid=NETUID, now_ms=NOW)


def test_oversize_and_non_canonical_records_are_refused():
    key = throwaway_key()
    with pytest.raises(ann.AnnouncementError, match="TOO_LARGE"):
        verify(b" " * (ann.MAX_RECORD_BYTES + 1), netuid=NETUID, now_ms=NOW)
    pretty = json.dumps(json.loads(signed(key)), indent=2).encode()
    with pytest.raises(ann.AnnouncementError, match="NOT_CANONICAL"):
        verify(pretty, netuid=NETUID, now_ms=NOW)


def test_axon_fetch_url_refuses_non_global_addresses():
    import ipaddress

    def v4(text):
        return int(ipaddress.IPv4Address(text))

    assert ann.axon_fetch_url(v4(PUBLIC), 8091, 4) == (
        f"http://{PUBLIC}:8091/.well-known/sn87-miner-announcement.json")
    six = int(ipaddress.IPv6Address("2606:2800:220:1:248:1893:25c8:1946"))
    assert ann.axon_fetch_url(six, 8091, 6).startswith("http://[2606:2800:220:1:")
    for bad in ("127.0.0.1", dotted(10, 0, 0, 5), dotted(192, 168, 1, 1),
                dotted(169, 254, 169, 254), dotted(0, 0, 0, 0), dotted(224, 0, 0, 1)):
        with pytest.raises(ann.AnnouncementError, match="AXON_NOT_GLOBAL"):
            ann.axon_fetch_url(v4(bad), 8091, 4)
    with pytest.raises(ann.AnnouncementError, match="AXON_INVALID"):
        ann.axon_fetch_url(v4(PUBLIC), 0, 4)
    with pytest.raises(ann.AnnouncementError, match="AXON_INVALID"):
        ann.axon_fetch_url(v4(PUBLIC), 80, 5)


def test_serve_axon_dry_run_builds_parameters_and_sends_nothing():
    key = throwaway_key()
    plan = ann.serve_axon_dry_run(record(key, endpoint=f"https://{PUBLIC}:8443"))
    assert plan["status"] == "NOT SENT" and plan["buildable"] is True
    assert plan["call"] == "SubtensorModule.serve_axon" and plan["signed_by"] == key.ss58_address
    assert plan["params"] == {
        "netuid": NETUID, "version": 0, "ip": 1572395042, "port": 8443, "ip_type": 4,
        "protocol": 4, "placeholder1": 0, "placeholder2": 0}
    named = ann.serve_axon_dry_run(record(key))
    assert named["buildable"] is False and "IP address only" in named["reason"]


def test_the_dry_run_parameter_names_are_the_sdk_call_parameters():
    import inspect

    from bittensor._generated import calls

    owner = next(v for v in vars(calls).values()
                 if inspect.isclass(v) and hasattr(v, "serve_axon")
                 and getattr(v.serve_axon, "__qualname__", "").endswith("serve_axon"))
    sdk = set(inspect.signature(owner.serve_axon).parameters)
    key = throwaway_key()
    plan = ann.serve_axon_dry_run(record(key, endpoint=f"https://{PUBLIC}"))
    assert set(plan["params"]) == sdk


def test_the_module_has_no_send_path():
    """The announcement module imports no network, chain client or process module; the chain
    SDK appears only as a lazy ``sp_core`` import for signing and verifying bytes."""
    import ast

    import sn87_provenonce.miner_node.announcement as module

    tree = ast.parse(Path(module.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or "") + ":"
                         + ",".join(alias.name for alias in node.names))
    assert imported == {
        "__future__:annotations", "ipaddress", "collections.abc:Iterable",
        "dataclasses:dataclass", "typing:Any", "urllib.parse:urlsplit",
        "sn87_provenonce.canonical:canonical_bytes,parse_canonical", "bittensor:sp_core",
        "hashlib", "re",
    }


def test_cli_announce_then_verify_round_trip(monkeypatch, tmp_path, capsys):
    mnemonic = __import__("bittensor").sp_core.Keypair.generate_mnemonic()
    monkeypatch.setenv("SN87_TEST_MINER_HOTKEY", mnemonic)
    out = tmp_path / "announcement.json"
    assert main(["announce", "--hotkey-env", "SN87_TEST_MINER_HOTKEY", "--netuid", "582",
                 "--endpoint", f"https://{PUBLIC}:8443", "--valid-days", "2",
                 "--axon-dry-run", "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert "NOT SENT" in err and "never sends it" in err and mnemonic not in err
    assert main(["verify-announcement", str(out), "--netuid", "582"]) == 0
    assert "announcement OK" in capsys.readouterr().out
    assert main(["verify-announcement", str(out), "--netuid", "1"]) == 2
    assert "ANNOUNCEMENT_WRONG_NETUID" in capsys.readouterr().err
    # an existing output file is never overwritten
    assert main(["announce", "--hotkey-env", "SN87_TEST_MINER_HOTKEY", "--netuid", "582",
                 "--endpoint", f"https://{PUBLIC}:8443", "--out", str(out)]) == 2
    assert "OUTPUT_NOT_WRITTEN" in capsys.readouterr().err
