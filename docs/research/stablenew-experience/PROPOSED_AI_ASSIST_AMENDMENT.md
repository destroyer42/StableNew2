# Proposed amendment: AI-assisted planning (DRAFT FOR OWNER DECISION — NOT ACTIVE)

**Status: draft text for review. Nothing in this file changes `AI_ASSIST.md`, `STATUS.md`, `config/`, code, tests or any hold. The policy change is presented as a decision (section 6), not as an approved implementation.** Requested by the owner on 2026-11-05 (DR-A25) after the owner chose model-assisted planning before qualification completes (DR-A11). Quoted text is from `docs/Subsystems/AiAssist/AI_ASSIST.md` and `STATUS.md` at `ed1e989f`.

## 1. Vocabulary (the distinctions the owner asked for)

| Term | Meaning in this draft | Touched by this draft? |
|---|---|---|
| **Planning assistance** | A new, typed, validated *proposal* produced by one bounded offline model request: an ordered list of steps drawn from closed lists (models, workflows, assets, stages), each with a rationale. It is text for an operator review surface. It has no authority and no submit path. | **Yes — the only new capability proposed.** |
| **Generation** | Image/video/audio production by the canonical Intent → Compiler → NJR → JobService → Queue → runner path, including any GPU work. | **No.** Unchanged. Planning is subordinate to it (section 3, rule P5). |
| **Candidate evaluation** | Running a registered-but-unqualified model (`qualified: false`) to measure it (`allow_candidate=True`, the PR-AI-111 harness). | **Decision D-2** below; today only the qualification harness may do this. |
| **Download / import** | Acquiring or installing a model or runtime file. | **No.** Every download or import keeps its own named authorization. |
| **Inference** | Launching the contained one-shot child to produce model output. | **No relaxation.** Every physical inference keeps its own named authorization and the existing gates. |

Planning assistance **is** inference when it uses a model. This draft therefore does not create a way to infer without the existing authorization; it only defines what a planning request may *return*.

## 2. What stays exactly as it is (preserved on purpose)

1. **Per-operation authorization.** `AI_ASSIST.md` §7: "a physical run needs named authorization for each download, for inference, and a quiet host". Preserved verbatim.
2. **Runtime ownership.** §2 and §4 "Composition and shutdown": one application-owned `AiAssistIntegration`, built after the production JobService, fenced and joined at shutdown before repository closure; single-flight; `run_bounded` only; no server, socket or resident process; `AiCancelToken` request-scoped.
3. **Physical holds.** `STATUS.md`: "qualification remains held on D12b and a per-session ETW canary capture", S2 onward not authorized. No planning feature lifts them; a first physical planning inference needs the same authorization any inference needs.
4. **CPU-only, offline, contained** (D2, D3, D8; §4 first bullet; invariant 4). No GPU, no network, no `-hf`/`--host`/`--port`.
5. **Hash pinning and no operator override** (D6; §5; invariant 3).
6. **Refusals surfaced, never sanitised** (D5; invariant 6) and **no training capture** (D7).
7. **No AI authority over the queue.** The import ratchet `ai_assist_forbidden_imports` (queue, repository, job service, runner, NJR core, backends, GUI) is unchanged; a plan is converted to Intent **outside** `src/ai_assist`, by the existing GUI/controller path, after operator approval.
8. **Physical GPU qualification hold.** Nothing here authorizes GPU, Forge or SVD qualification activity.

## 3. Rules the amendment would add (all restrictive toward the model)

