# StableNew AI model selection

Last reviewed: 2026-10-17

The single authority for choosing a coding model and effort. `AGENTS.md`, the work-package template and the agent
files point here instead of copying it. This is a starting heuristic, not a routing rule and not authority to act
(capability is separate from owner authorization).

## What every package records

- **Before:** one line in the PR body or work package, `Model recommendation`: the Claude Code model + effort and the Codex
  model + effort, with a few words on why that is the lowest tier likely to finish the whole package, and an **expected usage**
  as an order of magnitude (for example "about 10M cache-read, 60k output"). Add a preferred host only when one materially fits
  better; otherwise stay in the current session and keep its context.
- **After:** one line in the completion report, `Model / usage`: host, actual model, effort, repair passes, result
  (PASS / FAIL / BLOCKED), and the measured tokens from `python tools/usage_report.py --since-commit <first commit of the
  package> --line` (it sums the usage both hosts already log locally; run it from the same machine). The script reports tokens
  only. Never estimate a missing value or convert tokens to a price. Do not commit just to persist this line; the PR body is the
  record.

## Selection matrix (starting heuristic)

| StableNew work profile | Codex default | Claude Code default |
|---|---|---|
| Git/status/docs cleanup/mechanical validation | GPT-6 Luna Low/Medium | Haiku 4.5 High, or Sonnet 5.5 Low |
| Narrow known-root-cause bug | GPT-6.1 Sol Medium | Sonnet 5.5 Medium/High |
| Normal substantial known-architecture PR | GPT-6.1 Sol High | Sonnet 5.5 High |
| Difficult bounded lifecycle/persistence/concurrency/cross-file PR | GPT-6.1 Sol High or XHigh | Sonnet 5.5 XHigh |
| Material architecture/ownership ambiguity | GPT-6 Astra High/XHigh | Opus 5.5 High/XHigh |
| Very large well-specified repo-wide autonomous work | GPT-6 Astra XHigh/Max | Fable 5.1 XHigh/Max |
| Routine independent verification | GPT-6.1 Sol Medium | Sonnet 5.5 Medium |
| High-risk verification / security review | GPT-6 Astra High | Opus 5.5 High |

Weigh also: architecture ambiguity, number of interacting subsystems, cost of a wrong implementation, cost of another
discovery pass, and how much valuable context the current session already holds. Prefer the current productive session over
switching hosts for a small theoretical gain; when switching, hand over branch/worktree, exact SHA, acceptance contract,
accepted evidence, unresolved findings and authorization boundaries, and do not restart discovery.

## Effort

- Start at the lowest effort likely to complete the **whole package** correctly, not just its first edit.
- Medium for bounded known work; High is the default for substantial work; XHigh for lifecycle, concurrency, persistence or
  cross-file interactions where failure is costly; Max only when lower-effort evidence has failed. Max can do worse than XHigh
  (extra agent activity causes timeouts and out-of-scope edits).
- If a model is struggling, do not raise its effort indefinitely; if capability is the constraint, move up a model.

## Splitting a package across models

The session picks one model and effort for the top-level executor. Where the host allows a delegated task to run on a different
model (Claude Code's Agent tool takes a `model`), recommend a split only when a package has a clearly separable hard part:
for example, run the package at Sonnet 5.5 High and delegate the one architecture-ambiguous analysis to Opus 5.5, or delegate
read-only exploration to a cheaper model. Do not split for small packages; delegation costs a fresh context.

## Keeping the table honest

The matrix is a prior. The PR history is the evidence, and it is read from merged PR bodies and follow-up commits, not from a
separate ledger file. Review it after every ten merged PRs, or when a new model family or price change lands. Change a row only on
a pattern, never on a single outlier, and move one step at a time:

- **Raise a row** when at least 2 of the last 5 PRs in that class needed 2 or more repair passes, or ended FAIL or BLOCKED,
  at that tier.
- **Try lowering a row** when the last 5 PRs in that class were clean (at most one repair pass) at that tier; try the lower tier on
  the next PR of that class only, and keep it if that one is also clean.
- A "repair pass" is a commit pushed to the PR after its first full CI run or review, made to fix a defect in that PR (not a scope
  change or a rebase).
- With fewer than 5 PRs in a class, do not change the row.

Compare each PR's expected usage with the measured line. Investigate any PR whose measured output or cache-read tokens are more
than 3 times the expectation (or less than a third of it): the cause is usually a mis-sized package, repeated discovery,
or a session that carried too much context, and it points to a fix in the recommendation, the package size, or the session policy.

Questions for the review: did a model cause repair passes that a higher tier would have avoided; did a cheaper model cost more
overall through rediscovery; was the cost mostly reasoning or re-reading repository context.
