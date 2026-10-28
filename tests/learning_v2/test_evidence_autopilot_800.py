"""Catalog-driven offline proposals and unchanged canonical Learning preparation."""

import copy
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.generation_profiles.evidence_baseline import baseline_catalog
from src.generation_profiles.evidence_catalog import Claim, EvidenceCatalog, EvidenceRecord
from src.gui.controllers.model_evidence_proposals import preview_selected, save_drafts
from src.learning.evidence_autopilot import (
    EvidenceProposalPlanner,
    ProposalPlanningContext,
    describe,
    selected_proposals,
)
from src.learning.experiment_store import LearningExperimentStore
from tests.learning_v2.test_profile_publication_660 import make_publication


@pytest.fixture
def context(tmp_path):
    resolver = make_publication(tmp_path).resolver
    target = resolver.resolve("test.safetensors")
    baseline = {
        "txt2img": {
            "model": "test.safetensors",
            "vae": "",
            "steps": 30,
            "cfg_scale": 7.0,
            "sampler_name": "Euler",
            "scheduler": "Normal",
            "width": 1024,
            "height": 1024,
            "seed": 42,
        },
        "backend_options": {"image": {"backend_id": "forge_webui"}},
    }
    resources = {
        "models": ["test.safetensors"],
        "samplers": ["Euler", "DPM++ 2M"],
        "schedulers": ["Normal", "Karras", "Automatic"],
        "vaes": [],
    }
    return ProposalPlanningContext(target, baseline_catalog(), baseline, resources)


def plan(context):
    return EvidenceProposalPlanner().plan(context)


def drafts(result):
    return [p for p in result.proposals if p.runnable]


def test_refs_keep_only_highest_matching_identity_scope(context):
    claim = Claim(
        "steps", 50, "community", "https://example.com/source", "2026-10-28", "hypothesis", "low"
    )
    catalog = EvidenceCatalog(
        (
            EvidenceRecord(
                "correct",
                "checkpoint",
                "sdxl",
                "exact",
                (claim,),
                sha256=context.target.identity.sha256,
            ),
            EvidenceRecord("wrong-hash", "checkpoint", "sdxl", "exact", (claim,), sha256="b" * 64),
            EvidenceRecord("wrong-family", "checkpoint", "sd15", "family", (claim,)),
            EvidenceRecord("superseded", "checkpoint", "sdxl", "family", (claim,)),
        )
    )
    selected = next(
        p
        for p in drafts(plan(replace(context, catalog=catalog)))
        if p.document["variable"] == "steps"
    )
    assert [r["record_id"] for r in selected.document["evidence_refs"]] == ["correct"]


def test_learning_bounds_refuse_step180_before_selection(context):
    claim = Claim(
        "steps", 180, "community", "https://example.com/source", "2026-10-28", "hypothesis", "low"
    )
    catalog = EvidenceCatalog(
        (EvidenceRecord("too-large", "checkpoint", "sdxl", "family", (claim,)),)
    )
    proposal = next(
        p
        for p in plan(replace(context, catalog=catalog)).proposals
        if p.document["variable"] == "steps"
    )
    assert not proposal.runnable
    assert not proposal.document["default_selected"]


@pytest.mark.parametrize("placement", ["positive", "negative", "global", "structured"])
def test_delayed_adapter_context_refused_without_side_effects(
    context, monkeypatch, tmp_path, placement
):
    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver",
        lambda: make_publication(tmp_path).resolver,
    )
    result = plan(context)
    selected = (drafts(result)[0].proposal_id,)
    token = "<lora:unverified:1>"
    args = {"prompt": "a lighthouse"}
    if placement == "positive":
        args["prompt"] += token
    elif placement == "negative":
        args["negative"] = "<lyco:unverified:1>"
    elif placement == "global":
        args["global_policy"] = {
            "positive_enabled": True,
            "positive_text": token,
            "negative_enabled": False,
            "negative_text": "",
        }
    else:
        args["prompt_metadata"] = {"selected_prompt_loras": [{"name": "unverified", "weight": 1}]}
    with pytest.raises(ValueError, match="Adapter"):
        preview_selected(result, selected, context, **args)
    assert not (tmp_path / "experiments").exists()


