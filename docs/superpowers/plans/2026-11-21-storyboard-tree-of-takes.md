# Storyboard Tree of Takes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A top-level Storyboard tab where the operator grows a scene as a tree of takes: pick a handoff frame anywhere
in a clip's stitched cut, queue 1-6 parallel takes or a 1-6 row sequential chain from it, and get a frame-exact stitched
MP4 per take.

**Architecture:** Each take is a sequence job under a new plan policy, `stablenew.video_sequence_policy.v2`. The plan
carries a storyboard link: the storyboard id, one take id per segment, the parent, and an optional lead-in. The lead-in is
the parent cut's first K frames, pinned by a hashed cut manifest. Segment 0 starts from the exact handoff PNG. The
executor prepends the lead-in at assembly and writes the take's cut manifest after every committed segment. A
submission service crosses `JobService.submit_njrs` once per Continue. The tab is presentation only: it reads status
back from the repository and runs every file or admission step on a registered worker.

**Tech Stack:** Python 3.14, Tk (ttk), Pillow, the existing ASM-332 assembly engine (FFmpeg), pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-storyboard-tree-of-takes-design.md` (approved by Rob 2026-11-21). Read it
with this plan. Section numbers below such as "spec 7.6" point there.

**Execution class:** Architectural. **Model recommendation:** Claude Code Opus 5.5 High (Codex: GPT-6 Astra High).

## Global Constraints

- Canonical path only: `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr ->
  Handler -> Artifacts/History`. One `JobService.submit_njrs` call per Continue. No queue watcher and no follow-up
  submission when a job finishes.
- `SEQUENCE_POLICY_VERSION = "stablenew.video_sequence_policy.v1"` is unchanged. New:
  `SEQUENCE_POLICY_VERSION_V2 = "stablenew.video_sequence_policy.v2"`. A v1 plan's `_content()` is byte-identical to
  today. The `storyboard` key never appears in v1 content, not even as `null`.
- Schemas: cut manifest `stablenew.storyboard_cut.v1`; storyboard file `stablenew.storyboard-tree.v1`.
- Storyboard files: `%LOCALAPPDATA%/StableNew/storyboard_trees/<storyboard_id>.json`. Writes go through
  `src/utils/atomic_io.py`, with revision compare-and-swap, an exclusive `.lock` and a 2 MB cap. Malformed or
  future-schema files are never rewritten.
- Decoded root frames: `<output root>/storyboards/<storyboard_id>/root/`. Lead-in frames are referenced, never copied.
- 1-6 rows per Continue. The per-job cap stays at 12 segments and 972 generated frames. The lead-in does not count.
- A take with a lead-in starts from the exact handoff PNG: no source preparation and no substitute file. Admission
  refuses a handoff PNG that is not exactly the target size.
- Takes never inherit `interpolation` (RIFE). Sequences keep refusing smoothing. A smoothed root uses its generated
  frames at the workflow's fps.
- v2 plans: assembly always on, colour matching off.
- Ratchets: strict mypy with zero errors in new modules (`$PY tools/ci/run_mypy_ratchet.py`), ruff ratchets, no new
  blind `except`, no raw or daemon threads. GUI file and admission work runs through `build_edit_work_runner`
  (`src/gui/view_contracts/edit_work_runner.py`).
- `src/controller/app_controller.py` gains zero net lines (ceiling 5,010 in
  `tools/ci/controller_surface_baseline.json`). New controller modules stay under 600 lines. No ceiling is raised.
- No repository table or schema change. No file is moved or deleted by the storyboard: Drop only hides.
- Display is 1-based and storage is 0-based. `handoff_index` is the 0-based index of the handoff frame in the parent
  cut, so `K = handoff_index + 1`.
- Fixed copy (spec 7.2, 7.3, 7.9): `Storyboard` (tab); `New from clip or image…`; `Open…`; `Show dropped (N)`;
  `Export cut…`; `Continue from this frame`; `Compare these side by side`; `Preview`; `Queue N takes`;
  `Queue chain of N`; `+ Add row (up to 6)`; `Write with AI…` (disabled, reason `AI Assist is not set up` or the
  readiness record's reason); `Continue in Storyboard`; `not encoded`; `frames missing or changed`; `replay of <label>`;
  `This clip was smoothed to {smoothed_fps} fps. The storyboard uses its {n} generated frames at {fps} fps.`;
  `Only the smoothed video is left; its in-between frames were invented, so it cannot be continued exactly`.
- Interpreter: `PY=C:/Users/rob/projects/StableNew-main/.venv/Scripts/python.exe`. Run every command from the
  worktree root.
- Branches: PR A on `claude/vid-story-380-execution`, cut from `claude/vid-story-380-design` (it carries the spec and
  this plan). PR B on `claude/vid-story-380-workspace`, stacked on PR A. Work in worktrees, never the live
  `StableNew-main` checkout. No push, merge or PR creation without Rob's go-ahead (`AGENTS.md` section 5).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Parent frames moved after a take was made** (for example a Review Discard moved them to `output/_archive`):
   Continue from that take or any descendant is refused with `frames missing or changed` and the first bad path. Its
   stitched MP4 still plays. Tests: Task A8 `test_submit_refuses_when_a_lead_in_frame_was_moved` and Task B1
   `test_projection_flags_missing_parent_frames_but_keeps_the_mp4`.
2. **Two windows editing one storyboard while a Continue is in flight:** a stale revision is refused before anything
   is queued. Test: Task A8 `test_stale_revision_is_refused_before_submission`.
3. **A handoff frame inside an earlier shot of a sequential chain:** the parent becomes the take that owns that frame,
   and the lead-in is that take's cut prefix. Tests: Task B2 `test_frame_in_a_middle_chain_take_branches_from_it` and
   Task A8 `test_branch_from_a_middle_chain_take_uses_its_prefix`.
4. **A take cancelled during assembly:** it has a manifest but no MP4. Its card says `not encoded` and offers Resume,
   and Continue from its frames works. Tests: Task A5
   `test_cancel_during_assembly_leaves_a_complete_cut_manifest` and Task B1
   `test_projection_reports_not_encoded_with_manifest`.
5. **A storyboard file close to the 2 MB cap:** the pending-take write is refused with the size message and nothing
   is queued. Test: Task A8 `test_oversize_storyboard_refuses_before_submission`.

## File Structure

PR A (execution):

| File | Responsibility |
|---|---|
| `src/video/sequence_plan.py` (modify) | v2 policy constant, `StoryboardLeadIn`, `StoryboardPlanLink`, plan field `storyboard`, v2 validation |
| `src/video/storyboard_cut.py` (create) | Cut manifest model, read/write, lead-in verification, take-manifest construction |
| `src/video/workflow_source_preparation.py` (modify) | `passthrough_declared_workflow_source`: an exact-size source record with no re-save |
| `src/video/video_workflow_njr_builder.py` (modify) | `freeze_inputs(..., exact_source=False)` |
| `src/video/sequence_admission.py` (modify) | `freeze_sequence_plan(..., storyboard=None)` builds v2 plans and runs lead-in checks |
| `src/video/sequence_job_build.py` (create) | `build_sequence_njr`: the shared core of sequence NJR building |
| `src/controller/video_sequence_controller.py` (modify) | `build_sequence_job` delegates to `build_sequence_njr` |
| `src/video/sequence_ledger.py` (modify) | optional `cut_manifest` record |
| `src/pipeline/video_sequence_executor.py` (modify) | lead-in verification, per-segment cut manifest, lead-in prepend at assembly |
| `src/video/storyboard_root.py` (create) | Root preparation from a clip job or a still image |
| `src/video/storyboard_tree.py` (create) | Storyboard file model, labels, cut ownership arithmetic |
| `src/video/storyboard_tree_store.py` (create) | Atomic, revision-checked storage of storyboard files |
| `src/controller/storyboard_submission_service.py` (create) | Create roots, preview, submit, reconcile |
| `src/controller/video_workflow_controller.py` (modify) | Exposes `storyboards` (the service) |
| `src/video/storyboard_history.py` (modify) | Refuses v2 plans in "Create Storyboard from Sequence" |

PR B (workspace):

| File | Responsibility |
|---|---|
| `src/video/storyboard_projection.py` (create) | Read-only status, outputs and frame-health projection per take |
| `src/video/storyboard_frame_cache.py` (create) | Bounded LRU of downscaled frames and thumbnails (Tk-free, worker-side) |
| `src/gui/view_contracts/storyboard_tree_contract.py` (create) | Tk-free tab state: columns, selection, slider, rows, button states |
| `src/gui/views/storyboard_tab_frame_v2.py` (create) | The tab: toolbar, columns, viewer, Continue panel |
| `src/gui/widgets/storyboard_columns_v2.py` (create) | Shot columns with take cards (canvas, lazy thumbnails) |
| `src/gui/widgets/storyboard_viewer_v2.py` (create) | Frame viewer with the whole-cut slider and join ticks |
| `src/gui/views/storyboard_compare_window_v2.py` (create) | Compare-only synchronized playback of sibling clips |
| `src/gui/main_window_v2.py` (modify) | Registers the tab after Video Workflow |
| `src/gui/controllers/video_workspace_handoff.py` (modify) | `route_job_to_storyboard` |
| `src/gui/job_history_panel_v2.py`, `src/gui/views/video_workflow_recent_outputs_panel_v2.py`, `src/gui/views/video_workflow_tab_frame_v2.py` (modify) | `Continue in Storyboard` entries |

---

## Part A: PR A, execution

### Task A1: Sequence plan policy v2

**Files:**
- Modify: `src/video/sequence_plan.py`
- Test: `tests/video/test_pr_vid_story_380_plan.py`

**Interfaces:**
- Produces:
  - `SEQUENCE_POLICY_VERSION_V2: Final = "stablenew.video_sequence_policy.v2"`
  - `SEQUENCE_POLICIES: Final = (SEQUENCE_POLICY_VERSION, SEQUENCE_POLICY_VERSION_V2)`
  - `ROOT_PARENT: Final = "root"`
  - `@dataclass(frozen=True, slots=True) class StoryboardLeadIn`: `manifest_path: str`, `manifest_sha256: str`,
    `frame_count: int` (K), `handoff_path: str`, `handoff_sha256: str`. Methods `to_dict() -> dict[str, Any]` and
    `from_dict(data: Mapping[str, Any]) -> StoryboardLeadIn`, strict keys.
  - `@dataclass(frozen=True, slots=True) class StoryboardPlanLink`: `storyboard_id: str`, `parent_id: str` (a take id
    or `ROOT_PARENT`), `take_ids: tuple[str, ...]` (one per segment), `handoff_index: int | None`,
    `lead_in: StoryboardLeadIn | None = None`. Methods `to_dict` and `from_dict`, strict keys.
  - `SequencePlan.storyboard: StoryboardPlanLink | None = None` and `"storyboard"` added to `PLAN_KEYS`.
    `_content()` adds `"storyboard"` only when `self.storyboard is not None`.

- [ ] **Step 1: Capture the v1 golden digest before touching the module**

Build the fixture plan below (`_v1_fixture()`, three video_workflow segments, policy v1, source set) on unmodified code
and print `plan.plan_sha256()`. Paste the hex into the test as `V1_GOLDEN`.

- [ ] **Step 2: Write the failing tests**

```python
def test_v1_digest_is_unchanged():
    plan = _v1_fixture()
    assert plan.plan_sha256() == V1_GOLDEN
    assert "storyboard" not in plan._content()
    assert SequencePlan.from_dict(plan.to_dict()).plan_sha256() == V1_GOLDEN

