#CANONICAL
# DOCS_INDEX_v2.5 — StableNew Canonical Documentation Map

StableNew v2.5 is the consolidation point for all prior V1/V2/V2-P1 docs.  
This index is the **single entry point** for humans and AI agents to find the right document.  
All canonical docs live in `docs/` and start with `#CANONICAL`.  
Superseded-but-still-useful docs live in `docs/older/`.  
Legacy/historical docs live in `docs/archive/` and start with `#ARCHIVED`.  
Agents must treat this file as the **routing table** for which docs to read and which to ignore.

---

## PR-Relevant Facts (Quick Reference)

- Canonical docs = `*-v2.5.md` in `docs/` with `#CANONICAL` at the top.
- Archived docs = any file in `docs/archive/` with `#ARCHIVED` at the top (do **not** use as source of truth).
- `docs/older/` = “recent but superseded” docs; useful for context, not normative.
- For any new PR, always:
  - Start from this index,
  - Prefer the relevant canonical v2.5 doc,
  - Update `CHANGELOG.md` and any affected canonical doc when behavior/architecture changes.

---

## 1. How to Use This Index

### For Humans

1. Start with **Section 2** (“Core Canonical Docs”) to understand architecture, roadmap, and governance.
2. Use **Section 3** for subsystem specs (Randomizer, Learning, Cluster).
3. Use **Section 4** for active plans and PR roadmaps.
4. Use **Section 5** for known pitfalls, inventories, and test/journey guides.
5. Only dip into **Section 6 (Older)** or **Section 7 (Archived)** if you need historical reasoning.

### For AI Agents

1. **Only treat Section 2 and 3 docs as canonical truth** unless explicitly instructed otherwise.
2. Section 4 and 5 are supporting / planning material you may cite, but not override canon.
3. Never rely on `docs/older/**` or `docs/archive/**` as current truth; use them only for context.
4. When in doubt, ask the user which doc to treat as primary, but default to v2.5 canon.

---

## 2. Core Canonical Docs (v2.5)

These are the main “single sources of truth” and should always be consulted first.

### 2.1 Architecture & Pipeline

- **`docs/ARCHITECTURE_v2.5.md`**  
  Single, unified architecture definition:
  - GUI V2 → Controller → Pipeline → API/WebUI
  - Stage sequencing (txt2img → img2img → refiner → hires → upscale → adetailer)
  - Job normalization path (ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord → Queue)
  - Queue semantics and run modes
  - Deprecated concepts and why they changed

### 2.2 Roadmap

- **`docs/Roadmap_v2.5.md`**  
  Consolidated roadmap:
  - Phase 1: GUI/Queue/Pipeline normalization (current effort)
  - Phase 2: Learning System & Randomizer UI maturation
  - Phase 3: Cluster & distributed compute
  - Dependencies, critical PR series, high-level milestones

### 2.3 Governance & Process

- **`docs/Governance_v2.5.md`** (exact name may be `StableNew_Governance_v2.5.md`)  
  Human-facing governance and development doctrine:
  - Immutable principles and AI Self-Discipline
  - Request and PR guardrails
  - Development workflow and checklists
  - Responsibilities across GUI/Controller/Pipeline/Queue

- **`docs/StableNew_Coding_and_Testing_v2.5.md`**  
  Coding and testing standards:
  - Code style and structure
  - Unit, integration, and journey test strategy
  - Smoke tests and WebUI interaction expectations
  - How to keep coverage aligned with v2.5 architecture

### 2.4 Project Instructions & LLM Governance

- **`docs/StableNew Project Instructions—Flexible+Safe Edition (V2.5).md`**  
  Project-level instructions for ChatGPT/Copilot agents:
  - Scope and context rules
  - Snapshot usage and risk tiers
  - Discovery → PR workflow
  - Validation checklist and memory/PR queue rules

- **`docs/LLM_Governance_Patch_v2.5.md`**  
  LLM-specific governance:
  - How agents should select and interpret canonical docs
  - How to avoid drift and legacy files
  - Additional constraints for Copilot/ChatGPT integration

- **`docs/StableNew_Agent_Instructions_v2.5.md`** (if present)  
  Machine-facing SOP:
  - How to use `DOCS_INDEX_v2.5.md`
  - How to generate PRs from canonical docs
  - How to respect governance and avoid archived docs