def test_fixed_execution_intent_is_private_preserved_and_revision_bound(
    context, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver",
        lambda: make_publication(tmp_path).resolver,
    )
    baseline = copy.deepcopy(context.baseline)
    baseline.update(
        prompt_optimizer={"enabled": False}, pipeline={"output_dir": "C:/private/results"}
    )
    context = replace(context, baseline=baseline)
    result = plan(context)
    assert "private" not in result.canonical_json
    chosen = (drafts(result)[0].proposal_id,)
    store = LearningExperimentStore(tmp_path / "experiments")
    save_drafts(result, chosen, context, store)
    saved = store.load_session(chosen[0])["current_experiment"]["baseline_config"]
    assert saved["prompt_optimizer"] == {"enabled": False}
    [(state, records, _)] = preview_selected(result, chosen, context, prompt="a lighthouse")
    assert state.current_experiment.baseline_config["prompt_optimizer"] == {"enabled": False}
    assert all(r.config["prompt_optimizer"] == {"enabled": False} for r in records)
    assert all(r.config["pipeline"]["output_dir"] == "C:/private/results" for r in records)
    changed = copy.deepcopy(baseline)
    changed["prompt_optimizer"]["enabled"] = True
    with pytest.raises(ValueError, match="stale"):
        preview_selected(result, chosen, replace(context, baseline=changed), prompt="a lighthouse")
    changed = copy.deepcopy(baseline)
    changed["prompt"] = "another delayed prompt"
    assert plan(replace(context, baseline=changed)).plan_id == result.plan_id


def test_catalog_drives_candidates_without_folklore_or_prompt(context, monkeypatch):
    for name in ("socket.socket", "urllib.request.urlopen", "subprocess.Popen", "builtins.open"):
        monkeypatch.setattr(name, Mock(side_effect=AssertionError("Planning must be pure")))
    original = copy.deepcopy(context.baseline)
    result = plan(context)
    assert result.canonical_json == plan(context).canonical_json
    by_variable = {p.document["variable"]: p for p in drafts(result)}
    assert set(by_variable) == {"cfg_scale", "steps"}
    assert by_variable["cfg_scale"].document["values"] == [7.0, 5.0]
    assert by_variable["steps"].document["values"] == [30, 50]
    assert all(type(v) is int for v in by_variable["steps"].document["values"])
    assert all(p.document["expected_images"] == 12 for p in by_variable.values())
    assert all(p.document["default_selected"] for p in by_variable.values())
    assert context.baseline == original
    assert all(not p.document.get("prompt") for p in result.proposals)
    empty = plan(replace(context, catalog=EvidenceCatalog()))
    assert not drafts(empty)
    assert "fallback recipe" in empty.canonical_json


def test_planning_drops_private_baseline_data_and_does_not_mutate_it(context):
    source = copy.deepcopy(context.baseline)
    source.update(prompt="private prompt", output_dir="C:/private/images", ratings=[5])
    source["txt2img"].update(prompt="private stage prompt", negative_prompt="private negative")
    result = plan(replace(context, baseline=source))
    assert "private" not in result.canonical_json
    assert source["prompt"] == "private prompt"


@pytest.mark.parametrize("damage", ["catalog", "resources", "baseline", "identity"])
def test_context_drift_refuses_before_any_write(context, tmp_path, damage):
    accepted = plan(context)
    if damage == "catalog":
        changed = replace(context, catalog=EvidenceCatalog())
    elif damage == "resources":
        changed = replace(context, resources={**context.resources, "samplers": ["Euler"]})
    elif damage == "baseline":
        baseline = copy.deepcopy(context.baseline)
        baseline["txt2img"]["steps"] = 31
        changed = replace(context, baseline=baseline)
    else:
        changed = replace(
            context,
            target=replace(
                context.target, identity=replace(context.target.identity, sha256="b" * 64)
            ),
        )
    store = LearningExperimentStore(tmp_path / "experiments")
    with pytest.raises(ValueError, match="stale"):
        save_drafts(accepted, tuple(p.proposal_id for p in drafts(accepted)), changed, store)
    assert store.list_handles() == []


def test_save_is_create_only_and_never_rewrites_edited_or_completed_draft(context, tmp_path):
    result = plan(context)
    chosen = (drafts(result)[0].proposal_id,)
    store = LearningExperimentStore(tmp_path / "experiments")
    assert save_drafts(result, chosen, context, store) == chosen
    payload = store.load_session(chosen[0])
    payload["current_experiment"]["name"] = "operator edited"
    payload["plan"] = [{"job_id": "completed-job", "status": "completed"}]
    store.save_session(display_name="Edited", experiment_id=chosen[0], payload=payload)
    before = (store.root / chosen[0] / "session.json").read_bytes()
    save_drafts(result, chosen, context, LearningExperimentStore(store.root))
    assert (store.root / chosen[0] / "session.json").read_bytes() == before


