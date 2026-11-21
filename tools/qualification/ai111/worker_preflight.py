"""Score reviewed, digest-bound AI-111 worker evidence without contacting a worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{64}")
LIMIT = 1024 * 1024
SCHEMA = "stablenew.ai111.worker-preflight/1"
IDENTITIES = frozenset(
    {
        "host_boot",
        "ct_config",
        "executable",
        "linked_runtime",
        "model_manifest",
        "model_layers",
        "observer",
        "tool",
        "firewall",
        "logging",
        "authorization",
    }
)
CHECKS = {
    "egress": frozenset(
        {
            "active_ct_policy",
            "all_interfaces",
            "ipv4_tcp",
            "ipv6_tcp",
            "udp_dns",
            "dhcpv4_acquisition_and_renewal",
            "dhcp_scope_enforced",
            "other_outbound",
            "no_preexisting_egress",
            "continuous_attribution",
            "zero_loss",
            "no_unauthorized_egress",
            "loopback",
            "ssh",
            "rollback",
        }
    ),
    "privacy": frozenset(
        {
            "source_review",
            "active_sink_inventory",
            "replay_disabled",
            "success",
            "invalid_request",
            "cancellation",
            "no_unknown_forwarding",
            "stable_logging",
        }
    ),
    "provenance": frozenset(
        {
            "accepted_executable_build",
            "linked_runtime",
            "publisher_revision",
            "selected_model_layers",
            "license_text",
            "license_accepted",
        }
    ),
}
EVIDENCE_FILES = (
    "identity.json",
    "egress.json",
    "privacy.json",
    "quiescence.json",
    "provenance.json",
)
CATEGORIES = frozenset({"success", "invalid_request", "cancellation"})
EVENTS = ("admitted", "populated", "terminal", "empty")


def _digest(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _closed(value: object, keys: frozenset[str] | set[str]) -> bool:
    return isinstance(value, dict) and value.keys() == keys


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


def _check_attestations(section: str, evidence: object) -> list[tuple[str, str]]:
    if not _closed(evidence, CHECKS[section]):
        return [("INCONCLUSIVE", f"{section}.schema")]
    issues = []
    for key, record in sorted(evidence.items()):
        if not _closed(record, {"result", "observation_sha256"}) or not _digest(
            record["observation_sha256"]
        ):
            issues.append(("INCONCLUSIVE", f"{section}.{key}"))
        elif record["result"] != "PASS":
            verdict = "HOLD" if record["result"] == "FAIL" else "INCONCLUSIVE"
            issues.append((verdict, f"{section}.{key}"))
    return issues


def _check_quiescence(evidence: object) -> list[tuple[str, str]]:
    if not _closed(evidence, {"method", "event_loss", "other_clients", "events"}):
        return [("INCONCLUSIVE", "quiescence.schema")]
    if evidence["method"] != "owned_cgroup_v2_teardown":
        return [("INCONCLUSIVE", "quiescence.observer")]
    issues = []
    for key in ("event_loss", "other_clients"):
        if not _count(evidence[key]):
            issues.append(("INCONCLUSIVE", f"quiescence.{key}"))
        elif evidence[key]:
            issues.append(("HOLD", f"quiescence.{key}"))
    events = evidence["events"]
    if not isinstance(events, list) or len(events) != len(CATEGORIES) * len(EVENTS):
        return [*issues, ("INCONCLUSIVE", "quiescence.incomplete_lifecycle")]

    last_time = -1
    seen_requests, seen_cgroups, seen_epochs, seen_categories = set(), set(), set(), set()
    for offset in range(0, len(events), len(EVENTS)):
        lifecycle = events[offset : offset + len(EVENTS)]
        if not all(
            _closed(
                event,
                {
                    "sequence",
                    "monotonic_ns",
                    "request",
                    "category",
                    "invocation",
                    "cgroup",
                    "event",
                },
            )
            for event in lifecycle
        ):
            return [*issues, ("INCONCLUSIVE", "quiescence.event_schema")]
        first = lifecycle[0]
        if (
            not all(_digest(first[key]) for key in ("request", "invocation", "cgroup"))
            or not isinstance(first["category"], str)
            or first["category"] not in CATEGORIES
        ):
            return [*issues, ("INCONCLUSIVE", "quiescence.event_identity")]
        for key, seen in (
            ("request", seen_requests),
            ("invocation", seen_epochs),
            ("cgroup", seen_cgroups),
            ("category", seen_categories),
        ):
            if first[key] in seen:
                return [*issues, ("INCONCLUSIVE", "quiescence.reused_identity")]
            seen.add(first[key])
        for index, (expected, event) in enumerate(zip(EVENTS, lifecycle, strict=True), offset):
            if (
                not _count(event["sequence"])
                or event["sequence"] != index
                or not _count(event["monotonic_ns"])
                or event["monotonic_ns"] <= last_time
                or event["event"] != expected
                or any(
                    event[key] != first[key]
                    for key in ("request", "invocation", "cgroup", "category")
                )
            ):
                return [*issues, ("INCONCLUSIVE", "quiescence.event_order_or_binding")]
            last_time = event["monotonic_ns"]
    return issues


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("oversize artifact")
    return data


def score(directory: Path, accepted_manifest_sha256: str, current: object) -> dict[str, object]:
    """Evaluate one model arm. Acceptance pins and current identity are external inputs."""
    issues = []
    try:
        manifest = _read(directory / "manifest.sha256")
        if hashlib.sha256(manifest).hexdigest() != accepted_manifest_sha256:
            raise ValueError("manifest identity")
        lines = manifest.decode("ascii").splitlines()
        if len(lines) != len(EVIDENCE_FILES):
            raise ValueError("manifest coverage")
        records = {}
        for name, line in zip(sorted(EVIDENCE_FILES), lines, strict=True):
            expected, separator, filename = line.partition("  ")
            if not separator or filename != name or not _digest(expected):
                raise ValueError("manifest member")
            raw = _read(directory / name)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("artifact integrity")
            records[name] = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, ValueError, RecursionError):
        return _report(accepted_manifest_sha256, [("INCONCLUSIVE", "bundle.integrity")])

    identity = records["identity.json"]
    if (
        not _closed(identity, {"schema", "ct_id", "run", "activated_ns", "closed_ns", "bindings"})
        or identity["schema"] != SCHEMA
        or type(identity["ct_id"]) is not int
        or identity["ct_id"] != 110
        or not _digest(identity["run"])
        or not _count(identity["activated_ns"])
        or not _count(identity["closed_ns"])
        or identity["closed_ns"] <= identity["activated_ns"]
        or not _closed(identity["bindings"], IDENTITIES)
        or not all(_digest(value) for value in identity["bindings"].values())
    ):
        return _report(accepted_manifest_sha256, [("INCONCLUSIVE", "identity.schema")])
    if current != identity["bindings"]:
        issues.append(("INCONCLUSIVE", "identity.current_mismatch"))

    identity_sha256 = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    for name in sorted(set(EVIDENCE_FILES) - {"identity.json"}):
        section = name.removesuffix(".json")
        record = records[name]
        if not _closed(record, {"identity_sha256", "observations"}) or (
            record["identity_sha256"] != identity_sha256
        ):
            issues.append(("INCONCLUSIVE", f"{section}.binding"))
            continue
        observations = record["observations"]
        if section == "quiescence":
            problems = _check_quiescence(observations)
            issues.extend(problems)
            if not problems and any(
                not identity["activated_ns"] <= event["monotonic_ns"] <= identity["closed_ns"]
                for event in observations["events"]
            ):
                issues.append(("INCONCLUSIVE", "quiescence.outside_policy_window"))
        else:
            issues.extend(_check_attestations(section, observations))
    # Observation references are not yet resolved to independently reviewed
    # physical evidence. A self-consistent bundle cannot grant readiness.
    issues.append(("INCONCLUSIVE", "bundle.physical_evidence_verifier_unavailable"))
    return _report(accepted_manifest_sha256, issues)


def _report(manifest: str, issues: list[tuple[str, str]]) -> dict[str, object]:
    verdict = "HOLD" if any(value == "HOLD" for value, _ in issues) else "INCONCLUSIVE"
    return {
        "schema": SCHEMA,
        "verdict": verdict,
        "accepted_manifest_sha256": manifest if _digest(manifest) else None,
        "execution_authorized": False,
        "issues": [{"verdict": value, "requirement": reason} for value, reason in issues],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--accepted-manifest-sha256", required=True)
    parser.add_argument("--current-bindings", type=Path, required=True)
    args = parser.parse_args()
    try:
        current = json.loads(_read(args.current_bindings), object_pairs_hook=_unique_object)
    except (OSError, ValueError, RecursionError):
        current = None
    report = score(args.directory, args.accepted_manifest_sha256, current)
    print(json.dumps(report, indent=2))
    return 1 if report["verdict"] == "HOLD" else 2


if __name__ == "__main__":
    raise SystemExit(main())
