"""Hermetic evidence catalog, source boundary and complete draft-to-SQLite journey."""

import copy
import io
import json
import shutil
from dataclasses import replace
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from src.assets.evidence_census import CensusBudget, refresh_census
from src.assets.registry import AssetRegistry
from src.generation_profiles.contract import KIND_RESEARCH
from src.generation_profiles.evidence_baseline import baseline_catalog
from src.generation_profiles.evidence_catalog import Claim, EvidenceCatalog, EvidenceRecord
from src.generation_profiles.evidence_refresh import EvidenceRefresh, Lookup, public_get
from src.generation_profiles.evidence_report import build_report, export_report, validate_report
from src.generation_profiles.identity import ModelIdentityResolver, RegistryShaLookup
from src.generation_profiles.service import GenerationProfileService
from src.generation_profiles.store import GenerationProfileStore
from src.image_backends.model_policy import RegistryFamilyLookup
from src.learning.evidence_proposals import (
    evidence_gaps,
    freeze_proposal_context,
    propose,
    save_proposal,
    validate_proposal_snapshot,
)
from src.learning.experiment_execution import thaw_snapshot
from src.learning.experiment_store import LearningExperimentStore
from src.learning.setting_evidence import compare_settings
from src.pipeline.backend_setting_evidence import setting_values
from tests.assets.checkpoint_fixtures import checkpoint, tensor_checkpoint


@pytest.fixture
def world(tmp_path):
    root = tmp_path / "webui"
    path = tensor_checkpoint(root / "models/Stable-diffusion/nested/model.safetensors")
    registry = AssetRegistry(webui_root=root, cache_path=tmp_path / "registry.json")
    census = refresh_census(registry, verify=True)
    resolver = ModelIdentityResolver(
        family_lookup=RegistryFamilyLookup(registry), sha_lookup=RegistryShaLookup(registry)
    )
    target = resolver.resolve(path.name)
    assert target.identity.sha256 and target.identity.family == "sdxl"
    config = {
        "txt2img": {
            "model": path.name,
            "vae": "",
            "steps": 30,
            "cfg_scale": 5.0,
            "sampler_name": "Euler",
            "scheduler": "Normal",
            "width": 1024,
            "height": 1024,
            "seed": 42,
        },
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "adetailer_enabled": False,
            "upscale_enabled": False,
            "refiner_enabled": False,
        },
    }
    resources = {
        "models": [path.name],
        "samplers": ["Euler", "DPM++ 2M"],
        "schedulers": ["Normal", "Karras"],
        "vaes": [],
    }
    return SimpleNamespace(
        root=root,
        path=path,
        registry=registry,
        census=census,
        resolver=resolver,
        target=target,
        config=config,
        resources=resources,
    )


def proposal(world, **kwargs):
    args = {
        "variable": "steps",
        "values": (30, 50),
        "prompt": "a lighthouse at dusk",
        "resources": world.resources,
    }
    args.update(kwargs)
    return propose(baseline_catalog(), world.target, world.config, **args)


def test_census_roots_duplicates_renames_and_unchanged(world):
    shutil.copyfile(world.path, world.path.with_name("renamed.safetensors"))
    checkpoint(world.root / "embeddings/active.safetensors")
    checkpoint(world.root / "models/embeddings/inactive.safetensors")
    checkpoint(world.root / "models/VAE-approx/approx.safetensors")
    checkpoint(world.root / "models/ESRGAN/upscaler.safetensors")
    census = refresh_census(world.registry, verify=True)
    assert census["counts"]["checkpoint"] == 2
    assert any(row["duplicate_of"] for row in census["assets"])
    assert (
        next(r for r in census["assets"] if "embeddings/inactive" in r["relative"])["active"]
        is False
    )
    again = refresh_census(world.registry, verify=True)
    assert again["hash_bytes"] == 0
    assert again["unchanged"] >= 4
    assert str(world.root) not in json.dumps(census)


