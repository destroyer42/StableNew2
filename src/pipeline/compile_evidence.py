"""One bounded, read-only model/LoRA evidence context per PromptPack build (PR-PROMPT-140).

Automatic prompt adaptation needs two facts per build: the ``ModelPolicy`` of the selected checkpoint and, for exact-admission
targets, the existing PR-IMG-117 decision for each distinct LoRA name. Both come from ``AssetRegistry``'s *persisted snapshot*
only (no refresh, no scan, no hashing, no network), the registry is created lazily and at most once per build, the policy is
resolved once per distinct model name and each LoRA name is looked up once however many Matrix variants or LoRAs the build
has. When the snapshot cannot decide, the answer is "unverified" - never a guess - and the backend's fail-closed admission
(which refreshes) stays final. Tests and callers may inject both lookups.

Explicit fresh selection may call ``prepare_lora_selection`` before adaptation.
That bounded background seam prepares complete LoRA evidence once through the
existing registry; generic compilation and Learning do not call it.
"""

from __future__ import annotations

from typing import Any

from src.image_backends.forge_klein_lora import LoraResolver, RegistryLoraResolver
from src.image_backends.model_policy import (
    FamilyLookup,
    ModelPolicy,
    RegistryFamilyLookup,
    resolve_model_policy,
)
from src.image_backends.model_policy_lora import LoraEvidenceContext


class _LazyRegistry:
    """Defers constructing ``AssetRegistry`` until a lookup actually needs it, then reuses that one instance."""

    def __init__(self) -> None:
        self._registry: Any | None = None

    def _get(self) -> Any:
        if self._registry is None:
            from src.assets import AssetRegistry

            self._registry = AssetRegistry()
        return self._registry

    @property
    def webui_root(self) -> Any:
        return self._get().webui_root

    def cached_snapshot(self) -> Any:
        return self._get().cached_snapshot()


class CompileEvidence:
    def __init__(self, *, family_lookup: FamilyLookup | None = None, lora_resolver: LoraResolver | None = None) -> None:
        registry = _LazyRegistry()
        self._registry = registry
        self._injected_lora_resolver = lora_resolver is not None
        self._selection_prepared = False
        self._family_lookup: FamilyLookup = family_lookup or RegistryFamilyLookup(registry)
        self.lora_evidence = LoraEvidenceContext(lora_resolver or RegistryLoraResolver(registry, cache_only=True))
        self._policies: dict[str, ModelPolicy] = {}
        self.policy_lookups = 0
        self.model_identities: dict[str, dict[str, Any]] = {}

    def prepare_lora_selection(self, *, cancelled: Any = None) -> None:
        """One complete registry assessment before explicit fresh selection."""
        if self._selection_prepared:
            return
        if not self._injected_lora_resolver:
            from src.prompting.pack_lora_evidence import prepare_selection_evidence

            self.lora_evidence = prepare_selection_evidence(self._registry._get(), cancelled=cancelled)
        self._selection_prepared = True

    def policy_for(self, model_name: str | None) -> ModelPolicy:
        key = str(model_name or "").strip()
        policy = self._policies.get(key)
        if policy is None:
            self.policy_lookups += 1
            policy = resolve_model_policy(key or None, family_lookup=self._family_lookup)
            self._policies[key] = policy
        return policy


__all__ = ["CompileEvidence"]
