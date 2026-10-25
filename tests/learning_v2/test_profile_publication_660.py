"""Publication uses durable, field-specific evidence, never a broad recommendation tier."""

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import pytest

from src.generation_profiles.contract import KIND_LEARNING, SOURCE_LEARNING, ProfileRef
from src.generation_profiles.identity import ModelIdentityResolver, match_learning_identity
from src.generation_profiles.service import GenerationProfileService
from src.generation_profiles.store import GenerationProfileStore
from src.image_backends.model_policy import resolve_model_policy
from src.learning.experiment_execution import freeze_snapshot, snapshot_digest
from src.learning.model_capabilities import policy_context
from src.learning.profile_publication import ProfilePublicationService


def make_publication(tmp_path):
    policy = resolve_model_policy(
        "test.safetensors",
        family_lookup=lambda _name: SimpleNamespace(
            status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sdxl")
        ),
    )
    resolver = ModelIdentityResolver(
        policy_resolver=lambda _name: policy, sha_lookup=lambda _name: "a" * 64
    )
    return ProfilePublicationService(GenerationProfileStore(tmp_path / "profiles"), resolver)


@pytest.fixture
def publication(tmp_path):
    return make_publication(tmp_path)


def records(service, values=(20, 30, 40)):
    model = service.resolver.resolve("test.safetensors")
    baseline = {
        "model": "test.safetensors",
        "steps": 20,
        "cfg_scale": 6.0,
        "sampler_name": "Euler",
        "sampler": "Euler",
        "scheduler": "Normal",
        "width": 1024,
        "height": 1024,
        "vae": "",
        "seed": -1,
        "batch_size": 1,
        "n_iter": 1,
    }
    snapshot = {
        "schema_version": 2,
        "experiment_id": "experiment-1",
        "stage": "txt2img",
        "variable_under_test": "Steps",
        "variant_values": list(values),
        "model_identity": model.identity.to_dict(),
        "model_policy_context": policy_context(model.policy, "test.safetensors", "txt2img"),
        "baseline_config": {"txt2img": baseline},
        "seed_policy": {"requested_sample_count": 1, "requested_base_seed": 42},
    }
    return [
        {
            "run_id": f"rating-{i}",
            "primary_model": "test.safetensors",
            "metadata": {
                "record_kind": "learning_experiment_rating",
                "experiment_id": "experiment-1",
                "job_id": f"job-{i}",
                "image_path": f"private/output-{i}.png",
                "variable_under_test": "Steps",
                "variant_value": value,
                "user_rating": 5 if value == 30 else 3,
                "learning_context": {"experiment_id": "experiment-1", "variant_id": f"variant-{i}"},
                "frozen_experiment": {
                    "experiment_id": "experiment-1",
                    "variant_id": f"variant-{i}",
                    "snapshot": copy.deepcopy(snapshot),
                    "snapshot_sha256": snapshot_digest(freeze_snapshot(snapshot)),
                    "controlled_evidence_valid": True,
                    "variable_validation_reason": "valid",
                    "actual_all_seeds": [42],
                    "executed_config": {"txt2img": {**baseline, "steps": value, "seed": 42}},
                },
            },
        }
        for i, value in enumerate(values)
    ]


def test_steps_golden_publication(publication):
    rows = records(publication)
    proposal = publication.evaluate(rows, "test.safetensors", experiment_id="experiment-1")
    assert proposal.settings == {"steps": 30}
    assert proposal.sample_count == 3
    assert proposal == publication.evaluate(rows, "test.safetensors", experiment_id="experiment-1")
    assert not publication.store.root.exists()
    with pytest.raises(ValueError, match="confirmation"):
        publication.publish(proposal, rows, "test.safetensors", name="Findings", confirmed=False)
    saved = publication.publish(proposal, rows, "test.safetensors", name="Findings", confirmed=True)
    assert saved.revision == 1
    assert (
        GenerationProfileStore(publication.store.root).load(saved.ref).to_dict() == saved.to_dict()
    )
    assert saved.settings == {"steps": 30}
    assert "private" not in str(saved.to_dict())
    with pytest.raises(ValueError, match="already published"):
        publication.publish(proposal, rows, "test.safetensors", name="Findings", confirmed=True)