def test_sidecar_changes_refresh_without_model_rehash(world):
    world.path.with_suffix(".civitai.info").write_text(json.dumps({"baseModel": "SD 1.5"}))
    census = refresh_census(world.registry, verify=True)
    assert census["hash_bytes"] == 0
    assert census["assets"][0]["compatibility"] == "conflicting"
    target = world.resolver.resolve(world.path.name)
    assert evidence_gaps(baseline_catalog(), target)[0].priority == "P0"


def test_changed_bytes_invalidate_exact_identity(world):
    old = world.target.identity.sha256
    with world.path.open("ab") as stream:
        stream.write(b"changed")
    assert world.registry.verified_sha256(world.path) is None
    refresh_census(world.registry, verify=True)
    assert world.resolver.resolve(world.path.name).identity.sha256 != old


@pytest.mark.parametrize(
    "budget",
    [CensusBudget(max_assets=0), CensusBudget(max_hash_bytes=0), CensusBudget(max_seconds=0)],
)
def test_bounded_partial_scan(world, budget):
    world.registry = AssetRegistry(webui_root=world.root, cache_path=world.root / "fresh.json")
    result = refresh_census(world.registry, verify=True, budget=budget)
    assert not result["complete"] and result["hash_bytes"] == 0


def test_cancel_and_corrupt_headers(world):
    assert refresh_census(world.registry, cancelled=lambda: True)["cancelled"]
    world.path.with_name("bad.safetensors").write_bytes(b"bad")
    bad = refresh_census(world.registry, verify=True)
    assert any(
        r["header"]["error"] for r in bad["assets"] if r["relative"].endswith("bad.safetensors")
    )


def test_observed_boundary_cannot_escape_or_hash_wrong_kind(world):
    observed = world.registry.observe().files[0]
    with pytest.raises(ValueError, match="outside"):
        world.registry.refresh(
            observed_files=(replace(observed, path=str(world.root.parent / "other.safetensors")),)
        )
    with pytest.raises(ValueError, match="root"):
        world.registry.refresh(observed_files=(replace(observed, kind="lora"),))
    with pytest.raises(ValueError, match="changed"):
        world.registry.refresh(observed_files=(replace(observed, size=observed.size + 1),))


def claim(field="steps", value=50, **kwargs):
    return Claim(
        field,
        value,
        kwargs.get("classification", "exact_publisher"),
        kwargs.get("source", "https://huggingface.co/publisher/model"),
        "2026-10-27",
        "Exact model-card recommendation",
        kwargs.get("confidence", "high"),
        kwargs.get("caveat", ""),
    )


def exact(world, claims):
    return EvidenceRecord(
        "exact-test", "checkpoint", "sdxl", "exact", tuple(claims), world.target.identity.sha256
    )


def test_catalog_roundtrip_conflicts_and_exact_precedence(world, tmp_path):
    catalog = EvidenceCatalog(
        (*baseline_catalog().records, exact(world, [claim(), claim("cfg_scale", 6.0)]))
    )
    assert (
        EvidenceCatalog.from_document(json.loads(json.dumps(catalog.to_document()))).revision
        == catalog.revision
    )
    assert EvidenceCatalog.load(catalog.save_revision(tmp_path)).revision == catalog.revision
    assert catalog.exact_profile(world.target.identity).settings["steps"] == 50
    assert catalog.exact_profile(replace(world.target.identity, sha256="b" * 64)) is None
    conflicted = EvidenceCatalog((exact(world, [claim(value=30), claim(value=50)]),))
    assert (
        next(r for r in conflicted.coverage(world.target.identity) if r.field == "steps").status
        == "conflicting"
    )
    assert conflicted.exact_profile(world.target.identity) is None


def test_hypotheses_never_become_executable_defaults(world):
    for confidence in ("medium", "low", "unknown"):
        catalog = EvidenceCatalog((exact(world, [claim(confidence=confidence)]),))
        assert catalog.exact_profile(world.target.identity) is None
    sdxl = {c.field: c for c in baseline_catalog().coverage(world.target.identity)}
    assert sdxl["width"].status == "recommended"
    assert sdxl["steps"].status == "hypothesis" and sdxl["scheduler"].status == "hypothesis"
    assert sdxl["vae"].status == "unavailable"


