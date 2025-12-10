# StableNew v2.5 — GitHub Copilot Instructions
#CANONICAL
# Do not modify without updating DOCS_INDEX_v2.5.md

These are mandatory rules for GitHub Copilot when generating, modifying, or assisting with StableNew code.  
Copilot must obey these instructions at all times.

---

# 0. BLUF / TLDR (Hard Rules)

- Use ONLY canonical documentation (`*-v2.5.md` with `#CANONICAL`).  
- Ignore all archived docs (files containing `#ARCHIVED` or located in `docs/archive/`).  
- Do NOT guess architecture or file structure. When unclear → request snapshot or clarification.  
- Respect subsystem boundaries (GUI → Controller → Pipeline → Queue → Runner).  
- All logic changes MUST include tests.  
- All PRs must follow StableNew PR template.  
- Never invent new APIs, modules, or architectural concepts.  
- Never bypass ConfigMergerV2, JobBuilderV2, NormalizedJobRecord, or JobService.  
- Never change pipeline stage ordering or semantics.

---

# 1. Canonical Documentation Priority

Copilot must load and follow these documents in this order:

1. `docs/ARCHITECTURE_v2.5.md`
2. `docs/Governance_v2.5.md`
3. `docs/Roadmap_v2.5.md`
4. `docs/StableNew_Agent_Instructions_v2.5.md`
5. `docs/StableNew_Coding_and_Testing_v2.5.md`
6. `docs/Randomizer_Spec_v2.5.md`
7. `docs/Learning_System_Spec_v2.5.md`
8. `docs/Cluster_Compute_Spec_v2.5.md`

If a document is not listed above, Copilot must not treat it as authoritative.

---

# 2. Snapshot Discipline

Before modifying code or generating large changes:

- Copilot must ensure the **latest snapshot + repo_inventory.json** is available.
- If missing, Copilot must instruct:
  > “Please upload the latest snapshot and repo_inventory.json.”

Copilot must never assume file content or guess structure.

---

# 3. Subsystem Boundaries (Enforced)

Copilot must enforce strict separation:

### GUI Layer
- Responsible only for widgets, inputs, event bindings, and visual state.
- Must not implement pipeline logic or job construction.
- Must call controller callbacks for actions.

### Controller Layer
- Orchestrates pipeline flow only.
- Must call ConfigMergerV2, JobBuilderV2, JobService.
- Must not embed merging, building, or runner logic.

### Pipeline Layer
- Pure logic: merging configs, building jobs, normalizing job records.
- Must not import GUI, controllers, or queue.

### Queue Layer
- Responsible for job ordering, persistence, lifecycle.
- Must not mutate configs or implement pipeline logic.

### Runner Layer
- Executes pipeline stages in exact canonical order.
- Must not randomize or alter configuration.

---

# 4. PR Requirements (Copilot MUST follow)

Copilot must generate PRs that contain:

- **Title**
- **Summary**
- **Problem**
- **Intent**
- **Allowed / Forbidden files**
- **Implementation steps**
- **Required tests**
- **Acceptance criteria**
- **Rollback plan**
- **Risk Tier**

No PR may merge without tests for logic-affecting changes.

---

# 5. Coding Standards (Required)

Copilot must obey:

- Use `@dataclass` for structured data.
- Prefer pure functions (no side effects).
- Avoid duplicating logic across modules.
- Do not mutate incoming configs; create copies.
- Use typed classes, not raw dicts.
- Controllers must use helper methods and dependency injection.
- Pipeline logic must be deterministic.

Reference: `StableNew_Coding_and_Testing_v2.5.md`

---

# 6. Testing Standards (Required)

Copilot must include:

### Unit tests
- For ConfigMergerV2, JobBuilderV2, RandomizerEngineV2, NormalizedJobRecord.

### Integration tests
- For PipelineControllerV2 + JobService interaction.

### GUI behavior tests
- For Randomizer panel, Preview panel, Queue panel.

### Principles
- “Failing first” test methodology.
- Clear naming conventions: `test_<behavior>_v2`.

No PR modifying logic may omit tests.

---

# 7. When Copilot Must Ask the User

Copilot must request clarification when:

- Architecture impact is unclear.
- File or function location is ambiguous.
- User request conflicts with canonical docs.
- Request involves modifying forbidden subsystems (executor, runner).

Copilot must respond:
> “This request conflicts with canonical architecture/governance. Please clarify.”

---

# 8. Forbidden Actions

Copilot must never:

- Modify executor or runner internals without explicit permission.
- Invent pipeline stages or modify ordering.
- Embed pipeline logic in GUI widgets.
- Introduce new subsystems without roadmap alignment.
- Change RandomizerEngine semantics.
- Alter JobBuilderV2 or ConfigMergerV2 without corresponding tests.
- Touch `docs/archive/` files.
- Reference non-canonical documentation.

---

# 9. Drift Prevention (Self-Check Before Output)

Copilot must internally validate:

- Am I quoting or using only canonical v2.5 docs?
- Am I respecting subsystem boundaries?
- Did I avoid hallucinating file structure?
- Do proposed changes require tests?
- Does this PR follow the template?
- Did I avoid touching forbidden files?
- Am I preserving deterministic behavior?

If the answer to any check is “no,” Copilot must not generate the code.

---

# 10. Versioning and Documentation Enforcement

- Canonical documents must end with `v2.5.md`.
- Any architectural or governance changes must update:
  - DOCS_INDEX_v2.5.md
  - Relevant subsystem spec.
- Copilot must not introduce undocumented behaviors.

---

# End of .github/copilot-instructions.md
#CANONICAL