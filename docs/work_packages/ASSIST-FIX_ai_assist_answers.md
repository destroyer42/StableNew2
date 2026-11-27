# ASSIST-FIX: AI Assist answers reliably

Status: merged as PR #472 (2026-11-27); the follow-up below is on its own branch. With the follow-up the current
model measured 0.0% refused and 1 malformed in 208 requests over two samples (1.0% and 0.0% per sample). Package 9 of
the 2026-11-27 Value Assessment.

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
5. Motion-phrase helper on the V1 prompt-only panel, with Undo. This amends AI Assist invariant 10: the remote
   `MOTION_PHRASE` request is now a product path that sends a picture (owner to accept at merge).
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
| G1 | Live: refused under 5%, malformed under 1% | PR #472: refused 0.0%, malformed 1.9% (not met). Follow-up: refused 0.0%; malformed 1.0% on seed 1 (at the line, not under it) and 0.0% on seed 2 |

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

## Offline result

`score` and `offline` on the log (104 requests; answered = 90):

| | refused | malformed |
|---|---|---|
| before (measured) | 25: 24.0% of all, 27.8% of answered | 11: 10.6% / 12.2% |
| after, if the model complies with the new contract | 0% | 0% |
| after, if the model repeats each logged failure | 24.0% | 10.6% |

The two "after" rows are the ends of a range, not a prediction: no model ran. `offline` shows only that the new
service classifies and retries each logged failure class as intended.

## Live replay result (2026-11-27, owner-approved)

Source `f5f31446` (request path unchanged since), `qwen3.5:4b-q4_K_M` on Ollama 0.40.16, seed 1, 104 rebuilt cases,
every case answered. No motion pictures were sent.

| arm | suggestion | refused | malformed | worker seconds |
|---|---|---|---|---|
| old contract, no retry | 84 | 5 (4.8%) | 15 (14.4%) | 307 |
| new contract, one retry | 102 | 0 (0.0%) | 2 (1.9%) | 373 |

- Old-contract malformed: 11 plan `target_not_in_closed_list` (11 of 18 plans), 4 `slot_repeated`. The plan schema
  change removed all 11.
- New contract: 3 first attempts were malformed, the retry recovered 1. Left: 1 `slot_repeated` (slot variety; the
  array schema cannot forbid naming a slot twice) and 1 `protected_tokens_changed` (rewrite).
- Every suggestion in both arms passed the slot-variety judge where it applies; quality was not judged.
- **Limits:** the old contract refused only 4.8% here against 24% in the log. Goals were neutral placeholders, not the
  owner's, so refusals under the owner's own goals are **not demonstrated**. The truncated answers in the log did not
  recur. One seed, one run.
- **Next candidate (not done):** say "one entry per slot" in the slot-variety instruction, give the retry the failure
  reason, and re-measure with another seed.

## Owner decisions (2026-11-27, relayed by the orchestrating session)

- Invariant 10 amendment: "Accept". Motion Suggest may send the reduced 512 px, metadata-stripped picture to the AI
  worker.
- Uncensored trial: "Yes, try it". Pull `huihui_ai/qwen3.5-abliterated:4B` beside the current model and run the replay
  with both. The current model stays the default; switching needs the owner's OK on the result.
- Orchestrator adjudication on 1.9% malformed: merge #472 as is, then fix in a follow-up.

## Follow-up: wording, retry reason, and the two-model replay

Changes (frame `ai_assist.frame/3`): the slot-variety instruction says one entry per slot; the retry adds a fixed
sentence chosen by the first attempt's reason code (nothing from the answer is quoted); `live --model` measures an
installed model without adding it to the application's approved list.

**Model added to the AI worker** (Ollama `/api/pull` over the existing forward; nothing else changed on the host):

| name | digest | bytes | capabilities | licence (`/api/show`) |
|---|---|---|---|---|
| `huihui_ai/qwen3.5-abliterated:4B` | `9acbd90c2645120ea1e4a5fe7ec9c4fe000e547ccebc8a24f950315d582003e6` | 3,315,333,475 | completion, vision, tools, thinking | Apache-2.0 |

It is **not** approved in the application and is not in `config/ai_worker_manifest.json`.

**Replay, new contract with one retry** (104 rebuilt cases per run; seed 1 is the same 104 as before, seed 2 a new
sample; no pictures). "Usable" is a suggestion that, for slot variety, holds at least one value the application would
offer.

| model | seed | usable | suggestion | refused | malformed | timeout | first attempt malformed | worker s |
|---|---|---|---|---|---|---|---|---|
| current | 1 | 103 | 103 | 0 | 1 | 0 | 2 | 382 |
| uncensored | 1 | 102 | 104 | 0 | 0 | 0 | 0 | 313 |
| current | 2 | 104 | 104 | 0 | 0 | 0 | 0 | 364 |
| uncensored | 2 | 95 | 101 | 0 | 0 | 3 | 0 | 320 |

