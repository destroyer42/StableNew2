# PR-VID-120 — Capability-Aware Backend-Neutral Video Execution Contract

Status: **COMPLETE / ACCEPTED / INTEGRATED.** Contract only: no Wan2.2, VACE, SCAIL or other new production backend, workflow,
model, GPU work, GUI feature, or resource scheduler. Native SVD remains the only accepted
production video backend.

## 1. Before and after

**Before.** `VideoBackendCapabilities` was keyed by `stage_types`; `VideoBackendRegistry` kept a
one-backend-per-stage `_stage_map`; `PipelineRunner` detected video work with
`is_registered_stage(stage_name)` and picked the backend with `get_for_stage(stage_name)`. The stage
string (`svd_native`, `animatediff`, `video_workflow`) therefore owned task, backend and
capabilities at once, and a requested control that a backend ignored was dropped silently.

**After.** Four concepts are separate and explicit:

| Concept | Owner | Where it lives |
|---|---|---|
| Task (`image_to_video`) | StableNew | `VideoBackendCapabilities.tasks`, `VideoExecutionRequest.task` |
| Controls (semantic input forms) | StableNew | `VideoBackendCapabilities.controls/required_controls`, `VideoExecutionRequest.requested_controls` |
| Backend (`svd_native`, `comfy`, ...) | explicit `backend_id` | `video_execution.backend_id` in the immutable stage config; registry lookup by id |
| Workflow (versioned profile under a backend) | existing `WorkflowSpec` / registry | `workflow_id` + `workflow_version`; governance and capability tags |

Raw Comfy graphs and model payloads stay adapter-private. Identity preservation is **not** a
capability: it is an observed, qualified result (PR-VID-110).

## 2. Contract

`VideoBackendCapabilities` (`src/video/video_backend_types.py`): `backend_id`, `tasks`
(`image_to_video` is the only known task; unknown tasks are rejected at construction, so naming a
future task never makes it runnable), `controls`, `required_controls`. Known controls:
`source_image`, `prompt_text`, `negative_prompt`, `start_anchor`, `end_anchor`, `mid_anchors`,
`control_video`, `pose_video`, `camera_intent`; unknown names (including model names) raise. The
old `stage_types` and `requires_input_image` / `supports_*` flags are **bounded legacy input**: the
flags fold into `controls` / `required_controls` and are re-synced, so there is one source of truth.

`VideoExecutionRequest` reuses the existing DTO and adds only `task` and `requested_controls`.
Prompt, anchors, workflow id/version, workflow inputs and backend options keep their existing
fields. No second request type and **no new top-level NJR field**: explicit intent rides in the
existing immutable stage config as a `video_execution` block:

    {"backend_id": "...", "task": "image_to_video", "controls": ["prompt_text"],
     "workflow_id": "...", "workflow_version": "..."}

`WorkflowSpec` gained `accepted_controls` (base controls `source_image`, `prompt_text`,
`negative_prompt` plus capability-tag opt-ins) and tags `control_video`, `pose_video`,
`camera_intent`; approved / experimental / disabled governance is unchanged and authoritative.
`ComfyWorkflowVideoBackend.validate_workflow` checks an explicit workflow (known, approved, pinned,
declares every requested control) before dispatch and never selects or substitutes one.

## 3. Resolution (one canonical resolver)

`src/video/video_execution_resolver.py` owns resolution so `PipelineRunner` stays generic:

1. `build_intent(stage_type, stage_config, has_source_image)` reads the neutral block, or, for a
   historical stage-owned record, the bounded legacy mapping.
2. `resolve(...)` looks the backend up **by explicit `backend_id`** (never by task, order, stage
   name or model) and validates task, required and unsupported controls; every failure is a
   deterministic `VideoContractError` (`unknown_backend`, `backend_required`, `unsupported_task`,
   `unknown_control`, `unsupported_control`, `missing_control`, `invalid_workflow`) raised **before
   any backend is called**. There is no fallback and no best-effort dropping.
3. `apply(request, intent)` stamps task/controls/workflow identity on the request, records a
   `video_contract` block in the request's `context_metadata`, and runs the explicit-workflow check.

