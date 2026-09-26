---
name: feature-delivery
description: Deliver a bounded StableNew feature or refactor from end state through implementation, validation, and PR-ready evidence.
---
Follow `AGENTS.md`.

Use this skill for a feature/refactor with a concrete user-visible or
architecture-preserving end state.

1. Establish current branch/HEAD/worktree once and reuse it while unchanged.
2. Read `STATUS.md`, the relevant `CODEX_MAP.md` row, and only relevant
   authority sections.
3. Convert the request into observable acceptance criteria and explicit
   exclusions. Use `docs/CODEX_WORK_PACKAGE_TEMPLATE.md` for work large enough
   to need a durable contract.
4. Classify Narrow / Standard / Architectural.
5. Research only unresolved code ownership or current external semantics.
6. For Architectural work, stop for owner approval on material decisions.
7. Implement the smallest coherent solution.
8. Add/update deterministic tests for changed behavior.
9. Validate targeted behavior first; reuse valid exact-SHA evidence; run the
   repository PR gate when required.
10. Independently inspect the final diff against acceptance.
11. Trigger security review only when the change crosses a relevant trust
    boundary.
12. Update canonical docs only when their truth changed.
13. Stop when the acceptance contract is true. Do not start the next roadmap
    item.

Never direct-push to `main` or merge/release without explicit approval.