@pytest.mark.parametrize("values", [(20,), (20, 30), (20, 20, 20)])
def test_insufficient_cohort(publication, values):
    assert not publication.evaluate(records(publication, values), "test.safetensors").settings


def test_latest_rating_does_not_inflate_counts(publication):
    rows = records(publication)
    assert publication.evaluate(rows + copy.deepcopy(rows), "test.safetensors").sample_count == 3


@pytest.mark.parametrize(
    "kind",
    [
        "review_tab_feedback",
        "learning_model_comparison_rating",
        "learning_grid_rating",
        "video_workflow_quality_rating",
        "",
    ],
)
def test_other_sources_refuse(publication, kind):
    rows = records(publication)
    for row in rows:
        row["metadata"]["record_kind"] = kind
    assert not publication.evaluate(rows, "test.safetensors").settings


def rewrite_snapshots(rows, change):
    for row in rows:
        frozen = row["metadata"]["frozen_experiment"]
        change(frozen["snapshot"])
        frozen["snapshot_sha256"] = snapshot_digest(freeze_snapshot(frozen["snapshot"]))


@pytest.mark.parametrize(
    "missing",
    [
        "snapshot",
        "snapshot_sha256",
        "executed_config",
        "controlled_evidence_valid",
        "variable_validation_reason",
        "variant_id",
        "experiment_id",
    ],
)
def test_missing_execution_proof_refuses(publication, missing):
    rows = records(publication)
    for row in rows:
        del row["metadata"]["frozen_experiment"][missing]
    proposal = publication.evaluate(rows, "test.safetensors")
    assert not proposal.ready
    assert proposal.blockers


@pytest.mark.parametrize(
    "field,value",
    [
        ("controlled_evidence_valid", False),
        ("controlled_evidence_valid", 1),
        ("variable_validation_reason", "backend_restart_boundary"),
        ("snapshot_sha256", "bad"),
        ("experiment_id", "other"),
        ("variant_id", "other"),
    ],
)
def test_contradictory_proof_refuses(publication, field, value):
    rows = records(publication)
    for row in rows:
        row["metadata"]["frozen_experiment"][field] = value
    assert not publication.evaluate(rows, "test.safetensors").ready


@pytest.mark.parametrize("rating", [None, True, 0, 6, "5", float("nan"), float("inf")])
def test_invalid_or_draft_rating_refuses(publication, rating):
    rows = records(publication)
    for row in rows:
        row["metadata"]["user_rating"] = rating
    assert not publication.evaluate(rows, "test.safetensors").ready


@pytest.mark.parametrize(
    "location",
    [
        "value",
        "variable",
        "primary_model",
        "executed_model",
        "frozen_model",
        "policy",
        "stage",
        "hash",
        "missing_hash",
        "missing_identity",
    ],
)
def test_identity_context_and_value_conflicts(publication, location):
    rows = records(publication)
    for row in rows:
        meta = row["metadata"]
        if location == "value":
            meta["frozen_experiment"]["executed_config"]["txt2img"]["steps"] = 90
        elif location == "variable":
            meta["variable_under_test"] = "CFG Scale"
        elif location == "primary_model":
            row["primary_model"] = "other.safetensors"
        elif location == "executed_model":
            meta["frozen_experiment"]["executed_config"]["txt2img"]["model"] = "other.safetensors"

    def change(snapshot):
        if location == "frozen_model":
            snapshot["baseline_config"]["txt2img"]["model"] = "other.safetensors"
        elif location == "policy":
            snapshot["model_policy_context"]["policy_id"] = "other"
        elif location == "stage":
            snapshot["stage"] = "img2img"
        elif location == "hash":
            snapshot["model_identity"]["sha256"] = "b" * 64
        elif location == "missing_hash":
            snapshot["model_identity"]["sha256"] = None
        elif location == "missing_identity":
            del snapshot["model_identity"]

    rewrite_snapshots(rows, change)
    assert not publication.evaluate(rows, "test.safetensors").ready


