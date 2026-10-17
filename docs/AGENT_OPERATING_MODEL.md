# StableNew Agent Operating Model

How agent work is done. The rules (authority, protected actions, runtime safety, validation) live only in `AGENTS.md`; this
file adds procedure and never restates them. Model and effort choice lives in `docs/AI_MODEL_SELECTION.md`.

The repository is durable memory. A session is temporary working memory.

## Default workflow: single lane

`Owner outcome -> one primary Claude Code or Codex session -> focused validation -> optional risk-triggered independent review ->
feature-branch PR / required CI -> owner-authorized integration`

One active editing session owns one coherent package and worktree. After verifying branch, SHA and worktree, that session creates
or switches to the authorized short-lived feature branch, edits, validates and commits locally without a separate Release
session; push and PR creation need the publication authorization described in `AGENTS.md` section 5. No VS Code Agents window,
`StableNew Delivery` or `StableNew Release` session is required for ordinary work.

### Specialist agents are optional

The `.github/agents` set is available when it adds value; it is not a mandatory sequence.

- **Researcher:** meaningful external research, or uncertain code ownership that would pollute implementation context.
- **Architect:** genuine architecture, lifecycle or ownership ambiguity, or a material design decision.
- **Builder:** implementation or repair delegated inside an orchestrated run.
- **Verifier:** independent acceptance review when change risk warrants the extra context.
- **Security Review:** only when a security trigger below applies.
- **Release:** optional Git lifecycle and closeout specialist, never required merely to create a feature branch.
- **Delivery:** orchestration only, with no Git tools; on `main` it stops and emits a Branch Bootstrap Capsule. That is a limit of
  its tool set, not a repository rule.

Native custom-agent handoff is unavailable in the current Codex Agent Host (`CODEX_AGENT_HOST_NATIVE_HANDOFF_UNAVAILABLE`), so an
orchestrated run that needs Release ends with a Release-ready capsule and an explicit operator transition to a top-level Release
session, which validates the capsule before any mutation and reuses accepted evidence only while it is unchanged. A nested Release
is not a supported Git mutation path.

### Package sizing: prefer larger coherent packages

Optimize total successful-work cost, not PR count. Default to the largest coherent package that shares one product outcome and
context, stays within understood architecture, validates together safely, and needs no new material owner decision. Keep adjacent
authorized implementation, tests and affected documentation together. Do not create separate sessions or PRs solely for
documentation closeout, branch choreography, mechanical Git steps, repeated context discovery, or artificial phases that share one
acceptance contract.

Split when a genuinely different product objective begins, a new architecture or product decision is needed, authority over shared
state changes, ownership becomes ambiguous, more than two materially different failure classes emerge, or the package can no longer
be reviewed and validated as one unit.

### Reduce PR, CI and review churn

One context-acquisition pass; one coherent implementation pass; focused tests while editing; at most one batched repair pass per
failure class; one final aggregate diff review; one full local gate near the end; required GitHub CI once the branch is
substantially complete. Reuse green exact-SHA evidence while relevant source is unchanged. Do not commit or push to solicit feedback
on an incomplete subphase unless remote evidence is genuinely required.

### Task classes

- **Narrow:** skip research and architecture analysis when code and acceptance are obvious. The primary session implements and runs
  focused validation.
- **Standard:** establish architecture fit and the validation plan before editing, in the primary session. Architect only for real
  ambiguity; Researcher only for uncertain ownership, external semantics or current upstream behavior.
- **Architectural:** research and architecture analysis are both performed and return the decision that needs owner approval.
  Implementation starts after the decision is approved and the affected authority is updated.

## Context and session policy

Always-loaded context stays small: `AGENTS.md`, `CLAUDE.md` when using Claude, `.github/copilot-instructions.md` when using Copilot.
Task procedure lives in skills, loaded on demand. Do not use chat history as an authority.

**Where the tokens go.** A session re-reads its whole context on every turn. Cached reads are cheaper than fresh input but still
scale with context length times number of turns, so a long session spends far more on re-reading than on anything it writes
(measured on the roadmap session: about 217M cached tokens read against about 0.43M written). Long contexts are the cost to manage,
not the documentation read at the start.

- **One session per work package** (one PR, or a few tightly related ones). Start a fresh session at the package boundary.
  Carrying a session across unrelated packages costs more every turn and degrades recall.