def test_v2_round_trips_and_the_digest_covers_the_link():
    plan = _v2_fixture(lead_in=True)
    again = SequencePlan.from_dict(plan.to_dict())
    assert again == plan and again.storyboard.take_ids == ("t1",)
    other = replace(plan, storyboard=replace(plan.storyboard, take_ids=("t2",)))
    assert other.plan_sha256() != plan.plan_sha256()

@pytest.mark.parametrize("mutate, message", [
    (lambda p: replace(p, storyboard=None), "v2 plan needs its storyboard link"),
    (lambda p: replace(p, policy_version=SEQUENCE_POLICY_VERSION), "only a v2 plan carries a storyboard link"),
    (lambda p: replace(p, storyboard=replace(p.storyboard, take_ids=())), "one take id per segment"),
    (lambda p: replace(p, segments=(replace(p.segments[0], overlap_frames=0),)), "segment 0 overlaps the handoff frame by 1"),
    (lambda p: replace(p, source={"path": "x.png", "sha256": "0" * 64}), "segment 0 starts from the handoff frame"),
    (lambda p: replace(p, assembly=replace(p.assembly, enabled=False)), "a storyboard take is always assembled"),
    (lambda p: replace(p, color_match=SequenceColorMatch(enabled=True)), "colour matching is off for storyboard takes"),
    (lambda p: replace(p, policy_version="stablenew.video_sequence_policy.v3"), "unsupported sequence execution policy"),
])
def test_v2_validation_refusals(mutate, message):
    assert any(message in error for error in mutate(_v2_fixture(lead_in=True)).validate())

def test_v2_without_lead_in_keeps_segment_zero_overlap_zero():
    plan = _v2_fixture(lead_in=False)
    assert plan.validate() == [] and plan.segments[0].overlap_frames == 0

def test_take_ids_must_be_unique():
    plan = _v2_fixture(lead_in=False, segments=2)
    bad = replace(plan, storyboard=replace(plan.storyboard, take_ids=("t1", "t1")))
    assert any("take ids must be unique" in e for e in bad.validate())
```

`_v2_fixture(lead_in, segments=1)` builds a v2 plan whose `source` equals the lead-in handoff `{path, sha256}`, with
segment 0 overlap 1 when `lead_in` is true, and `take_ids` of `t1..tN`.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_plan.py -q`
Expected: FAIL on import of `SEQUENCE_POLICY_VERSION_V2`.

- [ ] **Step 4: Implement the policy in `src/video/sequence_plan.py`**

`validate()` accepts either policy. With v2: the link must be present; `len(take_ids) == len(segments)`; ids unique
and non-empty; assembly enabled; colour matching off. With a lead-in: `frame_count >= 1`, both SHA-256 values well
formed, `handoff_index == frame_count - 1`, `source == {"path": handoff_path, "sha256": handoff_sha256}`, and segment 0
`overlap_frames == 1`. Without a lead-in: segment 0 overlap 0. With v1, a link is refused. In `_validate_segment`, the
"segment 0 has nothing before it to overlap" rule applies unless the plan is v2 with a lead-in. Add the new names to
`__all__`.

- [ ] **Step 5: Run the new tests and the existing sequence suites**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_plan.py tests/video/test_pr_vid_seq_330_admission.py tests/video/test_pr_vid_seq_330_executor.py tests/video/test_pr_vid_seq_330_checkpoint.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit** (`git add` both files; message `PR-VID-STORY-380: sequence plan policy v2 with storyboard link`)

### Task A2: Cut manifest

**Files:**
- Create: `src/video/storyboard_cut.py`
- Test: `tests/video/test_pr_vid_story_380_cut_manifest.py`

**Interfaces:**
- Consumes: `StoryboardLeadIn` (A1); `FileRecord` from `src/video/sequence_ledger.py`; `atomic_write_json` from
  `src/utils/atomic_io.py`.
- Produces:
  - `CUT_MANIFEST_SCHEMA: Final = "stablenew.storyboard_cut.v1"`; `BASIS_NATIVE`, `BASIS_DECODED` (re-exported from
    `sequence_ledger`).
  - `class CutManifestError(ValueError)`.
  - `@dataclass(frozen=True, slots=True) class CutFrame`: `path: str`, `sha256: str`.
  - `@dataclass(frozen=True, slots=True) class CutRange`: `owner: str`, `start: int`, `end: int` (inclusive),
    `basis: str`, `trimmed: int` (leading generated frames dropped: 1 for a take after overlap, 0 for the root).
  - `@dataclass(frozen=True, slots=True) class CutManifest`: `fps: int`, `width: int`, `height: int`,
    `frames: tuple[CutFrame, ...]`, `ranges: tuple[CutRange, ...]`, `lead_in_frames: int`, `job_id: str | None`.
    Methods: `validate() -> list[str]`, `to_dict()`, `from_dict(data)`, `owner_of(index: int) -> CutRange`,
    `segment_ranges() -> tuple[CutRange, ...]` (ranges starting at or after `lead_in_frames`, in order),
    `prefix(count: int) -> CutManifest` (the first `count` frames, with ranges truncated).
  - `write_cut_manifest(path: Path, manifest: CutManifest) -> CutFrame` (atomic; returns the path and the file's
    SHA-256).
  - `read_cut_manifest(path: str | Path, *, expected_sha256: str | None = None) -> CutManifest`.
  - `verify_lead_in(lead_in: StoryboardLeadIn, *, target_size: tuple[int, int], fps: int, hash_file: FileHasher) ->
    CutManifest`: the admission checks of spec 7.6. Hashes the manifest file and the handoff PNG, and checks that every
    lead-in frame exists. It does not hash every frame.
  - `lead_in_frames(lead_in: StoryboardLeadIn, *, hash_file: FileHasher) -> list[Path]`: re-hashes every one of the K
    frames against the manifest (executor, before assembly).
  - `take_manifest(*, lead_in: CutManifest | None, segments: Sequence[tuple[str, Sequence[FileRecord], int, str]],
    fps: int, width: int, height: int, job_id: str) -> CutManifest`: each segment tuple is `(take_id, frames,
    overlap_frames, basis)`. It appends each segment's kept frames (overlap dropped) as one range with
    `trimmed = overlap_frames`.

- [ ] **Step 1: Write the failing tests**

```python
def test_round_trip_and_hash(tmp_path):
    manifest = _manifest(tmp_path, frames=5, ranges=[("root", 0, 4)])
    written = write_cut_manifest(tmp_path / "cut.json", manifest)
    assert read_cut_manifest(written.path, expected_sha256=written.sha256) == manifest

def test_ranges_must_cover_every_frame_in_order(tmp_path):
    gap = _manifest(tmp_path, frames=5, ranges=[("root", 0, 2), ("t1", 4, 4)])
    assert any("cover every frame" in e for e in gap.validate())

def test_owner_of_and_prefix(tmp_path):
    m = _manifest(tmp_path, frames=6, ranges=[("root", 0, 2), ("t1", 3, 5)])
    assert m.owner_of(4).owner == "t1"
    assert m.prefix(4).ranges == (CutRange("root", 0, 2, "native", 0), CutRange("t1", 3, 3, "native", 1))

def test_read_refuses_a_changed_file(tmp_path):
    written = write_cut_manifest(tmp_path / "cut.json", _manifest(tmp_path, frames=2, ranges=[("root", 0, 1)]))
    with pytest.raises(CutManifestError, match="changed since it was recorded"):
        read_cut_manifest(written.path, expected_sha256="0" * 64)

@pytest.mark.parametrize("breakage, message", [
    ("manifest_hash", "cut manifest changed"),
    ("k_zero", "lead-in length must be 1"),
    ("k_too_big", "lead-in length must be 1"),
    ("handoff_not_last", "handoff frame is not frame K"),
    ("handoff_changed", "handoff frame changed"),
    ("size", "not the target size 832x480"),
    ("fps", "plays at 24 fps, not 16"),
    ("frame_missing", "lead-in frame is missing"),
])
def test_verify_lead_in_refusals(tmp_path, breakage, message):
    lead_in, target, fps = _broken_lead_in(tmp_path, breakage)
    with pytest.raises(CutManifestError, match=message):
        verify_lead_in(lead_in, target_size=target, fps=fps, hash_file=sha256_of)

def test_lead_in_frames_rehashes_every_frame(tmp_path):
    lead_in = _lead_in(tmp_path, k=3)
    _overwrite_png(lead_in, index=1)
    with pytest.raises(CutManifestError, match="lead-in frame 2 changed"):
        lead_in_frames(lead_in, hash_file=sha256_of)

def test_take_manifest_drops_overlap_and_labels_takes(tmp_path):
    parent = _manifest(tmp_path, frames=4, ranges=[("root", 0, 3)]).prefix(3)
    seg = _records(tmp_path, 5)
    m = take_manifest(lead_in=parent, segments=[("t1", seg, 1, "native")], fps=16, width=32, height=32, job_id="j")
    assert len(m.frames) == 3 + 4 and m.lead_in_frames == 3
    assert m.segment_ranges() == (CutRange("t1", 3, 6, "native", 1),)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_cut_manifest.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `src/video/storyboard_cut.py`**

Keys are strict, as in `sequence_plan._unknown`. `validate()` checks: the schema; fps within 1-120; positive size; at
least one frame; ranges contiguous from 0 to the last frame; `basis` in the two bases;
`0 <= lead_in_frames <= len(frames)`; every SHA-256 well formed. Failure messages name the file and the frame number,
1-based.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_cut_manifest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: cut manifest model and lead-in verification`)

