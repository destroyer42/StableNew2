"""PR-IMG-PROFILE-630: the controller adapter between the Pipeline tab and the generation profile service.

A fake host and a fake Base Generation panel stand in for Tk. Nothing here builds a job, scans a runtime or dispatches.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.generation_profile_controller import (
    GenerationProfileController,
    draft_staleness_notices,
)
from src.generation_profiles.contract import KIND_CUSTOM, KIND_RESEARCH, ProfileRef
from src.generation_profiles.identity import ModelIdentityResolver
from src.generation_profiles.research import KLEIN_RESEARCH_ID, SDXL_RESEARCH_ID
from src.generation_profiles.service import GenerationProfileService
from src.generation_profiles.store import GenerationProfileStore
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1

SDXL_MODEL = "juggernaut.safetensors"
KLEIN = KLEIN_PROFILE_V1.transformer.filename
PROMPT = "a knight in the rain"
NEGATIVE = "blurry"


def _compat(family: str) -> Any:
    return SimpleNamespace(
        status=SimpleNamespace(value="resolved"),
        family=SimpleNamespace(value=family),
        checkpoint_architecture=None,
        structural_error=None,
    )


class FakePanel:
    """The editable Base Generation values, with the same seam as ``BaseGenerationPanelV2``."""

    def __init__(self, **values: Any) -> None:
        self.values: dict[str, Any] = {
            "model": SDXL_MODEL,
            "vae": "sdxl_vae.safetensors",
            "sampler": "DPM++ 2M",
            "scheduler": "Karras",
            "steps": 30,
            "cfg_scale": 7.0,
            "width": 768,
            "height": 768,
            "seed": 123,
        }
        self.values.update(values)
        self.applied: list[dict[str, Any]] = []

    def get_overrides(self) -> dict[str, Any]:
        return {**self.values, "vae_name": self.values["vae"]}

    def apply_profile_values(self, values: dict[str, Any]) -> None:
        self.applied.append(dict(values))
        names = {"sampler_name": "sampler"}
        for key, value in values.items():
            self.values[names.get(key, key)] = value


class FakeSidebar:
    def __init__(self, panel: FakePanel) -> None:
        self.panel = panel
        self.source: str | None = None

    def get_base_generation_panel(self) -> FakePanel:
        return self.panel

    def set_settings_source(self, kind: str, name: str = "") -> None:
        self.source = kind


class FakeHost:
    def __init__(
        self, panel: FakePanel, tmp_path: Path, *, models: list[str] | None = None
    ) -> None:
        self.panel = panel
        self.sidebar = FakeSidebar(panel)
        self.logs: list[str] = []
        self.override_pack_config_enabled = False
        self.flags = {"txt2img": True, "img2img": False, "adetailer": False, "upscale": False}
        self.stage_configs: dict[str, Any] = {
            "txt2img": {"steps": 30, "input_image_path": "D:/in/a.png", "mask_path": "D:/in/m.png"},
            "adetailer": {"adetailer_confidence": 0.4, "anchor_image": "D:/in/anchor.png"},
        }
        resources: dict[str, Any] = {"samplers": [], "schedulers": [], "vaes": []}
        if models is not None:
            resources["models"] = models
        self.app_state = SimpleNamespace(resources=resources, job_draft=SimpleNamespace(packs=[]))
        self.restored: list[dict[str, Any]] = []
        self.client_calls = 0
        families = {SDXL_MODEL: "sdxl"}
        resolver = ModelIdentityResolver(
            family_lookup=lambda name: _compat(families[name]) if name in families else None,
            sha_lookup=lambda name: None,
        )
        service = GenerationProfileService(GenerationProfileStore(tmp_path / "profiles"), resolver)
        self.profiles = GenerationProfileController(self, service)

    def _get_sidebar_panel(self) -> FakeSidebar:
        return self.sidebar

    def _append_log(self, text: str) -> None:
        self.logs.append(text)

    def _build_stage_flags(self) -> dict[str, bool]:
        return dict(self.flags)

    def _collect_current_stage_configs(self) -> dict[str, Any]:
        return {k: dict(v) for k, v in self.stage_configs.items()}

    def _apply_last_run_payload(self, config: dict[str, Any], snapshot: Any) -> None:
        self.restored.append(config)


@pytest.fixture
def host(tmp_path: Path) -> FakeHost:
    return FakeHost(FakePanel(), tmp_path)


def test_choosing_a_model_applies_its_preferred_profile_to_the_working_settings_only(
    host: FakeHost,
) -> None:
    host.panel.values["model"] = KLEIN
    plan = host.profiles.on_model_chosen(KLEIN)

    assert plan is not None and plan.profile.profile_id == KLEIN_RESEARCH_ID
    assert host.panel.applied and set(host.panel.applied[-1]) <= {
        "sampler_name",
        "scheduler",
        "steps",
        "cfg_scale",
        "width",
        "height",
        "vae",
    }
    assert host.panel.values["seed"] == 123  # a profile never touches seed or other working fields
    assert host.flags == {
        "txt2img": True,
        "img2img": False,
        "adetailer": False,
        "upscale": False,
    }  # never enables a stage
    assert any("[profiles]" in line for line in host.logs)


def test_the_same_model_chosen_again_is_not_reapplied_over_operator_edits(host: FakeHost) -> None:
    host.panel.values["model"] = SDXL_MODEL
    assert host.profiles.on_model_chosen(SDXL_MODEL) is not None
    host.panel.values["width"] = 640
    assert host.profiles.on_model_chosen(SDXL_MODEL) is None
    assert host.panel.values["width"] == 640


def test_switching_to_an_exact_model_discloses_what_its_executable_profile_owns(
    host: FakeHost,
) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    host.panel.values["model"] = KLEIN
    plan = host.profiles.on_model_chosen(KLEIN)

    assert plan is not None
    # The exact model's executable policy is final: the profile does not write values it owns, and says so.
    owned = [
        note for note in plan.notes if note.key == "vae" and "executable profile" in note.message
    ]
    assert owned and "vae" not in plan.changes


def test_a_vae_never_travels_to_a_different_model_family(host: FakeHost) -> None:
    host.panel.values.update(model=KLEIN, vae="klein_ae.safetensors")
    host.profiles.on_model_chosen(KLEIN)
    host.panel.values.update(model=SDXL_MODEL, vae="klein_ae.safetensors")
    plan = host.profiles.on_model_chosen(SDXL_MODEL)

    assert plan is not None
    assert (
        host.panel.values["vae"] == ""
    )  # reset to the checkpoint's own, even though SDXL has no VAE recommendation
    assert any(note.key == "vae" and note.status == "reset" for note in plan.notes)
    assert "VAE reset" in host.profiles.strip_view().status


def test_unverified_model_keeps_everything_and_says_so(host: FakeHost) -> None:
    host.panel.values["model"] = "mystery.safetensors"
    before = dict(host.panel.values)
    plan = host.profiles.on_model_chosen("mystery.safetensors")

    assert plan is not None and not plan.changes
    assert host.panel.values == before
    assert "profile" in host.profiles.strip_view().status.lower()


def test_profile_selection_restore_and_no_profile(host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    view = host.profiles.strip_view()
    assert view.selected_index >= 1 and view.can_restore

    host.panel.values["width"] = 640
    assert host.profiles.strip_view().status.startswith("Edited since the profile was applied")
    host.profiles.on_restore_selected()
    assert host.panel.values["width"] == 1024

    assert host.profiles.on_profile_selected(None) is None
    view = host.profiles.strip_view()
    assert view.selected_index == 0 and not view.can_restore
    assert host.panel.values["width"] == 1024  # "no profile" keeps the working values


def test_save_as_custom_update_and_favorite(host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    host.panel.values.update(steps=22, cfg_scale=5.5)

    ok, message = host.profiles.on_save_custom("Mine")
    assert ok and "Mine" in message and "revision 1" in message
    view = host.profiles.strip_view()
    assert view.can_update_custom and any(label.startswith("Custom: Mine") for label in view.labels)

    host.panel.values.update(steps=25)
    ok, message = host.profiles.on_save_custom("", update=True)
    assert ok and "revision 2" in message
    assert (
        host.profiles.service.get(
            ProfileRef(KIND_CUSTOM, view.refs[view.selected_index].profile_id, 1)
        ).settings["steps"]
        == 22
    )

    ok, message = host.profiles.on_toggle_favorite()
    assert ok and "favorite" in message.lower()
    assert host.profiles.strip_view().favorite


def test_save_without_a_model_is_refused_truthfully(tmp_path: Path) -> None:
    empty = FakeHost(FakePanel(model=""), tmp_path)
    ok, message = empty.profiles.on_save_custom("x")
    assert not ok and "model" in message.lower()
    ok, message = empty.profiles.save_startup_defaults()
    assert not ok and "model" in message.lower()


def test_research_profile_cannot_be_updated_in_place(host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    state = host.profiles.state()
    assert state.selected.kind == KIND_RESEARCH and state.selected.profile_id == SDXL_RESEARCH_ID
    assert not host.profiles.strip_view().can_update_custom
    ok, message = host.profiles.on_save_custom("", update=True)
    assert not ok


def test_listeners_hear_about_every_change_and_a_failing_listener_is_harmless(
    host: FakeHost,
) -> None:
    heard: list[int] = []
    host.profiles.add_listener(lambda: heard.append(1))
    host.profiles.add_listener(lambda: (_ for _ in ()).throw(RuntimeError("view gone")))
    host.profiles.on_model_chosen(SDXL_MODEL)
    host.profiles.notify_changed()
    assert len(heard) == 2


# --------------------------------------------------------------------------- startup defaults


def test_save_startup_defaults_persists_the_allowed_parts_and_confirms_truthfully(
    host: FakeHost,
) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    host.flags["adetailer"] = True
    ok, message = host.profiles.save_startup_defaults()

    assert ok and SDXL_MODEL in message
    document = host.profiles.service.store.load_startup_document()
    text = str(document)
    assert document["model_name"] == SDXL_MODEL
    assert document["stage_flags"]["adetailer"] is True
    assert document["profile"]["profile_id"] == SDXL_RESEARCH_ID
    for forbidden in ("input_image_path", "mask_path", "anchor_image", "D:/in"):
        assert forbidden not in text
    assert "seed" not in document["generation"]


def test_save_startup_defaults_failure_is_reported_not_swallowed(
    host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_document: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(host.profiles.service.store, "save_startup_document", broken)
    ok, message = host.profiles.save_startup_defaults()
    assert not ok and message


def test_startup_restore_fills_the_working_settings_and_stage_state(
    host: FakeHost, tmp_path: Path
) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    host.panel.values.update(steps=22, width=832, height=1216)
    host.flags["adetailer"] = True
    assert host.profiles.save_startup_defaults()[0]

    fresh = FakeHost(FakePanel(model="other.safetensors", steps=5), tmp_path)
    plan = fresh.profiles.restore_startup_defaults()

    assert plan is not None and plan.restores_anything
    assert fresh.panel.values["model"] == SDXL_MODEL
    assert (
        fresh.panel.values["steps"],
        fresh.panel.values["width"],
        fresh.panel.values["height"],
    ) == (22, 832, 1216)
    assert fresh.restored and fresh.restored[-1]["pipeline"]["adetailer_enabled"] is True
    assert fresh.sidebar.source == "startup"
    assert fresh.client_calls == 0
    # The saved profile is the one the strip shows, and an edit away from it is disclosed rather than hidden.
    assert fresh.profiles.state().selected.profile_id == SDXL_RESEARCH_ID
    assert fresh.panel.values["seed"] == 123


def test_startup_restore_with_no_saved_defaults_changes_nothing(host: FakeHost) -> None:
    before = dict(host.panel.values)
    assert host.profiles.restore_startup_defaults() is None
    assert host.panel.values == before and not host.restored and not host.panel.applied


def test_startup_restore_reports_a_missing_model_and_substitutes_nothing(tmp_path: Path) -> None:
    saver = FakeHost(FakePanel(), tmp_path)
    saver.profiles.on_model_chosen(SDXL_MODEL)
    assert saver.profiles.save_startup_defaults()[0]

    runtime = FakeHost(
        FakePanel(model="current.safetensors"),
        tmp_path,
        models=["current.safetensors", "another.safetensors"],
    )
    plan = runtime.profiles.restore_startup_defaults()

    assert plan is not None and not plan.restores_anything
    assert runtime.panel.values["model"] == "current.safetensors"
    assert not runtime.panel.applied and not runtime.restored
    assert any("not available" in line for line in runtime.logs)


def test_a_model_list_that_arrives_later_reveals_a_missing_startup_model(tmp_path: Path) -> None:
    saver = FakeHost(FakePanel(), tmp_path)
    saver.profiles.on_model_chosen(SDXL_MODEL)
    saver.profiles.save_startup_defaults()

    late = FakeHost(
        FakePanel(model="current.safetensors"), tmp_path
    )  # no model list yet: nothing to validate against
    assert late.profiles.restore_startup_defaults().restores_anything
    assert late.panel.values["model"] == SDXL_MODEL

    late.app_state.resources["models"] = ["current.safetensors"]
    late.profiles.on_resources_updated(late.app_state.resources)
    assert any("not offered by the runtime" in issue for issue in late.profiles.startup_issues)
    assert late.panel.values["model"] == SDXL_MODEL  # reported, never swapped silently


# --------------------------------------------------------------------------- draft truth


def _entry(**flags: bool) -> Any:
    return SimpleNamespace(
        stage_flags={
            "txt2img": True,
            "img2img": False,
            "adetailer": False,
            "upscale": False,
            **flags,
        }
    )


def test_no_notice_when_the_draft_matches_the_working_settings() -> None:
    flags = {"txt2img": True, "img2img": False, "adetailer": False, "upscale": False}
    built = {"override": False, "profile": "x"}
    assert (
        draft_staleness_notices(
            [_entry()],
            current_flags=flags,
            built_with=built,
            override_enabled=False,
            current_profile="x",
        )
        == ()
    )
    assert (
        draft_staleness_notices(
            [],
            current_flags={"adetailer": True},
            built_with=None,
            override_enabled=None,
            current_profile="",
        )
        == ()
    )


def test_stage_toggle_override_and_profile_changes_mark_the_preview_stale() -> None:
    notices = draft_staleness_notices(
        [_entry()],
        current_flags={"txt2img": True, "img2img": False, "adetailer": True, "upscale": False},
        built_with={"override": False, "profile": "a"},
        override_enabled=True,
        current_profile="b",
    )
    assert len(notices) == 3
    assert "adetailer is on now" in notices[0] and "Add the packs to the job again" in notices[0]
    assert "override was switched on" in notices[1]
    assert "model or generation profile changed" in notices[2]


def test_controller_notices_follow_the_draft_it_built(host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    host.app_state.job_draft.packs = [_entry()]
    host.profiles.note_draft_built()
    assert host.profiles.draft_notices() == ()

    host.flags["adetailer"] = True
    host.override_pack_config_enabled = True
    notices = host.profiles.draft_notices()
    assert len(notices) == 2

    host.profiles.on_save_custom(
        "Changed"
    )  # a different selected profile after the draft was built
    assert len(host.profiles.draft_notices()) == 3

    host.profiles.clear_draft_record()
    host.app_state.job_draft.packs = []
    assert host.profiles.draft_notices() == ()


def test_effective_lines_name_model_profile_and_override_precedence(host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    off = "\n".join(host.profiles.effective_lines())
    assert SDXL_MODEL in off and "Research" in off and "Override is OFF" in off
    host.override_pack_config_enabled = True
    assert "Override is ON" in "\n".join(host.profiles.effective_lines())