**Same cases, old contract, no retry:**

| model | seed | suggestion | refused | malformed | timeout |
|---|---|---|---|---|---|
| current | 1 | 83 | 4 | 17 | 0 |
| uncensored | 1 | 91 | 0 | 13 | 0 |
| current | 2 | 85 | 5 | 14 | 0 |
| uncensored | 2 | 90 | 0 | 8 | 6 |

- The one remaining malformed answer is a rewrite that changed a protected token, after its retry.
- **Recommendation: keep the current model.** Under the new contract neither model refused, and the current one gave
  more usable answers (207 of 208 against 197 of 208). The uncensored build's 3 timeouts have no established cause.
- **What this does not show:** refusals under the owner's own goals (goals were neutral placeholders; the one measured
  difference is that the uncensored build did not refuse when a refusal branch was offered), suggestion quality, or
  picture handling by either model.

## Live replay plan (as run, without `--motion-image`)

- **What it does:** 104 cases in the logged kind mix (70 slot variety, 18 plan, 6 target fit, 6 rewrite, 4 slot
  proposal), rebuilt in memory from the owner's PromptPacks, each sent with the old contract (no retry) and the new
  one. About 210 to 230 generations on the AI worker's GPU; at 3 to 13 s each, roughly 10 to 50 minutes.
- **What leaves the PC:** pack prompt text and matrix values, and any `--motion-image` picture, over the existing SSH
  forward to the owner's worker. Goals and the model/workflow lists are neutral placeholders.
- **What it writes:** counts and outcome codes to the console and `--out`. No prompt or answer text; a temporary AI
  root; the owner's event log and approval are only read. Nothing changes on the Proxmox host.
- **Preconditions:** the AI tunnel task is running and `python -m tools.ai_worker_check` reports `match`.

Plan only (sends nothing; verified: 104 cases build from the current packs):

```powershell
python -m tools.ai_assist_replay live --packs "$env:LOCALAPPDATA\StableNew\PromptPacks"
```

Run, after the OK (pictures: ordinary, non-library test sources chosen by the owner):

```powershell
python -m tools.ai_assist_replay live --packs "$env:LOCALAPPDATA\StableNew\PromptPacks" --motion-image <picture> --out reports\ai_assist_replay.json --owner-approved
```

- **Read-out:** G1 passes if the `after` arm shows `refused_pct_of_answered` under 5 and `malformed_pct_of_answered`
  under 1 (at 104 cases that is at most 5 refusals and 1 malformed). Check `usable_suggestions` too: if refusals
  turned into unusable answers, the count will not rise with the refusal fall. The goals are neutral, so the
  measured refusal rate may be lower than with the owner's own goals.
- **Image support is still unverified:** the motion cases are the first picture ever sent to this worker. An HTTP error or
  descriptions unrelated to the picture mean the installed model build does not take images.
- **If G1 fails on refusals:** the next lever is an uncensored build (below), measured with this same command.

## Uncensored builds of the same model (nothing downloaded)

All are third-party edits of `Qwen/Qwen3.5-4B`. Sizes are repository file sizes or Ollama tag sizes as read
2026-11-27. "Vision" decides whether the motion helper would keep working.

| candidate | source | size | licence | vision |
|---|---|---|---|---|
| `huihui_ai/qwen3.5-abliterated:4B` | ollama.com (huihui-ai) | 3.3 GB | not stated on Ollama; HF base repo says Apache-2.0 | yes (tag lists image input) |
| Huihui-Qwen3.5-4B-abliterated Q4_K_M + mmproj | hf.co/mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF | 2.71 GB + 0.37 (Q8) or 0.67 GB (f16) | Apache-2.0 | yes, separate projector |
| Qwen3.5-4B-Heretic Q4_K_M + mmproj | hf.co/darrellbest/Qwen3.5-4B-Heretic-GGUF | 2.78 GB + 0.67 GB | Apache-2.0 | yes, separate projector |
| Qwen3.5-4B-heretic Q4_K_M | hf.co/saidutta69/Qwen3.5-4B-heretic | 2.71 GB | Apache-2.0 | no projector file in the repo |
| `jaahas/qwen3.5-uncensored:4b` | ollama.com | 3.5 GB | not stated | no (text only) |

- **Recommended to try first:** `huihui_ai/qwen3.5-abliterated:4B`: most used (780K pulls shown), packaged for
  Ollama with image input, same size class as the installed model.
- **Unverified:** quality after abliteration (research note 08, findings 7 and 8: damage varies by method), and whether
  Ollama imports a separate Qwen3.5 projector from a Hugging Face GGUF.
- **Adopting one is a separate change:** the approved model names are a closed list in code
  (`remote_preview.MODEL_LABELS`, `VISION_MODELS`), plus `config/ai_worker_manifest.json`, a download on CT 110 and
  the owner's approval of its digest.