@pytest.mark.parametrize(
    "source",
    [
        "http://localhost/x",
        "file:///C:/private",
        "https://host/x?token=secret",
        "https://user:pw@host/x",
        "local:../../private",
    ],
)
def test_reject_untrusted_citations(source):
    with pytest.raises(ValueError):
        claim(source=source)


def test_accessories_and_unverified_identity_refuse_defaults(world):
    with pytest.raises(ValueError, match="Accessories"):
        EvidenceRecord("lora", "lora", "sdxl", "exact", (claim(),), "a" * 64)
    unknown = replace(world.target, identity=replace(world.target.identity, sha256=None))
    assert evidence_gaps(baseline_catalog(), unknown)[0].priority == "P0"
    assert evidence_gaps(baseline_catalog(), world.target, variant="turbo")[0].status == "blocked"


def test_exact_research_preference_preserves_favorites_startup(world, tmp_path, monkeypatch):
    catalog = EvidenceCatalog((*baseline_catalog().records, exact(world, [claim()])))
    profile = catalog.exact_profile(world.target.identity)
    monkeypatch.setattr(
        "src.generation_profiles.evidence_catalog.catalog_profiles", lambda: (profile,)
    )
    store = GenerationProfileStore(tmp_path / "profiles")
    service = GenerationProfileService(store, world.resolver)
    assert service.preferred_ref(world.target.identity)[0] == profile.ref
    assert service.get(profile.ref).kind == KIND_RESEARCH
    assert store.favorite_for(world.target.identity.key) is None
    assert store.load_startup_document() is None
    assert not any(
        o.profile.profile_id == profile.profile_id
        for o in service.options_for(replace(world.target.identity, sha256=None))
    )


@pytest.mark.parametrize(
    "alternatives,samples,total",
    [((30, 50), 6, 12), ((30, 40, 50), 5, 15), ((30, 40, 50, 60), 5, 20), ((30, 50), 10, 20)],
)
def test_deterministic_pilot_designs(world, alternatives, samples, total):
    first = proposal(world, values=alternatives, samples=samples)
    assert first.runnable, first.document["blocked_reasons"]
    assert first.document == proposal(world, values=alternatives, samples=samples).document
    assert first.document["expected_images"] == total
    assert first.document["seed_policy"]["requested_sample_count"] == samples
    assert world.target.identity.sha256[:8] in first.document["name"]
    assert len(first.proposal_id) < 64 and "/" not in first.proposal_id


def test_missing_resources_and_wrong_control_block_without_substitution(world):
    p = proposal(world, variable="sampler", values=("Euler", "Absent sampler"))
    assert not p.runnable and p.document["values"][1] == "Absent sampler"
    assert not proposal(world, values=(20, 50)).runnable
    assert not proposal(world, resources=None).runnable
    with pytest.raises(ValueError, match="Pilot"):
        proposal(world, samples=50)


def test_save_reopen_deduplicate_and_preserve_edited_draft(world, tmp_path):
    p = proposal(world)
    store = LearningExperimentStore(tmp_path / "experiments")
    identity = save_proposal(p, store)
    payload = store.load_session(identity)
    assert not payload["plan"] and not payload["current_experiment"]["execution_snapshot_json"]
    payload["current_experiment"]["description"] = "operator edited"
    store.save_session(display_name="edited", payload=payload, experiment_id=identity)
    assert save_proposal(p, store) == identity
    assert len(store.list_handles()) == 1
    assert (
        LearningExperimentStore(store.root).load_session(identity)["current_experiment"][
            "description"
        ]
        == "operator edited"
    )


@pytest.mark.parametrize(
    "service,identifier,revision",
    [
        ("huggingface", "../secret", "a" * 40),
        ("huggingface", "org/model", "main"),
        ("civitai", "private/path", ""),
        ("else", "a" * 64, ""),
    ],
)
def test_lookup_identifiers_refuse_paths_and_moving_refs(service, identifier, revision):
    with pytest.raises(ValueError):
        Lookup(service, identifier, revision)


