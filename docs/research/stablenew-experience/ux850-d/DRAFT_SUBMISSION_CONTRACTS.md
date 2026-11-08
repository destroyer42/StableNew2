# Draft, approval and submitted-job boundaries

These contracts distinguish **CURRENT source mechanisms** from **PROPOSED experience requirements**. B's J1 Create, J2 Edit, J3 Motion, J4 Discover and J5 Learn remain the journey vocabulary; [H1–H10](../ux850-b/HANDOFFS.md) define context transfer. No common replacement transaction or durable recovery journal is assumed already implemented.

## Four identities and commit points

| Boundary | Existing authority / commitment | Proposed UX rule and limit |
|---|---|---|
| Source → editable draft | Native source owner supplies verified content/provenance; draft belongs to destination, not source | Keep source ID/revision separate from destination draft ID/revision. Imported file provenance cannot acquire guessed pack/job lineage. Replacement consent concerns only unsent work |
| Draft → prepared executable snapshot | Appropriate current compiler creates immutable NJRs; Create Preview has a revision linearization point [D16–17](SOURCE_INDEX.md#d16) | Show effective config, source/profile/adaptation identities, inputs, count and warnings. An asynchronous result for an older revision cannot become current. Frozen Preview is not durable job admission |
| Prepared snapshot → admission | `JobService.submit_njrs` validates complete batch, then Queue/Repository commits [D04–09](SOURCE_INDEX.md#d04) | Submitted IDs and exact immutable content define admitted work. A lost response is an observation failure, not proof no jobs exist. Reconcile expected IDs before any further intent |
| Admission → result/recovery | Guarded lifecycle commits and runner result/artifact contracts | Submitted jobs continue under their owner when tabs/drafts change. UI clear, source save, profile application, archive, recovery and campaign stop-intent cannot alter a submitted NJR |

Current Create behavior may compile once when no accepted Preview exists, claim its revision and publish the exact result before admission; superseded compile is refused. Do not describe every route as requiring an already displayed Preview. Whether adaptive one-click confirmation may replace the current review contract is **G2 / F4**, not decided here.

## Current source-specific contracts

| Workflow / B trace | Frozen inputs and admission scope | Edits, restore and failure constraints |
|---|---|---|
| PromptPack → Create, H1 / J1 | Pack selection/settings/slots/Matrix and global prompt intent compiled through current builder; one accepted Create Preview is admitted unchanged | Pack/config changes invalidate Preview; saving defaults is explicit. Preserve self-contained/shared/temporary distinction. No compiler replacement or live read of GUI defaults during modern NJR execution |
| Model/profile → working controls, H7 / J1 | Application plan validates identity/hard policy/catalogs, changes working values; later compiler freezes them [D23](SOURCE_INDEX.md#d23) | Publishing an eligible profile is separate from selecting, applying, favoriting and startup save. Existing checkpoint selection can apply its preferred profile immediately; D does not replace that behavior with an invented universal Apply-only rule |
| Review/masked/outpaint/Photo, H3 / J2 | Current edit/reprocess service freezes supported source/settings and submits ordinary NJRs; original/parent stays referenced | General named regions, arbitrary pixel restoration and multistep approvals remain G7. Exact original-pixel restoration evidence is specifically outpaint, not universally every masked edit. Draft recovery never promotes baseline/preferred/final |
| History iteration/replay, H2/H9 / J2 | Existing supported iterate assessment or replay compiler makes new intent/NJR with explicit parent lineage [D40–41](SOURCE_INDEX.md#d40) | Saved historical settings are evidence, not current defaults. Missing/corrupt/unsupported source refuses; no guessed model, substitute media or original rewrite. Current replay strips active batch membership/run directives but retains frozen execution settings |
| Storyboard → sequence, H8 / J3 | Saved editable revision + readiness do not freeze random seeds; admission freezes exact segment plan/anchors/workflow through existing sequence compiler | Source changes need explicit reacceptance; edited plan is new work, not strict resume. Approval/experimental scope for new campaign/draft cannot be assumed from a parent; existing replay retains frozen backend options, see G3/G7 |
| Movie Clips, H5 / J3 | Existing assembly compiler freezes clip order/media/audio/export through one canonical assembly job | Existing encode profiles already exist. Timed titles/dialogue/effects/portable project/evaluator support is not inferred. Handoff never auto-builds |
| Designed Learning, H6 / J5 | Independent experiment baseline/snapshot and variant IDs; aligned ordinary NJRs through one `submit_njrs` call [D28](SOURCE_INDEX.md#d28) | Create edits cannot rewrite frozen study. Exact-job reconciliation governs projected status. Ratings/validity are post-execution evidence, not canonical job state |
| Qualification proposal selection / J5 | Whole-selection preflight/revision/compiled-record comparison, then write-ahead exact IDs and **one canonical batch per experiment** [D26](SOURCE_INDEX.md#d26) | Partial confirmed prefix remains after later failure/cancel. Stop next admission; do not report whole-selection rollback, cancel admitted jobs or retry unknown submission |
| Future campaign / J5 extension | **PROPOSED** P4–P6 approved plan/constraints and reserved IDs; current compilers + JobService only | Valid approval is checked before each bounded admission. Pause/stop controls future submission intent. Already queued/running job controls remain separate current commands, requiring their appropriate explicit user action |

## Proposed recovery envelope and lock resolution

P1 is a candidate UIStateStore extension, not a second source for saved documents. Recover into a separate draft **only after** validating schema/source identity and showing the base/current/recovered revisions. Offer explicit restore/copy or discard of that recovery entry. Never silently save over a PromptPack, startup settings, profile revision, experiment snapshot, Storyboard or historical NJR. If the base changed, retain both versions and require a deliberate merge/Save As through the native owner. Missing media remains missing, with known provenance; no automatic closest-path relink. An unreadable recovery entry does not justify overwriting the last valid saved source.

P2/P3 require G1 precedence. Candidate resolution is: enforce hard model/security restrictions first; compare exact source/profile/experiment identities; disclose locked-versus-incoming conflicts; preserve compatible working overrides; require an explicit temporary exception scoped to that draft/snapshot. This is a **candidate ordering**, not adopted policy. Unsupported and untested values are distinct. An exception cannot bypass hard restrictions, change a qualified envelope, mutate a published profile or grant approval for changed experiments. Recovered locks are inactive until their scope, model and revision validate.

## Approval applicability and invalidation

| Change | Required effect for a future approval-bound workflow |
|---|---|
| Prompt/adaptation/global policy, model/backend/workflow/profile revision, stage/seed/count, input bytes/anchors or output-affecting setting | Prepared executable approval becomes stale; recompile/review through the same owner. Existing NJRs remain untouched |
| Lock/exception, campaign bounds/window/expiry/resource policy, proposed evaluator release/applicability | Re-evaluate exact approval applicability under G1/G3/G4/G6; no silent extension of consent |
| Rating revision or new/conflicting evidence | Preserve observations and historical approval; mark derived conclusion/profile applicability for review. No automatic saved-profile/default/model replacement; 072 remains open |
| Rename, browse selection or presentation-only metadata | Do not recompile merely for appearance when execution identity is unchanged; metadata owner controls its own revision |
| Crash/restart | Restore canonical queued jobs under existing startup holds/auto-run; reconcile exact associations. Restoring a plan/draft is never fresh permission for unattended campaign continuation |

## Concurrency and failure obligations for later implementation

Use existing Preview revision guards, Learning execution/store locks and Storyboard CAS where they actually apply. They are not universal distributed transactions. A campaign reservation would need one serialized metadata generation plus exact NJR ID/fingerprint associations, committed **before** canonical admission, and a recovery reconciliation phase for every crash window. Neither side may compensate by deleting jobs or rewriting a newer draft. This obligation requires G3; D supplies no implementation or new state/schema.

If a callback arrives after tab disposal or after a draft revision changes, marshal via existing dispatcher/view contract, retain canonical job evidence, and suppress stale presentation writes. Error after a successful save/commit must distinguish durable success from failed refresh. These are future cross-workflow UX contracts with existing partial foundations, not a claim of present parity.

The late accepted A addendum reinforces the gap: `_on_load_selected_pack` calls `load_pack` without a dirty check in that route [D56](SOURCE_INDEX.md#d56); Smart Review's `_default_open_editor` passes no optional lineage [D57](SOURCE_INDEX.md#d57). Thus native Prompt loading and AI-assisted editing cannot be credited with universal unsent-work protection or preserved parentage. Other mitigation/controller backfill and actual operator impact were not established in D. Existing direct guarded handoffs do not prove these routes safe.
