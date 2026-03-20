Canonical_Document_Ownership_v2.6.md
Ownership Map, Precedence Table, and Contradiction Rules for StableNew v2.6

Status: Authoritative
Updated: 2026-03-19

## 1. Purpose

This document defines:

- which active docs are canonical
- which role owns them
- how contradictions are resolved
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
| `docs/Learning_System_Spec_v2.6.md` | 3 | Planner | Learning subsystem behavior change |
| `docs/GUI_Ownership_Map_v2.6.md` | 3 | Planner | GUI placement or ownership change |
| `docs/Movie_Clips_Workflow_v2.6.md` | 3 | Planner | Movie Clips workflow or ownership change |
| `docs/Image_Metadata_Contract_v2.6.md` | 3 | Planner | Image metadata field or policy change |
| `docs/KNOWN_PITFALLS_QUEUE_TESTING.md` | 3 | Planner | Queue-testing guidance change |
| `docs/E2E_Golden_Path_Test_Matrix_v2.6.md` | 3 | Planner | Golden-path coverage change |
| `docs/Randomizer_Spec_v2.6.md` | 3 | Planner | Randomizer subsystem behavior change |

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

## 6. Archive Rules

Move a document to `docs/archive/` when:

- it is historically useful but no longer active
- it describes a superseded runtime story
- it is stale analysis rather than active operating guidance
- it is a dormant subsystem reference no longer driving current work

Move a document to `docs/CompletedPR/` when:

- it is an implementation or planning record for a completed PR

## 7. Root Folder Rule

`docs/` root is reserved for the active document set only.

Backlog PR specs belong in `docs/PR_Backlog/`.
Completed PR records belong in `docs/CompletedPR/`.
Historical and reference material belongs in `docs/archive/`.

## 8. Maintenance Checklist

Before merging a docs-changing PR, verify:

- active doc references point to existing files
- archived docs are not still listed as active in `DOCS_INDEX_v2.6.md`
- no active doc still claims a superseded runtime story
- retained v2.5 docs are still truly needed