- **P1 Closed vocabulary.** A plan step may carry only identifiers from closed lists supplied with the request (the same technique as `WORKFLOW_CHOICE`); free text is rationale only and is never an executable value.
- **P2 Deterministic judge.** Each step is re-validated by `ModelPolicy`, cross-workflow compatibility, readiness and prerequisite checks and classified `valid | incompatible(reason) | unavailable(prerequisite) | needs operator input`. The model never classifies its own output. Invalid steps are shown, not repaired.
- **P3 Bounds.** Maximum steps, maximum jobs, maximum images/frames per plan; exceeding is refusal, not truncation.
- **P4 Operator approval is the only door.** An approved plan creates ordinary Intent that compiles to a frozen preview. The owner's accepted options (DR-A24): the frozen preview is a **mandatory visible confirmation**; the operator reviews the resolved workload and selects **Confirm & Queue**. "Immediately" means immediate admission *after* that confirmation, through the existing JobService/SQLite queue, never GPU execution or a bypass. Applies to confirmed Tier-2 plans; Tier-3 steps stay individually operator-controlled.
- **P5 Subordinate to generation.** Admission of a planning request is refused while a queue job is RUNNING, a GPU quarantine is active, or generation activity cannot be read; an in-flight planning request is terminated on the same conditions (D10, unchanged code paths: `GENERATION_ACTIVE`, `YIELDED_TO_GENERATION`). A job approved from an earlier plan may be *queued* while another job runs, and waits in the normal queue (DR-A24 item 4); only *new planning requests* are refused.
- **P6 Failure-closed.** Model absent, refusing, timed out, malformed, or admission refused: the manual path is unchanged and the outcome code is shown.
- **P7 Privacy.** The event log keeps its whitelist (codes, counts, 12-character digests). Plan content is not written to `events.jsonl`; an approved plan persists only as the normal Intent/NJR/history records the canonical path already stores.

## 4. Exactly which existing restrictions would need modification

| # | Location (current wording) | Proposed change | Needed for | Risk / note |
|---|---|---|---|---|
| R1 | `AI_ASSIST.md` §1: "turns one explicit operator request into a **typed, validated suggestion**: a prompt rewrite, a target-fit choice or a workflow choice" | Add a fourth kind, `PLAN_PROPOSAL`, as a typed suggestion. | Planning assistance | New schema, validator and tests; the kind still "has no field that can become an executable payload" if steps carry only closed-list IDs plus parameters from closed domains. |
| R2 | `AI_ASSIST.md` §3: "`AssistSuggestion` kinds: `PROMPT_REWRITE`, `TARGET_FIT_ADVICE`, `WORKFLOW_CHOICE`" and the "closed lists" sentence | Extend the kind list and closed-list sources (models, workflows with governance state, installed assets). | Planning assistance | Closed lists must come from existing policy, not from the model. |
| R3 | `AI_ASSIST.md` §8 invariant 2: "AI never edits authored intent without an explicit operator Accept into an editing buffer" | Amend to: "…explicit operator Accept into an editing buffer, **or** explicit operator approval of a plan that produces a frozen Preview (Confirm & Queue)". The model still never edits intent; the *operator's* approval creates it. | Tier-2 approval | This is the one real semantic widening; it is why DR-A24's mandatory visible preview matters. |
| R4 | `AI_ASSIST.md` §1: "It sits *before* Intent as an authoring aid" | Clarify that plan approval is an operator action in the GUI layer, still before Intent. | Clarity | Wording only. |
| R5 | `AI_ASSIST.md` §4 / §8 invariant 5 and D10 | **No change**, restated so P5 is explicit. | Subordination | Test coverage for plan requests under RUNNING/quarantine/unreadable. |
| R6 | `AI_ASSIST.md` §4 "Composition": "`allow_candidate=False` and `strict_offline=True`" | **Only if the owner selects D-2(b)**: allow candidate models for *planning evaluation* in an explicitly authorized, labelled session. Otherwise unchanged. | Testing models by using them (DR-A11) | See D-2. Never default-on; never a global switch (cf. DR-A2). |
| R7 | `AI_ASSIST.md` §7 qualification criteria | Add planning criteria *proposals* (valid-plan rate under closed lists, deterministic-validator agreement, zero out-of-list references, plan-bound compliance, refusal handling), frozen before any run. | Measuring planning quality | Criteria are proposals; thresholds not set here. |
| R8 | `AI_ASSIST.md` §6 privacy | State that plan content is not logged (P7). | Privacy | Consistent with D7. |
| R9 | `STATUS.md` line 135 | Replace by the one-line text in section 5. STATUS is "at its line cap; keep this subsystem to one line there". | Truthful status | One line only. |
| R10 | `tests/tools/test_architecture_ratchets.py` | **No change to `ai_assist_forbidden_imports`.** Add a check that `PLAN_PROPOSAL` conversion code lives outside `src/ai_assist`. | Guarding invariant 1 | The existing test asserts that no real `src/ai_assist/` path violates the rule (its `1` values are counts for synthetic forbidden imports, not a baseline). |

## 5. Proposed `STATUS.md` replacement (one line; not applied)

