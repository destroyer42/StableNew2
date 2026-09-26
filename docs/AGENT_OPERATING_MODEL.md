# StableNew Agent Operating Model

## Purpose

StableNew uses AI agents as a bounded software-delivery system rather than as a
single accumulating chat. The repository is durable memory. A session is
temporary working memory.

Rob owns product intent, priority, user-visible behavior, and approval of
material architecture or production decisions. Agents own normal technical
discovery, implementation detail, testing, repair, documentation impact, and
PR preparation inside an approved outcome.

## Control plane

The preferred interactive surface is the VS Code Agents window.

Use `StableNew Delivery` as the normal entry point. It delegates to specialist
agents with isolated contexts and returns only the information needed to
continue the task.

Specialists:

- **StableNew Researcher** — product/repo/current-technology discovery.
- **StableNew Architect** — architecture fit, execution class, boundaries,
  implementation plan, validation plan.
- **StableNew Builder** — implementation and repair in the assigned worktree.
- **StableNew Verifier** — independent acceptance review and test evidence.
- **StableNew Security Review** — triggered security review for sensitive
  surfaces.
- **StableNew Release** — branch/PR/CI closeout; never direct-to-main production
  release without owner approval.

## Normal delivery flow

`End state -> Research (when needed) -> Architecture/plan -> Build -> Verify ->
Security (when triggered) -> PR-ready -> CI/review repair -> owner merge/release`

Not every task uses every stage.

### Narrow change

Skip research and architecture delegation when current code and acceptance are
obvious. Builder implements, Verifier checks, Release prepares the PR.

### Standard change

Use Architect before Builder. Use Researcher only for uncertain code ownership,
external semantics, or current upstream behavior.

### Architectural change

Researcher and Architect both run. The Architect returns the decision that
requires owner approval. Implementation does not begin until the architecture
decision is approved and the appropriate repository authority is updated.

## Context policy

Always-loaded context stays small:

- `AGENTS.md`
- `CLAUDE.md` when using Claude
- `.github/copilot-instructions.md` when using Copilot surfaces

Task-specific procedure lives in skills and is loaded on demand.

Persistent project truth stays in canonical repository docs. Do not use chat
history as an architecture authority.

Agents should acquire repository state once, reuse it while unchanged, and
avoid repeatedly reading the full roadmap or architecture. Start from
`STATUS.md` and the relevant `CODEX_MAP.md` row.

## Worktree policy

Use a dedicated worktree for significant feature, refactor, or bug-fix work.

One worktree/session should normally own one coherent work package. Do not let
multiple editing agents write into the same worktree concurrently.

Read-only Researcher, Architect, Verifier, and Security Review may inspect the
same worktree. Only one Builder owns edits at a time.

## Token policy

1. Prefer repository state over conversation recap.
2. Delegate broad searches to an isolated Researcher and return a compact
   evidence capsule.
3. Do not send a builder the research transcript; send findings, constraints,
   paths, and acceptance criteria.
4. Use deterministic scripts for Git state, lint, type, test, and diff checks.
5. Do not rerun green expensive evidence when relevant source is unchanged.
6. Start a new session at coherent task/PR boundaries.
7. Use the lowest reasoning/model tier that reliably fits the execution class.
8. Escalate only when discovery proves the current execution class is
   insufficient.

## Security/release triggers

Invoke `StableNew Security Review` when a change touches any of these:

- dependencies or bootstrap/install behavior;
- credentials, tokens, secrets, environment variables, or authentication;
- subprocess/process ownership or shell execution;
- filesystem write/delete/move behavior or path traversal boundaries;
- network listeners, remote endpoints, downloads, or external services;
- deserialization of untrusted data;
- SQLite schema/data migration;
- updater/release/package installation behavior;
- model/workflow downloads or executing external workflow definitions;
- permission/privilege changes;
- CI/CD, signing, release, or deployment configuration.

Security Review is not required for ordinary pure UI copy, tests, docs, or
internal refactors that do not cross these boundaries.

## Product and architecture stop conditions

Stop for owner decision when evidence reveals a choice that materially changes:

- product-visible behavior not resolved by the request;
- canonical runtime ownership or an architecture invariant;
- user data migration/deletion semantics;
- compatibility policy;
- security boundary;
- supported hardware/platform scope;
- irreversible/shared external state.

Do not stop for ordinary file selection, refactoring needed for correctness,
test selection, implementation detail, or repair of failures caused by the
authorized change.

## Definition of PR-ready

A work package is PR-ready only when:

- the requested observable behavior is implemented;
- acceptance criteria are satisfied;
- regression coverage is present where appropriate;
- targeted validation passes;
- required StableNew gate/CI status is identified;
- the final diff is scoped and inspected;
- unrelated user work is preserved;
- architecture/controller impact is explicitly stated;
- canonical docs are updated only where truth changed;
- security review has passed when triggered;
- remaining debt/risk is stated.

## Production rule

No agent directly pushes to `main`.

Agents may prepare and push a feature branch and create a PR when authorized.
CI and review may be repaired automatically. Merge/release/deployment requires
an explicit owner action or an explicitly approved repository policy.

If StableNew later gains a fully automated release pipeline, production
credentials should live only in the CI environment and should never be
available to ordinary development agents.
