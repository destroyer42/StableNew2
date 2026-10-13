"""PromptPack OpenPose conditioning compilation (PR-IMG-CNET-210).

The one compile-time authority that turns a slot's authored ``controlnet_openpose`` declaration into the immutable
``FrozenOpenPose`` an NJR carries. It does three things the editor deliberately does not:

* gates the *target*: only an SDXL checkpoint on the Forge backend at the base txt2img stage is executable
  (``assess_openpose_target`` over the canonical ``ModelPolicy``), so unsupported work is refused here rather than
  silently losing its conditioning;
* verifies the *input*: the library image is read once, validated, hashed and copied into a content-addressed
  job-owned snapshot, so later library edits can never change a queued or replayed job;
* does so before any NJR exists, so one defective slot aborts the whole build with an actionable message.

Worker-side only (reads and hashes a bounded file). It is not a second compiler: the PromptPack job builder owns
compilation and calls this once per prepared slot.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.conditioning.openpose import OpenPoseDeclarationError, parse_declaration
from src.conditioning.openpose_library import (
    OpenPoseInputError,
    ValidatedImage,
    library_root,
    read_library_image,
)
from src.conditioning.openpose_snapshot import FrozenOpenPose, freeze_selection
from src.image_backends.model_policy import EVIDENCE_REGISTRY, ModelPolicy, resolve_model_policy
from src.image_backends.openpose_capability import (
    STATUS_UNVERIFIED,
    OpenPoseTarget,
    assess_openpose_target,
)

FAMILY_SOURCE_SNAPSHOT = "registry_snapshot"
FAMILY_SOURCE_HEADER = "checkpoint_header"

#: ``model_name -> CompatibilityProfile | None`` (header-only, worker-side). ``None`` means "no evidence".
HeaderProbe = Callable[[str], Any]


class OpenPoseCompileError(ValueError):
    """The slot's conditioning cannot be compiled; the message names the slot and says what to change."""


@dataclass(frozen=True, slots=True)
class CompiledConditioning:
    frozen: FrozenOpenPose
    #: Content-free evidence of *why* the target was admitted (family, where the family came from, backend).
    target: dict[str, Any]


def _default_header_probe(webui_root: Path | str | None) -> HeaderProbe:
    def probe(model_name: str) -> Any:
        from src.assets import AssetRegistry

        inspection = AssetRegistry(webui_root).inspect_named_checkpoint(model_name)
        return inspection.compatibility if inspection is not None else None

    return probe


class OpenPoseCompiler:
    """Configuration of the compile-time resolver (library root, snapshot root, header evidence).

    It holds **no** per-build state: a long-lived instance (the PromptPack builder is cached by the controller) must never
    serve an image it read for an earlier build, because a library file may have been replaced since. Each build asks for
    its own session with ``begin()``, whose image cache lives and dies with that one build.
    """

    def __init__(
        self,
        *,
        webui_root: Path | str | None = None,
        snapshot_root: Path | None = None,
        header_probe: HeaderProbe | None = None,
    ) -> None:
        self._webui_root = webui_root
        self._snapshot_root = snapshot_root
        self._header_probe = header_probe

    def begin(self) -> OpenPoseBuild:
        """A fresh per-build session (one library read per distinct image, never carried to the next build)."""

        return OpenPoseBuild(self)

    def compile_slot(self, raw: Any, **kwargs: Any) -> CompiledConditioning | None:
        """Convenience for a single slot: a throwaway session (no caching across calls)."""

        return self.begin().compile_slot(raw, **kwargs)

    # -- environment -----------------------------------------------------------------------------------------

    def _resolved_webui_root(self) -> Path | str | None:
        if self._webui_root is not None:
            return self._webui_root
        from src.assets import AssetRegistry

        return AssetRegistry().webui_root

    def _probe(self) -> HeaderProbe:
        if self._header_probe is None:
            self._header_probe = _default_header_probe(self._resolved_webui_root())
        return self._header_probe


