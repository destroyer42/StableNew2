# Decision handoff (final decision documentation; research/documentation session close)

**Status: handoff. Nothing here authorizes a push, PR, merge, production change, GPU/Forge/SVD activity, prototype, or AI policy change.** The owner accepted the documentation milestone *provisionally*; research qualification remains incomplete (DR-A32). This file consolidates the round-3 owner response (DR-A32 to DR-A38), reproduces the five AI-amendment proposals **verbatim** for adjudication, and points the next execution session at its bounded contract ([NEXT_SESSION_B2_B3_B5_CONTRACT.md](NEXT_SESSION_B2_B3_B5_CONTRACT.md)).

## 1. Round-3 dispositions in one table

| Topic | Owner decision | Status | Where recorded |
|---|---|---|---|
| Milestone | Accept the documentation milestone provisionally; qualification incomplete; no production change, GPU activity, publication or merge | accepted | DR-A32 |
| B2, B3, B5 | Approved **together as one bounded desktop-measurement session**, subject to preconditions (gate and pytest finished; **owner confirms the desktop is free**; disposable data; no generation/backend/restart/GPU; stop on interference, unexpected mutation or safety concern). Desktop availability is **never inferred** from "no pytest process" | approved, **conditional**; **not run** | DR-A33; contract file |
| B4 | **Not approved.** Separate approval requested immediately before changing display scaling, with original setting, restoration procedure and post-restoration verification | not approved | DR-A33; contract section 6 |
| Create Image directions | Recorded as accepted **product intent**, distinct from implemented behavior and from approved engineering scope; conflicts with existing authority identified, not overwritten | recorded | DR-A34; [workflows/create-image.md](workflows/create-image.md) |
| AI amendment | Policy direction recorded (Tier-1 advisory first; advice distinguishable from an execution plan; candidate evaluation via the existing authorized harness; per-download/per-inference authorization; lower priority than generation; physical GPU and qualification holds). **Not enacted. D-1 to D-5 are not adjudicated; no semantic widening is authorized until the owner reviews their exact text (section 2)** | direction recorded; decisions **pending** | DR-A35 |
| Qt licensing | **LGPL-3.0 as the provisional evaluation route**, limited to QtCore, QtGui, QtWidgets. Not GPL; no commercial purchase now. Module-level and third-party compliance review (attribution, source availability, library replacement, packaging) and a qualified software-licensing/legal reviewer **before any redistribution**. If LGPL is impractical, present the commercial route as a decision with evidence | provisional | DR-A36; [QT_PACKAGING_ASSESSMENT.md](QT_PACKAGING_ASSESSMENT.md) section 8 |
| Tk DPI awareness | Approve **experimental** DPI awareness for COA A0, **isolated from the production application**; measure current Tk behavior first; use equivalent scaling and DPI-awareness configurations for Tk-vs-Qt comparison; verify widget dimensions, text scaling, hit targets, clipping, screenshot consistency; **no change** to production DPI or global Windows display settings | approved (experimental, isolated) | DR-A37; [COMPARATIVE_PACKAGE_PROPOSAL.md](COMPARATIVE_PACKAGE_PROPOSAL.md) section 6a |
| Session boundary | Close this session after the decision documentation; the next execution session uses the **exact recorded branch and SHA**, the existing artifacts, and a narrowly bounded B2/B3/B5 contract, and does **not** repeat completed research, reviews or green validation; B4 stays separate; the comparative prototype stays a future package | accepted | DR-A38 |

## 2. AI amendment proposals D-1 to D-5 (verbatim) with recommended resolutions and existing-rule conflicts