def test_renamed_same_bytes_is_compatible_changed_bytes_are_not(publication):
    rows = records(publication)
    assert publication.evaluate(rows, "renamed.safetensors").ready
    other = ModelIdentityResolver(
        policy_resolver=lambda _: publication.resolver.resolve("test").policy,
        sha_lookup=lambda _: "b" * 64,
    )
    assert (
        not ProfilePublicationService(publication.store, other)
        .evaluate(rows, "test.safetensors")
        .ready
    )
    missing = ModelIdentityResolver(
        policy_resolver=lambda _: publication.resolver.resolve("test").policy,
        sha_lookup=lambda _: None,
    )
    assert (
        not ProfilePublicationService(publication.store, missing)
        .evaluate(rows, "test.safetensors")
        .ready
    )
    unknown = ProfilePublicationService(
        publication.store, ModelIdentityResolver(family_lookup=lambda _: None)
    )
    assert not unknown.evaluate(rows, "test.safetensors").ready


def test_exact_profile_versions_and_owned_controls(publication):
    resolver = ModelIdentityResolver()
    identity = resolver.resolve("flux-2-klein-4b-fp8.safetensors").identity
    changed = replace(identity, exact_profile={**identity.exact_profile, "version": 999})
    assert not match_learning_identity(identity, changed).applies
    assert match_learning_identity(identity, identity).applies
    rows = records(publication)
    target = publication.resolver.resolve("test.safetensors")
    from src.image_backends.model_policy import ControlMode, ControlPolicy

    policy = replace(
        target.policy,
        controls={**target.policy.controls, "steps": ControlPolicy(ControlMode.FIXED, 4)},
    )
    publication.resolver = ModelIdentityResolver(
        policy_resolver=lambda _: policy, sha_lookup=lambda _: "a" * 64
    )
    rewrite_snapshots(
        rows,
        lambda s: s.update(
            model_policy_context=policy_context(policy, "test.safetensors", "txt2img")
        ),
    )
    assert not publication.evaluate(rows, "test.safetensors").ready


def test_steps_does_not_launder_cfg_or_untested_baseline(publication):
    rows = records(publication)
    review = copy.deepcopy(rows)
    for row in review:
        row["metadata"].update(
            record_kind="review_tab_feedback", variable_under_test="CFG Scale", variant_value=7
        )
    proposal = publication.evaluate(rows + review, "test.safetensors")
    assert proposal.settings == {"steps": 30}
    assert {"cfg_scale", "width", "height", "vae"} <= dict(proposal.excluded).keys()


def test_rerating_is_effective_latest_and_stales_proposal(publication):
    rows = records(publication)
    proposal = publication.evaluate(rows, "test.safetensors")
    rerated = copy.deepcopy(rows[1])
    rerated["metadata"]["user_rating"] = 1
    changed = rows + [rerated]
    current = publication.evaluate(changed, "test.safetensors")
    assert current.sample_count == 3 and current.settings == {"steps": 20}
    with pytest.raises(ValueError, match="stale"):
        publication.publish(proposal, changed, "test.safetensors", name="Findings", confirmed=True)
    assert not publication.store.root.exists()
    rerated["metadata"]["frozen_experiment"]["controlled_evidence_valid"] = False
    assert not publication.evaluate(changed, "test.safetensors").ready