def test_opt_in_lookup_offline_cancel_rate_limits_and_candidates():
    requests = []
    lookup = Lookup("civitai", "a" * 64)
    refresh = EvidenceRefresh(
        lambda url: requests.append(url) or {"id": 7, "files": [{"hashes": {"SHA256": "a" * 64}}]},
        clock=lambda: 0,
    )
    with pytest.raises(ValueError, match="Confirm"):
        refresh.refresh(lookup, confirmed=False)
    assert not requests
    assert refresh.refresh(lookup, confirmed=True, cancelled=lambda: True)["status"] == "cancelled"
    result = refresh.refresh(lookup, confirmed=True)
    assert result["hash_matched"] and result["status"] == "candidate"
    assert "no executable defaults" in result["recommendation_status"]
    assert refresh.refresh(lookup, confirmed=True)["status"] == "rate_limited"
    assert requests == [lookup.url]
    assert (
        EvidenceRefresh(lambda _: (_ for _ in ()).throw(OSError())).refresh(lookup, confirmed=True)[
            "status"
        ]
        == "unavailable"
    )
    assert EvidenceRefresh(lambda _: []).refresh(lookup, confirmed=True)["status"] == "unavailable"
    failure = HTTPError(lookup.url, 429, "rate limited", {"Retry-After": "99999"}, None)
    assert (
        EvidenceRefresh(lambda _: (_ for _ in ()).throw(failure)).refresh(lookup, confirmed=True)[
            "retry_after_seconds"
        ]
        == 3600
    )


def test_public_get_response_bound_and_inflight_cancel(monkeypatch):
    from src.generation_profiles import evidence_refresh as module

    class Response(io.BytesIO):
        def read1(self, amount):
            return self.read(amount)

    opener = SimpleNamespace(open=lambda *a, **kw: Response(b'{"sha":"' + b"a" * 40 + b'"}'))
    monkeypatch.setattr(module, "build_opener", lambda *_: opener)
    assert public_get(Lookup("huggingface", "org/model", "a" * 40).url)["sha"] == "a" * 40
    with pytest.raises(TimeoutError):
        public_get(Lookup("civitai", "a" * 64).url, cancelled=lambda: True)
    opener.open = lambda *a, **kw: Response(b"x" * (module.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="limit"):
        public_get(Lookup("civitai", "a" * 64).url)


def test_report_roundtrip_redacts_paths_and_prompts(world, tmp_path):
    p = proposal(world)
    report = build_report(world.census, baseline_catalog(), [world.target], [p])
    assert validate_report(json.loads(json.dumps(report))) == report
    machine, readable = export_report(tmp_path, report)
    assert validate_report(json.loads(machine.read_text(encoding="utf-8"))) == report
    assert "Model Evidence Catalog" in readable.read_text(encoding="utf-8")
    assert "a lighthouse at dusk" not in machine.read_text(encoding="utf-8")
    assert str(world.root) not in machine.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        validate_report({**report, "contract": "model_evidence_report/999"})


def test_selected_compiled_dispatch_and_reported_are_separate(world):
    snap = {
        "baseline_config": world.config,
        "variable_under_test": "Steps",
        "evidence_proposal": {"coverage": []},
    }
    variant = SimpleNamespace(
        param_value=50, executed_config={"txt2img": {**world.config["txt2img"], "steps": 50}}
    )
    rows = compare_settings(snap, variant, {"steps": 50}, {})
    assert next(r for r in rows if r["tested"])["status"] == "not recorded"
    rows = compare_settings(snap, variant, {"steps": 50}, {"steps": 50})
    assert next(r for r in rows if r["tested"])["status"] == "matched"
    assert (
        compare_settings(snap, variant, {"steps": 50}, {"steps": 30})[2]["status"]
        == "conflicting evidence"
    )
    assert setting_values({"steps": True, "prompt": "secret", "width": -1}) == {}


def test_proposal_preview_and_canonical_sqlite_admission(world, tmp_path, monkeypatch):
    from src.controller.job_service import JobService
    from src.gui.learning_state import LearningState
    from src.learning.execution_controller import LearningExecutionController
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from tests.controller.test_job_service_unit import FakeRunner
    from tests.learning_v2.test_learning_independent_baseline_650 import Bench

    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver", lambda: world.resolver
    )
    p = proposal(world)
    store = LearningExperimentStore(tmp_path / "experiments")
    identity = save_proposal(p, store)
    state = LearningState.from_dict(store.load_session(identity))
    bench = Bench(tmp_path, resources=world.resources)
    bench.controller.learning_state = state
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(
        JobQueue(repository=repository), runner=FakeRunner(), require_normalized_records=True
    )
    bench.controller.execution_controller = LearningExecutionController(state, service)
    experiment = state.current_experiment
    bench.controller.build_plan(experiment)
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    assert snapshot["evidence_proposal"]["proposal_id"] == identity
    assert snapshot["images_per_value"] == 6
    bench.controller._learning_enabled = True
    bench.controller.run_plan()
    jobs = repository.list_job_models()
    assert len(jobs) == 2
    assert sum(job._normalized_record.workload.images_per_prompt for job in jobs) == 12
    before = [job.job_id for job in jobs]
    bench.controller.run_plan()
    assert [job.job_id for job in repository.list_job_models()] == before
    # Changed bytes after Preview cannot be compiled into a second experiment.
    with world.path.open("ab") as stream:
        stream.write(b"replace")
    with pytest.raises(ValueError, match="bytes changed"):
        from src.learning.model_policy_service import compile_variant

        compile_variant(copy.deepcopy(world.config), experiment)


