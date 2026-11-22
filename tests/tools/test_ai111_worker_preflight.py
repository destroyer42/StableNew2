"""Offline tests for the remote worker preflight and scope controls."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from functools import partial

import pytest

from tools.qualification.ai111 import worker_cgroup, worker_preflight, worker_privacy
from tools.qualification.ai111.worker_evidence import OLLAMA_REVISION, SINKS
from tools.qualification.ai111.worker_firewall import STATIC_NET0, candidate, console_step
from tools.qualification.ai111.worker_quiescence import OUTCOMES, Recorder, Runtime

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
    markers = {
        category: {
            "request_identity": _digest(f"request:{category}".encode()),
            "request": _digest(f"prompt:{category}".encode()),
            "response": _digest(f"response:{category}".encode()),
            "response_absence": None,
        }
        for category in OUTCOMES
    }
    scans = [
        {"complete": True, "bytes_read": 100, "matches": 0, "marker_sha256": marker}
        for record in markers.values()
        for marker in (record["request"], record["response"])
    ]
    privacy = records["privacy.json"]
    privacy["observations"] = {
        "attestations": privacy["observations"],
        "evidence": {
            "source_revision": OLLAMA_REVISION,
            "logging_before": SHA,
            "logging_after": SHA,
            "canaries": markers,
            "sinks": {
                sink: {"active": True, "inventory": SHA, "scans": copy.deepcopy(scans)}
                for sink in SINKS
            },
        },
    }
    provenance = records["provenance.json"]
    provenance["observations"] = {
        "attestations": provenance["observations"],
        "evidence": {
            "runtime": {
                "source_revision": OLLAMA_REVISION,
                "executable": SHA,
                "linked_runtime": SHA,
                "publisher_proof": SHA,
            },
            "model": {
                "manifest": SHA,
                "layers": SHA,
                "publisher": SHA,
                "revision": SHA,
                "license_text": SHA,
                "license_decision": "ACCEPTED",
                "license_decision_proof": SHA,
            },
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
                    "outcome": min(OUTCOMES[category]) if event == "terminal" else None,
                }
            )
    records["quiescence.json"] = {
        "identity_sha256": identity_digest,
        "observations": {
            "method": "owned_cgroup_v2_teardown",
            "observer_complete": True,
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
        ("egress", "pre_guest_exceptions_resolved", "UNKNOWN", "INCONCLUSIVE"),
        ("egress", "existing_flows_scoped_to_ssh", "FAIL", "HOLD"),
        ("egress", "static_ipv4_binding", "UNKNOWN", "INCONCLUSIVE"),
        ("egress", "dhcp_disabled_both_families", "FAIL", "HOLD"),
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
    observations = records[f"{area}.json"]["observations"]
    checks = observations if area == "egress" else observations["attestations"]
    checks[check]["result"] = value
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
        records["privacy.json"]["observations"]["attestations"]["success"]["unexpected"] = "text"
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
    assert (
        "IN ACCEPT -i net0 -source 192.168.1.182/32 -dest 192.168.1.22/32 -p tcp -dport 22"
        in rules["110.fw"]
    )
    assert "dhcp: 0" in rules["110.fw"]
    assert "ipfilter: 1" in rules["110.fw"]
    assert "ip=192.168.1.22/24" in STATIC_NET0
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


@pytest.mark.parametrize(
    ("finding", "verdict", "requirement"),
    [
        ("leak", "HOLD", "privacy.sink.syslog.retained_content"),
        ("unreadable", "INCONCLUSIVE", "privacy.sink.journal"),
        ("missing_sink", "INCONCLUSIVE", "privacy.sink_inventory"),
        ("leak_and_missing_sink", "HOLD", "privacy.sink.syslog.retained_content"),
        ("unbound_canary", "INCONCLUSIVE", "privacy.canary_coverage"),
        ("missing_response", "INCONCLUSIVE", "privacy.canary_coverage"),
        ("logging_change", "INCONCLUSIVE", "privacy.logging_binding"),
        ("runtime_drift", "INCONCLUSIVE", "provenance.runtime_binding"),
        ("wrong_model", "INCONCLUSIVE", "provenance.model_binding"),
        ("license_rejected", "HOLD", "provenance.license_decision"),
        ("license_missing", "INCONCLUSIVE", "provenance.license_decision"),
    ],
)
def test_structured_evidence_detects_physically_relevant_failures(
    evidence, finding, verdict, requirement
):
    path, records, current, write = evidence
    privacy = records["privacy.json"]["observations"]["evidence"]
    provenance = records["provenance.json"]["observations"]["evidence"]
    if finding == "leak":
        privacy["sinks"]["syslog"]["scans"][0]["matches"] = 1
    elif finding == "unreadable":
        privacy["sinks"]["journal"]["scans"][0]["complete"] = False
    elif finding == "missing_sink":
        del privacy["sinks"]["forwarding"]
    elif finding == "leak_and_missing_sink":
        del privacy["sinks"]["forwarding"]
        privacy["sinks"]["syslog"]["scans"][0]["matches"] = 1
    elif finding == "unbound_canary":
        privacy["canaries"]["success"]["request_identity"] = SHA
    elif finding == "missing_response":
        privacy["canaries"]["success"]["response"] = None
    elif finding == "logging_change":
        privacy["logging_after"] = "b" * 64
    elif finding == "runtime_drift":
        provenance["runtime"]["executable"] = "b" * 64
    elif finding == "wrong_model":
        provenance["model"]["manifest"] = "b" * 64
    elif finding == "license_rejected":
        provenance["model"]["license_decision"] = "REJECTED"
    elif finding == "license_missing":
        provenance["model"]["license_decision_proof"] = None
    report = worker_preflight.score(path, write(), current)
    assert report["verdict"] == verdict
    assert {"verdict": verdict, "requirement": requirement} in report["issues"]


class FakePopulation:
    def __init__(self, digest):
        self.cgroup_sha256 = digest
        self.state = "populated"

    def population(self):
        return self.state


def test_recorder_binds_outcomes_and_recursive_teardown(evidence):
    path, records, current, write = evidence
    recorder = Recorder(iter(range(1, 50)).__next__)
    for category in OUTCOMES:
        unit = FakePopulation(_digest(f"cgroup {category}".encode()))
        epoch = _digest(f"invocation {category}".encode())
        recorder.admit(
            _digest(f"request:{category}".encode()),
            category,
            Runtime(epoch, unit, lambda epoch=epoch: epoch),
        )
        recorder.populated()
        recorder.terminal(min(OUTCOMES[category]))
        unit.state = "empty"
        recorder.empty()
    observations = recorder.evidence(event_loss=0, other_clients=0)
    assert observations["observer_complete"] is True
    records["quiescence.json"]["observations"] = observations
    report = worker_preflight.score(path, write(), current)
    assert not any(issue["requirement"].startswith("quiescence.") for issue in report["issues"])


@pytest.mark.parametrize(
    "failure", ["concurrent", "restarted", "lingering", "ambiguous", "reused", "population_error"]
)
def test_recorder_latches_lifecycle_failures(failure):
    recorder = Recorder(iter(range(1, 50)).__next__)
    unit = FakePopulation("b" * 64)
    epoch = ["c" * 64]
    runtime = Runtime(epoch[0], unit, lambda: epoch[0])
    recorder.admit(SHA, "cancellation", runtime)
    recorder.populated()
    if failure == "concurrent":
        action = partial(recorder.admit, "d" * 64, "success", runtime)
    elif failure == "ambiguous":
        action = partial(recorder.terminal, "unknown")
    else:
        recorder.terminal("cancelled")
        if failure == "restarted":
            epoch[0] = "d" * 64
        elif failure == "reused":
            unit.cgroup_sha256 = "d" * 64
            unit.state = "empty"
        elif failure == "population_error":

            def unreadable():
                raise OSError("observation lost")

            unit.population = unreadable
        action = recorder.empty
    with pytest.raises((ValueError, OSError)):
        action()
    assert recorder.evidence(event_loss=0, other_clients=0)["observer_complete"] is False
    with pytest.raises(ValueError):
        recorder.admit("e" * 64, "success", runtime)


@pytest.mark.parametrize(
    ("rollback", "console", "closed", "disconnected", "files", "policy", "expected"),
    [
        (False, False, True, False, True, True, "STOP"),
        (True, True, False, False, True, True, "STOP"),
        (True, True, True, False, True, False, "DISCONNECT_CT_NET0"),
        (True, True, True, True, False, False, "STOP"),
        (True, True, True, True, True, False, "RESTORE_BASELINE_WHILE_DISCONNECTED"),
        (False, True, True, True, True, False, "KEEP_DISCONNECTED"),
        (False, True, True, True, True, True, "PRESENT_SEPARATE_RECONNECT_DECISION"),
    ],
)
def test_console_activation_and_rollback_never_reconnect(
    rollback,
    console,
    closed,
    disconnected,
    files,
    policy,
    expected,
):
    assert (
        console_step(
            net0=STATIC_NET0 + ",link_down=1",
            rollback=rollback,
            console_verified=console,
            admission_closed=closed,
            path_disconnected=disconnected,
            exact_files_verified=files,
            effective_policy_verified=policy,
        )
        == expected
    )


def test_recorder_latches_identity_read_failure_before_admission():
    class MissingIdentity:
        @property
        def cgroup_sha256(self):
            raise OSError("identity unavailable")

    recorder = Recorder(iter(range(1, 20)).__next__)
    with pytest.raises(OSError):
        recorder.admit(SHA, "success", Runtime(SHA, MissingIdentity(), lambda: SHA))
    with pytest.raises(ValueError):
        recorder.admit(SHA, "success", Runtime(SHA, FakePopulation(SHA), lambda: SHA))


@pytest.mark.parametrize(
    "net0",
    [
        STATIC_NET0,
        STATIC_NET0.replace("vmbr0", "vmbr1") + ",link_down=1",
        STATIC_NET0 + ",link_down=1,ip=dhcp",
        STATIC_NET0 + ",link_down=1,link_down=1",
    ],
)
def test_console_stops_on_unfenced_or_changed_static_definition(net0):
    assert (
        console_step(
            net0=net0,
            rollback=False,
            console_verified=True,
            admission_closed=True,
            path_disconnected=True,
            exact_files_verified=True,
            effective_policy_verified=True,
        )
        == "STOP"
    )
