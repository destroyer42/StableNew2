# AI-211: "Advise plan" knows which model the operator selected

Status: work package (execution contract). Truth after merge lives in `docs/Subsystems/AiAssist/AI_ASSIST.md`.

## Objective

- Outcome: a plan request carries the model selected in Pipeline (when it can anchor a plan), the plan prompt tells the model to
  plan with it unless the goal names another allowed model, the dialog shows what was sent, and the deterministic judge notes
  any step that uses a different model. Advice only; every AI-210 read-only guarantee stays.
- In scope: `AssistRequest` (three optional plan-only fields), `render_prompt` for `PLAN_PROPOSAL` only, `build_plan_snapshot`,
  the judge note, the "Planning for" dialog line, tests, the runbook, `AI_ASSIST.md`.
- Explicit exclusions: any Intent / form / compiler / queue path; `src/pipeline/`, `src/queue/`; AI-202b areas
  (`AiPreviewDialog`, activation, `config/ai_model_registry.json`, `tools/ai_assist_admin`); `qualified` flags; the frozen
  qualification identities; any change to who is in the closed model list (see finding 1).

## Execution class and model recommendation

- Execution class: Standard (known architecture, one typed field set and a narrow GUI line, no ownership change).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5 High (`docs/AI_MODEL_SELECTION.md`); Codex GPT-6.1 Sol High.
- Branch `feat/ai-211-plan-current-model` from `origin/main` `ba108e1f`.

## Controller Surface Assessment

No controller or coordinator is touched. The only composition-root change is one extra argument in the existing `plan=` lambda in
`src/gui/main_window_v2.py` (the Prompt tab's `_model_projection`). `ai_assist_integration.py` and `AppController` are unchanged.

## Finding that motivated it

With an SDXL checkpoint selected in Pipeline the owner's advice planned every step with `flux-2-klein-4b-fp8`, a model nobody
selected. Cause: `build_plan_snapshot` built the closed lists from the model picker but set no `target_policy_id` and passed no
selection, so `render_prompt` wrote "Target policy: unspecified." and the model chose from the bare key list.

## Decision D21

1. **The request carries the selection.** `AssistRequest` gains `current_target` (empty, or exactly one of `allowed_targets`),
   `current_target_label` (printable, at most 400 characters) and `current_target_stages` (non-empty, image stages drawn from
   `allowed_stages`, never `video`). All three are plan-only (a rewrite, target or workflow request that sets one is a
   `ValueError`) and part of `digest()`; they are appended to the digest payload only when a selection is present, so every
   other request keeps the digest it had. The label and stages are needed because `render_prompt` is pure and `src/ai_assist`
   must not import the policy modules (R10): the caller states them from the same facts it already reads for the judge.
2. **Source of the selection (no new authority).** `build_plan_snapshot(..., selection)` receives the Prompt tab's
   `_model_projection`, the object the "Prompt Target" header and `_context` already read (`projection.policy`,
   `projection.model_name`). `current_target` is `projection.model_name` when it is a key of the closed `targets` list and its
   policy supports at least one allowed image stage; `target_policy_id` is `projection.policy.policy_id`; the label comes from the
   closed list; the stages are the intersection of the policy's stages (`TargetFact.stages`, the judge's own facts) with the
   allowed stages. The goal text and the prompt are never read.
3. **Not usable means not sent.** When the selection is not in the closed list (blocked, hidden by the visibility mode, no
   explicit-capability policy), is empty, or supports no allowed image stage, `current_target`, its label and stages and
   `target_policy_id` stay empty, the prompt is byte-identical to before, and the dialog says, in one fixed sentence
   (`UNANCHORED_NOTICE`): "The model selected in Pipeline is not available for planning (none selected, blocked, hidden or without
   a verified policy), so this advice is not anchored to your selection."
4. **The dialog shows what was sent**, in the status text area above the result (and while the request runs):
   `Planning for: <label> (selected in Pipeline)` or the sentence of point 3. It is derived from the request that was submitted
   (`planning_for_text(request)`), and also appears above fixed-copy refusals and failures.
5. **Judge note.** `PlanFacts.current_target` is the id that was sent. For an image step whose `target` differs from it,
   `judge_step` attaches `note = "This step uses a model other than the one selected in Pipeline."` The verdict is unchanged
   (the note is informational, never "invalid"); a `video` step names a workflow and never gets the note. The review prints
   `Note: ...` under the step and `Copy step N` includes it.
6. **Advice stays advice.** No new field or action reaches Intent, a form, the compiler or the queue. The AI-210 tests that pin
   this (`tests/gui_v2/test_ai_plan_advice.py`, `tests/ai_assist/test_plan_proposal.py`) pass unchanged.

## The prompt sentences (plan with a usable selection only)

Inserted after the `Allowed stages:` line, before the "If you cannot or will not help" line and the data block:

```
Currently selected model: <label>. Use this id for it: <id>. Stages it supports: <stage> | <stage> ...
Plan with the currently selected model unless the goal explicitly names a different allowed model. For image steps use only stages that the selected model supports; a video step names an allowed workflow instead.
```

The prompts of `PROMPT_REWRITE`, `TARGET_FIT_ADVICE`, `WORKFLOW_CHOICE`, and of a plan with no selection, are byte-identical to
before; `tests/ai_assist/test_ai211.py` pins their SHA-256 and digests. The label is checked for the reserved delimiters like any
other framed text. No prompt text, pack content or matrix value enters a plan request.

## Findings for the owner

1. **The owner's SDXL checkpoint is not in the closed model list.** `ultriumV9333NSFWSFW_ultriumV934NSFWSFW_pruned_fp16` has the
   `unverified_generic` model policy (`explicit_capabilities` is false), and `prompt_ai_targets` admits only models with explicit
   capabilities. Measured with the repository's policy resolver, the only picker entry that qualifies today is
   `flux-2-klein-4b-fp8`. Under D21 point 3 an SDXL selection is therefore *not anchored*: the dialog now says so, but the model
   still has only the Klein id to choose from, so advice for an SDXL selection will still name it. Anchoring an SDXL checkpoint
   would need the closed list to admit unverified-generic models (the generic policy lists `txt2img`, `img2img`, `adetailer`,
   `upscale`), which changes what Target Fit and Advise plan may recommend. That is a product decision and is not made here.
2. Behaviour on a real run is unproven: no model was executed for this package.

## Validation plan

Focused: `tests/ai_assist/test_ai211.py` (request validation, digest, prompt text with and without a selection, byte identity of
the other kinds, label impersonation), `tests/gui_v2/test_ai_plan_advice.py` (snapshot: selected and allowed, selected but not
allowed, nothing selected, hidden; judge note; review text), `tests/gui_v2/test_ai_suggestions_112.py` (the dialog line while
running, in the result, and on a refusal). Then `tests/ai_assist`, the frozen-digest tests in `tests/tools`, `tests/system`,
`tests/tools`, `tools/ci/run_pr_gate.py`, `git diff --check`, regenerated `docs/CODE_MAP.md`.

## Acceptance and evidence boundary

- Implementation: the code and documents above.
- Demonstration: deterministic tests with fakes only; the prompt text is asserted, not run.
- Qualification: none. `qualified` stays `false` for every model; the frozen Qwen screening plan, final plan, corpus and LFM3
  `FROZEN_CONTRACT_SHA256` are not digests of `render_prompt` output (AI-202 section 10.4) and their tests pass unmodified.
- Unverified / held: that a real model now plans with the selected model; any answer quality; anchoring for a model outside the
  closed list (finding 1).
