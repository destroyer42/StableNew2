# StableNew Agent Operating Model

## Purpose

StableNew uses AI agents as a bounded software-delivery system rather than as a
single accumulating chat. The repository is durable memory. A session is
temporary working memory.

Rob owns product intent, priority, user-visible behavior, and approval of
material architecture or production decisions. Agents own normal technical
discovery, implementation detail, testing, repair, documentation impact, and
PR preparation inside an approved outcome.

## Default workflow: single lane

`Owner outcome -> one primary Claude Code or Codex coding session -> focused validation ->
optional risk-triggered independent review -> feature-branch PR / required CI -> owner-authorized
integration`

One active editing session owns one coherent package and worktree. Neither the VS Code Agents
window, `StableNew Delivery`, nor `StableNew Release` is required for ordinary implementation.

### Local feature-branch lifecycle

After verifying branch/SHA/worktree and the owner-authorized package scope, the active coding
session may, as ordinary implementation actions and without a separate Release session:

- create or switch to the authorized short-lived feature branch (never edit `main` or another
  long-lived target);
- edit the package;
- run validation;
- make local feature-branch commits.

If the owner's initial authorization also explicitly includes feature-branch publication, the same
session may commit, push that feature branch, and open/update its PR after final aggregate
verification.

Separate, explicit, current owner authorization naming the action and target/scope is still required
for: integration or merge to `main` or another long-lived target; force-push or history rewrite;
tag/release; deployment; destructive migration; secrets/credentials; and any other
irreversible/shared/protected action. Auto Approve / Full Access changes available capability, not
the scope of owner authorization.

### Specialist agents are optional

The `.github/agents` workflow remains available when it adds value; it is not a mandatory stage
sequence. Use a specialist only when justified:

- **StableNew Researcher** — meaningful current/external research, or uncertain code ownership that
  would otherwise pollute implementation context.
- **StableNew Architect** — genuine architecture/lifecycle/ownership ambiguity or a material design
  decision.
- **StableNew Builder** — implementation/repair delegated inside an orchestrated run.
- **StableNew Verifier** — independent acceptance review when change risk warrants the extra context
  cost.
- **StableNew Security Review** — only when the security triggers below apply.
- **StableNew Release** — optional Git lifecycle/closeout specialist when independent Git
  verification is useful; never required merely to create a local feature branch.

`StableNew Delivery` is an orchestration-only coordinator that has no Git-execution tools. If it is
explicitly invoked while the workspace is on `main` or another long-lived target, it stops before
Builder edits and emits a Branch Bootstrap Capsule (its agent definition lists the fields). That is a
limitation of that agent's tool set, not a repository-wide requirement, and it does not apply to a
primary Claude Code or Codex session.

Native custom-agent handoff is unavailable in the current Codex Agent Host
(`CODEX_AGENT_HOST_NATIVE_HANDOFF_UNAVAILABLE`); an orchestrated run that needs Release ends with a
Release-ready capsule and an explicit operator transition to a top-level Release session.
Top-level Release independently validates the capsule before mutation, reuses accepted evidence only
while unchanged, and performs only explicitly authorized actions.

### Package sizing: prefer larger coherent packages

Optimize total successful-work cost, not PR count. Default to the largest coherent package that
shares one product outcome and context, stays within understood architecture, can be validated
together safely, and needs no new material owner decision. Keep adjacent authorized implementation,
tests, and affected documentation together when safe.

Do not create separate sessions or PRs solely for documentation closeout, branch choreography,
mechanical Git steps, repeated context discovery, or artificial phases that share one acceptance
contract. Stop and split when a genuinely different product objective begins, a new
architecture/product decision is required, destructive/shared-state authority changes, ownership
becomes ambiguous, more than two materially different failure classes emerge, or the combined
package can no longer be safely reviewed and validated as one unit.

### Reduce PR / CI / review churn

Use one repository/context acquisition pass; one coherent implementation pass; focused tests while
editing; at most one batched repair pass per failure class; one final aggregate diff/acceptance
review; one full local PR gate near final verification when applicable; and required GitHub CI after
the feature branch is substantially complete. Reuse green exact-SHA evidence while relevant source
is unchanged. Do not repeatedly commit or push merely to solicit feedback on incomplete subphases
unless remote evidence is genuinely required. Automated review findings are evidence, not
authorization; batch confirmed blocking findings instead of one commit per finding (see the review
and repair protocol below).

### Task classes and model selection

