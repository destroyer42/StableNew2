# AI-guided experience (research contracts)

**Status: PROPOSED research contracts. Nothing here authorizes implementation, model download, new execution authority or telemetry.** Baseline reality: Offline AI Assist is disabled and unqualified (EV-35). Invariants that already exist and bind every tier: AI output is never an executable job; deterministic engine and `ModelPolicy` stay authoritative; Accept revalidates a full source fingerprint; AI yields to generation and GPU quarantine; refusals are surfaced, never sanitised; nothing derived from prompts is persisted beyond digests/counts/codes ([AI_ASSIST](../../Subsystems/AiAssist/AI_ASSIST.md) §2, §8).

## 0. Owner direction recorded 2026-11-05

- **Model-assisted planning is wanted before offline qualification completes** (DR-A11): models are tested by being used. This research cannot lift the repository's qualification holds (`AI_ASSIST.md`, `STATUS.md`: D12b, ETW canary); how the two reconcile is DR-O11. Until then, anything model-assisted is labelled *unqualified/experimental* in this document's contracts.
- **Approval offers two choices** (DR-A13): *Send to Preview*, or *Send to Preview and queue immediately* (equivalent to clicking Queue on the resulting preview). The AI never submits; the operator's click does, through the normal path.
- **Telemetry:** local only, 90-day retention (DR-A12). Signals and opt-in default are open (DR-O5b).

## 1. Tier model

| Tier | Contract | Authority | Output |
|---|---|---|---|
| **1 Explain and suggest** | Recommends settings, explains model compatibility and trade-offs, "why is this disabled?" | None. Each suggestion has visible **Apply** / **Dismiss**; Apply edits only the current draft and is revalidated | Text or a typed single-field change |
| **2 Goal → editable plan** | Operator writes a goal; AI proposes a *structured, editable plan*; deterministic policy validates models, settings, assets, capabilities, prerequisites; operator approves/modifies/rejects | Approval produces ordinary **Intent**, then the canonical Compiler → NJR → queue path. **AI never submits** | A plan object (steps, parameters, rationale, validation status per step) |
| **3 Guided multi-step** | Suggests sequences (edit existing image, image→video, asset prep, multi-stage refinement, controlled Learning experiments) | Each step is **independently admissible**; one approval never grants unknown future operations or bypasses runtime/safety gates | An ordered list of separately approvable plans |

Tier N+1 is not unlocked by Tier N shipping; each needs its own qualification and owner authorization.

## 2. Governance rules (all tiers)

1. **Closed vocabulary.** A plan may reference only entries from deterministic closed lists (models via the existing picker policy, workflows with governance state, installed assets, valid stages). Free text is never a parameter value after validation.
2. **Deterministic validator is the judge.** Every step is classified `valid`, `incompatible (reason)`, `unavailable (missing prerequisite)`, or `needs operator input`; invalid steps are shown, not repaired silently.
3. **No silent routing.** Backend/engine selection comes only from a verified capability-policy decision that is shown and overridable where legal; experimental workflows keep their per-job opt-in; a frozen NJR is never edited.
4. **Plan ≠ job.** Approval creates Intent; every NJR is frozen through Preview. The operator then chooses one of two explicit actions (DR-A13): **Send to Preview** (stop there; Add to Queue is a separate click) or **Send to Preview and queue immediately**, which behaves exactly as if Queue had been clicked on that preview. In both, admission checks are identical to the manual path; "queue immediately" is never available for a plan with a step that is `incompatible`, `unavailable` or `needs operator input` (proposed; confirm in DR-O6b).
5. **Bounded.** Max steps, max jobs, max images/frames and resource ceilings per plan; exceeding shows a refusal (cf. frozen-plan limits in the journey harness).
6. **Provenance.** Plan, validator version, model identity (hash), suggestion text digest and operator edits are recorded as digests/codes only, consistent with the existing privacy rule (no prompt content in logs).
7. **Failure-closed.** Model absent, refusing, timed out, or admission refused → the manual path is unchanged and the reason is shown.

## 3. Hallucination and incompatibility controls

| Risk | Control |
|---|---|
| AI names a nonexistent model/LoRA | Closed-list resolution; unmatched names are shown as "not installed" |
| AI proposes unsupported backend/combination | `ModelPolicy`/capability policy and cross-workflow compatibility preflight decide; AI text never selects |
| Plan drifts from the operator's goal | Plan shows the parsed goal; each step carries a one-line reason; "Compare to my goal" is a deterministic checklist, not an AI opinion |
| Unsafe scope growth (Tier 3) | Per-step approval; budgets; no step may enable another step's approval |
| Stale context | Source fingerprint (pack/session/slots/model/visibility) rechecked at Accept; changed context invalidates |
| Sensitive prompts | Local only; refusals surfaced and never sanitised (D5); no training capture (D7) |
| Over-trust | Label confidence only if calibrated; otherwise do not show a score. Use evidence classes as in *What Should I Test Next?* (policy fact / research claim / controlled observation / subjective preference) |

## 4. Automation opportunities (candidates, deterministic-first)

Pre-fill readiness fixes ("start Forge", "select the matching model") as one-click *offers*, never auto-actions on external runtimes; pre-select the recommended approved video workflow (already done for Make Video); suggest Compare-with-Parent after an edit; propose the next safe Learning test (already deterministic); resume suggestions after interruption; batch triage. Each is a Tier-1 candidate **without** a language model.

## 5. Tier-by-tier open research questions

T1: Which operator questions can be answered deterministically? T2: What is the plan schema and who owns it (must not become a second job model)? T3: What is the smallest useful multi-step sequence (e.g., *edit region → animate*) and what does "independently admissible" look like in the UI? Q: Does any use need a model larger than the CPU-only v1 envelope?

## 6. Experience-improvement monitoring (optional, local, deterministic first)

**Not built here; requirements only.**

**Candidate signals (counts and codes, no content):** extra navigation (tab switches between prompt and queue), repeated action loops, workflow abandonment (opened, not queued), failed readiness attempts, disabled primary action viewed without success, repeated settings changes with no downstream change, queue/admission mismatches, inconsistent effective model settings, repeated errors/crashes, journey duration and operator-intervention counts (the golden-path comparator's `extra_interaction_count`, `lost_clicks`, `click_retries` already model this offline).

**Requirements before any collection:**

| Area | Requirement |
|---|---|
| Consent | Off by default; explicit opt-in; granular per signal class; revocable; visible indicator when on |
| Privacy | No prompts, paths, image/video content, model file names or hashes of user content; only event codes, counts, durations, app/feature version; local-only storage; no network |
| Retention | **90 days, local only (owner, DR-A12)**; size cap and user-visible "view / export / delete all" proposed; deletion is real |
| Control | Never changes settings or behavior; summaries are suggestions with cited events; uncertainty stated |
| Integrity | Deterministic checks produce the findings; a language model, if ever used, may only *summarize* cited events, never create evidence |
| Isolation | Separate store from the job repository; no queue/history authority; failure-closed |
| Scope | Disabled during physical qualification runs |

**Falsification:** if a signal cannot be defined without content, it is out of scope. The Windows-driver comparator is the existing, offline substitute for operator-journey metrics and should be exhausted before runtime telemetry is considered.

## 7. Items needing owner decisions

Answered: DR-A11 (model-assisted planning wanted now), DR-A12 (local, 90 days), DR-A13 (two approval options). Still open: DR-O11 (reconciling DR-A11 with the repository's qualification holds), DR-O5b (signals and opt-in default), DR-O6b (scope and disabled-state rules for "queue immediately").