def test_revision_catalog_and_no_side_effects(publication):
    rows = records(publication)
    originals = copy.deepcopy(rows)
    catalog = GenerationProfileService(publication.store, publication.resolver, research=lambda: ())
    custom = publication.store.save_custom(
        "Custom", publication.resolver.resolve("test").identity, {"steps": 15}
    )
    publication.store.set_favorite(custom.model.key, custom.ref)
    publication.store.save_startup_document({"operator": "unchanged"})
    before = {p: p.read_bytes() for p in publication.store.root.rglob("*.json")}
    working = {"steps": 12, "cfg_scale": 6}
    state = catalog.state_for("test", working)
    first = publication.publish(
        publication.evaluate(rows, "test"), rows, "test", name="Findings", confirmed=True
    )
    first_path = next(publication.store.root.glob("profiles/learning/*/r0001.json"))
    first_bytes = first_path.read_bytes()
    assert all(p.read_bytes() == content for p, content in before.items())
    assert working == {"steps": 12, "cfg_scale": 6}
    assert rows == originals
    assert catalog.state_for("test", working).selected == state.selected
    assert first.ref in [option.ref for option in catalog.state_for("test", working).options]
    assert all(note.source_class == SOURCE_LEARNING for note in first.evidence)
    replacement = copy.deepcopy(rows[1])
    replacement["metadata"]["user_rating"] = 1
    changed = rows + [replacement]
    proposal = publication.evaluate(changed, "test")
    assert proposal.differences(first) == ("steps: 30 -> 20",)
    second = publication.publish(
        proposal, changed, "test", name="Revised", confirmed=True, lineage=first.ref
    )
    assert second.revision == 2 and second.profile_id == first.profile_id
    assert first_path.read_bytes() == first_bytes
    assert second.model == first.model
    with pytest.raises(ValueError, match="stale"):
        publication.publish(
            proposal, changed, "test", name="Old ref", confirmed=True, lineage=first.ref
        )
    assert len(publication.store.revisions(KIND_LEARNING, first.profile_id)) == 2
    # Existing corrupt-latest behavior: retain readable prior revisions without touching corrupt bytes.
    corrupt = first_path.with_name("r0003.json")
    corrupt.write_text("broken", encoding="utf-8")
    assert publication.store.load(ProfileRef(KIND_LEARNING, first.profile_id)) == second
    assert corrupt.read_text() == "broken"


def test_concurrent_publish_and_immutable_store_boundary(publication, monkeypatch):
    rows = records(publication)
    proposal = publication.evaluate(rows, "test")

    def publish():
        try:
            return publication.publish(proposal, rows, "test", name="Concurrent", confirmed=True)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(), range(2)))
    saved = next(p for p in results if p is not None)
    assert sum(p is not None for p in results) == 1
    next_profile = replace(saved, revision=2, settings={"steps": 40})
    import src.generation_profiles.store as store_module

    actual = store_module.atomic_publish_json
    barrier = Barrier(2)

    def simultaneous(*args, **kwargs):
        barrier.wait(timeout=5)
        return actual(*args, **kwargs)

    monkeypatch.setattr(store_module, "atomic_publish_json", simultaneous)

    def direct():
        try:
            return GenerationProfileStore(publication.store.root).publish_learning_profile(
                next_profile
            )
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: direct(), range(2)))
    assert sum(p is not None for p in results) == 1
    assert publication.store.load(next_profile.ref).to_dict() == next_profile.to_dict()
    assert not list(publication.store.root.rglob("*.tmp"))


