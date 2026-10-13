"""PR-IMG-CNET-210: the toolkit-neutral editor view. A known-missing ControlNet model blocks; unavailable evidence does not."""

from __future__ import annotations

import pytest

from src.assets.controlnet_structure import STATUS_NOT_SDXL, STATUS_SDXL, STATUS_UNVERIFIED
from src.conditioning.openpose import new_declaration
from src.gui_v2.openpose_conditioning_view import (
    MODEL_MISSING,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_OK,
    describe_openpose,
)
from src.image_backends.openpose_capability import (
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED,
    OpenPoseTarget,
)

ASSET = "Standing/relaxed.png"
MODEL = "xinsir_openpose_sdxl"
SUPPORTED = OpenPoseTarget(STATUS_SUPPORTED, "supported", "SDXL on Forge: supported.", family="sdxl")


def _view(model_status, *, model: str = MODEL, target=SUPPORTED, identities=frozenset({ASSET}), **overrides):
    declaration = {**new_declaration(ASSET, model=model), **overrides}
    return describe_openpose(declaration, target=target, library_identities=identities, model_status=model_status)


def test_a_known_missing_model_makes_the_selection_non_executable() -> None:
    view = _view(MODEL_MISSING)

    assert view.executable is False
    assert view.worst == SEVERITY_ERROR
    assert any("is not installed in models/ControlNet" in line.text for line in view.lines)
    assert view.selection is not None and view.selection.model == MODEL  # the choice is kept, never rewritten


def test_unavailable_model_evidence_never_blocks() -> None:
    # ``None`` = the installed list was not read (not scanned, empty/unreadable folder): absence is not proven.
    view = _view(None)

    assert view.executable is True
    assert not any("ControlNet model" in line.text for line in view.lines)  # no claim either way


@pytest.mark.parametrize(
    ("model_status", "executable", "severity"),
    [
        (STATUS_SDXL, True, SEVERITY_OK),
        (STATUS_UNVERIFIED, True, SEVERITY_INFO),  # labelled unverified, still allowed
        (STATUS_NOT_SDXL, False, SEVERITY_ERROR),
        (MODEL_MISSING, False, SEVERITY_ERROR),
        (None, True, None),
    ],
)
def test_model_evidence_matrix(model_status, executable: bool, severity) -> None:
    view = _view(model_status)

    assert view.executable is executable
    model_lines = [line for line in view.lines if "ControlNet model" in line.text]
    if severity is None:
        assert model_lines == []
    else:
        assert [line.severity for line in model_lines] == [severity]


def test_missing_model_is_reported_alongside_other_blockers_not_instead_of_them() -> None:
    unsupported = OpenPoseTarget(STATUS_UNSUPPORTED, "backend", "OpenPose runs only on Forge.")

    view = _view(MODEL_MISSING, target=unsupported, identities=frozenset())

    assert view.executable is False
    texts = " | ".join(line.text for line in view.lines)
    assert "not in the OpenPose library" in texts and "not installed in models/ControlNet" in texts
    assert "OpenPose runs only on Forge" in texts


def test_an_unset_model_is_still_a_distinct_blocker() -> None:
    view = _view(MODEL_MISSING, model="")

    assert view.executable is False
    assert [line.text for line in view.lines if "Choose a ControlNet model" in line.text]
    assert not any("not installed" in line.text for line in view.lines)  # nothing to be "missing"


def test_a_disabled_declaration_ignores_model_evidence() -> None:
    view = _view(MODEL_MISSING, enabled=False)

    assert view.executable is False
    assert [line.severity for line in view.lines] == [SEVERITY_INFO]
