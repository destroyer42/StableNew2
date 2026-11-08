# Lifecycle diagrams and authority boundaries

Diagrams L1–L6 describe **CURRENT source contracts**, with explicit missing evidence. L7–L8 are **PROPOSED metadata intent only**. Boxes that mention UI/sequence/experiment status are not production job enums. Source and negative-test anchors are in [the index](SOURCE_INDEX.md); test bodies were inspected, not executed in D.

## L1 — draft, accepted Preview and atomic canonical admission

```mermaid
flowchart TD
  A[Editable source-specific draft] --> B[Existing compiler freezes NJRs]
  B --> C{Create Preview revision current?}
  C -->|No| X[Refuse stale compile; zero admission]
  C -->|Yes or explicit-NJR route| D[JobService validates complete batch]
  D --> E{All identities and NJRs valid?}
  E -->|No| X
  E -->|Yes| F[Queue admission lock]
  F --> G[SQLite transaction inserts entire batch]
  G -->|Write or identity failure| H[Rollback batch; preserve prior jobs]
  G -->|Commit| I[Queue projects whole batch under lock]
  I --> J[Notify submitted IDs and request runner]
  J -->|Startup error| K[IDs remain admitted; report startup failure]
  J -->|Worker available and eligible| M[Canonical atomic claim]
```

