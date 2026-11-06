"""Which Blender situation a motion-conversion journey is in, said precisely, and the isolated registration it stages.

The journey workspace is disposable and deliberately has no Blender registration: the operator's saved pointer lives in the
per-user store, which a journey never reads or writes.  "No Blender in the dialog" therefore says nothing about the host.  An
executable is supplied on purpose (``--blender`` or ``STABLENEW_JOURNEY_BLENDER``), verified with the product's own bounded
``--version`` check, and registered *inside the workspace only*.  Each way that can fail has its own state and wording, so a
HOLD names its cause and a verified installation is never reported missing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.video.motion_conversion import blender as bl

VERIFIED = "verified"
NOT_SUPPLIED = "not_supplied"
MISSING = "executable_missing"
NOT_BLENDER = "not_blender"
UNSUPPORTED = "unsupported_version"
VERIFICATION_FAILED = "verification_failed"

ENV_VARIABLE = "STABLENEW_JOURNEY_BLENDER"
#: The key in ``RunConfig.extras`` that carries the explicitly supplied executable.
EXTRAS_KEY = "blender_executable"

_BY_KIND = {
    bl.KIND_MISSING: MISSING,
    bl.KIND_NOT_BLENDER: NOT_BLENDER,
    bl.KIND_UNSUPPORTED: UNSUPPORTED,
    bl.KIND_VERIFICATION: VERIFICATION_FAILED,
}


@dataclass(frozen=True, slots=True)
class BlenderQualification:
    state: str
    detail: str
    candidate: str = ""
    install: bl.BlenderInstall | None = None

    @property
    def verified(self) -> bool:
        return self.state == VERIFIED and self.install is not None

    def hold_reason(self) -> str:
        """Why the conversion lane cannot run, or an empty string when it can."""

        if self.verified:
            return ""
        if self.state == NOT_SUPPLIED:
            return (
                "No Blender executable was supplied to this journey (--blender or "
                f"{ENV_VARIABLE}). The isolated workspace deliberately has no Blender registration, so Lane A "
                "(Convert sample) did not run and no render was faked; this does not say whether the host has Blender"
            )
        return (
            f"The supplied Blender executable was not usable ({self.state.replace('_', ' ')}): {self.detail}. "
            "Lane A (Convert sample) did not run and no render was faked"
        )


def supplied_executable(extras: dict[str, object] | None = None) -> str:
    """The executable the run was asked to use: the run's own setting first, then the environment."""

    value = (extras or {}).get(EXTRAS_KEY) or os.environ.get(ENV_VARIABLE, "")
    return str(value).strip()


def qualify_blender(
    candidate: str | Path | None,
    *,
    verify: Callable[..., bl.BlenderInstall] = bl.verify_blender,
) -> BlenderQualification:
    """Verify an explicitly supplied executable.  Nothing is searched for, downloaded or installed."""

    text = str(candidate or "").strip()
    if not text:
        return BlenderQualification(NOT_SUPPLIED, "no executable supplied")
    try:
        install = verify(text)
    except bl.BlenderProblem as problem:
        return BlenderQualification(
            _BY_KIND.get(problem.kind, VERIFICATION_FAILED), str(problem), candidate=text
        )
    return BlenderQualification(
        VERIFIED, install.version_text or "verified", candidate=text, install=install
    )


class RegistrationEscape(RuntimeError):
    """The Blender setting would not be written inside the disposable workspace."""


def stage_registration(install: bl.BlenderInstall, workspace_root: Path) -> Path:
    """Register ``install`` for the workspace's Motion Library settings; refuses to write anywhere else."""

    from src.video.motion_conversion import workbench

    target = workbench.settings_path()
    try:
        target.resolve().relative_to(Path(workspace_root).resolve())
    except ValueError as exc:
        raise RegistrationEscape(
            f"the Blender setting resolves to {target}, outside the journey workspace {workspace_root}"
        ) from exc
    workbench.save_blender_setting(install.executable)
    return target
