# StableNew Documentation Index v2.6

Status: Authoritative
Updated: 2026-09-06

## 0. Purpose

This index identifies the active documentation set and prevents historical
completion claims or backlog files from competing with the MVP recovery canon.

## 1. Active hierarchy

### Tier 1 — System constitution and direction

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md` — the **Finalized MVP Roadmap** and only
  active roadmap

### Tier 2 — Execution and workflow canon

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/ARCHITECTURE_ENFORCEMENT_CHECKLIST_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`
- `docs/Canonical_Document_Ownership_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `.github/INSTRUCTION_SURFACE.md`

### Tier 3 — Active subsystem references

- `docs/Architecture/ARTIFACT_METADATA_CONTRACTS_v2.6.md`
- `docs/Architecture/Image_Metadata_Contract_v2.6.md`
- `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/Architecture/SECONDARY_MOTION_POLICY_SCHEMA_V1.md`
- `docs/schemas/stablenew.image-metadata.v2.6.json`
- `docs/schemas/stablenew.review.v2.6.json`
- `docs/schemas/portable_review_summary.v2.6.json`
- `docs/schemas/artifact_metadata_inspection.v2.6.json`
- `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md`
- `docs/Subsystems/Testing/KNOWN_PITFALLS_QUEUE_TESTING.md`
- `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md`
- `docs/Subsystems/Training/Character_Embedding_Workflow_v2.6.md`
- `docs/Subsystems/Video/Movie_Clips_Workflow_v2.6.md`
- `docs/runbooks/TRACKED_RUNTIME_STATE_HYGIENE_v2.6.md`

Tier 3 references may describe post-MVP systems. They do not expand MVP scope
or override Tier 1/Tier 2. A contradiction affecting MVP must be resolved before
the affected runtime work proceeds.

### Tier 4 — Active approved PR specifications

- `docs/PR_Backlog/PR-ARCH-MVP-001-v2.6-Canon-Amendment.md`

`PR-ARCH-MVP-001` is implemented and remains here until merge review/closeout.
No runtime implementation spec is active after completed `PR-MVP-030`; the
next specification to generate is `PR-MVP-040`.

Completed recovery record:

- `docs/CompletedPR/PR-MVP-000-Recovery-Baseline-and-Repository-Completeness.md`
- `docs/CompletedPR/PR-MVP-005-Post-Baseline-Delta-Disposition.md`
- `docs/CompletedPR/PR-MVP-010-Test-Harness-Recovery.md`
- `docs/CompletedPR/PR-MVP-020-NJR-Core.md`
- `docs/CompletedPR/PR-MVP-030-Compilers-and-Submission.md`

`PR-MVP-005`, `PR-MVP-010`, `PR-MVP-020`, and `PR-MVP-030` are complete. The
former authorizes no runtime adoption or bulk branch integration; each
carry-forward requires the separately approved owner PR named in that record.
The latter records the authoritative isolated test gates, non-increasing Ruff
debt baseline, immutable NJR core, and typed submission cutover.

## 2. Canonical reading order

1. `README.md`
2. this index
3. `docs/ARCHITECTURE_v2.6.md`
4. `docs/GOVERNANCE_v2.6.md`
5. `docs/StableNew Roadmap v2.6.md`
6. `docs/StableNew_Coding_and_Testing_v2.6.md`
7. `docs/PR_TEMPLATE_v2.6.md`
8. relevant Tier 2/Tier 3 references
9. the active approved PR spec

## 3. Folder status

| Location | Status |
|---|---|
| `docs/` root | Tier 1/Tier 2 canonical docs only |
| `docs/Architecture/`, `docs/Subsystems/`, `docs/schemas/`, `docs/runbooks/` | Active Tier 3 references |
| `docs/PR_Backlog/` | Open planning material; only items listed above are active/approved |
| `docs/CompletedPR/` | Historical completed implementation records |
| `docs/CompletedPlans/` | Historical completed sequences and roadmaps |
| `docs/NeedsReview/` | Non-active material awaiting disposition |
| `docs/Research Reports/` | Evidence and research, not normative canon |
| `docs/archive/` | Superseded/reference-only history |

Existing unlisted files in `docs/PR_Backlog/` are frozen inputs for
`PR-MVP-005` disposition. They must not be executed or cited as current roadmap
authority.

## 4. Supersession rules

- The Finalized MVP Roadmap supersedes all earlier sequencing and status ledgers.
- `docs/ARCHITECTURE_v2.6.md` is the only active architecture definition.
- Completed and archived docs never become active by being linked from an old
  document.
- Code and tests are evidence of current implementation, not automatic
  architecture authority.
- A Tier 3 feature document does not admit that feature to MVP.

## 5. Maintenance rules

- Update this index in the same PR when active status or file location changes.
- Update all affected active docs when a runtime contract changes.
- Do not remove an architecture gap until implementation and clean-checkout
  verification pass.
- On PR completion, create one `docs/CompletedPR/PR-...md` record, update roadmap
  and index, and remove or relocate the backlog copy.
- Move uncertain material to `docs/NeedsReview/`; move superseded history to
  `docs/archive/`; never leave contradictory files active by default.
- Register new agent profiles/path-scoped instructions in
  `.github/INSTRUCTION_SURFACE.md` in the same PR.