### Task A3: Exact-size source pass-through

A14B reads its output size from `stage_config.source_preparation.target_dimensions`
(`src/video/workflow_catalog_wan_a14b.py` input bindings), so a take still needs a preparation record. The record must
point at the untouched handoff PNG.

**Files:**
- Modify: `src/video/workflow_source_preparation.py`, `src/video/video_workflow_njr_builder.py:474-528`
- Test: `tests/video/test_pr_vid_story_380_exact_source.py`

**Interfaces:**
- Produces:
  - `PASSTHROUGH_POLICY: Final = "exact_size_passthrough.v1"`
  - `passthrough_declared_workflow_source(*, source_path: str | Path, policy: Mapping[str, Any]) ->
    PreparedWorkflowSource`. It reads the image size, gets the declared target from `resolve_declared_target(policy, w,
    h)`, and raises `ValueError("The handoff frame is {w}x{h}, not the workflow's target size {tw}x{th}; it is used
    exactly as generated, never resized.")` when they differ. On success it returns a record with
    `prepared_image_path` and `original_source_path` both equal to the resolved source path, `policy=PASSTHROUGH_POLICY`,
    and equal `source_dimensions`, `target_dimensions` and `prepared_dimensions`. It writes nothing.
  - `VideoWorkflowNjrBuilder.freeze_inputs(..., exact_source: bool = False)`. When true and the workflow declares a
    preparation policy, it uses the pass-through instead of `prepare_declared_workflow_source`.

- [ ] **Step 1: Write the failing tests**

```python
def test_passthrough_writes_nothing_and_keeps_the_file(tmp_path):
    png = _png(tmp_path / "f.png", (832, 480))
    record = passthrough_declared_workflow_source(source_path=png, policy=A14B_POLICY)
    assert record.prepared_image_path == str(png.resolve())
    assert record.target_dimensions == {"width": 832, "height": 480}
    assert record.policy == PASSTHROUGH_POLICY
    assert not (tmp_path / "prepared_video_sources").exists()

def test_passthrough_refuses_a_wrong_size(tmp_path):
    with pytest.raises(ValueError, match="not the workflow's target size 832x480"):
        passthrough_declared_workflow_source(source_path=_png(tmp_path / "f.png", (830, 480)), policy=A14B_POLICY)

def test_freeze_inputs_exact_source_keeps_the_hash(tmp_path, a14b_builder):
    png = _png(tmp_path / "f.png", (832, 480))
    frozen = a14b_builder.freeze_inputs(png, _a14b_form(), prompt_per_segment=True, exact_source=True)
    assert frozen.prepared_source_path == str(png.resolve())
    assert frozen.prepared_source_sha256 == frozen.source_sha256
    assert frozen.source_preparation["target_dimensions"] == {"width": 832, "height": 480}
```

`A14B_POLICY` is read from the A14B catalog spec's `backend_defaults["source_preparation"]`. `a14b_builder` is a
`VideoWorkflowNjrBuilder` over the default registry with `output_dir_provider` set to `tmp_path`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_exact_source.py -q`
Expected: FAIL (name missing).

- [ ] **Step 3: Implement both changes**

Before choosing the policy string, grep `src` for readers of `source_preparation["policy"]` and the
`preparation_policy` metadata (`src/app/site_phone_followup.py`, `src/video/recent_video_outputs.py`). Confirm none of
them requires `cover_center_crop`. If one does, make it accept the pass-through, and add a test there.

- [ ] **Step 4: Run the tests and the builder's existing suites**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_exact_source.py tests/video -q -k "njr_builder or source_preparation or exact_source"`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: exact-size pass-through for handoff frames`)

### Task A4: v2 admission and the shared sequence NJR builder

**Files:**
- Modify: `src/video/sequence_admission.py:248-409`, `src/controller/video_sequence_controller.py:47-126`
- Create: `src/video/sequence_job_build.py`
- Test: `tests/video/test_pr_vid_story_380_admission.py`

**Interfaces:**
- Consumes: A1 types, A2 `verify_lead_in`, A3 `exact_source`.
- Produces:
  - `freeze_sequence_plan(..., storyboard: StoryboardPlanLink | None = None) -> SequencePlan`. With a link, the plan
    is v2 with `storyboard=link`, and assembly is forced on with colour matching off. If the intent asks for colour
    matching or disables assembly, it is refused with "a storyboard take is always assembled without colour
    matching". With a lead-in, segment 0's overlap is set to 1 (an explicit intent value other than 1 is refused), and
    `verify_lead_in(link.lead_in, target_size=target_size, fps=fps, hash_file=hash_file)` runs before the plan is
    built.
  - `build_sequence_njr(*, njr_builder: VideoWorkflowNjrBuilder, registry: Any, source_image_path: str, form_data:
    Mapping[str, Any], sequence_intent: Mapping[str, Any], continuity: Mapping[str, Any] | None = None, plan_origin:
    Mapping[str, Any] | None = None, storyboard: StoryboardPlanLink | None = None, exact_source: bool = False) ->
    VideoWorkflowBuild`. It holds today's body of `build_sequence_job` from the `unsupported_controls` check to
    `build_job`, without the `StoryboardDraft` checks. It also refuses `exact_source` when the lead-in's
    `handoff_sha256` differs from the frozen source hash.
  - `VideoSequenceControllerMixin.build_sequence_job` keeps its signature and draft checks and calls
    `build_sequence_njr`.

- [ ] **Step 1: Write the failing tests**

```python
def test_storyboard_link_freezes_a_v2_plan_starting_from_the_handoff(tmp_path, a14b_builder, registry):
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)   # 81 frames at 832x480, handoff = frame 78
    built = build_sequence_njr(
        njr_builder=a14b_builder, registry=registry, source_image_path=str(handoff),
        form_data=_a14b_form(), sequence_intent=_intent(rows=1),
        storyboard=_link(lead_in, take_ids=("t1",)), exact_source=True)
    plan = _plan_of(built.njr)
    assert plan.policy_version == SEQUENCE_POLICY_VERSION_V2
    assert plan.source == {"path": str(handoff.resolve()), "sha256": sha256_file(handoff)}
    assert plan.segments[0].overlap_frames == 1 and plan.assembly.enabled

def test_a_changed_handoff_is_refused_before_an_njr_exists(tmp_path, a14b_builder, registry):
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    _overwrite_png(handoff)
    with pytest.raises(SequencePlanError, match="handoff frame changed"):
        build_sequence_njr(njr_builder=a14b_builder, registry=registry, source_image_path=str(handoff),
                           form_data=_a14b_form(), sequence_intent=_intent(rows=1),
                           storyboard=_link(lead_in, take_ids=("t1",)), exact_source=True)

def test_storyboard_takes_refuse_smoothing(tmp_path, a14b_builder, registry):
    form = {**_a14b_form(), "interpolation": {"enabled": True, "multiplier": 2}}
    with pytest.raises(SequencePlanError, match="RIFE smoothing is not applied inside a sequence"):
        build_sequence_njr(njr_builder=a14b_builder, registry=registry, source_image_path=str(_still(tmp_path)),
                           form_data=form, sequence_intent=_intent(rows=1), storyboard=_link(None, take_ids=("t1",)))

def test_sequential_chain_uses_carry_last_frame(tmp_path, a14b_builder, registry):
    lead_in, handoff = _lead_in_from_root(tmp_path, k=81)
    built = build_sequence_njr(njr_builder=a14b_builder, registry=registry, source_image_path=str(handoff),
                               form_data=_a14b_form(), sequence_intent=_intent(rows=3),
                               storyboard=_link(lead_in, take_ids=("t1", "t2", "t3")), exact_source=True)
    plan = _plan_of(built.njr)
    assert [s.anchor_policy for s in plan.segments] == ["source", "carry_last_frame", "carry_last_frame"]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_admission.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement and refactor**

Move the shared body into `src/video/sequence_job_build.py` without changing behaviour. `build_sequence_job` keeps its
`StoryboardDraft` agreement checks before and after the call.

