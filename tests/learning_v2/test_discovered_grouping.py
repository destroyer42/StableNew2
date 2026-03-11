# Tests: Learning subsystem
# PR: PR-CORE-LEARN-040 — Output scanner and grouping engine

"""Tests for GroupingEngine — group-key and candidate grouping contract."""

from __future__ import annotations

from src.learning.discovered_grouping import GroupingEngine, _find_varying_fields, _group_key
from src.learning.output_scan_models import ScanRecord
from src.learning.discovered_review_models import STATUS_WAITING_REVIEW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    seed: int = 42,
    cfg: float = 7.0,
    sampler: str = "Euler",
    steps: int = 20,
    model: str = "sd_xl_base_1.0",
    stage: str = "txt2img",
    artifact_path: str = "",
) -> ScanRecord:
    rec = ScanRecord(
        artifact_path=artifact_path or f"output/run1/img_{seed}.png",
        stage=stage,
        model=model,
        sampler=sampler,
        steps=steps,
        cfg_scale=cfg,
        seed=seed,
        positive_prompt="a fantasy knight",
        negative_prompt="",
    )
    # Compute derived keys manually
    from src.learning.output_scanner import _normalize_prompt, _sha256_short, _dedupe_key
    import json

    def _ph(pos: str, neg: str) -> str:
        combined = f"{_normalize_prompt(pos)}||{_normalize_prompt(neg)}"
        return _sha256_short(combined.encode("utf-8"))

    rec.prompt_hash = _ph(rec.positive_prompt, rec.negative_prompt)
    rec.input_lineage_key = ""
    # Build dedupe key
    key_parts = {
        "stage": rec.stage,
        "model": rec.model,
        "sampler": rec.sampler,
        "scheduler": rec.scheduler,
        "steps": rec.steps,
        "cfg_scale": rec.cfg_scale,
        "seed": rec.seed,
        "width": rec.width,
        "height": rec.height,
        "positive_prompt": _normalize_prompt(rec.positive_prompt),
        "negative_prompt": _normalize_prompt(rec.negative_prompt),
    }
    raw = json.dumps(key_parts, sort_keys=True).encode("utf-8")
    rec.dedupe_key = _sha256_short(raw)
    return rec


def _make_group(n: int = 4, *, cfg_values: list[float] | None = None) -> list[ScanRecord]:
    """Create a group with varying cfg_scale by default."""
    cfgs = cfg_values or [4.0, 6.0, 7.0, 8.0]
    return [_make_record(seed=i + 100, cfg=cfgs[i % len(cfgs)]) for i in range(n)]


# ---------------------------------------------------------------------------
# Varying field detection
# ---------------------------------------------------------------------------


def test_find_varying_fields_detects_cfg_scale():
    records = _make_group()
    varying = _find_varying_fields(records)
    assert "cfg_scale" in varying


def test_find_varying_fields_detects_steps():
    records = [_make_record(seed=i, steps=s) for i, s in enumerate([10, 20, 30, 40])]
    varying = _find_varying_fields(records)
    assert "steps" in varying


def test_find_varying_fields_excludes_seed_only():
    records = [_make_record(seed=i) for i in range(4)]
    varying = _find_varying_fields(records)
    # Seeds vary, but seed must not appear in SEED_ONLY exclusion test
    # No other fields vary so result should be empty
    assert "seed" not in varying
    # cfg and steps are constant so not in varying either
    assert not varying


def test_find_varying_fields_excludes_seed():
    records = [_make_record(seed=i, cfg=7.0) for i in range(4)]
    varying = _find_varying_fields(records)
    assert "seed" not in varying


def test_find_varying_fields_single_record_empty():
    assert _find_varying_fields([_make_record()]) == []


def test_find_varying_fields_empty_empty():
    assert _find_varying_fields([]) == []


# ---------------------------------------------------------------------------
# GroupingEngine.build_candidates
# ---------------------------------------------------------------------------


def test_engine_basic_eligible_group():
    engine = GroupingEngine()
    records = _make_group()
    candidates = engine.build_candidates(records)
    assert len(candidates) == 1
    assert candidates[0].status == STATUS_WAITING_REVIEW
    assert "cfg_scale" in candidates[0].varying_fields


def test_engine_group_below_minimum_rejected():
    engine = GroupingEngine(min_group_size=3)
    records = _make_group(2)  # Only 2
    candidates = engine.build_candidates(records)
    assert len(candidates) == 0


def test_engine_seed_only_group_rejected():
    engine = GroupingEngine()
    records = [_make_record(seed=i) for i in range(5)]
    candidates = engine.build_candidates(records)
    # Only seed varies — must be rejected
    assert len(candidates) == 0


def test_engine_assigns_group_id():
    engine = GroupingEngine()
    records = _make_group()
    candidates = engine.build_candidates(records)
    assert candidates[0].group_id.startswith("disc-")


def test_engine_group_id_is_deterministic():
    engine = GroupingEngine()
    records = _make_group()
    id1 = engine.build_candidates(records)[0].group_id
    id2 = engine.build_candidates(records)[0].group_id
    assert id1 == id2


def test_engine_skips_existing_group_ids():
    engine = GroupingEngine()
    records = _make_group()
    candidates = engine.build_candidates(records)
    existing_id = candidates[0].group_id
    candidates2 = engine.build_candidates(records, existing_group_ids={existing_id})
    assert len(candidates2) == 0


def test_engine_deduplication_within_records():
    """Duplicate ScanRecords (same dedupe_key) should create only one item."""
    engine = GroupingEngine()
    base = _make_record(seed=1, cfg=7.0)
    dup = _make_record(seed=1, cfg=7.0)
    assert base.dedupe_key == dup.dedupe_key
    group = [base, dup] + [_make_record(seed=i, cfg=float(i)) for i in range(2, 5)]
    candidates = engine.build_candidates(group)
    if candidates:
        # The duplicated item should be collapsed
        assert len(candidates[0].items) <= len(group) - 1


def test_engine_groups_separate_prompts_separately():
    """Records from different prompts must not be grouped together."""
    engine = GroupingEngine()

    from src.learning.output_scanner import _normalize_prompt, _sha256_short
    def _ph(pos: str) -> str:
        combined = f"{_normalize_prompt(pos)}||"
        return _sha256_short(combined.encode("utf-8"))

    records_a = _make_group(4)
    records_b = []
    for i in range(4):
        r = _make_record(seed=i + 50, cfg=float(i + 1))
        r.positive_prompt = "a space explorer"
        r.prompt_hash = _ph("a space explorer")
        records_b.append(r)

    candidates = engine.build_candidates(records_a + records_b)
    assert len(candidates) == 2


def test_engine_builds_items_for_each_record():
    engine = GroupingEngine()
    records = _make_group(4)
    candidates = engine.build_candidates(records)
    assert len(candidates[0].items) == 4


def test_engine_item_ids_are_unique():
    engine = GroupingEngine()
    records = _make_group(5)
    candidates = engine.build_candidates(records)
    item_ids = [i.item_id for i in candidates[0].items]
    assert len(set(item_ids)) == 5


def test_engine_candidates_are_ordered_deterministically():
    engine = GroupingEngine()
    records1 = _make_group(4)
    records2 = list(reversed(_make_group(4)))
    c1 = engine.build_candidates(records1)
    c2 = engine.build_candidates(records2)
    assert [c.group_id for c in c1] == [c.group_id for c in c2]