- **Carry state in files, not chat.** `STATUS.md`, the task map, the PR body, the branch and the work-package contract are the
  handoff; a fresh session needs only those plus the files it touches. Keep them short so orientation stays cheap.
- **Compaction is a fallback**, not a strategy. If a package outgrows its context, compact at a natural boundary (a finished
  phase) and say what to keep; do not compact mid-edit.
- **Acquire repository state once** and reuse it while unchanged; do not re-read the whole roadmap or architecture. Start from
  `STATUS.md` and the relevant `docs/CODEX_MAP.md` row, and find modules in the generated `docs/CODE_MAP.md`.
- **Keep noisy work out of the main context.** Delegate broad searches, long CI logs and large file surveys to an isolated
  subagent that returns a compact evidence capsule (findings, paths, constraints, acceptance), never a transcript.
- **Wait on CI in the background** instead of polling with long commands in the foreground.
- Routine startup must not inspect `~/.codex/memories`, provider memory, historical chats or archived plans; use them only for an
  explicitly historical question or one identified missing fact.
- Use deterministic scripts for Git state, lint, type, test and diff checks, and do not rerun green expensive evidence.

## Worktree policy

Use a dedicated worktree for significant feature, refactor or bug-fix work. One worktree and session normally own one package; never
let two editing agents write into the same worktree. Read-only specialists may inspect it. Preserve unrelated dirty work.

## Security triggers

Invoke `StableNew Security Review` when a change touches: dependencies or bootstrap/install; credentials, tokens, secrets,
environment variables or authentication; subprocess or process ownership; filesystem write/delete/move or path boundaries; network
listeners, remote endpoints or downloads; deserialization of untrusted data; SQLite schema or data migration;
updater/release/package installation; model or workflow downloads, or executing external workflow definitions; permission or
privilege changes; CI/CD, signing, release or deployment configuration. It is not required for ordinary UI copy, tests, docs or
internal refactors that stay inside these boundaries.

## Review and repair

Codex review is on demand, not a mandatory stage. The ordinary path is one top-level implementation host, focused local validation,
`run_pr_gate.py` once near the end, risk-proportionate GitHub CI, independent product-owner review and the merge decision. Request a
second specialist review when it materially lowers risk: security; persistence, schema or migration; concurrency, cancellation or
process lifecycle; runtime ownership; model or backend identity; unusually large cross-cutting refactors; repeated repair failure;
architecture ambiguity; or an owner request. Prefer one review of a substantially complete implementation over review of every
repair push. Account-level Codex Auto Review is an owner or platform setting; do not invent a repository workaround.

CI and review output is evidence, never scope or authorization. Before repair, collect findings against current HEAD and classify
each as current blocking in-scope defect, current non-blocking debt, stale/duplicate/already-fixed, or future-hardening/out-of-scope.
Only a confirmed current blocking in-scope defect, a security defect, or a required-CI failure caused by the package authorizes
repair. Batch confirmed findings into one repair pass, then one independent reverification; close stale or repeated bot findings
against HEAD without mutation.

Stop rule: if review or validation uncovers more than two materially different failure classes, or needs a new product or
architecture decision, preserve the branch, SHA and evidence and re-scope. A materially new blocking class after the reverification
is a stop-and-report boundary, not authority for another loop. Once acceptance is true, required CI is green and the remaining
findings are non-blocking, stop rather than improve the package further.

### Post-runtime evidence freeze

After a bounded qualification package's final authorized physical, GPU or external-state run, its executed harness and protocol are
evidence-frozen. Later changes to them need a demonstrated defect affecting the validity, interpretation, preservation, security or
reproducibility of captured evidence, or a required-CI defect blocking publication. A hypothetical safer future run is not enough
when none is authorized; a new run is a new package with its own acceptance contract. Do not rerun physical evidence because
deterministic post-run processing was corrected unless the correction invalidates the captured run.

## Definition of PR-ready

The requested observable behavior is implemented; acceptance criteria are satisfied; regression coverage is present where
appropriate; targeted validation passes; required gate and CI status is identified; the final diff is scoped and inspected;
unrelated user work is preserved; architecture and controller impact is stated; canonical docs changed only where truth changed
(`STATUS.md` edited in place, never narrated); security review has passed when triggered; remaining debt and risk is stated.
Before the next functional phase, verify the exact SHA and diff and the applicable validation and CI, and update only the affected
authority.