> Offline AI Assist has application-owned queue observation/shutdown and Prompt-tab Suggest/review/explicit rewrite acceptance; Suggest remains disabled without a qualified installation. A planning-assistance proposal (typed `PLAN_PROPOSAL`, closed lists, deterministic validation, operator-confirmed frozen preview, subordinate to generation) is drafted for owner decision in `docs/research/stablenew-experience/PROPOSED_AI_ASSIST_AMENDMENT.md` and is **not active**. Nothing is installed or physically executed, all models are NOT TESTED, and qualification remains held on D12b and a per-session ETW canary capture (…existing runbook and LFM3 sentence unchanged…); every download and every inference still needs its own named owner authorization.

(The ellipsis marks the existing runbook/LFM3 text, which would be kept verbatim.)

## 6. Decisions required from the owner

| ID | Decision | Options | Recommendation (not a decision) |
|---|---|---|---|
| D-1 | Adopt the `PLAN_PROPOSAL` kind and R1–R4, R7–R10 as drafted? | (a) yes, as an implementation package after this research; (b) yes but Tier-1 only first (no plan object, advice only); (c) no | (b) then (a): Tier-1 needs no new kind or invariant change and is testable without a model (deterministic offers, EV-36/37). |
| D-2 | How may unqualified candidate models be exercised for planning? | (a) only through the existing qualification harness (no application change; `allow_candidate=False` stays); (b) application-level `allow_candidate=True` only inside a per-session, per-inference owner-authorized, visibly labelled *evaluation* session; (c) not before qualification | (a) for now: it satisfies "test the models by using them" with zero change to application composition; revisit (b) after the first candidate passes the safety gates. The owner may prefer (b); then R6 is required. |
| D-3 | Wording of invariant 2 (R3). | as drafted / stricter (plan approval only creates a Preview, never a queue admission, which would remove the "Confirm & Queue" shortcut) | As drafted, because DR-A24 already requires a visible preview and an explicit confirmation. |
| D-4 | Are planning proposals allowed while a job is RUNNING? | refuse (P5, current D10 behavior) / allow when the model is CPU-only | Refuse. The measured 742/AI-assist design rests on D10; relaxing it needs its own evidence. |
| D-5 | Who authorizes the first physical planning inference? | named owner authorization per inference (current rule) / session-level authorization | Keep per inference (preserves the owner's stated requirement). |

### 6a. Owner round-3 direction and clarifications (2026-11-05; no decision on D-1 to D-5 yet)

The owner gave a **policy direction** (Tier-1 advisory planning first; advice visibly distinguishable from an authorized execution plan; candidate evaluation through the existing authorized harness with no second execution or scheduling authority; per-download and per-inference authorization preserved; lower priority than generation; physical GPU and qualification holds preserved) and said it **does not substitute for adjudicating the exact text** of D-1 to D-5. No semantic widening is authorized until that review. Clarifications found while preparing the decision handoff (see `DECISION_HANDOFF.md` section 2):

- Single-item advice fits the three existing `AssistSuggestion` kinds and needs no amendment; *advisory planning* (ordered steps) needs R1, R2, R4, R7, R8 but **not R3**, because an advisory artifact has no approval-to-Preview path. D-1(b)'s wording "no new kind or invariant change" is accurate only for single-item advice.
- Proposed (not applied) rule **P8: advice is not a plan.** An `ADVISORY` artifact is labelled differently from a validated, approvable plan and can never enter the Confirm & Queue path.

## 7. Facts to settle before any activation

- Run `tests/ai_assist` and `tests/tools/test_architecture_ratchets.py` (per `AI_ASSIST.md` §9) on the exact SHA before any activation; this research did not run them.
- The registry holds four unqualified candidates plus a frozen LFM3 contract; none has run (`STATUS.md`). No planning-quality data exists.
- Closed-list sources for plan steps (video workflows with governance state, asset inventory) exist for deterministic readiness but have not been assembled into a single "plan vocabulary"; that is part of D-1(a)'s package.
- This draft was written by the research session; it has not been reviewed by the `AI_ASSIST` authors or run against the ratchet tests.

## 8. Non-goals

No code, config, manifest, model download, runtime import, or inference; no change to Forge/SVD/GPU holds; no second queue or runner; no activation.