@pytest.mark.parametrize("values,total", [((5,), 12), ((5, 6), 15), ((5, 6, 8), 20)])
def test_designs_keep_distinct_source_alternatives_and_common_seed_policy(context, values, total):
    claims = tuple(
        Claim(
            "cfg_scale",
            v,
            "community",
            "https://example.com/research",
            "2026-10-28",
            "hypothesis",
            "low",
        )
        for v in values
    )
    catalog = EvidenceCatalog(
        (EvidenceRecord("candidates", "checkpoint", "sdxl", "family", claims),)
    )
    [proposal] = drafts(plan(replace(context, catalog=catalog)))
    assert proposal.document["expected_images"] == total
    assert proposal.document["values"][0] == 7.0
    assert proposal.document["seed_policy"]["requested_base_seed"] == 42
    confirmation = drafts(plan(replace(context, catalog=catalog, samples=10)))[0]
    assert confirmation.document["expected_images"] == 20


def test_blocked_and_metadata_rows_cannot_enter_drafts(context):
    result = plan(context)
    blocked = next(p for p in result.proposals if not p.runnable)
    assert not blocked.document["default_selected"]
    with pytest.raises(ValueError, match="blocked"):
        selected_proposals(result, (blocked.proposal_id,))
    assert "No qualifying alternate" in describe(blocked) or "Evidence:" in describe(blocked)


def test_preview_uses_learning_freeze_and_compiler_without_execution_binding(
    context, monkeypatch, tmp_path
):
    resolver = make_publication(tmp_path).resolver
    monkeypatch.setattr("src.generation_profiles.identity.ModelIdentityResolver", lambda: resolver)
    result = plan(context)
    chosen = tuple(p.proposal_id for p in drafts(result))
    outputs = preview_selected(result, chosen, context, prompt="a lighthouse at dusk")
    assert len(outputs) == 2
    for state, records, summary in outputs:
        frozen = json.loads(state.current_experiment.execution_snapshot_json)
        assert frozen["prompt_text"] == "a lighthouse at dusk"
        assert frozen["evidence_proposal"]["contract"] == "qualification_proposal/2"
        assert len(records) == 2
        assert summary.total_images == 12
        assert all(record.job_id for record in records)
        assert all(not variant.job_id for variant in state.plan)
        if frozen["variable_under_test"] == "Steps":
            assert all(type(value) is int for value in frozen["variant_values"])
        assert frozen["variant_values"][0] == (
            7.0 if frozen["variable_under_test"] == "CFG Scale" else 30
        )


def test_exact_specificity_wins_and_same_specificity_conflicts_stay(context):
    def claim(value, classification="community"):
        return Claim(
            "cfg_scale",
            value,
            classification,
            "https://example.com/evidence",
            "2026-10-28",
            "candidate",
            "medium",
        )

    family = EvidenceRecord("family", "checkpoint", "sdxl", "family", (claim(2),))
    exact = EvidenceRecord(
        "exact",
        "checkpoint",
        "sdxl",
        "exact",
        (claim(5), claim(6)),
        sha256=context.target.identity.sha256,
    )
    [proposal] = drafts(plan(replace(context, catalog=EvidenceCatalog((family, exact)))))
    assert set(proposal.document["values"]) == {7.0, 5, 6}
    assert {r["record_id"] for r in proposal.document["evidence_refs"]} == {"exact"}
    assert proposal.document["expected_images"] == 15


@pytest.mark.parametrize(
    "damage", ["fractional_steps", "missing_sampler", "absolute_resource", "unverified_model"]
)
def test_negative_inputs_never_invent_replacements(context, damage):
    if damage == "fractional_steps":
        baseline = copy.deepcopy(context.baseline)
        baseline["txt2img"]["steps"] = 30.5
        with pytest.raises(ValueError, match="whole number"):
            plan(replace(context, baseline=baseline))
    elif damage == "absolute_resource":
        with pytest.raises(ValueError, match="Absolute"):
            plan(
                replace(context, resources={**context.resources, "samplers": ["C:/private/Euler"]})
            )
    elif damage == "missing_sampler":
        result = plan(replace(context, resources={**context.resources, "samplers": []}))
        assert not drafts(result)
        assert "unavailable" in result.canonical_json.lower()
    else:
        result = plan(
            replace(
                context,
                target=replace(
                    context.target, identity=replace(context.target.identity, sha256=None)
                ),
            )
        )
        assert not drafts(result)
        assert all(p.document["priority"] == "P0" for p in result.proposals)


def test_v2_diagnostic_export_and_legacy_details_remain_readable(context):
    from src.generation_profiles.evidence_report import build_report, render_report
    from src.learning.evidence_proposals import propose

    result = plan(context)
    report = build_report(
        {"assets": [], "complete": False}, context.catalog, [context.target], result.proposals
    )
    assert "qualification_proposal/2" in json.dumps(report)
    assert "Proposed experiments" in render_report(report)
    legacy = propose(
        context.catalog,
        context.target,
        context.baseline,
        variable="steps",
        values=(30, 50),
        prompt="legacy prompt",
        resources=context.resources,
    )
    assert legacy.document["contract"] == "qualification_proposal/1"
    assert "unavailable" in describe(legacy)