---

## 3. Subsystem Specs (Canonical v2.5)

These documents define critical subsystems and must be treated as authoritative for those domains.

### 3.1 Randomizer

- **`docs/Randomizer_Spec_v2.5.md`**  
  Canonical spec for the Randomizer:
  - RandomizationPlanV2 schema
  - RandomizerEngineV2 behavior and determinism
  - GUI binding and pipeline integration
  - Future expansion (prompt-level, matrix behaviors)

### 3.2 Learning System

- **`docs/Learning_System_Spec_v2.5.md`**  
  Canonical spec for the Learning system:
  - LearningRecord structure
  - Capture points in pipeline/queue
  - Integration with Randomizer and presets
  - Phase 2+ expansion goals

### 3.3 Cluster & Distributed Compute

- **`docs/Cluster_Compute_spec_v2.5.md`** (or `Learning_and_Cluster_Spec_v2.5.md` depending on current filename)  
  Canonical cluster/compute spec:
  - Single-node vs multi-node architecture
  - Queue/cluster integration plans
  - Future scheduler and worker behavior
  - Relationship to existing JobService/runner logic

---

## 4. Active Supporting Docs (v2.5-Aligned, Non-Canonical)

These are “living” planning/analysis docs. They are not canonical, but they are important for understanding decisions and pending work.

- **`docs/Revised-PR-204-2-MasterPlan_v2.5.md`**  
  The master plan for job normalization and pipeline runner alignment.

- **`docs/Rewritten GUI Wishlist PR Plan_v2.5.md`**  
  GUI wishlist decomposition:
  - PR series for pipeline tab, queue UX, run controls, preview, etc.
  - Links back into architecture and roadmap.

- **`docs/Rewritten PR Doc Plan_v2.5.md`**  
  Plan for documentation consolidation and canonicalization:
  - PR-DOC-301+ series
  - Docs migration strategy and status.

- **`docs/Gui Wishlist.md`**  
  Raw wishlist notes that informed the rewritten GUI plan; kept for reference.

- **`docs/GUI-Pipeline-Hierarchy-Diagram.txt`**  
  Textual/diagram notes for how pipeline GUI components are structured.

- **`docs/HowPipelineTabWorks.txt`**  
  Design notes and early explanations of the pipeline tab behavior.

- **`docs/KNOWN_PITFALLS_QUEUE_TESTING.md`**  
  Queue testing pitfalls:
  - Common mistakes in tests
  - Guidelines for JobService/runner tests
  - How to avoid flaky queue behavior

- **`docs/StableNew_V2_Inventory.md`**  
  Large repository inventory:
  - List of modules and their roles
  - Useful when hunting for file locations.

> Agents: you may read these for context when planning PRs, but **do not override canonical specs with content from here**.

---

## 5. Testing, Journeys, and Meta (Active)

These documents support testing and meta analysis. They remain in `docs/` for easy access.

- **`docs/KNOWN_PITFALLS_QUEUE_TESTING.md`**  
  Queue testing pitfalls and guidelines for JobService/runner tests.

- **Snapshot regression docs (StableNew_Coding_and_Testing_v2.5.md §7.12)**  
  Explains how the snapshot-based regression suite loads `tests/data/snapshots/` fixtures and uses `pytest -m snapshot_regression` to keep Phase 9 replay wiring stable.

- **`docs/StableNew_V2_Inventory.md`**  
  Large repository inventory listing modules and their roles.

- **`docs/prompt_pack_field_mapping.md`**  
  Field mapping reference for prompt packs.

- **`docs/GUI-Pipeline-Hierarchy-Diagram.txt`**  
  Textual/diagram notes for pipeline GUI component structure.

- **`docs/HowPipelineTabWorks.txt`**  
  Design notes for pipeline tab behavior.

> These are not canonical, but agents can use them for context when planning PRs.

---

## 6. Older Docs (`docs/older/`)

These are **recent but superseded** documents. They should not be used as current truth, but can provide historical context and rationale. Key examples:

