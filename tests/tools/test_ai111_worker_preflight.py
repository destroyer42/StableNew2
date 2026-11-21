"""Offline tests for the remote worker preflight and scope controls."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os

import pytest

from tools.qualification.ai111 import worker_cgroup, worker_preflight, worker_privacy
from tools.qualification.ai111.worker_firewall import candidate

SHA = "a" * 64


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _encode(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")


@pytest.fixture
def evidence(tmp_path):
    identity = {
        "schema": worker_preflight.SCHEMA,
        "ct_id": 110,
        "run": SHA,
        "activated_ns": 0,
        "closed_ns": 50,
        "bindings": dict.fromkeys(worker_preflight.IDENTITIES, SHA),
    }
    identity_digest = _digest(_encode(identity))
    records = {"identity.json": identity}
    for area, checks in worker_preflight.CHECKS.items():
        records[f"{area}.json"] = {
            "identity_sha256": identity_digest,
            "observations": {
                check: {"result": "PASS", "observation_sha256": SHA} for check in checks
            },
        }
    events = []
    for category in sorted(worker_preflight.CATEGORIES):
        for event in worker_preflight.EVENTS:
            events.append(
                {
                    "sequence": len(events),
                    "monotonic_ns": len(events) + 1,
                    "request": _digest(f"request:{category}".encode()),
                    "category": category,
                    "invocation": _digest(f"invocation:{category}".encode()),
                    "cgroup": _digest(f"cgroup:{category}".encode()),
                    "event": event,
                }
            )
    records["quiescence.json"] = {
        "identity_sha256": identity_digest,
        "observations": {
            "method": "owned_cgroup_v2_teardown",
            "event_loss": 0,
            "other_clients": 0,
            "events": events,
        },
    }

    def write():
        lines = []
        for label, record in sorted(records.items()):
            raw = _encode(record)
            (tmp_path / label).write_bytes(raw)
            lines.append(f"{_digest(raw)}  {label}\n")
        manifest = "".join(lines).encode("ascii")
        (tmp_path / "manifest.sha256").write_bytes(manifest)
        return _digest(manifest)

    return tmp_path, records, copy.copy(identity["bindings"]), write


def test_self_consistent_bundle_without_verified_observations_cannot_admit(evidence):
    path, _, current, write = evidence
    report = worker_preflight.score(path, write(), current)
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["execution_authorized"] is False
    assert report["issues"] == [
        {
            "verdict": "INCONCLUSIVE",
            "requirement": "bundle.physical_evidence_verifier_unavailable",
        }
    ]


@pytest.mark.parametrize(
    ("area", "check", "value", "verdict"),
    [
        ("egress", "active_ct_policy", "FAIL", "HOLD"),
        ("egress", "ipv6_tcp", "UNKNOWN", "INCONCLUSIVE"),
        ("egress", "udp_dns", "FAIL", "HOLD"),
        ("egress", "dhcpv4_acquisition_and_renewal", "UNKNOWN", "INCONCLUSIVE"),
        ("egress", "dhcp_scope_enforced", "FAIL", "HOLD"),
        ("egress", "no_unauthorized_egress", "FAIL", "HOLD"),
        ("egress", "all_interfaces", "UNKNOWN", "INCONCLUSIVE"),
        ("egress", "zero_loss", "FAIL", "HOLD"),
        ("egress", "continuous_attribution", "UNKNOWN", "INCONCLUSIVE"),
        ("egress", "ssh", "FAIL", "HOLD"),
        ("egress", "rollback", "FAIL", "HOLD"),
        ("privacy", "success", "FAIL", "HOLD"),
        ("privacy", "invalid_request", "FAIL", "HOLD"),
        ("privacy", "cancellation", "UNKNOWN", "INCONCLUSIVE"),
        ("privacy", "replay_disabled", "FAIL", "HOLD"),
        ("privacy", "no_unknown_forwarding", "UNKNOWN", "INCONCLUSIVE"),
        ("privacy", "active_sink_inventory", "UNKNOWN", "INCONCLUSIVE"),
        ("privacy", "stable_logging", "FAIL", "HOLD"),
        ("provenance", "accepted_executable_build", "UNKNOWN", "INCONCLUSIVE"),
        ("provenance", "license_accepted", "FAIL", "HOLD"),
    ],
)
def test_mandatory_attestations(evidence, area, check, value, verdict):
    path, records, current, write = evidence
    records[f"{area}.json"]["observations"][check]["result"] = value
    report = worker_preflight.score(path, write(), current)
    assert report["verdict"] == verdict
    assert {"verdict": verdict, "requirement": f"{area}.{check}"} in report["issues"]


@pytest.mark.parametrize(
    "key", ["firewall", "logging", "host_boot", "model_manifest", "authorization"]
)
def test_current_identity_drift(evidence, key):
    path, _, current, write = evidence
    current[key] = "b" * 64
    assert worker_preflight.score(path, write(), current)["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "operation", ["missing", "altered", "wrong_manifest", "unbound", "extra_field"]
)
def test_bundle_integrity(evidence, operation):
    path, records, current, write = evidence
    if operation == "unbound":
        records["privacy.json"]["identity_sha256"] = "b" * 64
    if operation == "extra_field":
        records["privacy.json"]["observations"]["success"]["unexpected"] = "text"
    digest = write()
    if operation == "missing":
        (path / "privacy.json").unlink()
    if operation == "altered":
        (path / "privacy.json").write_bytes(b"{}")
    if operation == "wrong_manifest":
        digest = "b" * 64
    assert worker_preflight.score(path, digest, current)["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    ("failure", "verdict"),
    [
        ("terminal_missing", "INCONCLUSIVE"),
        ("lingering", "INCONCLUSIVE"),
        ("observer_loss", "HOLD"),
        ("other_client", "HOLD"),
        ("reused_cgroup", "INCONCLUSIVE"),
        ("restarted", "INCONCLUSIVE"),
        ("duplicate", "INCONCLUSIVE"),
        ("out_of_window", "INCONCLUSIVE"),
        ("unsupported", "INCONCLUSIVE"),
    ],
)
def test_teardown_fails_closed(evidence, failure, verdict):
    path, records, current, write = evidence
    observation = records["quiescence.json"]["observations"]
    events = observation["events"]
    if failure == "terminal_missing":
        del events[2]
    if failure == "lingering":
        events[3]["event"] = "populated"
    if failure == "observer_loss":
        observation["event_loss"] = 1
    if failure == "other_client":
        observation["other_clients"] = 1
    if failure == "reused_cgroup":
        for event in events[4:8]:
            event["cgroup"] = events[0]["cgroup"]
    if failure == "restarted":
        events[2]["invocation"] = "b" * 64
    if failure == "duplicate":
        events[2]["sequence"] = events[1]["sequence"]
    if failure == "out_of_window":
        events[-1]["monotonic_ns"] = 60
    if failure == "unsupported":
        observation["method"] = "api_ps"
    assert worker_preflight.score(path, write(), current)["verdict"] == verdict


def test_candidate_contains_no_host_policy_or_outbound_exception():
    rules = candidate("192.168.1.182")
    assert "enable: 0" in rules["host.fw"]
    assert "policy_out: ACCEPT" in rules["cluster.fw"]
    assert "policy_out: DROP" in rules["110.fw"]
    assert "IN ACCEPT -source 192.168.1.182/32 -p tcp -dport 22" in rules["110.fw"]
    assert "OUT ACCEPT" not in rules["110.fw"]
    for unsafe in ("::1", "8.8.8.8", "127.0.0.1", "192.168.1.1/24", "192.168.1.2\n[RULES]"):
        with pytest.raises(ValueError):
            candidate(unsafe)


def test_privacy_reports_counts_only_and_spans_buffer_boundary(monkeypatch):
    marker = b"AI111-SYNTHETIC-MARKER-9a2d"
    monkeypatch.setattr(worker_privacy, "CHUNK", 9)
    raw = b"line: " + marker + b"\nresponse: " + marker
    assert worker_privacy.scan(io.BytesIO(raw), marker) == {
        "marker_sha256": _digest(marker),
        "bytes_read": len(raw),
        "matches": 2,
        "complete": True,
    }


def test_privacy_unreadable_is_incomplete():
    class Broken(io.BytesIO):
        def read(self, size=-1):
            raise OSError("not reported")

    result = worker_privacy.scan(Broken(), b"AI111-SYNTHETIC-MARKER-9a2d")
    assert result["complete"] is False
    assert result["matches"] == 0


def test_privacy_nonblocking_read_is_incomplete():
    class Unavailable(io.RawIOBase):
        def read(self, size=-1):
            return None

    result = worker_privacy.scan(Unavailable(), b"AI111-SYNTHETIC-MARKER-9a2d")
    assert result["complete"] is False


@pytest.mark.skipif(os.name != "posix", reason="Linux cgroup file descriptor semantics")
def test_cgroup_pins_identity_and_rejects_path_replacement(tmp_path, monkeypatch):
    name = "ai111-wcq-" + "f" * 32 + ".service"
    invocation = "d" * 32
    boot = tmp_path / "boot_id"
    boot.write_text("b" * 32, encoding="ascii")
    monkeypatch.setattr(worker_cgroup, "BOOT_ID", boot)
    unit = tmp_path / name
    with pytest.raises(FileNotFoundError), worker_cgroup.pin(name, invocation, root=tmp_path):
        pytest.fail("missing cgroup was pinned")
    unit.mkdir()
    events = unit / "cgroup.events"
    events.write_bytes(b"populated 1\nfrozen 0\n")
    with worker_cgroup.pin(name, invocation, root=tmp_path) as scope:
        assert scope.population() == "populated"
        events.write_bytes(b"populated 0\nfrozen 0\n")
        assert scope.population() == "empty"
        events.write_bytes(b"populated 0\npopulated 1\n")
        with pytest.raises(ValueError, match="ambiguous"):
            scope.population()
        events.write_bytes(b"populated 0\n")
        unit.rename(tmp_path / "old")
        unit.mkdir()
        events.write_bytes(b"populated 0\n")
        with pytest.raises(ValueError, match="changed"):
            scope.population()