- [ ] **Step 4: Run the new tests and every existing sequence and storyboard suite**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_admission.py tests/video/test_pr_vid_seq_330_admission.py tests/pipeline/test_pr_vid_seq_330_canonical.py tests/pipeline/test_pr_vid_seq_330_prompts.py tests/video/test_storyboard_drafts.py tests/gui_v2/test_storyboard350_ui.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: v2 admission and shared sequence NJR builder`)

### Task A5: Ledger and executor

**Files:**
- Modify: `src/video/sequence_ledger.py:235-330`, `src/pipeline/video_sequence_executor.py`
- Test: `tests/video/test_pr_vid_story_380_executor.py`. Import `Segments`, `_executor`, `_fake_assemble`, `_png` and
  `_decoder` from `tests/video/test_pr_vid_seq_330_executor.py` rather than copying them.

**Interfaces:**
- Consumes: A1 plan link, A2 `take_manifest`, `write_cut_manifest`, `read_cut_manifest`, `lead_in_frames`.
- Produces:
  - `SequenceLedger.cut_manifest: Mapping[str, Any] | None = None` (`{"path", "sha256"}`). `to_dict()` emits the key
    only when it is set, so v1 ledgers keep today's shape.
  - Executor constant `CUT_MANIFEST_FILE_NAME: Final = "storyboard_cut.json"`, written at `run_dir /
    CUT_MANIFEST_FILE_NAME`.
  - `sequence_artifact_payload(...)` adds `"cut_manifest": {"path", "sha256"}` for v2 plans only.

Behaviour (spec 7.4, 7.6):
- `_begin`, for a v2 plan with a lead-in, at any start (fresh, resume or replay): reads the parent manifest with
  `expected_sha256=lead_in.manifest_sha256` and hashes the handoff PNG. A mismatch raises `SequencePlanError` before
  any dispatch.
- After `_begin` (when a resumed prefix exists) and after each committed segment, before `_persist()`: build the
  manifest with `take_manifest` (the lead-in is the parent manifest's `prefix(K)`; segments come from the ledger in
  order, labelled with `plan.storyboard.take_ids`, basis from each segment's frames). Write it and set
  `ledger.cut_manifest`.
- `_assemble_movie`, for a v2 plan with a lead-in: prepends `lead_in_frames(...)` to `frames`, and adds
  `{"segment": "lead_in", "frames_used": K}` first in `used`. Segment 0's overlap trim then drops its re-rendered
  handoff frame.

- [ ] **Step 1: Write the failing tests**

```python
def test_lead_in_is_prepended_and_the_handoff_appears_once(tmp_path):
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    calls, outcome = _run(tmp_path, plan)
    frames = calls.assembled_frames
    assert frames[:5] == lead_in.frame_paths and len(frames) == 5 + (plan.segments[0].frame_count - 1)
    assert frames.count(lead_in.frame_paths[4]) == 1

def test_cut_manifest_is_written_after_every_committed_segment(tmp_path):
    plan, _ = _v2_plan_with_lead_in(tmp_path, k=5, segments=3)
    with pytest.raises(RuntimeError):
        _run(tmp_path, plan, fail_on=2)
    manifest = read_cut_manifest(tmp_path / "run" / CUT_MANIFEST_FILE_NAME)
    assert [r.owner for r in manifest.segment_ranges()] == ["t1", "t2"]
    assert _ledger(tmp_path).cut_manifest["sha256"] == sha256_of(tmp_path / "run" / CUT_MANIFEST_FILE_NAME)

def test_cancel_during_assembly_leaves_a_complete_cut_manifest(tmp_path):
    plan, _ = _v2_plan_with_lead_in(tmp_path, k=5, segments=2)
    with pytest.raises(CancellationError):
        _run(tmp_path, plan, cancel_in_assembly=True)
    manifest = read_cut_manifest(tmp_path / "run" / CUT_MANIFEST_FILE_NAME)
    assert [r.owner for r in manifest.segment_ranges()] == ["t1", "t2"]

def test_a_changed_parent_manifest_stops_before_dispatch(tmp_path):
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    _touch_manifest(lead_in)
    with pytest.raises(SequencePlanError, match="cut manifest changed"):
        _run(tmp_path, plan)
    assert _segments_dispatched(tmp_path) == 0

def test_a_changed_lead_in_frame_stops_before_encoding(tmp_path):
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    calls = _run_with_hook(tmp_path, plan, before_assembly=lambda: _overwrite_png(lead_in.frame_paths[2]))
    assert calls.raised_message.startswith("lead-in frame 3 changed") and calls.assembled_frames is None

def test_resume_reverifies_the_lead_in_and_rewrites_the_manifest_for_the_prefix(tmp_path):
    plan, _ = _v2_plan_with_lead_in(tmp_path, k=5, segments=3)
    ledger_path, sha = _failed_parent_run(tmp_path, plan, fail_on=2)
    _run(tmp_path / "child", plan, resume=_resume_block(plan, ledger_path, sha, start=2))
    manifest = read_cut_manifest(tmp_path / "child" / "run" / CUT_MANIFEST_FILE_NAME)
    assert [r.owner for r in manifest.segment_ranges()] == ["t1", "t2", "t3"]

def test_v1_ledgers_and_artifacts_keep_their_shape(tmp_path):
    outcome, plan = _run_v1(tmp_path)
    assert "cut_manifest" not in outcome.ledger.to_dict()
    assert "cut_manifest" not in sequence_artifact_payload(outcome, plan)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_executor.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the ledger field and the executor behaviour above**

- [ ] **Step 4: Run the new tests and the existing executor, checkpoint and runner suites**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_executor.py tests/video/test_pr_vid_seq_330_executor.py tests/video/test_pr_vid_seq_330_checkpoint.py tests/pipeline/test_pr_vid_seq_330_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: lead-in assembly and per-segment cut manifests`)

### Task A6: Root preparation

**Files:**
- Create: `src/video/storyboard_root.py`
- Test: `tests/video/test_pr_vid_story_380_root.py`

**Interfaces:**
- Consumes: A2 manifest API; `plan_from_njr`, `sequence_stage_name`, `find_ledger_path` (`src/video/sequence_resume.py`);
  `locate_ledger` (`src/video/sequence_locator.py`); `read_ledger`; `decode_clip_to_frames`
  (`src/video/sequence_frames.py:152`); `workflow_segment_errors`; `frame_count_policy`.
- Produces:
  - `ROOT_SETTING_KEYS: Final = frozenset({"workflow_id", "workflow_version", "frame_count", "negative_prompt",
    "motion_profile", "output_route"})`
  - `class StoryboardRootError(ValueError)`
  - `@dataclass(frozen=True, slots=True) class SmoothingNote`: `smoothed_fps: int`, `fps: int`, `frame_count: int`,
    and `text() -> str` returning the fixed copy.
  - `@dataclass(frozen=True, slots=True) class PreparedRoot`: `kind: Literal["clip", "image"]`,
    `job_id: str | None`, `image_path: str | None`, `image_sha256: str | None`, `manifest: CutFrame | None` (path and
    SHA-256 of the root cut manifest; `None` for an image), `settings: Mapping[str, Any]` (only `ROOT_SETTING_KEYS`),
    `fps: int`, `width: int`, `height: int`, `smoothing: SmoothingNote | None`.
  - `prepare_clip_root(*, repository: Any, job_id: str, storyboard_id: str, output_root: str | Path, registry: Any,
    hash_file: FileHasher = sha256_of, decode_clip: ClipDecoder = decode_clip_to_frames, cancel_token: CancelToken |
    None = None) -> PreparedRoot`
  - `prepare_image_root(*, image_path: str | Path, settings: Mapping[str, Any], registry: Any) -> PreparedRoot`

Behaviour (spec 7.3), choosing by job kind:
- **v2 take job:** the root manifest is a copy of its cut manifest, re-ranged as one `root` range.
- **v1 sequence job:** frames come from its ledger, after overlap trim. When colour matching was used, the
  colour-matched copies are taken instead (exactly the frames encoded). One `root` range, basis `decoded` if any
  segment was decoded.
- **Frames-out single job:** use the natural-ordered `frame_paths` recorded in `video_workflow_artifact`. Cross-check
  them against the backend manifest's `frames_out` record (`frame_count`, and `frame_sha256_digest` = SHA-256 of the
  comma-joined per-frame hashes). Find the record under `_write_manifest`'s `provenance_extra` in
  `src/video/comfy_workflow_backend.py`.
- **Encoded-only job:** decode the unsmoothed Comfy file. When `interpolation` is recorded, that is the output path that
  is not the smoothed `primary_path`. Frames go to `<output_root>/storyboards/<storyboard_id>/root/`, basis `decoded`.
- **Any job with a recorded `interpolation`:** `smoothing` is set from that record's output fps. The generated frames
  are used.
- **Refused** (`StoryboardRootError`, with a readable reason): job missing or not completed; not a Comfy
  `video_workflow` job (native SVD included); the workflow fails `workflow_segment_errors`; frames missing or failing
  their hashes, naming the first bad path; a smoothed job whose generated frames and unsmoothed file are gone (the
  fixed copy).
- Nothing durable is published until success. Decoded frames go to a temporary sibling folder that is renamed into
  place.

- [ ] **Step 1: Write the failing tests**

```python
def test_frames_out_root_references_frames_without_copying(tmp_path):
    repo, job_id, frames = _frames_out_job(tmp_path, count=81, size=(832, 480))
    root = prepare_clip_root(repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG)
    manifest = read_cut_manifest(root.manifest.path, expected_sha256=root.manifest.sha256)
    assert [f.path for f in manifest.frames] == [str(p) for p in frames]
    assert not (tmp_path / "storyboards").exists() or not any((tmp_path / "storyboards").rglob("*.png"))

def test_smoothed_root_uses_generated_frames_and_notes_it(tmp_path):
    repo, job_id, _ = _frames_out_job(tmp_path, count=81, smoothed_fps=32)
    root = prepare_clip_root(repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG)
    assert root.fps == 16 and root.smoothing.text() == (
        "This clip was smoothed to 32 fps. The storyboard uses its 81 generated frames at 16 fps.")