def test_failed_atomic_publish_preserves_prior_revision(publication, monkeypatch):
    rows = records(publication)
    saved = publication.publish(
        publication.evaluate(rows, "test"), rows, "test", name="Saved", confirmed=True
    )
    before = {p: p.read_bytes() for p in publication.store.root.rglob("*.json")}
    import src.utils.atomic_io as atomic

    def fail(*_args, **_kwargs):
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(atomic.os, "rename" if atomic.os.name == "nt" else "link", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        publication.store.publish_learning_profile(replace(saved, revision=2))
    assert {p: p.read_bytes() for p in publication.store.root.rglob("*.json")} == before
    assert not list(publication.store.root.rglob("*.tmp"))


@pytest.mark.parametrize("kind", ["sampler", "scheduler", "vae"])
def test_resources_are_qualified_but_never_substituted(publication, kind):
    from src.learning.variable_metadata import LEARNING_VARIABLES

    meta = LEARNING_VARIABLES[kind]
    key = meta.config_path.split(".")[-1]
    rows = records(publication)
    values = ["A", "B", "C"]
    rewrite_snapshots(
        rows, lambda s: s.update(variable_under_test=meta.display_name, variant_values=values)
    )
    for row, value in zip(rows, values, strict=True):
        data = row["metadata"]
        data.update(variable_under_test=meta.display_name, variant_value=value)
        data["frozen_experiment"]["executed_config"]["txt2img"].update(steps=20, **{key: value})
    unavailable = publication.evaluate(rows, "test")
    assert not unavailable.ready
    assert "availability" in dict(unavailable.excluded)[key]
    catalog_key = {"sampler": "samplers", "scheduler": "schedulers", "vae": "vaes"}[kind]
    assert not publication.evaluate(rows, "test", catalogs={catalog_key: ["unrelated"]}).ready
    ready = publication.evaluate(rows, "test", catalogs={catalog_key: values})
    assert ready.settings == {key: "B"}


def test_seed_readback_and_fixed_context_must_agree(publication):
    rows = records(publication)
    rows[0]["metadata"]["frozen_experiment"]["actual_all_seeds"] = [91]
    assert not publication.evaluate(rows, "test").ready
    rows = records(publication)
    rewrite_snapshots(rows, lambda s: s["baseline_config"]["txt2img"].update(cfg_scale=6))
    for row in rows:
        row["metadata"]["frozen_experiment"]["executed_config"]["txt2img"]["cfg_scale"] = 9
    assert not publication.evaluate(rows, "test").ready


def test_store_rejects_changed_model_and_exact_version_without_overwriting(publication):
    rows = records(publication)
    saved = publication.publish(
        publication.evaluate(rows, "test"), rows, "test", name="Saved", confirmed=True
    )
    with pytest.raises(ValueError, match="model"):
        publication.store.publish_learning_profile(
            replace(saved, revision=2, model=replace(saved.model, sha256="b" * 64))
        )
    with pytest.raises(ValueError, match="lineage"):
        publication.publish(
            publication.evaluate(rows, "test"),
            rows,
            "test",
            name="Invalid",
            confirmed=True,
            lineage=ProfileRef("custom", "other", 1),
        )
    assert len(publication.store.revisions(KIND_LEARNING, saved.profile_id)) == 1


def test_snapshot_captures_cached_identity_without_backfilling_history(publication, monkeypatch):
    from src.learning.ordinary_snapshot import ordinary_snapshot

    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver", lambda: publication.resolver
    )
    experiment = SimpleNamespace(
        experiment_id="e",
        name="Experiment",
        prompt_text="private prompt",
        stage="txt2img",
        variable_under_test="Steps",
        values=[20, 30],
        images_per_value=1,
        input_image_path=None,
    )
    target = publication.resolver.resolve("test")
    snapshot = ordinary_snapshot(
        experiment,
        baseline={"txt2img": {"model": "test"}},
        negative_prompt="",
        seed_policy={},
        prompt_source={},
        model_context=policy_context(target.policy, "test", "txt2img"),
    )
    assert snapshot["model_identity"] == target.identity.to_dict()
    historical = records(publication)
    rewrite_snapshots(historical, lambda s: s.pop("model_identity"))
    assert not publication.evaluate(historical, "test").ready