def test_context_cannot_relabel_variable_or_change_frozen_seed(world):
    p = proposal(world)
    snapshot = {
        "stage": "txt2img",
        "variable_under_test": "Steps",
        "variant_values": [30, 50],
        "baseline_config": world.config,
        "prompt_text": p.document["prompt"],
        "negative_prompt_text": "",
        "seed_policy": p.document["seed_policy"],
        "images_per_value": 6,
        "model_identity": world.target.identity.to_dict(),
    }
    snapshot["evidence_proposal"] = freeze_proposal_context(
        p.document, snapshot, "operator hypothesis"
    )
    validate_proposal_snapshot(snapshot)
    for key, value in (
        ("variable_under_test", "CFG Scale"),
        ("seed_policy", {"requested_base_seed": 999}),
        ("baseline_config", {"txt2img": {"vae": "foreign"}}),
    ):
        changed = {**snapshot, key: value}
        with pytest.raises(ValueError):
            validate_proposal_snapshot(changed)


def test_create_only_store_cannot_overwrite_results(tmp_path):
    store = LearningExperimentStore(tmp_path)
    store.save_session(
        display_name="original", payload={"results": ["keep"]}, experiment_id="evidence760-test"
    )
    with pytest.raises(FileExistsError):
        store.save_session(
            display_name="replacement",
            payload={"results": []},
            experiment_id="evidence760-test",
            create_only=True,
        )
    assert store.load_session("evidence760-test") == {"results": ["keep"]}
    assert store.list_handles()[0].display_name == "original"


def test_unc_export_and_publication_require_reported_proof(world):
    from src.generation_profiles.evidence_report import _redact
    from src.learning.setting_evidence import require_rating_proof

    assert "private" not in _redact(r"\\nas\private\rob\model.safetensors")
    snap = {"evidence_proposal": proposal(world).document, "variable_under_test": "Steps"}
    with pytest.raises(ValueError, match="proof"):
        require_rating_proof({"variant_value": 50}, snap)
    row = {
        "field": "steps",
        "tested": True,
        "status": "matched",
        "selected": 50,
        "compiled_njr": 50,
        "backend_reported": 50,
    }
    meta = {
        "variant_value": 50,
        "qualification_tested_value_verified": True,
        "qualification_setting_evidence": [row],
    }
    require_rating_proof(meta, snap)
    with pytest.raises(ValueError, match="conflicts"):
        require_rating_proof({**meta, "variant_value": 30}, snap)