The five proposals are copied **unchanged** from section 6 of [PROPOSED_AI_ASSIST_AMENDMENT.md](PROPOSED_AI_ASSIST_AMENDMENT.md) (the owner's round-3 reply said they were not in the status report it received):

| ID | Decision | Options | Recommendation (not a decision) |
|---|---|---|---|
| D-1 | Adopt the `PLAN_PROPOSAL` kind and R1–R4, R7–R10 as drafted? | (a) yes, as an implementation package after this research; (b) yes but Tier-1 only first (no plan object, advice only); (c) no | (b) then (a): Tier-1 needs no new kind or invariant change and is testable without a model (deterministic offers, EV-36/37). |
| D-2 | How may unqualified candidate models be exercised for planning? | (a) only through the existing qualification harness (no application change; `allow_candidate=False` stays); (b) application-level `allow_candidate=True` only inside a per-session, per-inference owner-authorized, visibly labelled *evaluation* session; (c) not before qualification | (a) for now: it satisfies "test the models by using them" with zero change to application composition; revisit (b) after the first candidate passes the safety gates. The owner may prefer (b); then R6 is required. |
| D-3 | Wording of invariant 2 (R3). | as drafted / stricter (plan approval only creates a Preview, never a queue admission, which would remove the "Confirm & Queue" shortcut) | As drafted, because DR-A24 already requires a visible preview and an explicit confirmation. |
| D-4 | Are planning proposals allowed while a job is RUNNING? | refuse (P5, current D10 behavior) / allow when the model is CPU-only | Refuse. The measured 742/AI-assist design rests on D10; relaxing it needs its own evidence. |
| D-5 | Who authorizes the first physical planning inference? | named owner authorization per inference (current rule) / session-level authorization | Keep per inference (preserves the owner's stated requirement). |

**Owner policy direction (round 3), not an adjudication.** The owner's six principles bear on these proposals as follows; none replaces the exact text review:

| Owner principle | Bears on | Observation |
|---|---|---|
| Tier-1 advisory planning first | D-1 | Consistent with D-1(b). Clarification found while preparing this handoff: single-item advice (prompt rewrite, target fit, workflow choice) already fits the three existing `AssistSuggestion` kinds and needs **no** amendment, but *advisory planning* (an ordered list of steps) is a new kind (R1, R2, plus R4, R7, R8). It does **not** need R3 (the invariant-2 widening), because an advisory plan has no approval-to-Preview path. D-1(b)'s phrase "Tier-1 needs no new kind or invariant change" is therefore accurate only for single-item advice. |
| Advice visibly distinguishable from an authorized execution plan | D-1, D-3 | Not yet a rule in the draft. Proposed addition (not applied): an `ADVISORY` artifact can never enter the Confirm & Queue path and is labelled differently from a validated, approvable plan. |
| Candidate evaluation uses the existing authorized harness; no second execution or scheduling authority | D-2 | Matches D-2(a); makes R6 (`allow_candidate=True` in the application) unnecessary. |
| Preserve explicit per-download and per-inference authorization | D-5 | Matches D-5 "per inference". D-5's "session-level" alternative would conflict with this principle. |
| Planning is lower priority than active generation | D-4 | Matches D-4 "refuse" (D10 behavior). |
| Preserve physical GPU and qualification holds | all | Preserved by section 2 of the draft; nothing in D-1 to D-5 lifts a hold. |

| ID | Recommended resolution | Existing rules the alternatives would conflict with | Owner status |
|---|---|---|---|
| D-1 | (b) Tier-1 first, with the clarification above: single-item advice needs no change; advisory planning needs R1, R2, R4, R7, R8 but not R3; defer R3 and Tier-2 until Tier-1 is measured | `AI_ASSIST.md` section 1 (three suggestion kinds), section 3 (kinds list and closed lists), section 8 invariant 2 (only for Tier-2 via R3), `STATUS.md` line 135 (one-line cap; holds on D12b and the per-session ETW canary; S2 onward not authorized) | **PENDING** |
| D-2 | (a) candidate models only through the existing qualification harness; keep `allow_candidate=False` in the application | Alternative (b) conflicts with section 4 ("`allow_candidate=False` and `strict_offline=True`"), section 5 (a registered candidate is "usable only with `allow_candidate`, for the qualification harness"), and the owner's no-second-authority principle | **PENDING** |
| D-3 | As drafted, but only when Tier-2 is considered; moot for Tier-1 | Section 8 invariant 2 ("Accept into an editing buffer"); the "stricter" alternative (approval only creates a Preview) contradicts DR-A24's Confirm & Queue; `EXPERIENCE_ARCHITECTURE` section 5 item 1 | **PENDING** |
| D-4 | Refuse planning requests while a job is RUNNING (current D10) | D10 and section 4 "AI yields to generation"; invariant 5. The "allow when CPU-only" alternative would contradict them and the owner's lower-priority principle | **PENDING** |
| D-5 | Keep authorization per download and per inference | Section 7 ("a physical run needs named authorization for each download, for inference, and a quiet host"); the session-level alternative contradicts it and the owner's principle | **PENDING** |

Until the owner adjudicates the exact text above, **no semantic widening is authorized** and `AI_ASSIST.md`, `STATUS.md`, `config/` and the ratchets stay as they are.

## 3. Create Image product intent (recorded; details in the workflow file)

Owner product directions: **Hybrid Create Image**, **automatic model profiles**, **customizable basic interface**. They are recorded as *accepted product intent*, not as implemented behavior and not as previously approved engineering scope. The October 24 IMG-PROFILE-630 / LEARN-PROFILE-660 planning is related and **is** implemented and merged on `main`. What exists, what does not, and the conflicts with existing authority are in [workflows/create-image.md](workflows/create-image.md) section "Owner product intent (2026-11-05)".

## 4. Open items for the owner after this handoff

| ID | Item | Needed for |
|---|---|---|
| DR-O11b | Adjudicate D-1 to D-5 (section 2) | any AI-assist amendment |
| DR-O21 | Confirm, **at the start of the execution session**, that the Windows desktop is free for exclusive automated control (typed in chat; process absence is not enough) | B2/B3/B5 |
| DR-O22 | Name the qualified licensing/legal reviewer and the point at which the LGPL compliance review happens (before any redistribution) | Qt redistribution |
| DR-O23 | Per-edit confirmation of what "preserve valid user overrides" must mean when a model is re-selected (see create-image.md gaps) | Create Image profile work |
| DR-O24 | Request/approve B4 only when it is time (original setting, restoration, verification) | real 125%/150% runs |
| DR-O12b | Open the comparative package (after B2/B3/B5, B4 or a documented alternative, and the licensing assessment) | COA A0 vs COA B |

## 5. Session boundary

This research/documentation session ends with this handoff. Do not repeat: the evidence register, the independent review, the validation of the documentation set (link check, `git diff --check`, docs-only classification, completeness and CI-truth), the B1 pixel measurements, the Qt module/size audit, the token-variance investigation. The next execution session follows [NEXT_SESSION_B2_B3_B5_CONTRACT.md](NEXT_SESSION_B2_B3_B5_CONTRACT.md) exactly, including its kickoff text.
