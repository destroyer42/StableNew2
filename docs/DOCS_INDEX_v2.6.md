DOCS_INDEX_v2.6.md
Canonical Documentation Map & Navigation Guide

Status: Authoritative
Updated: 2025-12-09**

0. Purpose

This index defines the canonical document set that describes StableNew v2.6.
It establishes:

Document hierarchy

Official supersession of older documents

Pointers to all core design artifacts

Required reading order

Integration of PR-CORE documents into architecture

Archival rules for obsolete materials

This file is the root of truth for all project documentation.

1. Canonical Document Hierarchy (Highest → Lowest Authority)

StableNew v2.6 uses a strict ordering.
If two documents conflict, the one higher in this list wins.

1.1 Tier 1 — System Constitution (Unchallengeable)

These documents define the fundamental design and governance of the system.

Architecture_v2.6.md

Governance_v2.6.md

Roadmap_v2.6.md

1.2 Tier 2 — Canonical Specification Layer

These describe all required subsystem behaviors.

PromptPack_Lifecycle_v2.6.md

Builder Pipeline Deep-Dive_v2.6.md

DebugHub_v2.6.md

StableNew_Coding_and_Testing_v2.6.md

PR_TEMPLATE_v2.6.md

Agents_v2.6.md

Copilot-Instructions_v2.6.md

All subsystem design and implementation must align with these documents.

1.3 Tier 3 — Subsystem Specifications (Foundational but Replaceable)

These detail specific behaviors within parts of the system.

Randomizer_Spec_v2.6.md

Learning_System_Spec_v2.6.md

Cluster_Compute_Spec_v2.6.md

Queue_and_Runner_Lifecycle_Spec_v2.6.md (implicit in CORE-C; may be explicitized)

History_and_Restore_Spec_v2.6.md (if applicable)

These documents may evolve as long as they do not contradict Tiers 1–2.

1.4 Tier 4 — PR-CORE Documents (Implementation-Level Governance)

PR-CORE-A — Unified Job Path (NJR-Only)

PR-CORE-B — Deterministic Builder Pipeline

PR-CORE-C — Queue/Runner Unified Lifecycle

PR-CORE-D — GUI V2 Alignment & Preview System

PR-CORE-E — Global Negative, Sweeps, and Overrides

These documents do not define new architecture;
they implement and enforce the architecture.

1.5 Tier 5 — Testing Infrastructure

E2E_Golden_Path_Test_Matrix_v2.6.md

KNOWN_PITFALLS_QUEUE_TESTING.md

Test_Fixtures_Guide_v2.6.md (if present in repo)

These ensure fidelity to the architectural guarantees.

1.6 Tier 6 — Reference & Ancillary Docs

Developer_Onboarding_v2.6.md (future recommended doc)

Model_Profiles_Guide_v2.6.md (optional)

UI/UX Style Guide v2.6

Any auto-generated documentation

These support development but are not canonical.

2. Documents Superseded by v2.6

The following MUST be archived:

Any v2.5 versions of architecture, roadmap, governance

Any PromptPack descriptions prior to v2.6

Any Builder Deep Dive, DebugHub, Randomizer, Learning specs prior to v2.6

Any documentation referencing:

DraftBundle

legacy RunPayload

manual prompt mode

GUI-driven prompt entry

V1 or V1.5 pipeline

multi-path job creation

legacy prompt-resolver paths

These should be moved to:

docs/archive/v2.0–v2.5/

3. Required Document Reading Order

New contributors and agents must follow this exact order:

3.1 Phase 1 — System Foundations

Architecture_v2.6

Governance_v2.6

Roadmap_v2.6

3.2 Phase 2 — Execution Path

PromptPack_Lifecycle_v2.6

Builder Pipeline Deep-Dive_v2.6

DebugHub_v2.6

3.3 Phase 3 — Coding Standards & PR Workflow

StableNew_Coding_and_Testing_v2.6

