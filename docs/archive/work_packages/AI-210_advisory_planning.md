# AI-210: Tier-1 advisory planning assistant

Status: work package (execution contract). Truth after merge lives in `docs/Subsystems/AiAssist/AI_ASSIST.md`.

## Objective

- Outcome: the operator types a goal in plain words, presses an explicit **Advise** button, and reads back an
  **advisory** step list (which stage / model / workflow would fit), each step judged by deterministic code and shown
  read-only. It is advice, never an executable plan (owner decisions D13 to D17; amendment D-1, D-3, D-4, rules R1, R2, R4,
  R7, R8, P1 to P3, P5 to P8).
- In scope: typed `PLAN_PROPOSAL` kind (contract, framing, schema, strict validator); a deterministic judge outside
  `src/ai_assist`; a toolkit-neutral advice view model; the smallest GUI entry (a goal field and an **Advise plan** button in
  the existing suggestion dialog); worker-thread judging via the integration; tests; `AI_ASSIST.md`, amendment status wording,
  the one `STATUS.md` AI Assist line.
- Explicit exclusions: R3, Confirm & Queue, any Intent / compiler / queue / form-filling path (D-3, P8); any change under
  `src/pipeline/` or `src/queue/`; `allow_candidate`, `strict_offline` and every ratchet unchanged; no new tab; no Learning or
  Smart Review connection; no model, llama.cpp binary, download, GPU or backend is started.

## Execution class and model recommendation

- Execution class: Standard (known architecture, new typed kind plus a narrow GUI surface, no ownership change).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High (substantial known-architecture PR, `docs/AI_MODEL_SELECTION.md`).
- Task start: 2026-11-13T22:16:46Z, Claude Code session `6ff7a8cd-d939-47a9-9547-ae5f42a979d7` (started by coordinating session `local_ded6f184-9d33-48d3-876e-43da15db7f73`).
- Branch `feat/ai-210-advisory-plan` from `origin/main` `010650cf`.

## Controller Surface Assessment

`src/controller/app_controller_services/ai_assist_integration.py` is a service module, not a ratcheted controller. It gains one
method, `submit_plan`, sharing the existing single-flight, lifetime-checked GUI delivery and adding a worker-thread `judge`
callback. `AppController` is not touched. The composition root (`main_window_v2.py`) gains one binding of the advice sources
to the existing Prompt-tab AI object. No controller ceiling is raised.

## Schema (`ai_assist.suggestion/1`, kind `plan_proposal`)

Request (`AssistRequest`): `goal_text` (operator words, at most 1000 characters, data between the existing delimiters),
`allowed_targets` (model ids), `allowed_workflows` (workflow ids), `allowed_stages` (closed stage ids). `PLAN_PROPOSAL`
needs a goal, at least one stage, and at least one target or workflow.

Response (one JSON object): `schema`, `status` (`ok` | `refused`), `kind: "plan_proposal"`, `steps`: 1 to 6 objects, each
exactly `{stage, target|null, workflow|null, count, rationale}`:

- `stage` in `allowed_stages`; an image stage (`txt2img`, `img2img`, `adetailer`, `upscale`) takes a `target` from
  `allowed_targets` and no `workflow`; the `video` stage takes a `workflow` from `allowed_workflows` and no `target`.
- `count` is an integer 1 to 8 (images or clips this step would produce); the plan total is at most 24.
- `rationale` is free text of at most 240 characters, control characters refused; it is display text only and is never an
  identifier. No other field exists, so nothing in the result can become Intent, a payload, a path or a command.

`AssistSuggestion.steps` carries `PlanStep` records; `to_diagnostics` reports only a step count.

## Closed-list sources (nothing from free text)

- Models: the existing Prompt-tab model picker projection `prompt_ai_targets` (`project_model_selection`, explicit
  capabilities, not blocking, visibility filtered). The judge re-reads the same authority at completion
  (`resolve_model_policy` stages and the backend projection), so a model removed or blocked since the request is
  `unavailable` / `incompatible`.
- Workflows with governance state: `VideoWorkflowController.list_workflow_specs()` records (`governance_state`,
  `workflow_version`, display name). The judge re-reads the record, then runs the controller's existing
  `workflow_preflight(workflow_id, version)` gates on the worker thread; a blocked gate is `unavailable(prerequisite)`, an
  unknown gate is `needs_operator_input`.
- Installed assets are covered by those two authorities (installed checkpoints through the picker; model files, nodes and
  launch flags through the preflight gates). A step cannot name an asset, so there is no separate asset closed list.
- Stages: `src.image_backends.model_policy` stage constants plus `video`.

## Deterministic judge (P2)

`judge_plan` (in `src/gui_v2/ai_plan_advice.py`, never in `src/ai_assist`) classifies each step `valid | incompatible(reason) |
unavailable(prerequisite) | needs_operator_input`: image step, stage not in the model policy's stages is `incompatible`;
model not present or blocked is `unavailable`/`incompatible`; workflow `experimental` needs a per-job opt-in the operator
alone can give, so `needs_operator_input`; `disabled` or unknown is `unavailable`. A judge failure shows no steps (never
"valid by default"). Invalid steps are shown with their reason and never repaired or dropped.

## Bounds (P3)

At most 6 steps, count 1 to 8 per step, total 24, goal 1000 characters, rationale 240. An over-bound response is `MALFORMED`
(`plan_too_many_steps`, `step_count_out_of_bounds`, `plan_total_over_bound`); nothing is truncated.

## No execution authority (D-3, P8)

The result and view model have no field or action that creates Intent, edits authored intent, fills a form, compiles, previews
or queues. The only per-step action is **Copy text**. Every plan surface says "Advice, not a plan" and carries the Preview
label when the trust tier is Preview. Conversion code, if ever added, belongs outside `src/ai_assist` (R10) in a later package.

## Validation plan

Focused: `tests/ai_assist/test_plan_proposal.py` (schema, out-of-list ids, bounds, judge classes, admission refusals while
RUNNING / quarantine / unreadable / yielded, Preview not enabled, content-free event log, no intent-creating action) and
`tests/gui_v2/test_ai_plan_advice.py` (view model, copy text), using the existing fake child, no model, binary, network, GPU or
display. Then `tests/ai_assist`, `tests/tools` ratchet/census, mypy/ruff ratchets, `tools/ci/run_pr_gate.py`,
`git diff --check`, regenerated `docs/CODE_MAP.md`.

## Acceptance and evidence boundary

- Implementation: the code and documents above.
- Demonstration: deterministic tests with fakes only.
- Qualification: none. No model has been run; output quality is unverified until AI-201 and PR-AI-111. The planning
  qualification criteria in `AI_ASSIST.md` section 7 are proposals with no thresholds.
- Held: first physical activation (AI-201); any physical planning inference; R3 / Confirm & Queue (not adopted).
