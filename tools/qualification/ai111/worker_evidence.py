"""Closed, content-free privacy and provenance evidence for worker preflight."""

from __future__ import annotations

import re

from tools.qualification.ai111.worker_quiescence import OUTCOMES

OLLAMA_REVISION = "d63b702609c4300a2ca07be2bdb0adb9834725e5"
SHA = re.compile(r"[0-9a-f]{64}")
SINKS = frozenset(
    {
        "journal",
        "syslog",
        "forwarding",
        "replay",
        "temporary_files",
        "crash",
        "client_history",
        "desktop_tunnel",
    }
)


def digest(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def closed(value: object, keys: frozenset[str] | set[str]) -> bool:
    return isinstance(value, dict) and value.keys() == keys


def count(value: object) -> bool:
    return type(value) is int and value >= 0


def _canary_markers(canaries: object, requests: dict[str, str]) -> set[str] | None:
    if not closed(canaries, set(OUTCOMES)) or requests.keys() != OUTCOMES.keys():
        return None
    markers = set()
    for category, record in canaries.items():
        if (
            not closed(record, {"request_identity", "request", "response", "response_absence"})
            or record["request_identity"] != requests[category]
            or not digest(record["request"])
        ):
            return None
        response = record["response"]
        absence = record["response_absence"]
        if digest(response) and absence is None:
            fresh = {record["request"], response}
            if len(fresh) != 2:
                return None
        elif category != "success" and response is None and digest(absence):
            fresh = {record["request"]}
        else:
            return None
        if markers & fresh:
            return None
        markers.update(fresh)
    return markers


def _sink_findings(sink: str, record: object, markers: set[str]) -> list[tuple[str, str]]:
    key = f"privacy.sink.{sink}"
    if not closed(record, {"active", "inventory", "scans"}) or (
        type(record["active"]) is not bool
        or not digest(record["inventory"])
        or not isinstance(record["scans"], list)
    ):
        return [("INCONCLUSIVE", key)]
    scans = record["scans"]
    seen = set()
    findings = []
    for scan in scans:
        if not closed(scan, {"complete", "marker_sha256", "bytes_read", "matches"}):
            findings.append(("INCONCLUSIVE", key))
            continue
        marker = scan["marker_sha256"]
        if count(scan["matches"]) and scan["matches"] > 0:
            findings.append(("HOLD", f"{key}.retained_content"))
        if (
            not digest(marker)
            or marker in seen
            or not count(scan["matches"])
            or not count(scan["bytes_read"])
            or scan["complete"] is not True
        ):
            findings.append(("INCONCLUSIVE", key))
            continue
        seen.add(marker)
    if seen != markers if record["active"] else bool(scans):
        findings.append(("INCONCLUSIVE", key))
    return list(dict.fromkeys(findings))


def privacy(
    record: object, bindings: dict[str, str], requests: dict[str, str]
) -> list[tuple[str, str]]:
    if not closed(
        record, {"source_revision", "logging_before", "logging_after", "canaries", "sinks"}
    ):
        return [("INCONCLUSIVE", "privacy.evidence_schema")]
    findings = []
    if record["source_revision"] != OLLAMA_REVISION:
        findings.append(("INCONCLUSIVE", "privacy.source_revision"))
    if (
        record["logging_before"] != bindings["logging"]
        or record["logging_after"] != bindings["logging"]
    ):
        findings.append(("INCONCLUSIVE", "privacy.logging_binding"))
    markers = _canary_markers(record["canaries"], requests)
    if markers is None:
        findings.append(("INCONCLUSIVE", "privacy.canary_coverage"))
    sinks = record["sinks"]
    if not closed(sinks, SINKS):
        findings.append(("INCONCLUSIVE", "privacy.sink_inventory"))
    if isinstance(sinks, dict):
        for sink in sorted(SINKS & sinks.keys()):
            findings.extend(_sink_findings(sink, sinks[sink], markers or set()))
    return findings


def provenance(record: object, bindings: dict[str, str]) -> list[tuple[str, str]]:
    if not closed(record, {"runtime", "model"}):
        return [("INCONCLUSIVE", "provenance.evidence_schema")]
    runtime = record["runtime"]
    model = record["model"]
    findings = []
    if not closed(
        runtime, {"source_revision", "executable", "linked_runtime", "publisher_proof"}
    ) or (
        runtime["source_revision"] != OLLAMA_REVISION
        or runtime["executable"] != bindings["executable"]
        or runtime["linked_runtime"] != bindings["linked_runtime"]
        or not digest(runtime["publisher_proof"])
    ):
        findings.append(("INCONCLUSIVE", "provenance.runtime_binding"))
    if not closed(
        model,
        {
            "manifest",
            "layers",
            "publisher",
            "revision",
            "license_text",
            "license_decision",
            "license_decision_proof",
        },
    ):
        return [*findings, ("INCONCLUSIVE", "provenance.model_schema")]
    if (
        model["manifest"] != bindings["model_manifest"]
        or model["layers"] != bindings["model_layers"]
        or not all(digest(model[key]) for key in ("publisher", "revision", "license_text"))
    ):
        findings.append(("INCONCLUSIVE", "provenance.model_binding"))
    if not digest(model["license_decision_proof"]):
        findings.append(("INCONCLUSIVE", "provenance.license_decision"))
    elif model["license_decision"] == "REJECTED":
        findings.append(("HOLD", "provenance.license_decision"))
    elif model["license_decision"] != "ACCEPTED":
        findings.append(("INCONCLUSIVE", "provenance.license_decision"))
    return findings
