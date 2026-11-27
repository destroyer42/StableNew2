# ASSIST-FIX: AI Assist answers reliably

Status: in progress (2026-11-27). Package 9 of the 2026-11-27 Value Assessment.

Execution class: Standard. Model recommendation: Claude Code, Sonnet 5.5, medium to high effort
(`docs/AI_MODEL_SELECTION.md`). Canonical execution path unchanged: AI Assist stays advisory and before Intent.

## Outcome

On the approved remote worker, AI Assist refuses under 5% of requests and returns a malformed answer under 1% of
the time, and the V1 prompt-only video panel can suggest a motion phrase.

The 5% and 1% targets are met only when a live replay shows it. Offline evidence cannot show it (see below).

## Starting evidence

Local event log, 104 requests, 2026-11-14 to 11-25 (counts and codes only; the log holds no prompt text, D7):

| | all 104 | model-answered 90 | remote 86 |
|---|---|---|---|
| refused by model | 25 (24.0%) | 27.8% | 24 (27.9%) |
| malformed | 11 (10.6%) | 12.2% | 9 (10.5%) |

- Every refusal but none of the text kind: `status_refused`, the branch the request schema offered.
- Remote malformed: 6 `not_json` slot variety answers of 3,100 to 3,700 characters (consistent with the 768-token
  answer cap), and 3 `target_not_in_closed_list` plans. The plan schema allowed a `null` target on an image step,
  which the validator rejects (inference from the code; the raw answers were not kept).
- **Worker version (slice 1, done):** `python -m tools.ai_worker_check` reports Ollama 0.40.16 and both model digests
  as recorded. The structured-output bug (ollama/ollama#14645) was fixed by PR #15901, merged 2026-07-07; 0.40.16 is
  later (2026-11-09), and reports put the bug on `/api/chat` while AI Assist uses `/api/generate`.
  **No upgrade is needed.** The bug does not explain the measured failures.

## Scope

1. Remove the refusal branch from the schema and the instruction text. A refusal is still surfaced when it happens
   (D5, invariant 6): explicit `status: "refused"`, refusal-shaped plain text, or a refusal written into the answer's
   own content.
2. Plan steps get one schema shape for image stages and one for the video stage.
3. One retry of a remote request after a malformed answer, with a tighter instruction. Never after a refusal, a
   transport failure or a cancel. The event log records `attempts` and the first attempt's reason.
4. `tools/ai_assist_replay.py`: score the event log, replay synthetic fixtures, and run a live before/after
   comparison (owner approval required).
5. Motion-phrase helper on the V1 prompt-only panel, with Undo.
6. Candidate list of uncensored builds (no download).

## Exclusions

Model change or download; Ollama upgrade; any change on the Proxmox host; local CPU retry; AI visual qualification
tracks (`config/ai_visual_candidates.json` stays unreadable from `src/`); anything that queues a job.

## Acceptance

| id | criterion | evidence |
|---|---|---|
| A1 | No request schema or instruction offers a refusal | tests |
| A2 | A refusal in any of the three forms is `REFUSED_BY_MODEL`, never a suggestion | tests |
| A3 | Malformed once then valid gives a suggestion with `attempts` 2; twice gives `MALFORMED`; refusals are not retried | tests |
| A4 | The replay tool prints counts and codes only | tests |
| A5 | The motion button writes only the Motion field, only if source, prompt and field are unchanged since the press; Undo restores it | tests |
| A6 | The image sent is downscaled, re-encoded without metadata, and sent only to an approved vision-capable remote model | tests |
| A7 | PR gate, `tests/ai_assist`, `tests/system`, `tests/tools` pass | run output |
| G1 | Live: refused under 5%, malformed under 1% | **owner-approved live replay, not yet run** |

## Offline limits

The log has no prompts, so the 104 requests cannot be re-sent. Offline "after" rates are not measurable: removing the
refusal branch and retrying change what the model generates. The live replay uses cases rebuilt in memory from the
owner's prompt packs in the log's kind mix, and runs the old and new contracts on identical cases.

## Controller Surface Assessment

No ratcheted controller changes. `AiAssistIntegration.submit` is reused unchanged.

## Token-efficient validation plan

Focused AI Assist tests per slice; `tests/ai_assist`, `tests/gui_v2` AI and video workflow tests after the GUI slice;
the PR gate, `tests/system` and `tests/tools` once on the final tree.

## Risks

- The grammar can no longer express a refusal, so the model may answer with unusable content instead. The content
  check catches refusal wording only; the live replay reports it.
- First time an image (potentially explicit) is sent to the AI worker, over the same operator-managed SSH forward.
- The instruction frame changes bytes (`ai_assist.frame/2`). The held AI-111 text qualification contract must be
  re-frozen against it before any qualification run.
