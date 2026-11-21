"""Deterministic rendering, installed-evidence and rollback checks for CT 110."""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import asdict, replace

import pytest

from tools.qualification.ai111.worker_dhcp_guard import GUEST_MAC, LINK_TABLE, TABLE, Port, render
from tools.qualification.ai111.worker_firewall import candidate
from tools.qualification.ai111.worker_guard_validation import (
    TABLE_CHAINS,
    Observation,
    fingerprint,
    main,
    rollback_stage,
    verified,
)

PORT = Port("veth110i0", 21, "vmbr0")
SERVER = "192.168.1.1"
SERVER_MAC = "02:00:00:00:00:01"
SSH_SOURCE = "192.168.1.182"
PIN = "a" * 64


def test_rules_only_dispatch_the_pinned_port_and_default_drop():
    rules = render(PORT, server_ipv4=SERVER, server_mac=SERVER_MAC, ssh_ipv4=SSH_SOURCE)
    assert rules.startswith(f"table bridge {TABLE} {{")
    for key, hook, direction in (
        ("iif", "prerouting", "guest_egress"),
        ("oif", "postrouting", "guest_ingress"),
    ):
        assert f"hook {hook} priority -150; policy accept;" in rules
        assert f"meta {key} {PORT.index} jump {direction}" in rules
        assert f'meta {key}name "{PORT.name}" jump {direction}' in rules
        assert f"meta {key} != {PORT.index} counter drop" in rules
        assert f'meta {key}name != "{PORT.name}" counter drop' in rules
    assert 'meta ibrname != "vmbr0" counter drop' in rules
    assert 'meta obrname != "vmbr0" counter drop' in rules
    assert rules.count("\n        counter drop\n") == 3
    assert f"table netdev {LINK_TABLE}" in rules
    assert 'hook ingress device "veth110i0" priority -500; policy drop;' in rules
    assert "ether daddr & ff:ff:ff:ff:ff:f0 == 01:80:c2:00:00:00 counter drop" in rules
    assert "ether type { ip, arp } counter accept" in rules


def test_only_reserved_ipv4_dhcp_and_approved_ssh_are_allowed():
    rules = render(PORT, server_ipv4=SERVER, server_mac=SERVER_MAC, ssh_ipv4=SSH_SOURCE)
    assert "ip daddr 255.255.255.255 udp sport 68 udp dport 67 counter accept" in rules
    assert f"ether daddr {SERVER_MAC} ip saddr 192.168.1.22 ip daddr {SERVER} udp sport 68" in rules
    assert f"ether saddr {SERVER_MAC} ether daddr {GUEST_MAC} ip saddr {SERVER} " in rules
    assert f"ether saddr {SERVER_MAC} ether daddr ff:ff:ff:ff:ff:ff ip saddr {SERVER} " in rules
    allow_udp = [rule for rule in rules.splitlines() if "udp" in rule and "accept" in rule]
    assert len(allow_udp) == 4
    assert all(
        " udp sport 68 udp dport 67 " in r or " udp sport 67 udp dport 68 " in r for r in allow_udp
    )
    assert f"ip daddr {SSH_SOURCE} tcp sport 22 ct state established ct direction reply" in rules
    assert "dhcp: 0" in candidate(SSH_SOURCE)["110.fw"]


@pytest.mark.parametrize(
    ("name", "index", "bridge"),
    [
        ("eno1", 21, "vmbr0"),
        ("veth111i0", 21, "vmbr0"),
        ("fwln110i0", 21, "vmbr0"),
        ("veth110i1", 21, "vmbr0"),
        ("veth110i0", 0, "vmbr0"),
        ("veth110i0", True, "vmbr0"),
        ("veth110i0", 21, 'bad"\n'),
    ],
)
def test_rejects_unsupported_ports(name, index, bridge):
    with pytest.raises(ValueError):
        Port(name, index, bridge)


@pytest.mark.parametrize(
    ("server", "mac"),
    [
        ("8.8.8.8", SERVER_MAC),
        ("192.168.1.22", SERVER_MAC),
        (SSH_SOURCE, SERVER_MAC),
        (SERVER, "ff:ff:ff:ff:ff:ff"),
        (SERVER, GUEST_MAC),
        (SERVER, '02:00:00:00:00:01"\n'),
    ],
)
def test_rejects_invalid_or_unscoped_server_identity(server, mac):
    with pytest.raises(ValueError):
        render(PORT, server_ipv4=server, server_mac=mac, ssh_ipv4=SSH_SOURCE)