Create revision guards apply at their accepted-Preview boundary; explicit NJR routes have their own compiler/review contracts. There is no distributed UI/SQLite transaction. The snapshot is accepted before admission; post-boundary edits belong to later work. Repository commit precedes queue projection and notifications; on crash in that gap, startup restores the durable rows. An observer/acknowledgement failure after commit does not justify resubmission. Sources [D04–09](SOURCE_INDEX.md#d04), [D16–17](SOURCE_INDEX.md#d16). Existing `test_batch_admission_atomicity` covers rollback, projection order, concurrent admissions and startup failure; catastrophic in-process projection allocation failure is not newly fault-injected here.

## L2 — the five durable job states, dispatch and restart

```mermaid
flowchart LR
  Q[QUEUED] -->|Eligible atomic claim| R[RUNNING]
  Q -->|Canonical cancel before claim| C[CANCELLED]
  R -->|Success| D[COMPLETED]
  R -->|Failure or restart interruption| F[FAILED]
  R -->|Canonical cancellation| C
  R -->|Positive evidence never dispatched| Q
```

This exactly maps `_ALLOWED_TRANSITIONS`, [D06](SOURCE_INDEX.md#d06), and enum [D52](SOURCE_INDEX.md#d52). Terminal records cannot become QUEUED; same-status metadata/result handling is not shown as a new lifecycle. `DISPATCHED`, `PAUSED`, `HELD`, `ACTION_REQUIRED`, `UNCONTROLLED`, campaign stage and ledger state are **not additional SQLite job statuses**.

RUNNING means claimed by the worker, not proof the POST was dispatched. Dispatch certainty is separate typed evidence. Return to QUEUED requires positive evidence no generation began and no completed/checkpoint work; absence of checkpoints is insufficient [D11](SOURCE_INDEX.md#d11). A restart converts persisted RUNNING to existing FAILED with `INTERRUPTED_RESTART_ACTION_REQUIRED`, ambiguous outcome and automatic replay false [D10](SOURCE_INDEX.md#d10). History renders Interrupted without inventing a sixth state. Queue pause/holds/fence can leave Q ineligible without changing its state. New explicit replay is a separate identity starting at Q, with parent lineage [D40](SOURCE_INDEX.md#d40).

## L3 — cancellation, uncertain dispatch and process ownership

```mermaid
flowchart TD
  A[Explicit current job control via JobService] --> B{Cancel and Return requested?}
  B -->|No| C[Canonical cancellation and worker signal]
  B -->|Yes| D[Worker assesses typed dispatch evidence]
  D -->|Never dispatched and no completed work| E[Guarded return of same job to QUEUED]
  D -->|Unknown or dispatched or progress exists| F[CANCELLED with return refusal; inspect output]
  C --> G[Existing backend cancellation contract]
  F --> G
  G --> H{OS process lifecycle action involved?}
  H -->|Owned by its manager| I[Existing manager-only operation]
  H -->|External or unknown owner| J[No adopt kill or restart; observe and explain]
```

Cancellation is not proof the backend stopped or produced no artifact. A1111 supported interrupt remains within its existing API contract; external processes are never adopted/terminated/restarted automatically. The generic job process-registration API is not permission to register an arbitrary observed PID. Source scan found its definition but no production `register_external_process(...)` callsite; that limited static result does not certify every dynamic extension. Sources [D11/D13](SOURCE_INDEX.md#d13), [D45–46](SOURCE_INDEX.md#d45). For transport loss, the client raises unknown outcome after one generation POST and never automatically replays it [D12](SOURCE_INDEX.md#d12). All physical cancellation/process behavior remains untested here.

## L4 — current settings, profile publication and recovered draft proposal

```mermaid
flowchart TD
  S[Saved startup defaults] --> V[Validated startup restore plan]
  V --> W[Editable working controls]
  M[Operator chooses model or profile] --> P[Identity and policy application plan]
  P --> W
  W --> C[Existing compiler then canonical admission L1]
  E[Eligible Learning evidence] --> U[Explicit immutable profile publication]
  U --> R[Profile catalog revision]
  R --> M
  W -->|Explicit save startup| S
  R -->|Separate explicit favorite| F[Favorite reference]
  D[PROPOSED recovered draft P1] --> G{G1 approved and source revisions compatible?}
  G -->|No| H[Keep saved source and recovery separate]
  G -->|Yes and operator restores| W
```

The P1 branch is **PROPOSED**; no recovery implementation is claimed. Publication does not itself select/apply/favorite/save startup. Model selection's existing immediate preferred-profile application is preserved as current behavior [D53](SOURCE_INDEX.md#d53). No arrow writes a published revision or historical NJR from W. Locks are a G1 proposal over the application plan, not a hidden override channel. Sources [D21–24](SOURCE_INDEX.md#d21).

## L5 — Learning selection, per-experiment admission and evidence

```mermaid
flowchart TD
  A[Independent baseline and saved experiment intent] --> B[Freeze variants and preflight full selection]
  B --> C[Explicit confirmation and revalidate every saved revision]
  C -->|Stale or invalid| X[Zero new admissions; preserve drafts]
  C -->|Valid| D[Write ahead exact IDs for next experiment]
  D --> E[One JobService batch for that experiment]
  E -->|Acknowledged| F[Track exact repository jobs]
  E -->|Lost or raised response| G[Reconcile expected IDs; stop without retry]
  F --> H{Next experiment still selected and not cancelled?}
  H -->|Yes| D
  H -->|No| I[Retain admitted prefix; no next admission]
  F --> J[Repository terminal evidence and artifact availability]
  G --> J
  J --> K[Controlled-validity checks and append-only human ratings]
  K --> L[Current rating projection and eligible findings]
  L --> M[Separate reviewed profile publication L4]
```

Whole-selection preflight is not whole-selection transactionality. A previous experiment can stay admitted when the next session write/admission fails. Sessions retain exact associations; SQLite remains the only job lifecycle authority. Startup `QualificationBatchService.restore` reconciles without resubmission and is actually wired in the Learning tab through the existing background thread registry [D30](SOURCE_INDEX.md#d30). Missing/duplicate/conflicting IDs and unavailable repository become action-required analytical projections, not fabricated successful completion. Sources [D25–32](SOURCE_INDEX.md#d25); `test_qualification_batch_810` negative cases.

## L6 — Storyboard, sequence checkpoint and explicit new-job resume

```mermaid
flowchart TD
  A[Editable Storyboard] --> B[Explicit save with revision CAS]
  A --> C[Readiness Summary only]
  C --> D[Existing admission freezes plan seeds and anchors]
  D --> E[JobService admits one sequence NJR]
  E --> F[Runner verifies inputs then executes segment]
  F --> G[Verify output and exact final frame]
  G --> H{Ledger commit succeeded?}
  H -->|No| I[Stop; no next segment dispatch]
  H -->|Yes| J{More segments?}
  J -->|Yes| F
  J -->|No| K[Assembly and canonical result]
  I --> L[Operator inspects parent job and checkpoint]
  L --> M[Explicit Resume builds NEW NJR with lineage]
  M --> N[Verify same plan and pinned finished prefix]
  N -->|Valid| O[JobService admits child; runner verifies again]
  N -->|Invalid or missing| P[Refuse resume without parent mutation]
  O --> Q[Copy verified prefix into child; execute suffix]
```

Cancellation/failure/restart can also lead to inspection L; the diagram focuses on the most important partial-write case. Uncommitted produced media may exist even if the ledger has no completed entry. Explicit resume may regenerate an in-flight unfinished segment, with a new job identity, after operator inspection; this is not automatic replay of an unknown POST. A changed plan is new authored work; strict resume refuses it. Assembly-only resume is possible when every segment is verified. The old NJR/ledger remains unchanged. Sources [D34–39](SOURCE_INDEX.md#d34); checkpoint failure and admission-to-execution media-change tests in the source index.

## L7 — PROPOSED campaign submission intent, no new job lifecycle

```mermaid
flowchart TD
  A[PROPOSED versioned campaign plan P4] --> B[PROPOSED approval P5 at G3 and G4]
  B --> C[Reconcile all reserved exact job IDs]
  C --> D{Valid approval bounds window resources and dependencies?}
  D -->|No or unknown| E[Hold future submission intent; explain]
  D -->|Yes| F[Existing compiler freezes bounded next batch]
  F --> G[PROPOSED serialized reservation P6]
  G --> H[Existing JobService canonical admission L1]
  H --> I[Observe repository; update associations only]
  I --> C
  P[PROPOSED pause or stop future submissions] --> E
  E -->|Explicit valid resume intent| C
  X[Already queued or running jobs] --> Y[Remain under existing job controls L2 and L3]
```

All nodes P4–P6 and the eligibility policy are pending design/adoption. No campaign queue, worker, compiler, runner, cancellation service, automatic backend repair or `campaign_paused` job status is proposed. A global queue pause/resume is not a per-campaign control. Stop-future-admission does not cancel existing work. In-flight admission versus pause/stop must have an owner-approved linearization rule (G3), otherwise implementation must wait. Restart requires reconciliation and valid explicit unattended-continuation authority; stored plan or resource availability alone never supplies it.

## L8 — PROPOSED archive/import reference recovery

```mermaid
flowchart TD
  A[PROPOSED archive or external package] --> B[Read-only integrity and version validation]
  B -->|Invalid or unsupported| C[Retain original; refuse consequential integration]
  B -->|Valid bytes| D[PROPOSED import receipt P9 with external provenance]
  D --> E[Assess comparability dependence and missing media]
  E --> F[PROPOSED Library references P7 or analytical evidence view]
  F --> G{Explicit consequential promotion approved?}
  G -->|No| H[Observation remains external or conditional]
  G -->|Yes under G5 and G6| I[Existing reviewed publication or new intent compiler]
  I --> J[Canonical path for any new generation]
```

Valid hashes prove byte identity, not trustworthy scientific claims, sample independence, local execution or qualification. Current Photo archive/restore, Motion manifest/relink and Storyboard JSON import/export are narrower source-specific mechanisms; none implements this general flow. Archive recovery cannot overwrite historical jobs, approved settings or original evidence. Destructive deletion/portable packaging remain explicit G5 decisions. There is no imported second History.
