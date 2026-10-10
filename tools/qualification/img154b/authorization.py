"""D6 (154B): the exact-case owner authorization record, its binding and the operator confirmation phrase.

Nothing in this package WRITES an authorization record, and no code path, flag or preflight result can stand in for one. The
record is data the owner places outside the package (for one specific case identity, manifest, payload, code revision and
policy revision, with a limited validity). This module only reads it and refuses on any mismatch. The record cannot be
cryptographically attributed to the owner; the controls are that it is never generated here, that it is bound to exact
digests, that it expires, that the physical path additionally requires an interactive typed confirmation of the same
digests, and that the activation path refuses under a test runner.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tools.qualification.img154.core import Finding, digest, valid_utc
from tools.qualification.img154.manifest import QualificationManifest, build_manifest
from tools.qualification.img154b.request import SEMANTICS_REVISION, FrozenPayload

AUTHORIZATION_SCHEMA = "stablenew.img154b.owner-authorization.v1"
RISK_ID = "DIAG-GPU-130"
MAX_VALIDITY_S = 24 * 3600
REQUIRED_STATEMENT = (
    "I, the product owner, authorize exactly one physical qualification case with the frozen manifest, payload and code "
    "revision named here, and I accept the residual unresolved DIAG-GPU-130 GPU hard-failure risk, including a black screen, "
    "driver hang or forced restart that no software can recover."
)


class AuthorizationError(ValueError):
    """The authorization record is absent, malformed or not for this case."""


@dataclass(frozen=True)
class CodeRevision:
    """The trusted code identity: a clean Git checkout plus the hash of the qualification sources actually executed."""

    state: str
    sha: str | None
    source_sha256: str | None

    @property
    def trusted(self) -> bool:
        return self.state == "clean" and bool(self.sha) and bool(self.source_sha256)

    @classmethod
    def from_probe(cls, info: Mapping[str, Any]) -> CodeRevision:
        return cls(str(info.get("state")), info.get("sha"), info.get("source_sha256"))


@dataclass(frozen=True)
class OwnerAuthorization:
    attempt_identity: str
    manifest_digest: str
    payload_digest: str
    semantics_revision: str
    policy_revision: str
    evidence_contract_revision: str
    git_sha: str
    source_sha256: str
    accepted_risks: tuple[str, ...]
    cases: int
    retries: int
    authorized_by: str
    authorized_utc: str
    expires_utc: str
    statement: str
    challenge: str

    def record_digest(self) -> str:
        return digest(
            {
                "attempt_identity": self.attempt_identity,
                "manifest_digest": self.manifest_digest,
                "payload_digest": self.payload_digest,
                "git_sha": self.git_sha,
                "source_sha256": self.source_sha256,
                "authorized_utc": self.authorized_utc,
                "expires_utc": self.expires_utc,
                "challenge": self.challenge,
            }
        )


def binding(
    manifest: QualificationManifest, payload: FrozenPayload, code: CodeRevision
) -> dict[str, Any]:
    """Everything an authorization is bound to (the material the challenge digests)."""

    return {
        "attempt_identity": manifest.attempt_identity(),
        "manifest_digest": manifest.digest(),
        "payload_digest": payload.payload_digest,
        "semantics_revision": payload.semantics_revision,
        "policy_revision": manifest.policy_revision,
        "evidence_contract_revision": manifest.evidence_contract_revision,
        "git_sha": code.sha,
        "source_sha256": code.source_sha256,
        "cases": 1,
        "retries": 0,
    }


def authorization_challenge(
    manifest: QualificationManifest, payload: FrozenPayload, code: CodeRevision
) -> str:
    """A deterministic digest of the binding. The owner copies it into the record to show the exact case was reviewed."""

    return digest(
        {"namespace": "stablenew.img154b.challenge.v1", **binding(manifest, payload, code)}
    )


def confirmation_phrase(manifest: QualificationManifest, payload: FrozenPayload) -> str:
    """What the operator must TYPE at the physical activation prompt: the exact case, not a flag or a yes."""

    return f"RUN-ONE-PHYSICAL-CASE {manifest.attempt_identity()[:12]} {manifest.digest()[:12]} {payload.payload_digest[:12]}"


def parse_authorization(raw: object) -> OwnerAuthorization:
    if not isinstance(raw, Mapping):
        raise AuthorizationError("the authorization record is not an object")
    if raw.get("schema") != AUTHORIZATION_SCHEMA:
        raise AuthorizationError("unknown authorization schema")
    try:
        risks = raw["accepted_risks"]
        if not isinstance(risks, list) or not all(isinstance(item, str) for item in risks):
            raise AuthorizationError("accepted_risks must be a list of strings")
        fields: dict[str, Any] = {
            name: raw[name]
            for name in (
                "attempt_identity",
                "manifest_digest",
                "payload_digest",
                "semantics_revision",
                "policy_revision",
                "evidence_contract_revision",
                "git_sha",
                "source_sha256",
                "authorized_by",
                "authorized_utc",
                "expires_utc",
                "statement",
                "challenge",
            )
        }
        cases, retries = raw["cases"], raw["retries"]
    except KeyError as exc:
        raise AuthorizationError(f"missing field {exc.args[0]!r}") from exc
    if any(not isinstance(value, str) or not value.strip() for value in fields.values()):
        raise AuthorizationError("every named field must be a non-empty string")
    for number in (cases, retries):
        if isinstance(number, bool) or not isinstance(number, int):
            raise AuthorizationError("cases and retries must be integers")
    return OwnerAuthorization(accepted_risks=tuple(risks), cases=cases, retries=retries, **fields)


def read_authorization_text(text: str) -> OwnerAuthorization:
    try:
        return parse_authorization(json.loads(text))
    except ValueError as exc:
        if isinstance(exc, AuthorizationError):
            raise
        raise AuthorizationError("the authorization record is not valid JSON") from exc


def verify_authorization(
    auth: OwnerAuthorization | None,
    *,
    manifest: QualificationManifest | None = None,
    payload: FrozenPayload,
    code: CodeRevision,
    now_utc: str,
) -> list[Finding]:
    """Exact binding and freshness. Any gap is a refusal; there is no partial authorization."""

    plan = manifest or build_manifest()
    if auth is None:
        return [
            Finding(
                "AUTHORIZATION_ABSENT",
                "refuse",
                "no separately recorded owner authorization exists",
            )
        ]
    findings: list[Finding] = []

    def mismatch(code_name: str, detail: str) -> None:
        findings.append(Finding(code_name, "refuse", detail))

    expected = binding(plan, payload, code)
    if not code.trusted:
        mismatch("CODE_REVISION_UNTRUSTED", "the checkout is not a clean, identified revision")
    if auth.attempt_identity != expected["attempt_identity"]:
        mismatch("AUTHORIZATION_CASE_MISMATCH", "the record names a different case identity")
    if auth.manifest_digest != expected["manifest_digest"]:
        mismatch("AUTHORIZATION_MANIFEST_MISMATCH", "the record names a different manifest")
    if auth.payload_digest != expected["payload_digest"]:
        mismatch("AUTHORIZATION_PAYLOAD_MISMATCH", "the record names a different request payload")
    if auth.semantics_revision != SEMANTICS_REVISION:
        mismatch(
            "AUTHORIZATION_SEMANTICS_MISMATCH",
            "the record names another request-semantics revision",
        )
    if (
        auth.policy_revision != plan.policy_revision
        or auth.evidence_contract_revision != plan.evidence_contract_revision
    ):
        mismatch(
            "AUTHORIZATION_POLICY_MISMATCH", "the record names other policy or evidence revisions"
        )
    if code.trusted and (auth.git_sha != code.sha or auth.source_sha256 != code.source_sha256):
        mismatch("AUTHORIZATION_CODE_MISMATCH", "the record names another code revision")
    if RISK_ID not in auth.accepted_risks:
        mismatch(
            "AUTHORIZATION_RISK_NOT_ACCEPTED", f"{RISK_ID} is not among the accepted residual risks"
        )
    if auth.cases != 1 or auth.retries != 0:
        mismatch("AUTHORIZATION_SCOPE", "an authorization covers exactly one case with no retry")
    if auth.statement != REQUIRED_STATEMENT:
        mismatch(
            "AUTHORIZATION_STATEMENT",
            "the authorization statement is not the required exact statement",
        )
    if auth.challenge != authorization_challenge(plan, payload, code):
        mismatch(
            "AUTHORIZATION_CHALLENGE", "the record does not carry the challenge of this exact case"
        )
    if (
        not valid_utc(auth.authorized_utc)
        or not valid_utc(auth.expires_utc)
        or not valid_utc(now_utc)
    ):
        mismatch("AUTHORIZATION_TIME_INVALID", "authorization times are not valid timestamps")
    else:
        issued = datetime.fromisoformat(auth.authorized_utc)
        expires = datetime.fromisoformat(auth.expires_utc)
        now = datetime.fromisoformat(now_utc)
        if not (issued <= now <= expires):
            mismatch("AUTHORIZATION_EXPIRED", "the authorization is not valid at this time")
        if (expires - issued).total_seconds() > MAX_VALIDITY_S or expires <= issued:
            mismatch(
                "AUTHORIZATION_VALIDITY",
                "the authorization validity window is invalid or longer than 24 hours",
            )
    return findings


def source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