def test_learning_application_refuses_changed_exact_version_and_missing_bytes(publication):
    from src.generation_profiles.application import plan_application
    from src.generation_profiles.contract import GenerationProfile

    exact = ModelIdentityResolver().resolve("flux-2-klein-4b-fp8.safetensors")
    old = replace(exact.identity, exact_profile={**exact.identity.exact_profile, "version": 1})
    profile = GenerationProfile(
        "old",
        1,
        KIND_LEARNING,
        "Historical",
        old,
        {"steps": 4},
        executable_profile=old.exact_profile,
        provenance={"historical": True},
    )
    plan = plan_application(profile=profile, match=None, working={"steps": 8}, policy=exact.policy)
    assert plan.status == "identity_conflict" and not plan.changes
    model = publication.resolver.resolve("test").identity
    assert not match_learning_identity(model, replace(model, sha256=None)).applies


def test_registry_sha_requires_current_file_fingerprint(tmp_path):
    from src.assets import AssetKind, AssetRegistry
    from src.generation_profiles.identity import RegistryShaLookup

    path = tmp_path / "checkpoint.safetensors"
    path.write_bytes(b"original checkpoint fixture")
    fingerprint = path.stat()
    registry = AssetRegistry(webui_root=tmp_path, cache_path=tmp_path / "registry.json")
    registry._loaded = True
    registry._entries[str(path.resolve())] = {
        "sha256": "a" * 64,
        "size": fingerprint.st_size,
        "mtime_ns": fingerprint.st_mtime_ns,
    }
    record = SimpleNamespace(
        sha256="a" * 64, locations=[SimpleNamespace(kind=AssetKind.CHECKPOINT, path=path)]
    )
    registry.cached_snapshot = lambda: SimpleNamespace(records_for=lambda _: [record])
    lookup = RegistryShaLookup(registry)
    assert lookup(path.name) == "a" * 64
    path.write_bytes(b"changed bytes under the same checkpoint filename")
    assert lookup(path.name) is None


def test_duplicate_findings_in_an_older_revision_are_not_republished(publication):
    rows = records(publication)
    first = publication.publish(
        publication.evaluate(rows, "test"), rows, "test", name="First", confirmed=True
    )
    changed = copy.deepcopy(rows)
    changed[1]["metadata"]["user_rating"] = 1
    second = publication.publish(
        publication.evaluate(changed, "test"),
        changed,
        "test",
        name="Second",
        confirmed=True,
        lineage=first.ref,
    )
    old_findings = publication.evaluate(rows, "test")
    assert old_findings.already_published(second.ref).ref == first.ref
    with pytest.raises(ValueError, match="already published"):
        publication.publish(
            old_findings, rows, "test", name="Duplicate", confirmed=True, lineage=second.ref
        )


def test_incompatible_learning_startup_reference_remains_readable_but_not_applied(publication):
    rows = records(publication)
    saved = publication.publish(
        publication.evaluate(rows, "test"), rows, "test", name="Saved", confirmed=True
    )
    catalog = GenerationProfileService(publication.store, publication.resolver, research=lambda: ())
    catalog.select("test", saved.ref, {"steps": 20})
    catalog.save_startup_defaults(
        "test", {"steps": 30}, stage_flags={"txt2img": True}, stage_settings={}
    )
    current = publication.resolver.resolve("test")
    catalog._resolver = ModelIdentityResolver(
        policy_resolver=lambda _: current.policy, sha_lookup=lambda _: None
    )
    defaults, plan = catalog.plan_startup(available_models=["test"])
    assert defaults is not None and plan.model_name is None and plan.issues
    assert publication.store.load(saved.ref) == saved


def test_one_experiment_cannot_claim_two_different_frozen_variables(publication):
    steps = records(publication)
    cfg = records(publication, (4, 6, 8))
    rewrite_snapshots(cfg, lambda s: s.update(variable_under_test="CFG Scale"))
    for row in cfg:
        meta = row["metadata"]
        meta["job_id"] += "-cfg"
        meta["image_path"] += "-cfg"
        meta["variable_under_test"] = "CFG Scale"
        meta["frozen_experiment"]["executed_config"]["txt2img"].update(
            steps=20, cfg_scale=meta["variant_value"]
        )
    assert not publication.evaluate(steps + cfg, "test").ready