class OpenPoseBuild:
    """One build's compile session: caches each library image it reads so Matrix variants read the file once."""

    def __init__(self, compiler: OpenPoseCompiler) -> None:
        self._compiler = compiler
        self._images: dict[str, ValidatedImage] = {}

    # -- compilation -----------------------------------------------------------------------------------------

    def compile_slot(
        self,
        raw: Any,
        *,
        label: str,
        model_name: str | None,
        backend_id: str,
        policy_for: Callable[[str | None], ModelPolicy],
    ) -> CompiledConditioning | None:
        """The frozen conditioning of one slot, or ``None`` when the slot asks for none.

        ``policy_for`` is the build's cached policy lookup (``CompileEvidence.policy_for``), so the target decision uses
        exactly the evidence the rest of the compile uses. A missing or explicitly disabled declaration compiles to
        nothing (and so changes nothing); an enabled one either freezes completely or raises.
        """

        if raw is None or (isinstance(raw, Mapping) and raw.get("enabled") is False):
            return None
        if not isinstance(raw, Mapping):
            # A non-object value cannot be honored and must not be mistaken for "no conditioning".
            raise OpenPoseCompileError(
                f"{label}: the OpenPose conditioning declaration is malformed (it must be an object); "
                "re-select the pose image in the PromptPack editor."
            )
        try:
            selection = parse_declaration(raw)
        except OpenPoseDeclarationError as exc:
            raise OpenPoseCompileError(
                f"{label}: the OpenPose conditioning declaration is invalid: {'; '.join(exc.problems)}"
            ) from exc

        policy = policy_for(model_name)
        target = assess_openpose_target(policy, backend_id)
        source = FAMILY_SOURCE_SNAPSHOT if policy.evidence == EVIDENCE_REGISTRY else policy.evidence
        if target.status == STATUS_UNVERIFIED and model_name:
            policy, target, source = self._substantiate(model_name, backend_id, policy, target, source)
        if not target.executable:
            raise OpenPoseCompileError(f"{label}: {target.message}")

        try:
            image = self._image(selection.asset)
            frozen = freeze_selection(
                selection,
                library=library_root(self._compiler._resolved_webui_root()),
                snapshot_root=self._compiler._snapshot_root,
                image=image,
            )
        except OpenPoseInputError as exc:
            raise OpenPoseCompileError(f"{label}: {exc}") from exc
        except ValueError as exc:
            raise OpenPoseCompileError(f"{label}: {exc}") from exc
        return CompiledConditioning(
            frozen=frozen,
            target={
                "family": policy.family,
                "family_source": source,
                "backend_id": backend_id,
                "stage": "txt2img",
            },
        )

    def _substantiate(
        self,
        model_name: str,
        backend_id: str,
        policy: ModelPolicy,
        target: OpenPoseTarget,
        source: str,
    ) -> tuple[ModelPolicy, OpenPoseTarget, str]:
        """Upgrade an *unverified* target only on positive header evidence (never on a filename or a guess)."""

        try:
            compatibility = self._compiler._probe()(model_name)
        except Exception:  # noqa: BLE001 - unreadable evidence is absent evidence, never a pass
            compatibility = None
        if compatibility is None:
            return policy, target, source
        probed = resolve_model_policy(model_name, family_lookup=lambda _name: compatibility)
        probed_target = assess_openpose_target(probed, backend_id)
        if probed_target.executable:
            return probed, probed_target, FAMILY_SOURCE_HEADER
        return policy, target, source

    def _image(self, asset: str) -> ValidatedImage:
        cached = self._images.get(asset)
        if cached is None:
            _path, cached = read_library_image(library_root(self._compiler._resolved_webui_root()), asset)
            self._images[asset] = cached
        return cached


__all__ = [
    "CompiledConditioning",
    "OpenPoseBuild",
    "FAMILY_SOURCE_HEADER",
    "FAMILY_SOURCE_SNAPSHOT",
    "HeaderProbe",
    "OpenPoseCompileError",
    "OpenPoseCompiler",
]