`Narrow / Standard / Architectural` classify the task. **`docs/AI_MODEL_SELECTION.md` is the sole
canonical authority for model and effort selection**: its dated table, selection logic, effort rules,
empirical-calibration rules and review cadence are not duplicated here. Every new work-package prompt
states a **Codex** model + effort and a **Claude Code** model + effort from that document (current
model names, never a stale mapping), and a **preferred host** only when one materially fits better;
otherwise the work stays in the current host and session to preserve context. Every completion
report carries the `Model / usage` section that document defines.

When transferring hosts or models, preserve the branch/worktree, exact SHA, acceptance contract,
accepted evidence, unresolved findings and authorization boundaries, and do not restart discovery.

### Capability and permission model

Capability is separate from authorization. Global permissions remain conservative. Session Full
Access or Auto Approve changes what a session can do, not what the owner has authorized. Git
operations that mutate `.git` are supported in the active top-level coding session (or a top-level
Release session); a nested Release is not a supported Git mutation path. There is no custom Git
authority or tool, and no broad permission change. No agent is thereby authorized to merge or target
`main`, publish a release, deploy, mutate secrets, or perform destructive actions; those still
require explicit owner authorization naming the action and target/scope.

### Narrow change

Skip research and architecture analysis when current code and acceptance are
obvious. The primary session implements and runs focused validation; add an
independent Verifier only when risk warrants it, and Security Review when
triggered.

### Standard change

Establish the architecture fit and validation plan before editing, in the primary
session. Use an Architect only for genuine ambiguity, and a Researcher only for
uncertain code ownership, external semantics, or current upstream behavior.

### Architectural change

Research and architecture analysis are both performed, by the primary session or
by specialists. The analysis returns the decision that requires owner approval.
Implementation does not begin until the architecture decision is approved and the
appropriate repository authority is updated.

## Context policy

Always-loaded context stays small:

- `AGENTS.md`
- `CLAUDE.md` when using Claude
- `.github/copilot-instructions.md` when using Copilot surfaces

Task-specific procedure lives in skills and is loaded on demand.

Persistent project truth stays in canonical repository docs. Do not use chat
history as an architecture authority.

### Default startup context

The current checkout, the prompt/work-package contract, and the applicable
repository-local canonical authorities are sufficient by default. Routine
package startup must not inspect `~/.codex/memories`, provider memory,
historical chats, archived plans, or similar historical sources. Use such
sources only for an explicitly historical question or for a specifically
identified fact missing from the current prompt and repository evidence; keep
any retrieval targeted to that question or fact rather than broad.

Agents should acquire repository state once, reuse it while unchanged, and
avoid repeatedly reading the full roadmap or architecture. Start from
`STATUS.md` and the relevant `CODEX_MAP.md` row.

Reuse accepted exact-SHA evidence while relevant source is unchanged; a
documentation-only change does not invalidate source/runtime evidence. Do not
reuse evidence after a relevant source change, and do not broaden work merely
because an informational check is unrelated or unavailable.

## Worktree policy

Use a dedicated worktree for significant feature, refactor, or bug-fix work.

One worktree/session should normally own one coherent work package. Do not let
multiple editing agents write into the same worktree concurrently.

Read-only Researcher, Architect, Verifier, and Security Review may inspect the
same worktree. Only one editing session owns edits at a time.

Preserve unrelated dirty work and user data. An agent may integrate or push a
long-lived target only after explicit owner authorization; authorization must
name the integration action and target.

## Token policy

1. Prefer repository state over conversation recap.
2. Delegate broad searches to an isolated Researcher only when they would
   otherwise pollute the implementation context; return a compact evidence
   capsule.
3. Do not hand an implementer a research transcript; send findings, constraints,
   paths, and acceptance criteria.
4. Use deterministic scripts for Git state, lint, type, test, and diff checks.
5. Do not rerun green expensive evidence when relevant source is unchanged.
6. Start a new session at coherent task/PR boundaries; otherwise stay in the
   current session while it remains capable.
7. Use the lowest current model/effort that reliably fits the execution class.
8. Escalate only when discovery proves the current execution class is
   insufficient.

Each authored PR or bounded work package records:

- **Execution Profile + Model/Reasoning Recommendation** — execution class; the
  Codex and Claude Code model + effort chosen per `docs/AI_MODEL_SELECTION.md`;
  a preferred host only when one materially fits better; and why this is the
  lowest effective tier, including retry/failure cost where relevant;
- **Controller Surface Assessment** — whether controller/coordinator product
  code is touched; orchestration-only Delivery does not count as product
  controller code;
- **Token-Efficient Validation Plan** — the smallest focused checks, evidence
  reuse conditions, and any required full gate or CI follow-up.