@pytest.mark.parametrize(
    "readback,valid", [({}, False), ({"steps": 30}, True), ({"steps": 50}, False)]
)
def test_completion_readback_controls_eligibility(world, readback, valid):
    from src.gui.learning_state import LearningExperiment, LearningVariant
    from src.learning.experiment_execution import freeze_snapshot
    from src.learning.experiment_reconciliation import completion_evidence

    p = proposal(world)
    snapshot = {
        "evidence_proposal": p.document,
        "baseline_config": world.config,
        "variable_under_test": "Steps",
        "seed_policy": p.document["seed_policy"],
    }
    experiment = LearningExperiment(
        experiment_id="test",
        stage="txt2img",
        variable_under_test="Steps",
        execution_snapshot_json=freeze_snapshot(snapshot),
    )
    variant = LearningVariant(
        param_value=30, executed_config=world.config, variant_id="control", job_id="job"
    )
    result = {
        "all_seeds": [42, 43, 44, 45, 46, 47],
        "variants": [{"backend_reported_settings": readback, "dispatched_settings": {"steps": 30}}],
    }
    evidence = completion_evidence(experiment, variant, result)
    assert evidence.execution_metadata["controlled_evidence_valid"] is valid
    assert evidence.execution_metadata["qualification_tested_value_verified"] is valid


def test_catalog_pointer_digest_and_selected_context_redaction(world, tmp_path, monkeypatch):
    from src.generation_profiles import evidence_catalog as module
    from src.generation_profiles.evidence_report import _redact

    monkeypatch.setattr(module, "operator_catalog_root", lambda: tmp_path)
    (tmp_path / "selected.json").write_text(json.dumps({"revision": "a" * 64}))
    (tmp_path / ("a" * 64 + ".json")).write_text(json.dumps(baseline_catalog().to_document()))
    with pytest.raises(ValueError, match="mismatch"):
        module.load_operator_catalog()
    assert _redact(
        {
            "selected_context": {
                "baseline_config": world.config,
                "prompt_text": "private",
                "negative_prompt_text": "private negative",
            }
        }
    ) == {"selected_context": {}}


def test_verified_proposal_ratings_require_explicit_learning_publication(tmp_path):
    from src.learning.experiment_execution import freeze_snapshot, snapshot_digest
    from tests.learning_v2.test_profile_publication_660 import make_publication, records

    service = make_publication(tmp_path)
    source = records(service)
    snapshot = copy.deepcopy(source[0]["metadata"]["frozen_experiment"]["snapshot"])
    snapshot.update(
        prompt_text="frozen synthetic prompt", negative_prompt_text="", images_per_value=5
    )
    snapshot["seed_policy"]["requested_sample_count"] = 5
    target = service.resolver.resolve("test.safetensors")
    draft = propose(
        baseline_catalog(),
        target,
        snapshot["baseline_config"],
        variable="steps",
        values=(20, 30, 40),
        prompt=snapshot["prompt_text"],
        samples=5,
        resources={
            "models": ["test.safetensors"],
            "samplers": ["Euler"],
            "schedulers": ["Normal"],
            "vaes": [],
        },
    )
    assert draft.runnable, draft.document["blocked_reasons"]
    snapshot["evidence_proposal"] = freeze_proposal_context(
        draft.document, snapshot, "Before Run hypothesis"
    )
    rows = []
    for source_row in source:
        for sample in range(5):
            row = copy.deepcopy(source_row)
            metadata = row["metadata"]
            value = metadata["variant_value"]
            metadata["image_path"] += f"-{sample}"
            metadata["frozen_experiment"].update(
                snapshot=snapshot,
                snapshot_sha256=snapshot_digest(freeze_snapshot(snapshot)),
                actual_all_seeds=[42, 43, 44, 45, 46],
            )
            metadata.update(
                qualification_tested_value_verified=True,
                qualification_setting_evidence=[
                    {
                        "field": "steps",
                        "tested": True,
                        "status": "matched",
                        "selected": value,
                        "compiled_njr": value,
                        "backend_reported": value,
                    }
                ],
            )
            rows.append(row)
    findings = service.evaluate(rows, "test.safetensors", experiment_id="experiment-1")
    assert findings.settings == {"steps": 30}
    assert not service.store.root.exists()
    with pytest.raises(ValueError, match="confirmation"):
        service.publish(
            findings, rows, "test.safetensors", name="Qualified synthetic finding", confirmed=False
        )
    published = service.publish(
        findings, rows, "test.safetensors", name="Qualified synthetic finding", confirmed=True
    )
    assert published.settings == {"steps": 30} and published.revision == 1