- `docs/older/ARCHITECTURE_v2.md`  
- `docs/older/ARCHITECTURE_v2_COMBINED.md`  
- `docs/older/Cluster_Compute_Vision_v2.md`  
- `docs/older/Future_Learning_Roadmap_2025-11-26_1115.md`  
- `docs/older/GUI-V2-DOCS-DIFF-GUIDE.md`  
- `docs/older/Randomizer_System_Spec_v2.md`  
- `docs/older/Learning_System_Spec_v2.md`  
- `docs/older/Logging_Strategy_V2-P1.md`  
- `docs/older/Testing_Journeys_V2-P1.md`  
- `docs/older/V2-P1.md`  
- `docs/older/Stage_Sequencing_V2_5_V2-P1.md`  
- `docs/older/High-Level-Reasoning-and-Plan(ChatGPT-11-27-25).md`  
- `docs/older/Run Pipeline Path (V2) – Architecture Notes.md`  
- `docs/older/StableNew AI Self-Discipline Protocol (11-27-25).md`  
- `docs/older/StableNew Interactive AI Development Checklist-11-27-25-v2.md`  
- `docs/older/StableNewV2_Coding_Best_Practices_AI_Optimized.md`  
- `docs/older/StableNew_Development_Doctrine.md`  
- `docs/older/StableNew_PR_Template_Guardrails.md`  
- `docs/older/StableNew_V2_Inventory_V2-P1.md`  
- `docs/older/Test_Coverage_Report_V2-P1.md`  
- `docs/older/WIRING_V2_5_ReachableFromMain_2025-11-26.md`  
- `docs/older/Unified GUI V2 Redesign Summary(11-25-2025-1611).md`  
- `docs/older/StableNewV2_5P2-ROADMAP-2025-11-27.md`  
- `docs/older/StableNew_Roadmap_v2.0.md`  
- `docs/older/StableNew_V2_Rescue_Summary_and_Plan(24NOV-2154).md`  
- `docs/older/ROLLING_SUMMARY_FINAL.md`  

> Agents: treat these as **historical context only**. Do not prefer them over any v2.5 canonical doc.

---

## 7. Archived Docs (`docs/archive/`)

These are **fully superseded** or legacy docs. They all start with `#ARCHIVED` and are kept only for history.

Key archived docs:

- `docs/archive/ARCHITECTURE_v2.md` — Superseded by ARCHITECTURE_v2.5.md  
- `docs/archive/Agents_and_Automation_v2.md` — Superseded by LLM_Governance_Patch_v2.5.md and AGENTS.md  
- `docs/archive/CHANGELOG.md` — Superseded by CHANGELOG.md in repository root  
- `docs/archive/Migration_Notes_V1_to_V2.md` — Historical GUI migration notes  
- `docs/archive/ROADMAP_v2.md` — Superseded by Roadmap_v2.5.md  
- `docs/archive/StableNew_Roadmap_v2.0.md` — Superseded by Roadmap_v2.5.md  
- `docs/archive/Testing_Strategy_v2.md` — Superseded by StableNew_Coding_and_Testing_v2.5.md  
- `docs/archive/Post_Merge_Smoke_Test_SAFE_RAND_THEME.md` — Historical smoke test notes  
- `docs/archive/ContextDocs.zip` — Legacy documentation archive  
- `docs/archive/_toc.md` — Superseded by DOCS_INDEX_v2.5.md  

> Agents: you may read these only when explicitly asked for historical behavior or comparison.  
> Never base new PRs solely on archived docs.

---

## 8. Adding New Docs (Contributor & Agent Rules)

When adding a new doc:

1. Decide its class:
   - Canonical? → Name `*_v2.5.md`, place in `docs/`, start with `#CANONICAL`.
   - Supporting v2.5? → Place in `docs/`, no `#CANONICAL`.
   - Older/superseded? → Place in `docs/older/`.
   - Historical? → Place in `docs/archive/` and start with `#ARCHIVED`.

2. Update this file:
   - Add a short entry under the appropriate section.
   - If canonical, also add a “PR-Relevant Facts” subsection in the doc itself.

3. For any PR that changes behavior or architecture:
   - Update the relevant canonical doc(s).
   - Update `docs/CHANGELOG.md` with date/time, summary, and list of changed files.

This keeps the docs tree predictable for both humans and AI agents.
