# Shared PROPOSED interaction semantics

The common vocabulary is a presentation contract over existing services. It does not add job states, approval types, schemas or a new recovery manager. Existing mechanisms are source-locked in [A](../ux850-a/OWNERSHIP_BOUNDARY_MAP.md); the detailed routes are [J1–J5](JOURNEYS.md).

## Verbs and visible outcomes

| Verb | Meaning and required feedback | Must remain distinct |
|---|---|---|
| **Apply** | Copy a named proposal/profile/settings source into the identified editable draft/working controls; disclose material differences and compatible-value handling. Invalidate affected executable preview | Save to pack, startup defaults, publication, favorite and execution. Pinning shows a control; locking constrains a value and needs F1 policy |
| **Save / Save As** | Write only the explicitly named existing scope. Show saved identity/revision or clear failure; Save As creates independent identity according to its owner | Navigation, Apply, Queue; do not report a successful durable write as failed merely because refresh failed |
| **Preview** | Present the existing compiler/service's exact result and limitations; show count, effective values, source identity, restrictions and freshness | Readiness-only Storyboard summary versus frozen executable Preview. Preview never dispatches and is not qualification |
| **Submit / Add to Queue / Queue Sequence / Build** | Submit the currently accepted valid snapshot through existing service/compiler → NJR → `JobService.submit_njrs`. Show admitted IDs and actual partial/unknown outcome for that submission contract | Run Now enqueues with immediate-start policy. Movie Build queues assembly. No GUI runner or direct backend action |
| **Review** | Inspect artifact/evidence, verify provenance and record only deliberate supported rating/decision changes | A review is not automatically job success, profile publication, technical qualification or Preferred/Final promotion |
| **Cancel incoming placement** | No-op on both workspaces and navigation before committing replacement; explicit unsent-work gate | Cancelling a dialog never stops already admitted work |
| **Cancel job / existing queue controls** | Ask the canonical lifecycle owner, project acknowledgement/uncertainty, preserve record and result evidence | No direct process kill or fictitious new lifecycle. Cancel and Return uses current positive-dispatch/no-dispatch rules |
| **Recovery / Retry / Resume** | State what failed, what is known saved/admitted/dispatched, affected identity and the owning safe action. Verify existing jobs/files/checkpoints first | Never blind POST replay, inferred success, adoption/restart of external process, implicit changed-plan resume or repaired qualification |

## State and freshness rules

| Situation | Proposed response / owner boundary |
|---|---|
| Model/profile, prompt, source, mask, stage, count, workflow or relevant evidence changes | Mark affected Preview/approval stale and re-preview. Show changed values; do not mutate admitted NJRs. A harmless view expansion is not a material edit |
| Preview result arrives after a newer request | Discard superseded projection; preserve current draft. Use existing dispatcher/query ownership; no second reconciliation loop |
| Hard restriction conflicts with requested value | Refuse affected action with cause and compatible manual route; no silently ignored lock. Uncertainty/untested status alone is not a fabricated hard ban |
| Adaptive confirmation requested (UX-DEC-004 / A F4 / DR-A24) | Retain current explicit Preview/admission behavior in the recommendation. Present possible fast-path design for later owner choice; do not resolve this conflict by merging research |
| Unsupported advanced capability | Show an honest unavailable/held explanation in its relevant context and existing manual alternative. No clickable fictional timeline/evaluator/campaign control |
| Empty/no match/missing file/hidden content | Distinguish all four. Offer create/import, clear filter, verify/relink via owner, or deliberate visibility action respectively; never scan or load hidden bytes simply to fill the panel |
| Partial compile/admission | Show excluded items and exact known IDs at the relevant contract boundary. Create may skip unavailable pack entries before Preview; Review whole-selection preflight, atomic matrix submission and per-experiment batch admission differ |
| Save/admission acknowledgement uncertain | Preserve intent and exact identifiers, consult the existing store/repository, and show Requires Attention as a research/UI projection where supported. Do not tell the operator to repeat a possibly successful action blindly |
| Ineligible/conflicting/insufficient evidence | Preserve observations/conditions, explain applicability and separate preference from technical quality. Offer a create-only follow-up proposal; pending 072 is not resolved by a confidence badge |
| Shutdown, failed destination or lost attachment | Fail placement visibly without replacing unsent work; no background UI mutation after lifetime ends. Existing app/process ownership remains authoritative |

## Recovery ladder by failure boundary

1. **Before admission:** keep the draft; correct invalid inputs, missing assets or compatibility issues and rebuild Preview. A source-specific saved draft can be reopened; general unsaved recovery is not guaranteed.
2. **Admission known refused:** show cause and zero new IDs only when established by that service. Correct and explicitly submit anew. A partial batch uses exact known IDs and only its existing remaining-work mechanism.
3. **Admission/dispatch unknown:** reconcile exact repository associations; attention is preferable to duplicate work. Do not automatically replay a generation POST or relaunch a backend.
4. **Execution failed/cancelled:** inspect the repository outcome. Explicit Retry/Replay produces new NJR identity with lineage; strict sequence Resume validates unchanged plan/media/checkpoint and also creates a new job.
5. **Artifact/evidence missing or changed:** preserve canonical record and show what cannot be verified. Use source-specific identity checks for relink; do not substitute by filename or count missing images as poor ratings.
6. **Saved draft/profile conflict:** retain original revisions; reopen/Save As or operator-controlled fallback through the existing owner. Corrupt-draft/import, locks, general archive and campaign reauthorization semantics need their separately approved contracts.

Acceptance is documentary consistency here. Future implementation should verify same-snapshot submission, duplicate-pending suppression, late-result fencing, replacement cancel, explicit save scopes, exact-ID reconciliation and no hidden execution. These are targeted future cases, not claims of newly executed tests.