`PipelineRunner` only builds the intent, calls the resolver and passes the request on
(`run_njr` remains the sole public production entry; no Wan/VACE/SVD-family/Comfy-node branching
was added). The resolver is bound to the runner's current registry.

`VideoBackendRegistry` registers by unique `backend_id`, requires only a declared task, lets any
number of backends share `image_to_video`, and keeps `stage_types` as an optional legacy claim.
`list_backend_ids_for_task` was added; `get_for_stage` remains only for the legacy bridge.

## 4. Bounded legacy bridge

Qualifies: a video stage whose config has **no** `video_execution` block and whose stage type is
`svd_native`, `animatediff` or `video_workflow` (all persisted historical and currently
compiled work, including replayed NJRs). It resolves through the registry's stage claim with a
fixed baseline: `svd_native` -> `source_image` only (prompt text has always been context, never a
requested control); `animatediff` and `video_workflow` -> `source_image`, `prompt_text`,
`negative_prompt`, plus `end_anchor` / `mid_anchors` when configured. The same validation runs, so
there is a single routing authority with legacy input normalised into it.

Newly compiled work that needs anything beyond this should carry the neutral block. **Removal
condition:** every producer compiles the neutral block and replay of historical NJRs no longer
needs stage-owned routing; then delete `LEGACY_STAGE_BINDINGS`, `get_for_stage` / `_stage_map`,
`stage_types` and the legacy capability flags.

## 5. Evidence (fake backends, no GPU)

- `tests/video/test_video_execution_contract.py`: legacy flag folding and rejection of unknown
  controls/tasks; two backends sharing a task; duplicate id illegal; explicit id beats
  registration order; SVD rejects `prompt_text` before execution while a prompt-capable fake
  accepts it; unsupported/missing/unknown controls never call the backend; unknown backend,
  unsupported task and missing backend id are deterministic; no fallback between backends; the
  legacy bridge maps exactly the three stage types; workflow governance (disabled/unknown/wrong
  version) and undeclared controls fail before dispatch.
- `tests/integration/test_pr_vid_120_neutral_video_queue.py`: intent -> immutable NJR ->
  `JobService` -> SQLite -> `PipelineRunner.run_njr` -> the explicitly selected fake backend ->
  artifact, with the explicit intent identical after SQLite reload and in the replay NJR (new job
  identity, `parent_job_id` lineage), the NJR object unmutated, and an unsupported control failing the
  job with the backend never called.
- Regression: the existing runner, SVD-native, AnimateDiff, video-workflow, golden-path, workflow
  registry/compiler, queue and history tests give the same result as on `main` (the same 82
  environment-dependent local failures exist before and after; none new). No real GPU or model
  test was run; the accepted SVD and PR-VID-110 GPU evidence is reused.

## 6. For PR-VID-130

Build on this without rediscovery: compile the neutral `video_execution` block in the video
producers (Video Workflow controller and later UI) and have capability projections read
`VideoBackendCapabilities` / `WorkflowSpec.accepted_controls`. Still undecided and out of scope
here: whether/when to register any Wan2.2 workflow (it needs its own governance and dependency
declarations), GPU lease/resource arbitration between video and image runtimes, and retiring the
legacy bridge.

## 7. Acceptance clarification and next package

Stage names may keep classifying existing pipeline video stages and anchoring the bounded historical
bridge; acceptance does not require removing video stage types. The material requirement, met by the
explicit resolver, is that neutral backend selection is no longer stage-owned. The legacy bridge is
preserved and its removal condition (section 4) stands.

**Next authorized package: PR-VID-130 — Wan2.2 Experimental Prompt-Directed I2V Vertical Slice.**
Product decisions recorded for it (not implemented here): a versioned Comfy workflow with
`governance_state=experimental` and an explicit durable per-job opt-in (never labelled approved);
disabled workflows remain absolutely non-runnable; a bounded resource-readiness guard, not a generic GPU
scheduler/lease authority, that never terminates, adopts or restarts external A1111 or Comfy processes;
and the historical bridge stays until every producer emits neutral `video_execution` intent and replay
migration/normalization is proven.