def test_smoothed_root_with_only_the_smoothed_file_left_is_refused(tmp_path):
    repo, job_id, frames = _frames_out_job(tmp_path, count=81, smoothed_fps=32)
    _remove(frames, _unsmoothed_mp4(repo, job_id))
    with pytest.raises(StoryboardRootError, match="Only the smoothed video is left"):
        prepare_clip_root(repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG)

def test_a_mismatched_frames_out_digest_is_refused(tmp_path):
    repo, job_id, frames = _frames_out_job(tmp_path, count=81)
    _overwrite_png(frames[10])
    with pytest.raises(StoryboardRootError, match="do not match the hashes the backend recorded"):
        prepare_clip_root(repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG)

def test_sequence_root_uses_exactly_the_encoded_frames(tmp_path):
    repo, job_id, expected = _sequence_job(tmp_path, segments=2, color_matched=True)
    root = prepare_clip_root(repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG)
    assert [f.path for f in read_cut_manifest(root.manifest.path).frames] == expected

def test_encoded_only_root_decodes_the_unsmoothed_file(tmp_path):
    repo, job_id, decoder = _encoded_only_job(tmp_path, smoothed_fps=48)
    root = prepare_clip_root(repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path,
                             registry=REG, decode_clip=decoder)
    assert decoder.decoded_path == _comfy_original(repo, job_id)
    assert Path(read_cut_manifest(root.manifest.path).frames[0].path).parent == tmp_path / "storyboards" / ("s" * 32) / "root"

@pytest.mark.parametrize("kind, message", [
    ("svd", "native SVD"), ("not_completed", "has not completed"), ("driving_video", "driving video"),
    ("missing_frames", "frame is missing"),
])
def test_refusals(tmp_path, kind, message):
    repo, job_id = _refused_job(tmp_path, kind)
    with pytest.raises(StoryboardRootError, match=message):
        prepare_clip_root(repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG)

def test_image_root_keeps_only_root_settings(tmp_path):
    root = prepare_image_root(image_path=_png(tmp_path / "i.png", (832, 480)),
                              settings={**_a14b_settings(), "interpolation": {"enabled": True}}, registry=REG)
    assert root.kind == "image" and root.manifest is None and "interpolation" not in root.settings
```

Fakes: an in-memory repository with `get_job_model(job_id)` that returns a job carrying `_normalized_record` and
`result`, built with the same NJR builder the app uses (see `tests/helpers/make_video_313.py`).

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_root.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `src/video/storyboard_root.py`**

Read settings from the NJR's `video_workflow` stage config, at the keys where `VideoWorkflowNjrBuilder.build_job` writes
them. Never copy `interpolation`, `seed` or the experimental opt-in.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_root.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: storyboard root preparation`)

### Task A7: Storyboard file model and store

**Files:**
- Create: `src/video/storyboard_tree.py`, `src/video/storyboard_tree_store.py`
- Test: `tests/video/test_pr_vid_story_380_tree_store.py`

**Interfaces:**
- Produces, in `storyboard_tree.py`:
  - `TREE_SCHEMA: Final = "stablenew.storyboard-tree.v1"`, `MAX_ROWS: Final = 6`, `class StoryboardTreeError(ValueError)`
  - `@dataclass(frozen=True, slots=True) class TreeRoot`: `kind`, `job_id`, `image_path`, `image_sha256`,
    `manifest_path`, `manifest_sha256`, `settings: tuple[tuple[str, Any], ...]`, `fps`, `width`, `height`,
    `smoothing_text: str`.
  - `@dataclass(frozen=True, slots=True) class Take`: `take_id: str`, `parent_id: str`, `handoff_index: int | None`
    (`None` means the parent's last frame, used by chain positions above 0), `mode: Literal["parallel",
    "sequential"]`, `batch_id: str`, `chain_position: int`, `segment_index: int`, `prompt: str`,
    `negative_prompt: str`, `seed_intent: str`, `attempts: tuple[str, ...]`, `replay_of: str | None`,
    `mark: Literal["none", "kept", "dropped"]`, `created_at: str`.
  - `@dataclass(frozen=True, slots=True) class StoryboardTree`: `storyboard_id`, `title`, `revision`, `created_at`,
    `updated_at`, `root: TreeRoot`, `takes: tuple[Take, ...]`. Methods: `to_dict`; `from_dict` (strict keys; refuses a
    future schema); `children(parent_id) -> tuple[Take, ...]` in creation order;
    `label(take_id) -> str` (root `A`; children alternate digits and letters by depth: `A1`, `A1a`, `A1a1`, numbered by
    creation order among one parent's children); `depth(take_id) -> int`; `with_take(take)`; `with_mark(take_id,
    mark)`; `with_attempt(take_id, job_id)`; `without_takes(take_ids)`; `renamed(title)`; `duplicate(title)` (new id,
    revision 0).
- Produces, in `storyboard_tree_store.py`: `default_root() -> Path` (`.../StableNew/storyboard_trees`) and
  `class StoryboardTreeStore` with `load(storyboard_id) -> StoryboardTree`, `save(tree) -> StoryboardTree` (CAS on
  `revision`, returns revision + 1), `list_trees() -> list[tuple[str, str, str]]` (id, title, updated_at; unreadable
  files listed with title `"(unreadable)"`, never rewritten). It copies `storyboard_store.py`'s rules: `_locked`, the
  root-escape check, `_unique_object`, `MAX_BYTES = 2 * 1024 * 1024`, and `atomic_publish_json` for a new file versus
  `atomic_write_json`.

- [ ] **Step 1: Write the failing tests**

```python
def test_labels_alternate_digits_and_letters():
    tree = _tree(edges=[("root", "a"), ("root", "b"), ("a", "c"), ("a", "d"), ("d", "e")])
    assert [tree.label(t) for t in "abcde"] == ["A1", "A2", "A1a", "A1b", "A1b1"]

def test_round_trip_and_cas(tmp_path):
    store = StoryboardTreeStore(tmp_path)
    saved = store.save(_tree())
    assert store.load(saved.storyboard_id) == saved and saved.revision == 1
    with pytest.raises(StoryboardTreeError, match="Revision conflict"):
        store.save(replace(saved, revision=0))

def test_malformed_and_future_files_are_preserved(tmp_path):
    store = StoryboardTreeStore(tmp_path)
    path = tmp_path / ("f" * 32 + ".json")
    path.write_text('{"schema": "stablenew.storyboard-tree.v9"}', encoding="utf-8")
    with pytest.raises(StoryboardTreeError):
        store.load("f" * 32)
    assert path.read_text(encoding="utf-8") == '{"schema": "stablenew.storyboard-tree.v9"}'
    assert ("f" * 32, "(unreadable)") == store.list_trees()[0][:2]

def test_size_cap_refuses_without_writing(tmp_path):
    store = StoryboardTreeStore(tmp_path)
    saved = store.save(_tree())
    with pytest.raises(StoryboardTreeError, match="exceeds the 2 MB limit"):
        store.save(_huge(saved))
    assert store.load(saved.storyboard_id) == saved