The completion report records actual model, effort and host-reported usage in a `Model / usage`
section (`docs/AI_MODEL_SELECTION.md`); unavailable metrics are reported as unavailable, never
estimated.

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

## Checkpoint and documentation discipline

For Narrow and Standard work, use one focused discovery pass, one coherent
implementation pass, one focused repair pass, and final verification. Stop when
the accepted phase is complete rather than beginning the next roadmap item.
Architectural work requires owner continuation.

### Codex review is on demand, not a mandatory stage

Automated Codex PR review is not a mandatory StableNew stage. The ordinary workflow is one top-level
implementation host, focused local validation, `run_pr_gate.py` once near final, risk-proportionate
GitHub CI, independent product-owner review (ChatGPT) and the merge decision. Request a Codex review
when a second specialist reviewer materially lowers risk: security; persistence/schema/data
migration; concurrency/cancellation/process lifecycle; runtime ownership; model/backend identity and
provenance; unusually large cross-cutting refactors; repeated repair failure; material architecture
ambiguity; or an explicit owner request. For such a PR prefer one intentional review of a
substantially complete implementation over automatic review of every repair push. Account-level Codex
Auto Review is an owner/platform setting; do not invent a repository workaround for it.

### Review and repair protocol

Automated CI and review output is evidence, never scope or authorization.
Before repair, collect findings against current HEAD and classify each as a
current blocking in-scope defect, current non-blocking debt,
stale/duplicate/already-fixed, or future-hardening/out-of-scope. Only a confirmed
current blocking in-scope defect, security defect, or required-CI failure caused
by the package authorizes repair.

Repair-loop stop rule: if review or validation uncovers more than two materially different
failure classes, or requires a new product/architecture decision, STOP: preserve the branch, SHA and
evidence and re-scope before continuing. Do not grow one PR through successive unrelated repairs.
Batch confirmed review findings locally where possible before publishing the next repair SHA.

Batch confirmed findings into one coherent repair pass, then perform one
independent reverification. A materially new blocking failure class after that
reverification is a stop/report boundary, not authority for another open-ended
loop. Repeated, stale, or already-fixed bot findings are verified against current
HEAD and closed/reported without mutation. Once acceptance is true, required CI
is green, Verifier/Security conditions are satisfied, and findings remaining are
non-blocking or future-hardening, stop rather than improve the package further.

### Post-runtime evidence freeze

After a bounded qualification package's final authorized physical, GPU, or
external-state run, its executed harness/protocol is evidence-frozen. Post-run
qualification tooling/test changes require a demonstrated defect affecting the
validity, interpretation, preservation, security, or reproducibility of captured
evidence, or a required-CI defect blocking publication. A hypothetical future
run becoming safer or more robust is insufficient when no future run is
authorized. A newly desired run is a new or explicitly continued package with
its own acceptance contract. Do not rerun physical evidence solely because
deterministic post-run processing was corrected unless that correction actually
invalidates the captured physical run.

Before the next functional phase, verify exact SHA/diff and applicable
validation/required CI, accept based on behavior and architecture rather than
tests alone, determine whether canonical truth changed, and update only the
affected canonical authority. Do not narrate commits in canonical docs.

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

## Integration and production rule

An agent may integrate or push a long-lived target, merge a PR, release/tag,
deploy, mutate secrets/credentials, perform a destructive migration, or take an
irreversible/shared external action only when the current task has explicit
owner authorization naming the action and target/scope. A repository policy may
prescribe procedure, preconditions, or automation; it cannot authorize an
action without that current explicit owner authorization.

Immediately before an authorized long-lived integration or equivalent external
action, fail closed: verify the authorization and intended action/target are
present and unambiguous; local and remote refs, ancestry/fast-forward state,
worktree, aggregate diff against the accepted task/outcome, explicit exclusions,
any owner-supplied file constraints, unrelated-user-work preservation, required
CI/checks, and verifier/security findings all remain valid. On any drift,
missing evidence, or
ambiguity, stop and report. Do not force-push, rewrite history, choose an
alternate ref, bypass CI, widen scope, or infer authority.

Feature-branch publication (authorized in the initial package authorization or
separately) may create, commit, and push only after rechecking the exact current HEAD and aggregate diff against the
accepted task/outcome, explicit exclusions, any file constraints the owner
actually supplied, and preservation of unrelated user work. An approved outcome
authorizes its normal implementation file scope without an owner file list;
unexpected changes not reasonably attributable to that outcome stop publication.
It never authorizes long-lived-target integration. CI
and review may be repaired only within the accepted task scope.

If StableNew later gains a fully automated release pipeline, production
credentials should live only in the CI environment and should never be
available to ordinary development agents.
