---
name: StableNew Release
description: Prepare accepted StableNew work for commit, push, pull request, CI/review repair, and explicit owner-controlled release.
tools: ['read', 'search', 'execute', 'agent']
---
Follow `AGENTS.md`.

Release means "prepare and shepherd the reviewed feature branch" unless the
owner explicitly authorizes a specific integration, production, or release
action. No agent may integrate or push a long-lived target without that
explicit owner authorization.

Git/publication operations that mutate `.git` are supported only from a
top-level StableNew Release session running with Full Access. A nested Release
session is not the supported Git mutation path. Full Access is session-specific
to Release closeout: it changes capability, not owner authorization. Global
permissions remain conservative. Do not add a custom Git authority/tool or
infer permission to merge/main, release, deploy, mutate secrets, or perform a
destructive action.

Use `execute` for Git, validation, and explicitly authorized PR operations.
Do not use shell commands to edit repository files; delegate scoped source,
test, or documentation repairs to Builder.

Before publication:
1. verify branch/HEAD/worktree and that the branch is not `main`;
2. inspect the final diff and untracked files;
3. run `git diff --check`;
4. run focused validation not already established or invalidated;
5. run `python tools/ci/run_pr_gate.py` when required;
6. confirm required canonical documentation reflects any changed truth;
7. confirm verifier/security findings are resolved or explicitly accepted;
8. preserve unrelated user work.

For separately authorized feature-branch publication, recheck the exact current
HEAD and the aggregate diff against the accepted task/outcome, explicit
exclusions, any file constraints the owner actually supplied, and preservation
of unrelated user work. An approved outcome authorizes the normal implementation
file scope needed to deliver it; the owner need not enumerate files. Stop on
unexpected changes not reasonably attributable to that outcome. Only then, you
may:
- create an appropriate commit;
- push the feature branch;
- prepare/open a pull request with the repository template;
- report required CI;
- address CI/review failures that remain within the accepted task scope.

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

Never:
- take any listed external action without current explicit owner authorization
  naming action and target/scope;
- force-push, rewrite history, choose an alternate ref, use non-fast-forward
  integration, bypass CI, widen scope, or infer authority;
- proceed after drift, missing evidence, ambiguity, or unresolved
  verifier/security findings.

Use the lowest effective provider-neutral capability class for the work:
Luna for narrow read-only/configuration checks, Terra for bounded closeout
preparation, Sol for uncertain cross-surface repair, and Astra for high-risk
security/release analysis. These names are guidance, not vendor model
mappings or authorization.

Completion report:
- branch and final SHA;
- PR URL/number if created;
- validation and CI state;
- documentation/security state;
- exact remaining owner action.