def test_no_status_or_output_paths_are_stored():
    assert not {"status", "output_path", "plan"} & set(json.dumps(_tree().to_dict()).split('"'))
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_tree_store.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement both modules**

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/video/test_pr_vid_story_380_tree_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: storyboard file model and store`)

### Task A8: Storyboard submission service

**Files:**
- Create: `src/controller/storyboard_submission_service.py`
- Modify: `src/controller/video_workflow_controller.py` (construct the service in `__init__` and expose it),
  `src/video/storyboard_history.py:30` (refuse v2)
- Test: `tests/controller/test_pr_vid_story_380_submission.py`

**Interfaces:**
- Consumes: A4 `build_sequence_njr`, A6 root preparation, A7 tree and store, A2 `read_cut_manifest`, `plan_from_njr`,
  `RESUME_KEY`, `REPLAY_KEY`, `PLAN_KEY`, `SubmissionPolicy`.
- Produces:
  - `RECONCILE_WINDOW: Final = 200`
  - `@dataclass(frozen=True, slots=True) class ContinueRow`: `prompt: str`, `negative_prompt: str`, `seed: str`.
  - `@dataclass(frozen=True, slots=True) class ContinueRequest`: `storyboard_id: str`, `expected_revision: int`,
    `parent_id: str`, `handoff_index: int | None` (`None` only for an image root), `mode: Literal["parallel",
    "sequential"]`, `rows: tuple[ContinueRow, ...]`, `experimental_opt_in: bool = False`.
  - `@dataclass(frozen=True, slots=True) class ContinuePreview`: `jobs: int`, `segments: int`, `lead_in_frames: int`,
    `total_cut_frames: int`, `fps: int`, `workflow_id: str`, `workflow_version: str`, `seeds: tuple[str, ...]`.
  - `@dataclass(frozen=True, slots=True) class ContinueResult`: `job_ids: tuple[str, ...]`,
    `take_ids: tuple[str, ...]`, `tree: StoryboardTree`.
  - `class StoryboardSubmissionService` with `__init__(self, *, njr_builder, workflow_registry, job_service:
    Callable[[], Any], repository: Callable[[], Any], store: StoryboardTreeStore | None = None, output_root:
    Callable[[], str], new_id: Callable[[], str] = lambda: uuid.uuid4().hex, draw_seed: Callable[[], int] = lambda:
    secrets.randbelow(2**31))`. Methods, all synchronous and worker-safe:
    - `create_from_clip(job_id: str, title: str) -> StoryboardTree`
    - `create_from_image(image_path: str, settings: Mapping[str, Any], title: str) -> StoryboardTree`
    - `parent_cut(tree: StoryboardTree, take_id: str) -> CutManifest | None` (the node's cut: the root manifest, or
      the attempt manifest's prefix through that take's range)
    - `preview(request: ContinueRequest) -> ContinuePreview`
    - `submit(request: ContinueRequest) -> ContinueResult`
    - `reconcile(storyboard_id: str) -> StoryboardTree`
  - `VideoWorkflowController.storyboards: StoryboardSubmissionService` (the tab reaches it through the existing
    `app_controller.get_video_workflow_controller()`, so `AppController` is unchanged). Construct it with
    `job_service=self._job_service`, `repository=lambda: getattr(self._job_service(), "history_store", None)` (the
    same repository History reads with `get_job_model`) and
    `output_root=lambda: getattr(self._app_controller, "output_dir", None) or "output"`.

Behaviour:
- **submit:** 1-6 rows, each with a non-empty positive prompt (named by 1-based row). Then:
  1. Load the tree and refuse a stale `expected_revision`.
  2. Resolve the parent cut. K = `handoff_index + 1`, and the handoff is frame K-1 of the cut. A take's cut comes from
     its newest completed attempt's manifest, or else its newest attempt that has a manifest.
  3. Write a lead-in manifest for this admission: `parent_cut.prefix(K)`, written to
     `<output_root>/storyboards/<storyboard_id>/leadins/<batch_id>.json`. The plan pins that file's hash. A parent
     that is a take in a still-running chain has its job manifest rewritten after every segment, so pinning the job
     manifest itself would break the child. The copy holds frame references only, never frames.
  4. Build the form from `root.settings` plus the opt-in. Blank or `random` seeds are drawn with `draw_seed` and
     redrawn until they are unique within the batch.
  5. Parallel builds N NJRs with one segment each; sequential builds one NJR with N segments. All use
     `build_sequence_njr(..., exact_source=True)` when there is a lead-in.
  6. Write the pending takes (empty `attempts`) with CAS, cross `submit_njrs` once with every NJR, then write the
     attempts. When admission or submission raises, remove the pending takes and re-raise. When the second write fails,
     the takes stay pending and `reconcile` adopts them.
- **reconcile:** read `repository().list_recent_jobs(limit=RECONCILE_WINDOW)`. For each job whose id is in no take's
  attempts, read the plan with `get_job_model` and `plan_from_njr`. Skip it unless it is v2 and names this storyboard.
  Then:
  - pending takes matching `take_ids` adopt it as the first attempt;
  - a stage config with `RESUME_KEY`: append the job to those takes' attempts;
  - a stage config with `REPLAY_KEY`: create new sibling takes (new ids, `replay_of` = the original take id, same
    parent, handoff, prompts; a chain replay becomes a new chain) with `attempts=(job_id,)`.
  Save once if anything changed.
- **storyboard_history.from_history:** raise `StoryboardError("This job is a Storyboard take; the linear Storyboard
  editor cannot express its lead-in. Open it in the Storyboard tab.")` for a v2 plan.

- [ ] **Step 1: Write the failing tests**

```python
def test_parallel_submit_is_one_call_all_or_none(service, tree_with_clip_root):
    result = service.submit(_request(tree_with_clip_root, rows=3, mode="parallel", handoff_index=77))
    assert service.job_service_calls == [3]          # one submit_njrs call carrying three NJRs
    assert len(result.job_ids) == 3 and len(set(_seeds(service))) == 3
    assert all(t.attempts for t in result.tree.takes)

def test_admission_failure_queues_nothing_and_removes_pending(service, tree_with_clip_root):
    service.fail_build_on_row = 2
    with pytest.raises(SequencePlanError):
        service.submit(_request(tree_with_clip_root, rows=3, mode="parallel", handoff_index=77))
    assert service.job_service_calls == [] and service.store.load(tree_with_clip_root.storyboard_id).takes == ()

def test_stale_revision_is_refused_before_submission(service, tree_with_clip_root):
    with pytest.raises(StoryboardTreeError, match="Revision conflict"):
        service.submit(replace(_request(tree_with_clip_root, rows=1), expected_revision=0))
    assert service.job_service_calls == []

def test_oversize_storyboard_refuses_before_submission(service, near_cap_tree):
    with pytest.raises(StoryboardTreeError, match="exceeds the 2 MB limit"):
        service.submit(_request(near_cap_tree, rows=6))
    assert service.job_service_calls == []

def test_submit_refuses_when_a_lead_in_frame_was_moved(service, tree_with_clip_root):
    _move_to_archive(_root_frame(tree_with_clip_root, 10))
    with pytest.raises(CutManifestError, match="lead-in frame is missing"):
        service.submit(_request(tree_with_clip_root, rows=1, handoff_index=77))

def test_sequential_submit_is_one_job_with_a_chain_of_takes(service, tree_with_clip_root):
    result = service.submit(_request(tree_with_clip_root, rows=3, mode="sequential", handoff_index=80))
    chain = sorted(result.tree.takes, key=lambda t: t.chain_position)
    assert len(result.job_ids) == 1 and [t.handoff_index for t in chain] == [80, None, None]
    assert chain[1].parent_id == chain[0].take_id

def test_branch_from_a_middle_chain_take_uses_its_prefix(service, tree_with_finished_chain):
    middle = _chain_take(tree_with_finished_chain, position=1)
    request = _request(tree_with_finished_chain, rows=1, parent_id=middle.take_id, handoff_index=120)
    service.submit(request)
    assert _lead_in_of_last_njr(service).frame_count == 121

def test_stop_between_submission_and_recording_is_reconciled(service, tree_with_clip_root):
    service.store.fail_next_save_after = 1           # pending write succeeds, attempt write fails
    with pytest.raises(StoryboardTreeError):
        service.submit(_request(tree_with_clip_root, rows=2))
    tree = service.reconcile(tree_with_clip_root.storyboard_id)
    assert all(len(t.attempts) == 1 for t in tree.takes) and service.job_service_calls == [2]

def test_resume_joins_the_take_and_replay_becomes_a_sibling(service, tree_with_failed_and_completed_takes):
    tree = tree_with_failed_and_completed_takes
    service.fake_repository.add_resume_of(_take(tree, "failed").attempts[0])
    service.fake_repository.add_replay_of(_take(tree, "completed").attempts[0])
    after = service.reconcile(tree.storyboard_id)
    assert len(_take(after, "failed").attempts) == 2
    replay = next(t for t in after.takes if t.replay_of == _take(tree, "completed").take_id)
    assert replay.parent_id == _take(tree, "completed").parent_id and after.label(replay.take_id) != after.label(replay.replay_of)

def test_history_refuses_v2_plans(v2_job_repository):
    with pytest.raises(StoryboardError, match="Open it in the Storyboard tab"):
        from_history(v2_job_repository, "job-v2")
```

The `service` fixture wires the real NJR builder, registry and store over `tmp_path`. It uses a recording fake
`job_service` whose `submit_njrs` returns ids and records batch sizes, and a fake repository that serves those jobs back.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `$PY -m pytest tests/controller/test_pr_vid_story_380_submission.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the service, the controller exposure and the History refusal**

- [ ] **Step 4: Run the tests, the controller surface check and the Tk boundary check**

Run: `$PY -m pytest tests/controller/test_pr_vid_story_380_submission.py -q; $PY tools/ci/check_controller_surface.py; $PY tools/ci/check_controller_tk_boundary.py`
Expected: PASS. `app_controller.py` is still at or below 5,010 lines.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: storyboard submission service`)

### Task A9: PR A docs and validation

**Files:**
- Modify: `docs/Subsystems/Video/VIDEO_PIPELINE.md` section 7.1 (policy v2, storyboard link, lead-in, cut manifest,
  pass-through source), `docs/CODEX_MAP.md` (the video row), `STATUS.md` (the video line), `docs/CODE_MAP.md`
  (regenerated)

- [ ] **Step 1: Update the living docs** in the repository's plain style. State that no physical GPU run is claimed.
- [ ] **Step 2: Regenerate the code map**

Run: `$PY tools/generate_code_map.py`
Expected: `docs/CODE_MAP.md` lists the new modules.

- [ ] **Step 3: Run the ratchets and the gate in an isolated worktree** (never the live checkout)

Run: `$PY tools/ci/run_mypy_ratchet.py; $PY tools/ci/run_ruff_ratchets.py; $PY tools/ci/run_architecture_ratchets.py; $PY tools/ci/run_pr_gate.py; $PY -m pytest tests/tools -q`
Expected: every command exits 0. `tests/tools` covers the census the gate misses for new `src` modules.

- [ ] **Step 4: Commit** (`PR-VID-STORY-380: docs and code map for the execution package`)
- [ ] **Step 5: Stop and report to Rob** under `AGENTS.md` section 8, with the exact SHA and the gate evidence. Ask
  for the go-ahead to push and open PR A.

---

## Part B: PR B, workspace

### Task B1: Read-back projection

**Files:**
- Create: `src/video/storyboard_projection.py`
- Test: `tests/video/test_pr_vid_story_380_projection.py`

**Interfaces:**
- Consumes: A7 tree, A2 manifest reader, `JobRepository.get_job_entries(job_ids)`, `find_ledger_path`,
  `locate_ledger`, `read_ledger`, `read_ledger_progress`.
- Produces:
  - `@dataclass(frozen=True, slots=True) class TakeView`: `take_id: str`, `state: Literal["pending", "queued",
    "running", "completed", "failed", "cancelled", "unknown"]`, `status_text: str` (for example
    `running segment 2 of 4`), `shown_job_id: str | None`, `manifest: CutFrame | None`, `stitched_path: str | None`,
    `clip_path: str | None`, `encoded: bool`, `frames_ok: bool`, `problem: str` (`frames missing or changed: <first
    bad path>`), `can_resume: bool`, `can_replay: bool`.
  - `project_storyboard(tree: StoryboardTree, repository: Any, *, output_roots: Sequence[str], check_frames:
    Callable[[CutManifest], str | None]) -> dict[str, TakeView]`. It is read-only and touches no job state.
    `check_frames` returns the first missing path by existence check only. Hashing is left to admission.
