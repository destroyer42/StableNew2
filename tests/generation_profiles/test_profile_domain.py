"""Profile contract, identity, Research evidence, store and versioning (PR-IMG-PROFILE-630)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.generation_profiles.contract import (
    IDENTITY_MODEL,
    KIND_CUSTOM,
    KIND_LEARNING,
    KIND_RESEARCH,
    SOURCE_CLASSES,
    EvidenceNote,
    GenerationProfile,
    ModelIdentity,
    ProfileError,
    ProfileRef,
    validate_settings,
)
from src.generation_profiles.identity import (
    MATCH_CONFLICT,
    MATCH_EXACT,
    MATCH_OTHER_MODEL,
    MATCH_RENAMED,
    MATCH_UNVERIFIED_BYTES,
    ModelIdentityResolver,
    match_identity,
)
from src.generation_profiles.research import (
    KLEIN_RESEARCH_ID,
    SDXL_RESEARCH_ID,
    ZIMAGE_RESEARCH_ID,
    research_profiles,
)
from src.generation_profiles.store import (
    GENERATION_PROFILE_DIR_ENV,
    GenerationProfileStore,
    ProfileStoreError,
    resolve_generation_profile_dir,
)
from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1

SHA_A = "a" * 64
SHA_B = "b" * 64


def _compat(family: str | None, status: str = "resolved"):
    return SimpleNamespace(
        status=SimpleNamespace(value=status),
        family=SimpleNamespace(value=family) if family else None,
        checkpoint_architecture=None,
        structural_error=None,
    )


def _resolver(
    families: dict[str, str | None], shas: dict[str, str] | None = None
) -> ModelIdentityResolver:
    return ModelIdentityResolver(
        family_lookup=lambda name: _compat(families[name]) if name in families else None,
        sha_lookup=lambda name: (shas or {}).get(name),
    )


def _model_identity(
    key: str = "juggernaut", family: str = "sdxl", sha: str | None = None
) -> ModelIdentity:
    return ModelIdentity(
        kind=IDENTITY_MODEL,
        key=f"model:{family}:{key}",
        family=family,
        display_name=key,
        model_key=key,
        sha256=sha,
    )


# ---------------------------------------------------------------- contract


def test_settings_reject_stage_enablement_and_unknown_keys() -> None:
    for key in ("adetailer_enabled", "upscale_enabled", "seed", "model"):
        with pytest.raises(ProfileError):
            validate_settings({key: True})


@pytest.mark.parametrize(
    "settings",
    [
        {"steps": 0},
        {"steps": 1.5},
        {"steps": True},
        {"cfg_scale": float("nan")},
        {"cfg_scale": 99},
        {"width": 8},
        {"sampler_name": ""},
    ],
)
def test_settings_validation_rejects_bad_values(settings: dict) -> None:
    with pytest.raises(ProfileError):
        validate_settings(settings)


def test_profile_round_trips_and_is_equal() -> None:
    profile = GenerationProfile(
        "custom-x",
        2,
        KIND_CUSTOM,
        "Mine",
        _model_identity(sha=SHA_A),
        {"steps": 30, "cfg_scale": 6.5, "vae": ""},
    )
    assert GenerationProfile.from_dict(json.loads(json.dumps(profile.to_dict()))) == profile


def test_research_profile_requires_evidence_for_every_value() -> None:
    family = ModelIdentity(kind="family", key="family:sdxl", family="sdxl")
    with pytest.raises(ProfileError, match="without evidence"):
        GenerationProfile("r", 1, KIND_RESEARCH, "R", family, {"steps": 20})
    with pytest.raises(ProfileError):  # a research profile never binds to one checkpoint file
        GenerationProfile("r", 1, KIND_RESEARCH, "R", _model_identity(), {})


def test_value_cannot_be_both_set_and_unavailable() -> None:
    with pytest.raises(ProfileError):
        GenerationProfile(
            "c", 1, KIND_CUSTOM, "C", _model_identity(), {"steps": 20}, unavailable={"steps": "why"}
        )


@pytest.mark.parametrize(
    "bad", [{}, {"schema_version": 99}, {"schema_version": 1, "profile_id": "x"}, []]
)
def test_malformed_profile_documents_raise_profile_error(bad) -> None:
    with pytest.raises(ProfileError):
        GenerationProfile.from_dict(bad)


# ---------------------------------------------------------------- research


def test_research_profiles_cover_only_supported_models_and_cite_sources() -> None:
    profiles = {p.profile_id: p for p in research_profiles()}
    assert set(profiles) == {
        SDXL_RESEARCH_ID,
        KLEIN_RESEARCH_ID,
        ZIMAGE_RESEARCH_ID,
    }  # no Qwen / invented family
    for profile in profiles.values():
        assert profile.kind == KIND_RESEARCH
        for key in profile.settings:
            note = profile.evidence_for(key)
            assert note is not None and note.source_class in SOURCE_CLASSES and note.reviewed_on
        for note in profile.evidence:
            assert note.rationale


def test_exact_research_values_equal_the_executable_profiles() -> None:
    klein = latest_klein_profile()
    k = next(p for p in research_profiles() if p.profile_id == KLEIN_RESEARCH_ID)
    assert (
        k.settings["sampler_name"],
        k.settings["scheduler"],
        k.settings["steps"],
        k.settings["cfg_scale"],
    ) == (
        klein.sampler,
        klein.scheduler,
        klein.steps,
        klein.cfg_scale,
    )
    assert dict(k.executable_profile) == dict(klein.reference())
    z = next(p for p in research_profiles() if p.profile_id == ZIMAGE_RESEARCH_ID)
    assert (z.settings["steps"], z.settings["cfg_scale"]) == (
        ZIMAGE_PROFILE_V1.steps,
        ZIMAGE_PROFILE_V1.cfg_scale,
    )


def test_sdxl_research_does_not_invent_sampler_steps_or_cfg() -> None:
    sdxl = next(p for p in research_profiles() if p.profile_id == SDXL_RESEARCH_ID)
    assert set(sdxl.settings) == {"width", "height"}
    assert {"sampler_name", "scheduler", "steps", "cfg_scale"} <= set(sdxl.unavailable)


# ---------------------------------------------------------------- identity


def test_lookalike_filename_never_gets_an_exact_identity() -> None:
    resolver = _resolver({})
    other = resolver.resolve("my-flux2-klein-4b-fp8-merge.safetensors")
    assert other.identity.kind == IDENTITY_MODEL and other.identity.family == "unknown"
    assert other.unverified_reason


def test_registry_family_gives_a_model_identity_and_unknown_gets_a_reason() -> None:
    resolver = _resolver({"juggernaut.safetensors": "sdxl", "sd15.safetensors": "sd1"})
    sdxl = resolver.resolve("juggernaut.safetensors")
    assert sdxl.identity.key == "model:sdxl:juggernaut" and sdxl.unverified_reason == ""
    sd15 = resolver.resolve("sd15.safetensors")
    assert sd15.identity.family == "sd1" and sd15.unverified_reason  # labelled, not qualified
    missing = resolver.resolve("mystery.safetensors")
    assert missing.identity.family == "unknown" and "registry" in missing.unverified_reason.lower()


def test_identity_matching_distinguishes_rename_conflict_and_unverified() -> None:
    saved = _model_identity("juggernaut", sha=SHA_A)
    assert match_identity(saved, _model_identity("juggernaut", sha=SHA_A)).status == MATCH_EXACT
    assert (
        match_identity(saved, _model_identity("juggernaut-v2", sha=SHA_A)).status == MATCH_RENAMED
    )
    assert match_identity(saved, _model_identity("juggernaut", sha=SHA_B)).status == MATCH_CONFLICT
    assert match_identity(saved, _model_identity("other", sha=SHA_B)).status == MATCH_OTHER_MODEL
    assert match_identity(saved, _model_identity("juggernaut")).status == MATCH_UNVERIFIED_BYTES
    assert (
        match_identity(saved, _model_identity("juggernaut", family="sd1")).status
        == MATCH_OTHER_MODEL
    )


# ---------------------------------------------------------------- store


def test_store_dir_resolution_prefers_explicit_then_env(tmp_path: Path) -> None:
    assert resolve_generation_profile_dir(tmp_path / "x") == tmp_path / "x"
    assert (
        resolve_generation_profile_dir(environ={GENERATION_PROFILE_DIR_ENV: str(tmp_path / "e")})
        == tmp_path / "e"
    )
    win = resolve_generation_profile_dir(
        environ={"LOCALAPPDATA": str(tmp_path)}, system_name="Windows"
    )
    assert win == tmp_path / "StableNew" / "GenerationProfiles"
    assert GenerationProfileStore().root == Path(os.environ[GENERATION_PROFILE_DIR_ENV])


def test_custom_profile_revisions_are_immutable_and_versioned(tmp_path: Path) -> None:
    store = GenerationProfileStore(tmp_path, clock=lambda: "2026-10-24T00:00:00+00:00")
    model = _model_identity()
    first = store.save_custom("Fast", model, {"steps": 20, "cfg_scale": 6.0})
    second = store.save_custom(
        "Fast", model, {"steps": 28, "cfg_scale": 6.0}, profile_id=first.profile_id
    )
    assert (first.revision, second.revision) == (1, 2)
    history = store.revisions(KIND_CUSTOM, first.profile_id)
    assert [p.settings["steps"] for p in history] == [20, 28]
    assert (
        store.load(first.ref).settings["steps"] == 20
    )  # an older revision is still readable and unchanged
    assert store.load(ProfileRef(KIND_CUSTOM, first.profile_id)).settings["steps"] == 28
    revision_one = tmp_path / "profiles" / "custom" / first.profile_id / "r0001.json"
    with pytest.raises(ProfileStoreError, match="immutable"):
        store._publish(first)  # noqa: SLF001 - proves a revision file is never overwritten
    assert json.loads(revision_one.read_text(encoding="utf-8"))["settings"]["steps"] == 20


def test_custom_profile_cannot_change_model(tmp_path: Path) -> None:
    store = GenerationProfileStore(tmp_path)
    first = store.save_custom("A", _model_identity("one"), {"steps": 10})
    with pytest.raises(ProfileError):
        store.save_custom("A", _model_identity("two"), {"steps": 10}, profile_id=first.profile_id)


def test_failed_atomic_write_keeps_previous_revision_and_leaves_no_partial_file(
    tmp_path: Path, monkeypatch
) -> None:
    store = GenerationProfileStore(tmp_path)
    model = _model_identity()
    first = store.save_custom("A", model, {"steps": 10})
    import src.generation_profiles.store as store_module

    def boom(path, data, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(store_module, "atomic_write_json", boom)
    with pytest.raises(ProfileStoreError, match="disk full"):
        store.save_custom("A", model, {"steps": 99}, profile_id=first.profile_id)
    assert [p.settings["steps"] for p in store.revisions(KIND_CUSTOM, first.profile_id)] == [10]


def test_malformed_and_future_schema_revisions_are_skipped_not_fatal(tmp_path: Path) -> None:
    store = GenerationProfileStore(tmp_path)
    model = _model_identity()
    first = store.save_custom("A", model, {"steps": 10})
    folder = tmp_path / "profiles" / "custom" / first.profile_id
    (folder / "r0002.json").write_text("{not json", encoding="utf-8")
    future = first.to_dict() | {"revision": 3, "schema_version": 99}
    (folder / "r0003.json").write_text(json.dumps(future), encoding="utf-8")
    (folder / "r0004.json").write_text(
        json.dumps(first.to_dict() | {"revision": 7}), encoding="utf-8"
    )
    assert [p.revision for p in store.revisions(KIND_CUSTOM, first.profile_id)] == [1]
    assert len(store.diagnostics) == 3
    # the next save never reuses a skipped file's number
    assert store.save_custom("A", model, {"steps": 12}, profile_id=first.profile_id).revision == 5


def test_names_with_spaces_and_unicode_are_safe(tmp_path: Path) -> None:
    store = GenerationProfileStore(tmp_path)
    saved = store.save_custom("Ünïcode / slash: test", _model_identity(), {"steps": 10})
    assert store.load(saved.ref).name == "Ünïcode / slash: test"


def test_favorites_are_per_model_and_survive_corruption(tmp_path: Path) -> None:
    store = GenerationProfileStore(tmp_path)
    store.set_favorite("model:sdxl:a", ProfileRef(KIND_CUSTOM, "custom-1"))
    store.set_favorite("model:sdxl:b", ProfileRef(KIND_LEARNING, "learn-1", 2))
    store.set_favorite("model:sdxl:a", None)
    assert set(store.favorites()) == {"model:sdxl:b"}
    (tmp_path / "favorites.json").write_text("garbage", encoding="utf-8")
    assert store.favorites() == {}
    store.set_favorite("model:sdxl:c", ProfileRef(KIND_CUSTOM, "custom-2"))
    assert (tmp_path / "favorites.json.corrupt").read_text(encoding="utf-8") == "garbage"


def test_learning_seam_accepts_only_next_learning_revision_and_never_touches_custom(
    tmp_path: Path,
) -> None:
    store = GenerationProfileStore(tmp_path)
    model = _model_identity()
    custom = store.save_custom("Mine", model, {"steps": 10})
    learning = GenerationProfile(
        "learn-1",
        1,
        KIND_LEARNING,
        "Learned",
        model,
        {"steps": 24},
        evidence=(
            EvidenceNote(("steps",), "learning_evidence", "Won 12 of 15 reviewed comparisons."),
        ),
        provenance={"experiment_count": 3},
    )
    store.publish_learning_profile(learning)
    with pytest.raises(ProfileError, match="revision"):
        store.publish_learning_profile(learning)  # not the next revision
    with pytest.raises(ProfileError):
        store.publish_learning_profile(custom)  # wrong kind
    assert store.load(custom.ref) == custom
    assert [p.profile_id for p in store.list_latest(KIND_LEARNING)] == ["learn-1"]
    assert not list(tmp_path.glob("**/*.tmp"))
