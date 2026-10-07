"""One LoRA-selection assessment against a model policy (PR-IMG-130B; extracted from the PR-IMG-130A projection).

The Base Generation projection and the Prompt-tab compatibility analysis ask the same question of the same existing
admission path: which of these selected LoRAs does the model's policy admit? The decision itself is never made here. It
is ``evaluate_klein_loras`` (the PR-IMG-117 exact-evidence admission that the backend also runs), reached through the
policy's reference to that compatibility policy. Pure over an injected resolver; no scanning, hashing or network. A
selection is never removed or rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.image_backends.forge_klein_lora import (
    KleinLoraDecision,
    LoraResolver,
    evaluate_klein_loras,
    unavailable_decision,
)
from src.image_backends.model_policy import LORA_POLICY_KLEIN_4B_EXPLICIT, ModelPolicy


@dataclass(frozen=True, slots=True)
class LoraAssessment:
    #: LoRAs counted against the policy (selected slot LoRAs plus an applied style LoRA, as the caller supplied them).
    count: int
    #: The policy's upper bound (``None`` when unbounded or unknown).
    limit: int | None
    #: ``True`` when the policy states LoRA support (a bounded or unbounded SUPPORTED feature).
    supported: bool
    #: ``True`` when an exact compatibility policy decided (annotations/problems are authoritative evidence).
    exact: bool
    over_limit: bool = False
    not_verified: int = 0
    #: Per selected LoRA name: the admission annotation shown next to it.
    annotations: dict[str, str] = field(default_factory=dict)
    #: The admission problems exactly as the backend would report them (may name assets; for the GUI helper only).
    problems: tuple[str, ...] = ()
    #: The operator-facing blocking sentence for the Base Generation helper ("" when the selection is runnable).
    blocking: str = ""
    #: Per selected LoRA name: the stable machine-readable PR-IMG-117 decision status ("compatible", "unverified",
    #: "incompatible", "conflicting"), straight from the existing evaluator. Only "incompatible" is a definitive
    #: negative; "unverified" (absent/stale/generic evidence) and "conflicting" are never a basis to delete a LoRA.
    statuses: dict[str, str] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return bool(self.blocking)


def assess_lora_selection(
    policy: ModelPolicy, selected: Sequence[tuple[str, float]], resolver: LoraResolver | None
) -> LoraAssessment:
    lora = policy.feature("lora")
    count = len(selected)
    if lora.compatibility_policy == LORA_POLICY_KLEIN_4B_EXPLICIT and lora.supported:
        limit = int(lora.limit or 0)
        if not selected:
            return LoraAssessment(0, limit, True, True)
        prompt = " ".join(f"<lora:{name}:{weight:g}>" for name, weight in selected)
        problems, decisions, tags = evaluate_klein_loras(max_loras=limit, prompt=prompt, resolver=resolver)
        by_name = {decision.name: decision for decision in decisions}
        annotations: dict[str, str] = {}
        statuses: dict[str, str] = {}
        for name, _weight in selected:
            decision = by_name.get(name)
            if decision is None:
                continue
            statuses[name] = decision.status.value
            annotations[name] = (
                "verified for FLUX.2 Klein 4B"
                if decision.runnable
                else f"not verified for FLUX.2 Klein 4B ({decision.status.value}): {decision.reason}"
            )
        return LoraAssessment(
            count=count,
            limit=limit,
            supported=True,
            exact=True,
            over_limit=len(tags) > limit,
            not_verified=sum(1 for decision in decisions if not decision.runnable),
            annotations=annotations,
            statuses=statuses,
            problems=tuple(problems),
            blocking=(
                "This LoRA selection would be rejected before generation: " + "; ".join(problems) if problems else ""
            ),
        )
    if selected and not lora.supported and policy.qualified:
        version = (policy.profile_ref or {}).get("version")
        return LoraAssessment(
            count=count,
            limit=0,
            supported=False,
            exact=True,
            over_limit=True,
            blocking=f"{policy.display_name} (profile v{version}) does not support LoRAs.",
        )
    return LoraAssessment(count, lora.limit, lora.supported, False)


class LoraEvidenceContext:
    """One bounded, read-only LoRA evidence context (PR-PROMPT-140): each name is resolved at most once.

    Wraps the existing resolver (the cache-only ``RegistryLoraResolver`` in production) so a build with many Matrix
    variants and LoRAs consults the persisted registry snapshot once per distinct name and never refreshes, scans or
    hashes. ``lookups`` counts underlying resolver calls (an observable bound for tests and diagnostics).
    """

    def __init__(self, resolver: LoraResolver | None) -> None:
        self._resolver = resolver
        self._decisions: dict[str, KleinLoraDecision] = {}
        self.lookups = 0

    def __call__(self, name: str) -> KleinLoraDecision:
        key = str(name)
        cached = self._decisions.get(key)
        if cached is None:
            self.lookups += 1
            cached = (
                self._resolver(key)
                if self._resolver is not None
                else unavailable_decision(key, "no LoRA compatibility resolver is available")
            )
            self._decisions[key] = cached
        return cached


__all__ = ["LoraAssessment", "LoraEvidenceContext", "assess_lora_selection"]
