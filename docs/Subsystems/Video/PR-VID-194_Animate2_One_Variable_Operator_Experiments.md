# PR-VID-194 — One-Variable Operator Experiments (Video Workflow)

Status: **implemented and verified; pending owner final PR review; not merged into `main`.** Validation remains
CPU/fake-runtime only; no physical GPU run. Ready for operator A/B qualification after owner review and a separate
physical-run authorization. No promotion or readiness conclusion changes; Wan-Animate-2 stays EXPERIMENTAL and per-job
opt-in, native SVD stays the default.

## 1. What it is

"Compare one control": keep the current Video Workflow setup fixed and compare ONE declared operator control at 1 to 3
operator-supplied values. Variant A is always the current resolved value, so an experiment is 2 to 4 jobs. The first
consumer is Wan-Animate-2 (Motion Prompt, Pose Strength, Pose Start/End %, Reference Image Strength — the PR-VID-192
controls), but nothing in the mechanism names a workflow, backend, model or node: the variable list is exactly the
selected workflow's `operator_controls` projection (`src/video/workflow_controls.py`). A workflow that declares no
controls offers no experiment capability and refuses experiment values.

Deliberately absent: Cartesian or multi-variable experiments, adaptive/automatic search, scoring, winner selection,
auto-rerun and any durable experiment store. The operator looks at the results and chooses the next values.
Frame count, seed, workflow, driving video, source image, prompts and output route are frozen baseline inputs, never
the variable.

## 2. Architecture

No new queue, store, database, lifecycle, runner, compiler or history authority. The canonical path is unchanged:
`Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler ->
Artifacts/History`. Queue/History remain the only execution-status and result authority.

| Piece | Home | Responsibility |
|---|---|---|
| Shared NJR construction | `src/video/video_workflow_njr_builder.py` | `VideoWorkflowNjrBuilder`: form validation, `freeze_inputs` (concrete seed, source and driving-video hashes, declared source preparation) and `build_job` (one immutable NJR). Used by BOTH a normal submission and every experiment arm. |
| Experiment planning/admission | `src/video/video_workflow_experiment.py` | `VideoWorkflowExperimentService`: resolve baseline/candidates through the existing control validation, build every arm via the shared builder, run the controlled-diff gate, then admit. Produces a transient frozen `ExperimentPlan`. |
| Admission | `src/learning/experiment_execution.py` (reused) | `ExperimentAdmissionService.compile_all/submit` crosses `JobService.submit_njrs` once; `freeze_snapshot`/`thaw_snapshot`/`snapshot_digest` hold the frozen baseline. |
| Provenance | `LearningJobContext` (reused) via `ReprocessJobBuilder.build_reprocess_job(learning_context=...)` | Optional, default `None`; every other caller is unchanged. Jobs stay `SourceKind.VIDEO_WORKFLOW` / `WorkloadKind.VIDEO`. |
| Coordination | `src/controller/video_workflow_controller.py` | `preview_experiment`, `submit_experiment`, `resolve_experiment_baseline`; the controller delegates and no longer constructs NJRs (540 -> ~195 lines). `AppController` ownership and line ceiling are unchanged; it only exposes the controller as the public `get_video_workflow_controller()` and `sync_queue_state_after_direct_submission()` (renames of the previous private helpers). |
| GUI state | `src/gui/view_contracts/video_experiment_contract.py` | Toolkit-neutral `VideoExperimentSession`: transient, unsaved form state, preview invalidation. |
| GUI rendering | `src/gui/views/video_workflow_experiment_panel_v2.py` + `video_workflow_tab_frame_v2.py` | Renders the declared controls; builds no payload and branches on no workflow or model. |

## 3. Freeze and honesty contract

Preview freezes one baseline before any arm exists: workflow id/version/backend, source path and SHA-256, the prepared
source (content-addressed StableNew-owned PNG) and its SHA-256, driving-video path and SHA-256, prompts, frame count,
output route, the experimental opt-in and every operator control. A blank/random seed is resolved ONCE and reused by
every arm; an explicit seed is reused unchanged.

Candidates use the existing control validation (range, finite number, ordered pairs, text fallback); nothing is clamped
or rounded. An empty text candidate resolves to its declared fallback and the preview shows the resolved text. Refused:
no candidates, more than three, invalid values, ordered-pair violations, undeclared controls, a candidate equal to the
baseline after resolution and duplicate candidates.

