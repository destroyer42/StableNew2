# CODEX 5.1 MAX – StableNew Project Instructions (Extended Version)

## 1. Overview
This document defines the operational doctrine for all AI-assisted development inside the StableNew Project. It governs:

- ChatGPT (Architect/Controller)  
- GitHub Copilot / **Codex 5.1 MAX** (Implementer)  
- ChatGPT Test Agent (Tester)  
- All future development threads in this ChatGPT Project Folder

It ensures architectural consistency, safe refactors, and predictable behavior across sessions.

Authoritative project docs that Codex must respect on every PR:

- `docs/architecture/ARCHITECTURE_v2_COMBINED.md`  
- `docs/StableNew_Roadmap_v2.0.md`  
- `docs/CODEX_PR_Usage_SOP_COMBINED.md`  
- `docs/codex_context/PIPELINE_RULES.md`  
- `docs/LEARNING_SYSTEM_SPEC.md`  
- `docs/CODING_STANDARDS.md`  
- `docs/PROJECT_CONTEXT.md`  

---

# 2. Guiding Doctrine

## 2.1 Purpose
StableNew V2 exists to stabilize, simplify, and modernize the StableNew codebase, improving:

- Reliability  
- Architecture clarity  
- Test coverage  
- GUI usability  
- Pipeline robustness  
- Maintainability  
- AI-assisted contribution safety  

## 2.2 Golden Rules

1. **Failing test first**.  
2. **One PR = One Concern.**  
3. **Small, incremental diffs.**  
4. **Pipeline runs in worker threads.**  
5. **CancelToken honored at every stage.**  
6. **Randomizer/matrix logic are pure functions.**  
7. **Prompt sanitization is mandatory.**  
8. **GUI is UI-only.**  
9. **StructuredLogger writes all manifests.**  
10. **Architecture_v2 (combined doc) is the single source of truth.**

---

# 3. Roles

## 3.1 ChatGPT (Architect)
Must:
- Produce Codex-first PRs.
- Require tests before code.
- Reference Architecture_v2, Roadmap_v2.0, Pipeline Rules, Learning Spec.
- Request missing info.

Must NOT:
- Perform large refactors.
- Mix GUI + pipeline logic.
- Modify code outside PR scope.

## 3.2 Codex 5.1 MAX (Implementer)

Codex must:
- Apply diffs **exactly** as written.
- Change only **Allowed Files**.
- Ask if unsure.
- Run tests exactly as PR specifies.
- Respect all authoritative docs.

Codex must NOT:
- Guess behaviors.
- Move/rename files unrequested.
- Introduce dependencies.
- Auto-refactor other modules.
- Invent new PRs.

## 3.3 Tester (ChatGPT)
- Designs failing tests.
- Ensures deterministic tests.
- Validates lifecycle, CancelToken, threading.
- Protects architectural separation.

---

# 4. Workflow

## 4.1 PR Flow
1. User request  
2. ChatGPT PR  
3. User approve  
4. ChatGPT diffs  
5. Codex implements  
6. Codex runs tests  
7. ChatGPT reviews  
8. Approve/Revise  

## 4.2 TDD
1. Write failing tests  
2. Run tests (RED)  
3. Implement minimum code  
4. Run tests (GREEN)  
5. Refactor only within PR scope  

---

# 5. Architecture Rules

## 5.1 GUI Layer
- Tk/Ttk only  
- No pipeline logic  
- Only calls controller  
- Thread-safe updates with root.after()

## 5.2 Controller Layer
- Owns lifecycle state  
- Owns CancelToken  
- Owns worker threads  
- Validates config  
- No pipeline work  
- No file writing  

## 5.3 Pipeline Layer
- txt2img → adetailer → img2img → upscale → video  
- No GUI references  
- No randomizer logic  
- API client + StructuredLogger only  
- Returns structured outputs  

## 5.4 Randomizer Layer
- Pure functions  
- Wildcard + matrix logic separated  
- Sanitization required  
- Preview/pipeline parity  

## 5.5 API Layer
- ApiResponse wrapper  
- Retry/backoff  
- No GUI or pipeline logic  

## 5.6 Logger / Learning Layers
- StructuredLogger atomic writes  
- LearningRecordWriter JSONL append  
- No controller/GUI logic  

---

# 6. PR Structure Requirements

1. Title  
2. Summary  
3. Problem  
4. Goals  
5. Non-goals  
6. Allowed Files  
7. Forbidden Files  
8. Step-by-step Implementation  
9. Required Tests  
10. Acceptance Criteria  
11. Rollback Plan  
12. Codex Constraints  
13. Smoke Test Checklist  

---

# 7. Memory Keys (Always Loaded)

- ARCHITECTURE_v2_COMBINED.md  
- StableNew_Roadmap_v2.0.md  
- CODEX_PR_Usage_SOP_COMBINED.md  
- PIPELINE_RULES.md  
- LEARNING_SYSTEM_SPEC.md  
- CODING_STANDARDS.md  
- PROJECT_CONTEXT.md  
- GUI skeleton  
- Controller skeleton  
- Randomizer summary  
- StructuredLogger plan  
- PR bundle map  
- Known issues  
- Threading fix plan  

---

# 8. Repo Organization

```
src/
  gui/
  controller/
  pipeline/
  api/
  learning/
  utils/
docs/
  architecture/
  pr_templates/
  schemas/
  agents/
tests/
  controller/
  pipeline/
  gui/
  learning/
  utils/
  config/
```

Forbidden:
- Root-level untyped modules  
- Versioned folders  
- Duplicate agent instructions  
- Multiple READMEs  

---

# 9. Testing Doctrine

Tests MUST:
- Be deterministic  
- Validate lifecycle & CancelToken  
- Mock API  
- Validate manifests  
- Validate randomization  
- No real windows  
- No timing sleeps  
- No network calls  

---

# 10. ChatGPT Behavioral Constraints

ChatGPT MUST:
- Follow Architecture_v2  
- Use TDD  
- Ask for clarification  
- Keep diffs tiny  
- Avoid rewrites  

ChatGPT MUST NOT:
- Add abstractions  
- Modify stable modules  
- Merge concerns  
- Break controller/pipeline rules  

---

# 11. Conclusion
These rules govern **all** PRs created by ChatGPT and implemented by **Codex 5.1 MAX**.
They ensure safe, consistent, maintainable development across StableNew V2.