- Shown attempt: the newest completed attempt, or else the newest attempt. The manifest comes from the ledger
  (located as History does). The stitched path comes from the result's `assembled_video.output_path`. For a sequential
  chain, a middle take's `stitched_path` is the chain's file.

- [ ] **Step 1: Write the failing tests**

```python
def test_states_and_progress_text(tmp_path):
    views = project_storyboard(*_fixture(tmp_path, states=["queued", "running:2/4", "completed", "failed", "cancelled"]),
                               output_roots=[str(tmp_path)], check_frames=lambda m: None)
    assert [v.status_text for v in views.values()] == ["queued", "running segment 2 of 4", "completed", "failed", "cancelled"]

def test_projection_reports_not_encoded_with_manifest(tmp_path):
    view = _single(tmp_path, state="cancelled", manifest=True, mp4=False)
    assert view.manifest is not None and not view.encoded and view.can_resume

def test_projection_flags_missing_parent_frames_but_keeps_the_mp4(tmp_path):
    view = _single(tmp_path, state="completed", missing_frame="output/_archive/x/frame_0011.png")
    assert not view.frames_ok and view.problem.startswith("frames missing or changed: ")
    assert view.stitched_path is not None

def test_pending_take_has_no_job(tmp_path):
    assert _single(tmp_path, attempts=()).state == "pending"
```

- [ ] **Step 2: Run the tests and confirm they fail.** `$PY -m pytest tests/video/test_pr_vid_story_380_projection.py -q`
  (FAIL: module missing)
- [ ] **Step 3: Implement `src/video/storyboard_projection.py`**
- [ ] **Step 4: Run the tests and confirm they pass.** Same command; expected PASS.
- [ ] **Step 5: Commit** (`PR-VID-STORY-380: storyboard read-back projection`)

### Task B2: Frame cache and tab view contract

**Files:**
- Create: `src/video/storyboard_frame_cache.py`, `src/gui/view_contracts/storyboard_tree_contract.py`
- Test: `tests/gui_v2/test_pr_vid_story_380_contract.py` (Tk-free)

**Interfaces:**
- Produces:
  - `class FrameCache` with `__init__(self, *, max_frames: int = 400, max_thumbnails: int = 300, viewer_size: tuple[int,
    int] = (960, 540), thumb_size: tuple[int, int] = (92, 52))`, `frame(path: str) -> Image.Image` and
    `thumbnail(path: str) -> Image.Image`. Both downscale with LANCZOS and are thread-safe, worker-side only.
  - `@dataclass(frozen=True, slots=True) class Column`: `title: str` (`Shot 1`, or `Shot 2 · from A @ f78`), `cards:
    tuple[Card, ...]`.
  - `@dataclass(frozen=True, slots=True) class Card`: `take_id`, `label`, `excerpt` (prompt, at most 40 characters),
    `status_text`, `mark`, `on_path: bool`, `selected: bool`.
  - `class StoryboardTreeContract` with `__init__(self, tree: StoryboardTree, views: Mapping[str, TakeView])`,
    `columns(show_dropped: bool) -> tuple[Column, ...]`, `dropped_count() -> int`, `select(node_id: str) -> None`,
    `selected_cut_owners(cut_length: int, segment_lengths: Mapping[str, int]) -> tuple[str, ...]` (the owner of every
    frame of the selected node's cut, derived from the tree's parent and handoff links; manifest owner labels are
    provenance only), `joins() -> tuple[int, ...]` (the slider tick indices), `readout(index: int) -> str`
    (`frame 226 / 234 · A1b frame 78 of 81`, where the own number counts the trimmed overlap frame),
    `continue_target(index: int) -> tuple[str, int]` (the owning node and the handoff index),
    `validate_rows(rows) -> list[str]` (1-6 rows, non-empty prompt, seed blank, `random` or an integer in
    0..2147483647, messages naming 1-based rows), `queue_label(mode, n) -> str` (`Queue 3 takes` or
    `Queue chain of 3`), `ai_button() -> tuple[bool, str]` (always disabled; the reason comes from the AI readiness
    record when one is reachable, else `AI Assist is not set up`), and `continue_allowed(node_id) -> tuple[bool, str]`
    (refused when frames are not OK, when the node is pending, or when no cut exists).

- [ ] **Step 1: Write the failing tests**

```python
def test_columns_follow_depth_and_hide_dropped():
    c = StoryboardTreeContract(*_diner_tree())        # A; A1 A2(dropped) A3 A4; A1a A1b
    assert [col.title for col in c.columns(show_dropped=False)] == ["Shot 1", "Shot 2 · from A @ f78", "Shot 3 · from A1 @ f80"]
    assert [card.label for card in c.columns(show_dropped=False)[1].cards] == ["A1", "A3", "A4"]
    assert c.dropped_count() == 1

def test_frame_in_a_middle_chain_take_branches_from_it():
    c = StoryboardTreeContract(*_chain_tree())       # A -> C1 -> C2 -> C3 (one sequential job)
    c.select("C3")
    owner, handoff = c.continue_target(_index_inside("C1"))
    assert owner == "C1" and handoff == _index_inside("C1")

def test_readout_counts_the_trimmed_overlap_frame():
    c = StoryboardTreeContract(*_diner_tree()); c.select("A1b")
    assert c.readout(225) == "frame 226 / 234 · A1b frame 78 of 81"

def test_row_validation_and_labels():
    c = StoryboardTreeContract(*_diner_tree())
    assert c.validate_rows([_row(""), _row("x", seed="12x")]) == [
        "Row 1 needs a positive prompt.", "Row 2 seed must be blank, random or a whole number 0-2147483647."]
    assert c.queue_label("sequential", 2) == "Queue chain of 2"
    assert c.ai_button() == (False, "AI Assist is not set up")

def test_continue_is_refused_from_missing_frames():
    c = StoryboardTreeContract(*_diner_tree(missing_frames_for="A1"))
    assert c.continue_allowed("A1b")[0] is False
```

- [ ] **Step 2: Run the tests and confirm they fail.** `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_contract.py -q`
  (FAIL: module missing)
- [ ] **Step 3: Implement both modules** (no `tkinter` import in either)
- [ ] **Step 4: Run the tests and confirm they pass.** Same command; expected PASS.
- [ ] **Step 5: Commit** (`PR-VID-STORY-380: storyboard frame cache and view contract`)

### Task B3: Storyboard tab, columns and viewer

**Files:**
- Create: `src/gui/views/storyboard_tab_frame_v2.py`, `src/gui/widgets/storyboard_columns_v2.py`,
  `src/gui/widgets/storyboard_viewer_v2.py`
- Modify: `src/gui/main_window_v2.py` (register after Video Workflow: `self.storyboard_tab = self.add_tab("storyboard",
  self._support_tab_title("storyboard", "Storyboard"), _make_storyboard)`; set `app_controller` and `app_state` where
  `movie_clips_tab` is rewired, near line 1043)
- Test: `tests/gui_v2/test_pr_vid_story_380_tab.py` (`tk_root` fixture)

**Interfaces:**
- Consumes: B1, B2, and A8 through `app_controller.get_video_workflow_controller().storyboards`;
  `build_edit_work_runner`.
- Produces: `class StoryboardTabFrameV2(ttk.Frame)` with `__init__(self, parent, *, app_controller, app_state)`,
  `start_from_job(job_id: str, *, status_message: str | None = None) -> None`, `open_storyboard(storyboard_id: str) ->
  None`, and `status_var: tk.StringVar`.
- Toolbar: title, `saved N min ago`, `New from clip or image…` (a dialog: a completed job id from Recent outputs, or an
  image file plus the Make Video workflow line), `Open…` (from `list_trees`), `Show dropped (N)`, `Export cut…`, and
  Rename and Save As.
- The columns widget is a canvas with horizontal scroll. Cards load thumbnails lazily through the worker and the
  `FrameCache`. Clicking a card selects it, highlights its path, and shows ★ / ✕ toggles that save a mark with CAS.
- The viewer plays the selected cut's PNGs at the cut's fps from the cache. The slider spans the whole cut with ticks
  at `joins()`, ◀ ▶ step one frame, and paused shows the exact frame. `Continue from this frame` fills the Continue
  panel through `continue_target`. A smoothed root shows its note under the viewer.
- Every service call, projection and frame load runs on `build_edit_work_runner`. Opening a storyboard calls
  `reconcile` first.

- [ ] **Step 1: Write the failing tests**

```python
def test_tab_is_registered_after_video_workflow(gui_app_factory):
    window = gui_app_factory()
    titles = [window.center_notebook.tab(t, "text") for t in window.center_notebook.tabs()]
    assert titles.index("Storyboard") == titles.index("Video Workflow") + 1

def test_opening_reconciles_on_a_worker_and_renders_columns(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id)
    storyboard_tab.runner.drain()
    assert fake_service.calls[0] == ("reconcile", fake_service.diner_id)
    assert storyboard_tab.columns.column_titles() == ["Shot 1", "Shot 2 · from A @ f78", "Shot 3 · from A1 @ f80"]

def test_marks_save_without_touching_files(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id); storyboard_tab.runner.drain()
    storyboard_tab.columns.toggle_drop("A3"); storyboard_tab.runner.drain()
    assert fake_service.saved_marks == [("A3", "dropped")] and fake_service.files_touched == []
```