Controlled-diff gate (fail-closed, before anything is queued): each arm's NJR is serialized, job identity and the
`learning_context` removed, and every `operator_controls[<variable>]` representation masked. All arms must then be
byte-identical, each arm must record its own value consistently, carry the shared experiment identity with its own
variant index/value, and be a Video Workflow video job. Any other difference refuses the entire experiment and submits
zero jobs, with the first differing path in the message. The gate is re-run at admission.

Admission (`submit_experiment`): re-hashes the source, prepared source and driving video (a changed byte refuses the
experiment — "Build the preview again" — and submits zero jobs), re-verifies the gate and the per-job opt-in, then
makes one `JobService.submit_njrs` call with all NJRs. That call is all-or-none at the canonical boundary (one SQLite
transaction, then one runnable projection, then events and runner start), so a failure on any arm leaves no arm durable,
runnable or running and "nothing was queued" is literally true; the experiment layer holds no transaction logic. The result reports experiment id, variable, arm labels/values and
job ids.

Experimental opt-in stays off by default, per submission and never persisted. Preview requires it (it is part of the
frozen baseline) so an experimental workflow cannot be previewed or queued without the explicit opt-in; the checkbox is
part of the previewed inputs, so toggling it drops the preview.

## 4. Operator UI

"Compare one control" appears only when the selected workflow declares at least one control. It offers a variable
selector, the read-only resolved baseline, 1-3 candidate rows (an entry for a number control, a text box for a text
control), Build Preview (non-generating), Queue Experiment (only for a valid preview) and Cancel Preview. The preview
shows A/B/C/D with `<control> = <value>`, the experiment id, the frozen common seed, "Only <control> changes across
these jobs." and everything fixed (workflow, source and driving-video hashes, seed, frames, prompts, other control
values, output route). Any execution-affecting edit after a preview (variable, candidate, prompt, seed, frame count,
source/driving path, any control, route, opt-in) invalidates it; queueing re-checks the form again. Normal Queue Video
Workflow is unchanged when comparing is off.

All arms run in one shared run folder labelled by the experiment (`learning_<variable>_<id>`) inside the unchanged
output route, because the runner already groups jobs carrying a `LearningJobContext`. Output file names embed the job
id, so arms do not overwrite one another. A canceled preview leaves only the content-addressed prepared source image
(the same file a normal submission creates).

## 4a. Threading

Build Preview (hash source and driving video, prepare the source image, build 2-4 NJRs, run the diff gate) and Queue
Experiment (re-hash the frozen files, re-run the gate, one `submit_njrs`) never run on the Tk event thread. Each is three
steps on `VideoExperimentSession`: `begin_*` on the Tk thread (claims the busy state and captures a plain deep-copied
snapshot of the form, so a worker never sees a Tk variable or widget), `run_*` on a worker owned by the existing
`ThreadRegistry` (touches no session or Tk state), and `finish_*` back on the Tk thread via `TkUiDispatcher`
(`BackgroundWorkRunner` only wires spawn to dispatch; it is not a scheduler or queue). While a worker is outstanding
Build Preview, Queue Experiment and Cancel Preview are disabled and a second click schedules nothing. Any edit while a
preview builds (form, candidate, variable, toggle) bumps a token and the finished result is discarded rather than shown;
the form is also re-compared at completion. A panel destroyed before completion ignores the result. Refreshing
GUI-visible queue state (`sync_queue_state_after_direct_submission`) runs in the Tk-thread completion, not in the worker.
`sha256_file` hashes in 1 MiB chunks, so a large driving video is never loaded whole.

## 5. Not done / follow-ups

Durable Learning-Library review of video experiments is out of scope (the Learning models and review surfaces are
image-centric); the NJR `LearningJobContext` plus Queue/History provenance is the V1 record. Physical A/B qualification
of real Animate-2 behaviour is a separate, owner-authorized step.

## 6. Validation

`tests/video/test_pr_vid_194_one_variable_experiments.py` (service/controller, controlled-diff gate, frozen hashes and
seed, atomic one-call admission, opt-in, real SQLite queue with a fake Comfy proving the three graphs differ only in
the pose-strength input), `tests/gui_v2/test_video_workflow_experiment_ui.py` (neutral session and the Tk tab). No
live WebUI, Comfy, GPU or network.
