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

The VS Code Agents window is the supported current orchestration
implementation; it is not a universal or repository authority.

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
- **StableNew Release** — pre-build feature-branch bootstrap, branch/PR/CI
  closeout, and only explicitly authorized, verified integration.

### Capability and permission model

Luna, Terra, Sol, and Astra are provider-neutral capability classes. They are
guidance for selecting the lowest effective available reasoning/model tier;
they are not vendor names, model mappings, or authority grants. Use the lowest
class that can reliably complete the assigned work and escalate only when
discovery or validation shows that the current class is insufficient:

- **Luna** — narrow documentation/configuration edits, straightforward
  read-only inspection, and focused validation.
- **Terra** — bounded implementation, repair, and deterministic test work
  within an understood surface.
- **Sol** — materially uncertain, cross-surface, or architecture-sensitive
  work requiring deeper analysis and independent evidence.
- **Astra** — high-risk security, release, or integration analysis where the
  cost of an incorrect decision is substantial.

Capability is separate from authorization. Global permissions remain
conservative. Full Access is session-specific to top-level Release Git
lifecycle operations: narrowly authorized feature-branch bootstrap and
authorized publication/closeout; it changes available capability, not owner
authorization. Git/publication operations that mutate `.git` are supported
only in that top-level Release session using Full Access. A nested Release is
not a supported Git mutation path. Bootstrap and publication/closeout are two
distinct, mutually exclusive Git lifecycle modes; bootstrap authority never
carries forward publication authority.

There is no custom Git authority or tool, and no broad permission change. No
agent is thereby authorized to merge or target `main`, publish a release,
deploy, mutate secrets, or perform destructive actions. Those actions still
require explicit owner authorization naming the action and target/scope.

## Normal delivery flow

`End state -> Delivery startup check -> [not already on an appropriate
short-lived branch? emit Branch Bootstrap Capsule -> explicit operator
transition -> top-level Release + Full Access bootstrap -> explicit return to
Delivery] -> Research (when needed) -> Architecture/plan -> Build -> Verify ->
Security (when triggered) -> Release-ready capsule -> explicit operator
transition -> top-level Release -> Full Access closeout -> owner merge/release`

Not every task uses every stage.

### Branch bootstrap

Before delegating implementation, Delivery checks the current branch, HEAD,
and worktree. If the workspace is already on an appropriate short-lived
feature branch with state matching the supplied package, Delivery skips
bootstrap and proceeds directly to normal routing — the fast path.

If implementation is required and the current branch is `main` or another
long-lived target, Delivery stops before Builder edits and emits a **Branch
Bootstrap Capsule** rather than creating or switching branches itself,
staging, committing, mutating `.git`, spawning/nesting Release, or sending
Builder to edit `main`. The capsule contains:

- workspace path, when known;
- current branch;
- current HEAD;
- target/base ref, normally `origin/main`;
- worktree and untracked-file state;
- coherent package title/outcome;
- proposed short-lived feature-branch name;
- bootstrap authorization: create and/or switch to the approved short-lived
  feature branch necessary for this package — nothing more;
- prohibited actions: source/docs/config edits, staging, commit, push, PR
  creation, merge, long-lived-target mutation, force-push, tag/release,
  deployment, destructive migration, secrets/credentials.

The operator starts or selects a top-level StableNew Release session with
Full Access to independently verify the capsule and, within bootstrap
authority only, create/switch to the authorized short-lived branch, verify
the resulting HEAD/branch/worktree, report it, and stop. Release performs no
source edits and no publication under bootstrap authority alone. The operator
then explicitly returns to Delivery, which resumes under normal permissions
and routes to Researcher/Architect/Builder as usual.

Delivery is an orchestration-only coordinator. It routes work, preserves the
handoff contract, and reports the compact delivery capsule; it does not edit
code, docs, or configuration and does not become a Git or product authority.
Delivery ends after accepted Builder -> Verifier evidence and Security Review
evidence when triggered. It cannot commit, push, open a pull request, merge, or
mutate `.git`.

Native custom-agent handoff is unavailable in the current Codex Agent Host
(`CODEX_AGENT_HOST_NATIVE_HANDOFF_UNAVAILABLE`). When publication was
requested, Delivery must not nest, create, or spawn Release, switch workspace
or branch, mutate Git, or claim native handoff support. Instead it ends with a
compact Release-ready capsule and explicitly directs the operator to start or
select a top-level StableNew Release session in the same verified workspace.
The capsule contains the workspace path if known; branch; HEAD; `origin/main`;
expected changed-file set; Verifier verdict; Security verdict when applicable;
validation evidence; authorized publication actions; and prohibited actions.

Top-level Release independently validates the capsule before mutation,
reacquires current Git/ref/diff state, reuses accepted evidence only while
unchanged, and performs only explicitly authorized publication actions. The
operator selects session-specific Full Access for authorized closeout; it is a
capability, not authorization. Explicit owner approval remains required for
main integration, merge, tag/release, deployment, destructive migration,
secrets, force-push, and protected actions. A nested Release path is not
supported.

### Narrow change

Skip research and architecture delegation when current code and acceptance are
obvious. Builder implements and Verifier checks; insert Security Review when
triggered. Delivery ends with accepted evidence and, when publication was
requested, a Release-ready capsule plus explicit operator transition to a
top-level Release session for authorized closeout.

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
same worktree. Only one Builder owns edits at a time.

Preserve unrelated dirty work and user data. A Release agent may integrate or
push a long-lived target only after explicit owner authorization; authorization
must name the integration action and target.

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

Each authored PR or bounded work package records:

- **Execution Profile + Model/Reasoning Recommendation** — execution class,
  selected capability class, and why it is the lowest effective available
  tier, including retry/failure cost where relevant;
- **Controller Surface Assessment** — whether controller/coordinator product
  code is touched; orchestration-only Delivery does not count as product
  controller code;
- **Token-Efficient Validation Plan** — the smallest focused checks, evidence
  reuse conditions, and any required full gate or CI follow-up.

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

### Review and repair protocol

Automated CI and review output is evidence, never scope or authorization.
Before repair, collect findings against current HEAD and classify each as a
current blocking in-scope defect, current non-blocking debt,
stale/duplicate/already-fixed, or future-hardening/out-of-scope. Only a confirmed
current blocking in-scope defect, security defect, or required-CI failure caused
by the package authorizes repair.

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

Separately authorized feature-branch publication may create, commit, and push
only after rechecking the exact current HEAD and aggregate diff against the
accepted task/outcome, explicit exclusions, any file constraints the owner
actually supplied, and preservation of unrelated user work. An approved outcome
authorizes its normal implementation file scope without an owner file list;
unexpected changes not reasonably attributable to that outcome stop publication.
It never authorizes long-lived-target integration. CI
and review may be repaired only within the accepted task scope.

If StableNew later gains a fully automated release pipeline, production
credentials should live only in the CI environment and should never be
available to ordinary development agents.