`storyboard_tab` builds the frame on `tk_root` with a fake controller whose `get_video_workflow_controller().storyboards`
is `fake_service`, and with a synchronous runner exposing `drain()`. Follow `tests/gui_v2/test_storyboard350_ui.py` for
the runner setup.

- [ ] **Step 2: Run the tests and confirm they fail.** `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_tab.py -q`
- [ ] **Step 3: Implement the three GUI modules and the registration**
- [ ] **Step 4: Run the tests and the main-window suites**

Run: `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_tab.py tests/gui_v2 -q -k "main_window or tab_order or storyboard"`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: Storyboard tab with shot columns and viewer`)

### Task B4: Continue panel

**Files:**
- Modify: `src/gui/views/storyboard_tab_frame_v2.py`
- Test: `tests/gui_v2/test_pr_vid_story_380_tab.py`

**Interfaces:**
- Consumes: A8 `preview` and `submit`, B2 `validate_rows`, `queue_label`, `ai_button` and `continue_allowed`.
- Panel contents (spec 7.2):
  - the title `Continue <label> from its frame N`;
  - a Parallel/Sequential switch;
  - `Write with AI…`, disabled with its reason as a tooltip and status line;
  - 1-6 rows (positive, negative, seed) with `+ Add row (up to 6)` and a remove button per row;
  - a read-only engine line (`Engine: <workflow> · <W>×<H> · <frames> f · <fps> fps (inherited)`);
  - an experimental opt-in checkbox, shown only when the inherited workflow is experimental and never preset from the
    file;
  - `Preview`, which shows the `ContinuePreview` and submits nothing;
  - the queue button, labelled by `queue_label`.
- After queueing, the new takes appear as pending and then queued. Errors show inline with the service's message.

- [ ] **Step 1: Write the failing tests**

```python
def test_preview_submits_nothing(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "A1b", frame=78, rows=["sirens outside"])
    storyboard_tab.preview_button.invoke(); storyboard_tab.runner.drain()
    assert [c[0] for c in fake_service.calls].count("submit") == 0
    assert "lead-in 234 frames" in storyboard_tab.status_var.get()

def test_queue_parallel_sends_one_request(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "A1b", frame=78, rows=["a", "b", "c"])
    assert storyboard_tab.queue_button.cget("text") == "Queue 3 takes"
    storyboard_tab.queue_button.invoke(); storyboard_tab.runner.drain()
    request = fake_service.last_submit
    assert request.mode == "parallel" and len(request.rows) == 3 and request.handoff_index == 225

def test_ai_button_is_disabled_with_reason(storyboard_tab):
    assert str(storyboard_tab.ai_button.cget("state")) == "disabled"
    assert storyboard_tab.ai_reason_var.get() == "AI Assist is not set up"

def test_a_seventh_row_is_not_offered(storyboard_tab):
    _continue_from(storyboard_tab, "A1b", frame=78, rows=["r"] * 6)
    assert str(storyboard_tab.add_row_button.cget("state")) == "disabled"
```

- [ ] **Step 2: Run the tests and confirm they fail.** `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_tab.py -q -k "preview or queue or ai_button or seventh"`
  (FAIL: no Continue panel attributes)
- [ ] **Step 3: Implement the panel**
- [ ] **Step 4: Run the whole tab test file.** `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_tab.py -q`;
  expected PASS.
- [ ] **Step 5: Commit** (`PR-VID-STORY-380: Continue panel`)

### Task B5: Compare, Export, Resume and Replay

**Files:**
- Create: `src/gui/views/storyboard_compare_window_v2.py`
- Modify: `src/gui/views/storyboard_tab_frame_v2.py`
- Test: `tests/gui_v2/test_pr_vid_story_380_tab.py`

**Interfaces:**
- Consumes: `ComparisonClock` (`src/gui/view_contracts/video_review_contract.py:78`), the review preview decode
  (`src/video/review_preview.py`), `route_bundle_to_movie_clips`, and the controller's `resume_sequence` and
  `replay_sequence`.
- `class StoryboardCompareWindowV2(tk.Toplevel)` with `__init__(self, parent, *, clips: Sequence[tuple[str, str]])`
  (label and the take's own clip path). It plays clips in sync with no rating or evidence controls. Decoding uses the
  120-frame preview on a worker.
- `Compare these side by side` sits under a column with two or more non-dropped completed takes.
- `Export cut…` offers `Reveal stitched video` and `Send to Movie Clips`. A middle chain take's dialog states the chain
  file and the end timecode `ends at mm:ss.ff`. A take without an MP4 shows `not encoded` and offers Resume.
- Failed or cancelled cards offer Resume (chains) and Replay, through the video workflow controller's existing
  methods on the worker. Afterwards `reconcile` adopts the new job.

- [ ] **Step 1: Write the failing tests**

```python
def test_compare_opens_with_sibling_clips_and_no_rating(storyboard_tab, fake_service):
    window = storyboard_tab.open_compare("Shot 2 · from A @ f78")
    assert [label for label, _ in window.clips] == ["A1", "A3"] and not window.has_rating_controls()

def test_export_of_a_middle_chain_take_names_the_chain_file_and_end(storyboard_tab, fake_service):
    text = storyboard_tab.export_summary("C1")
    assert fake_service.chain_mp4 in text and "ends at 00:10.06" in text

def test_resume_goes_through_the_controller_then_reconciles(storyboard_tab, fake_service):
    storyboard_tab.resume_take("A4"); storyboard_tab.runner.drain()
    assert fake_service.controller_calls == [("resume_sequence", fake_service.job_of("A4"))]
    assert fake_service.calls[-1][0] == "reconcile"
```

- [ ] **Step 2: Run the tests and confirm they fail.** `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_tab.py -q -k "compare or export or resume"`
  (FAIL: methods missing)
- [ ] **Step 3: Implement the compare window and the actions**
- [ ] **Step 4: Run the whole tab test file.** `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_tab.py -q`;
  expected PASS.
- [ ] **Step 5: Commit** (`PR-VID-STORY-380: compare, export, resume and replay`)

### Task B6: Continue in Storyboard entry points

**Files:**
- Modify: `src/gui/controllers/video_workspace_handoff.py`, `src/gui/job_history_panel_v2.py` (button plus
  `_history_menu` entry, beside `Send to Movie Clips`), `src/gui/views/video_workflow_recent_outputs_panel_v2.py`,
  `src/gui/views/video_workflow_tab_frame_v2.py` (the Make Video result actions)
- Test: `tests/gui_v2/test_pr_vid_story_380_handoff.py`

**Interfaces:**
- Produces: `route_job_to_storyboard(*, main_window: Any, job_id: str, status_message: str | None = None) -> None`. It
  raises `RuntimeError("Storyboard tab is not available")` when the tab is missing, then selects the tab and calls
  `storyboard_tab.start_from_job(job_id, status_message=...)`. Add it to `__all__`.
- `Continue in Storyboard` is enabled for completed Comfy video jobs only. Root refusals (spec 7.3) appear in the tab's
  status line, not as dialogs.

- [ ] **Step 1: Write the failing tests**

```python
def test_route_selects_the_tab_and_starts_from_the_job(fake_main_window):
    route_job_to_storyboard(main_window=fake_main_window, job_id="job-1")
    assert fake_main_window.selected is fake_main_window.storyboard_tab
    assert fake_main_window.storyboard_tab.started == [("job-1", None)]

def test_history_entry_is_enabled_only_for_completed_comfy_video_jobs(history_panel):
    assert history_panel.storyboard_action_state(_job("completed", "video_workflow")) == "normal"
    assert history_panel.storyboard_action_state(_job("completed", "svd_native")) == "disabled"
    assert history_panel.storyboard_action_state(_job("running", "video_workflow")) == "disabled"

def test_recent_outputs_and_make_video_route_the_job(recent_panel, make_video_result):
    recent_panel.continue_in_storyboard("job-2"); make_video_result.continue_in_storyboard("job-3")
    assert recent_panel.window.storyboard_tab.started[-2:] == [("job-2", None), ("job-3", None)]
```

- [ ] **Step 2: Run the tests and confirm they fail.** `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_handoff.py -q`
  (FAIL: `route_job_to_storyboard` missing)
- [ ] **Step 3: Implement the route and the three entry points**
- [ ] **Step 4: Run the tests plus the History and Recent outputs suites**

Run: `$PY -m pytest tests/gui_v2/test_pr_vid_story_380_handoff.py tests/gui_v2 -q -k "history or recent_outputs or handoff"`
Expected: PASS.

- [ ] **Step 5: Commit** (`PR-VID-STORY-380: Continue in Storyboard entry points`)

### Task B7: PR B docs and validation

**Files:**
- Modify: `docs/Subsystems/Video/STORYBOARDS.md` (a Storyboard tab section, and the shared-word note from spec 10.3),
  `docs/CODEX_MAP.md`, `STATUS.md`, `docs/CODE_MAP.md` (regenerated)

- [ ] **Step 1: Update the living docs**, including the acceptance boundary: no physical GPU run is claimed. Rob's
  first live use is the demonstration: one clip, three parallel takes, then one take continued with a two-row
  sequential run.
- [ ] **Step 2: Regenerate the code map.** `$PY tools/generate_code_map.py`
- [ ] **Step 3: Run the ratchets, the gate and the tools census in an isolated worktree**

Run: `$PY tools/ci/run_mypy_ratchet.py; $PY tools/ci/run_ruff_ratchets.py; $PY tools/ci/run_architecture_ratchets.py; $PY tools/ci/run_pr_gate.py; $PY -m pytest tests/tools -q`
Expected: every command exits 0.

- [ ] **Step 4: Commit** (`PR-VID-STORY-380: docs and code map for the workspace package`)
- [ ] **Step 5: Stop and report to Rob** under `AGENTS.md` section 8 with the exact SHA. Ask for the go-ahead to push
  and open PR B (stacked on PR A).