@pytest.fixture
def nft_table():
    items = [{"metainfo": {}}]
    for (family, table), chains in TABLE_CHAINS.items():
        items.append({"table": {"family": family, "name": table, "handle": 1}})
        for chain in sorted(chains):
            items.append({"chain": {"family": family, "table": table, "name": chain}})
            items.append(
                {
                    "rule": {
                        "family": family,
                        "table": table,
                        "chain": chain,
                        "expr": [{"counter": {"packets": 1, "bytes": 100}}, {"drop": None}],
                    },
                }
            )
    return {"nftables": items}


@pytest.fixture
def observed():
    return Observation(PORT, GUEST_MAC, PIN, PIN, PIN, PIN, PIN, 0, 0, 0)


def test_rule_fingerprint_ignores_counters_and_handles_only(nft_table, observed):
    reviewed = fingerprint(nft_table)
    changed = copy.deepcopy(nft_table)
    changed["nftables"][1]["table"]["handle"] = 6
    changed["nftables"][3]["rule"]["expr"][0]["counter"]["packets"] = 2
    assert verified(reviewed, changed, observed, observed)
    changed["nftables"][3]["rule"]["expr"][-1] = {"accept": None}
    assert not verified(reviewed, changed, observed, observed)


@pytest.mark.parametrize(
    "changed",
    [
        {"port": Port("veth110i0", 22, "vmbr0")},
        {"guest_mac": SERVER_MAC},
        {"host_boot_sha256": "b" * 64},
        {"ct_config_sha256": "b" * 64},
        {"link_epoch_sha256": "b" * 64},
        {"native_rules_sha256": "b" * 64},
        {"firewall_observer_epoch_sha256": "b" * 64},
        {"observer_event_loss": 1},
        {"firewall_reload_sequence": 1},
        {"link_change_sequence": 1},
    ],
)
def test_observation_drift_fails_closed(nft_table, observed, changed):
    assert not verified(fingerprint(nft_table), nft_table, observed, replace(observed, **changed))


def test_lost_or_reordered_rules_fail_closed(nft_table, observed):
    review = fingerprint(nft_table)
    assert not verified(review, {}, observed, observed)
    assert not verified(review, nft_table, observed, None)
    bridge_only = {
        "nftables": [
            entry
            for entry in nft_table["nftables"]
            if next(iter(entry.values())).get("family") != "netdev"
        ]
    }
    assert not verified(review, bridge_only, observed, observed)
    rules = nft_table["nftables"]
    rules[3], rules[5] = rules[5], rules[3]
    assert not verified(review, nft_table, observed, observed)
    del rules[3]
    assert not verified(review, nft_table, observed, observed)


@pytest.mark.parametrize(
    ("console", "closed", "native_off", "guard", "quarantine", "stage"),
    [
        (False, True, True, True, False, "STOP"),
        (True, False, True, True, False, "STOP"),
        (True, True, False, True, False, "VERIFY_NATIVE_DISABLED"),
        (True, True, True, False, False, "QUARANTINE_CT_PATH"),
        (True, True, False, False, True, "VERIFY_NATIVE_DISABLED"),
        (True, True, True, False, True, "PRESERVE_QUARANTINE"),
        (True, True, True, True, False, "REMOVE_VERIFIED_GUARD"),
    ],
)
def test_rollback_interlock(console, closed, native_off, guard, quarantine, stage):
    assert (
        rollback_stage(
            console_verified=console,
            session_closed=closed,
            native_disabled_verified=native_off,
            guard_verified=guard,
            path_quarantined=quarantine,
        )
        == stage
    )


def test_snapshot_cli_checks_both_exports_and_observations(
    tmp_path, monkeypatch, capsys, nft_table, observed
):
    bridge = tmp_path / "bridge.json"
    link = tmp_path / "link.json"
    observation = tmp_path / "observation.json"
    for path, family in ((bridge, "bridge"), (link, "netdev")):
        entries = [
            entry
            for entry in nft_table["nftables"]
            if next(iter(entry.values())).get("family") == family
        ]
        path.write_text(json.dumps({"nftables": entries}), encoding="ascii")
    observation.write_text(json.dumps(asdict(observed)), encoding="ascii")
    flags = ["--bridge-rules", str(bridge), "--link-rules", str(link)]
    monkeypatch.setattr(sys, "argv", ["guard", "fingerprint", *flags])
    assert main() == 0
    pin = capsys.readouterr().out.strip()
    assert pin == fingerprint(nft_table)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "guard",
            "compare",
            *flags,
            "--reviewed-sha256",
            pin,
            "--reviewed-observation",
            str(observation),
            "--current-observation",
            str(observation),
        ],
    )
    assert main() == 0
    assert capsys.readouterr().out.strip() == "SNAPSHOT_MATCH"
    link.unlink()
    assert main() == 2
    assert capsys.readouterr().out.strip() == "INCONCLUSIVE"
