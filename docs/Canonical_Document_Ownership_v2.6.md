Canonical_Document_Ownership_v2.6.md
Ownership Map, Precedence Table, and Contradiction Rules for StableNew v2.6

Status: Authoritative
Updated: 2026-03-19

## 1. Purpose

This document defines:

- which active docs are canonical
- which role owns them
- how contradictions are resolved
- how the active docs are separated from completed, historical, and
   needs-review material
- which older docs remain active references vs archive-only history

## 2. Active Document Ownership Table

| Document | Tier | Owner | Update Trigger |
|---|---|---|---|
| `docs/ARCHITECTURE_v2.6.md` | 1 | Planner | Structural runtime change |
| `docs/GOVERNANCE_v2.6.md` | 1 | Planner | Process or rule change |
| `docs/StableNew Roadmap v2.6.md` | 1 | Planner | Priority or roadmap change |
| `docs/PROMPT_PACK_LIFECYCLE_v2.6.md` | 2 | Planner | PromptPack lifecycle or ownership change |
| `docs/Builder Pipeline Deep-Dive (v2.6).md` | 2 | Planner | PromptPack builder-path change |
| `docs/DEBUG HUB v2.6.md` | 2 | Planner | Diagnostics contract change |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | 2 | Planner | Coding or test policy change |
| `docs/PR_TEMPLATE_v2.6.md` | 2 | Planner | PR workflow change |
| `docs/DOCS_INDEX_v2.6.md` | 2 | Planner | Active doc location or status change |
| `docs/Canonical_Document_Ownership_v2.6.md` | 2 | Planner | Ownership or precedence change |
| `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` | 3 | Planner | Learning subsystem behavior change |
| `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md` | 3 | Planner | GUI placement or ownership change |
| `docs/Subsystems/Video/Movie_Clips_Workflow_v2.6.md` | 3 | Planner | Movie Clips workflow or ownership change |
| `docs/Architecture/Image_Metadata_Contract_v2.6.md` | 3 | Planner | Image metadata field or policy change |
| `docs/Subsystems/Testing/KNOWN_PITFALLS_QUEUE_TESTING.md` | 3 | Planner | Queue-testing guidance change |
| `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md` | 3 | Planner | Golden-path coverage change |
| `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md` | 3 | Planner | Randomizer subsystem behavior change |

## 3. Active v2.5 Retention Rule

No v2.5 subsystem specs remain in the active root docs set.

`docs/archive/reference/Cluster_Compute_Spec_v2.5.md` and
`docs/archive/reference/Randomizer_Spec_v2.5.md` are reference-only archive
material.

## 4. Precedence Rules

When documents appear to conflict:

1. Tier 1 overrides Tier 2.
2. Tier 2 overrides Tier 3.
3. Within the same tier, the more specific doc wins over the more general doc.
4. If the conflict still remains, the newer active revision wins.
5. If conflict is still unresolved, stop implementation and resolve it through a
   planner-owned docs update before continuing.

## 5. Contradiction Rules

No PR may knowingly leave an active contradiction in place.

If one active doc is updated in a way that changes runtime truth, the dependent
active docs must be updated in the same PR or explicitly retired from the
active set.

If a PR intentionally changes Tier 1 or Tier 2 truth, the PR spec and closeout
must explicitly name the affected canonical docs and validate the new wording
against the implemented code, tests, or both before merge.

## 6. Disposition Rules

Move a document to `docs/archive/` when:

- it is historically useful but no longer active
- it describes a superseded runtime story
- it is stale analysis rather than active operating guidance
- it is a dormant subsystem reference no longer driving current work

Move a document to `docs/CompletedPR/` when:

- it is the single final implementation and validation record for a completed
   PR

Move a document to `docs/CompletedPlans/` when:

- it is a completed executable roadmap, sweep, or multi-PR sequence record
- it is no longer an open planning surface but still useful as completion
   history

Move a document to `docs/NeedsReview/` when:

- its current applicability is unclear
- it is recent enough that silent archival would be risky
- it may still need content extraction, splitting, or confirmation before a
   final archive or active placement decision

## 7. Root Folder Rule

`docs/` root is reserved for Tier 1 and Tier 2 canonical docs only.

Active Tier 3 references belong in `docs/Architecture/`, `docs/Subsystems/`,
`docs/Research Reports/`, `docs/runbooks/`, or `docs/schemas/`.

Backlog PR specs belong in `docs/PR_Backlog/`.
Completed PR records belong in `docs/CompletedPR/`.
Completed sequence docs belong in `docs/CompletedPlans/`.
Ambiguous material belongs in `docs/NeedsReview/`.
Historical and reference material belongs in `docs/archive/`.

Do not add new Tier 3 files to the root even if older root placements still
remain during the transition cleanup.

## 8. Maintenance Checklist

Before merging a docs-changing PR, verify:

- if runtime or product truth changed, the PR explicitly names the affected
   canonical docs and updates them in the same PR
- one final `docs/CompletedPR/PR-...md` record exists for each completed PR
   touched by the work
- duplicate completed PR specs have been removed from `docs/PR_Backlog/`
- fully completed sequence docs have been moved to `docs/CompletedPlans/`
- ambiguous documents are relocated to `docs/NeedsReview/` instead of being
   left active by default
- active doc references point to existing files
- archived or needs-review docs are not still listed as active in
   `DOCS_INDEX_v2.6.md`
- no active doc still claims a superseded runtime story
- retained v2.5 docs are still truly needed