PR_TEMPLATE_v2.6

Agents_v2.6

Copilot-Instructions_v2.6

3.4 Phase 4 — Subsystem Specifics

Randomizer_Spec_v2.6

Learning_System_Spec_v2.6

Cluster_Compute_Spec_v2.6

3.5 Phase 5 — Testing Infrastructure

E2E_Golden_Path_Test_Matrix_v2.6

Test Fixtures Guide

Queue Testing Pitfalls

4. Canonical Repository Structure

Documentation must follow:

docs/
  ARCHITECTURE_v2.6.md
  Roadmap_v2.6.md
  Governance_v2.6.md
  PromptPack_Lifecycle_v2.6.md
  Builder_Pipeline_Deep_Dive_v2.6.md
  DebugHub_v2.6.md
  StableNew_Coding_and_Testing_v2.6.md
  PR_TEMPLATE_v2.6.md
  Agents_v2.6.md
  Copilot-Instructions_v2.6.md

  specs/
    Randomizer_Spec_v2.6.md
    Learning_System_Spec_v2.6.md
    Cluster_Compute_Spec_v2.6.md
    Queue_and_Runner_Lifecycle_Spec_v2.6.md
    History_and_Restore_Spec_v2.6.md

  tests/
    E2E_Golden_Path_Test_Matrix_v2.6.md
    KNOWN_PITFALLS_QUEUE_TESTING.md
    Test_Fixtures_Guide_v2.6.md

  archive/
    (all documents v2.0–v2.5)


This prevents confusion and avoids drift.

5. How Documents Must Be Maintained
5.1 Every PR Must Update Affected Documents

If a PR modifies:

builder

config logic

randomizer paths

DebugHub

GUI state flow

queue lifecycle

NJR format

…then the PR must also update the corresponding document(s).

If a PR modifies architecture:
→ It must be labeled PR-ARCHITECTURE-X, extremely rare.

If a PR modifies Roadmap or Governance:
→ It must be labeled PR-GOVERNANCE-X, even rarer.

5.2 Documentation Must Lead the Code

The order is:

Document the desired change

Publish the PR spec

Update tests

Codex implements the change

Validate behavior

Merge

Code never precedes documentation.

5.3 Conflicts Between Documentation and Code

If conflicts exist:

Documentation is assumed correct

Code must be updated

Tests updated accordingly

Codex must not refuse based on old code

If documentation is wrong (rare), then:

submit PR to update documentation

get explicit architectural approval

merge updated doc before implementation

6. Document Versioning Rules
6.1 Version Tags

Every file adheres to:

v2.6
v2.7 (future)
v3.0 (future)


Old versions moved to archive.

6.2 Change Logs

Each canonical file should include:

Updated: YYYY-MM-DD
Change Summary:
- …

6.3 No Hidden or Implicit Behavior

All behavior must be documented.

7. Agent Interaction With Documentation
7.1 ChatGPT (Planner)

Must cite canonical documents when reasoning

Must check documents before proposing solutions

Must reject user requests that violate governance

7.2 Codex (Executor)

Must follow PR specs exactly

Must implement documentation faithfully

Must not create undocumented behavior

7.3 Human Contributors

Must read Tier 1–3 documents before contributing

Must follow the PR template

Must update documentation when changing behavior

8. How Canonical Sets Evolve (Governance-Locked)

All architectural evolution proceeds through:

A Planner-generated architectural proposal

A PR-ARCHITECTURE-X document update

Human validation

Codex implementation

Updated tests

Merge into canonical docs index

This ensures documentation remains the first-order artifact.

9. Summary

DOCS_INDEX_v2.6 ensures:

All contributors know where canonical truth lives

All documentation is coherent and authoritative

No legacy documents mislead development

Every subsystem behaves consistently

PRs always update their corresponding documents

Architecture remains unified and stable

All future changes must update this index as part of the documentation governance workflow.

END — DOCS_INDEX_v2.6 (Canonical Edition)