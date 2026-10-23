# StableNew AI model selection

Last reviewed: 2026-10-23

The single authority for choosing a coding model and effort. `AGENTS.md`, the work-package template and the agent
files point here instead of copying it. This is a starting heuristic, not a routing rule and not authority to act
(capability is separate from owner authorization).

## What every package records

- **Before:** record `Model recommendation` in the PR body/work package: Claude Code and Codex model + effort, why that tier
  should finish the whole package, and **expected usage** (e.g. "about 10M cache-read, 60k output"). Name a preferred host only
  when one materially fits better; otherwise stay in the current session and keep its context.
- **Measurement boundary:** record an ISO 8601 timestamp with timezone **before repository discovery** and host/session IDs.
  End after final closeout; include implementation, delegated work, review and repair. Do not commit to start measurement.
- **After:** one line in the completion report, `Model / usage`: host, actual model, effort, repair passes, result
  (PASS / FAIL / BLOCKED), exact measurement window and the measured tokens from
  `python tools/usage_report.py --since <task-start> --until <closeout-end> --session codex:<id> --line`.
  Repeat `--session claude:<id>` or `--session codex:<id>` for all participating sessions; run on the machine holding the logs.
  Tokens only: never estimate missing telemetry or convert to a price. The PR body is the record; no commit just for this line.

- A **package-specific measurement** needs a documented start/end boundary, all participating sessions and no unrelated work inside it.
  `--session` selects an exact host-qualified union; `--match` still filters cwd (default `stablenew`; `--match ''` disables it).
  IDs: Claude `sessionId` (including subagent streams sharing it); Codex `session_meta.payload.id`; absent IDs use filename stems.
  JSON `rows[].sessions` lists participants and `selected_sessions` the filter. Include separate subagent IDs when recorded.
- A **project-wide time window** includes every matching session; label it accordingly. A **shared session** needs an independently
  supported time/session boundary for an exact PR total. Never reconstruct historical PR totals or allocate tokens proportionally.
- `--since-commit` retains **post-commit** semantics: starts at committer time, omitting earlier discovery/implementation.
  `--until-commit` ends at committer time. Neither defines full-package usage. Windows include the start and exclude the end.
- Streaming reads use event timestamps, irrespective of mtime; tokens belong to the response/counter event, not generation times.
  Missing/inaccessible/malformed telemetry is unavailable, not proven zero. Unlogged models are `unknown`, never the recommendation.
  Logs still being written may omit final response/closeout. Claude chunks deduplicate within each session/log stream.
- Codex deltas follow each event's active model. **Token events are not responses**: legacy JSON `requests` has `request_unit`;
  `token_events` counts Codex events and `responses` is null. Reasoning is reported separately **within output**, never added again.

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
Compare cache-read, output, fresh input and cache-write categories separately, after checking measurement completeness and scope.
Token ratios are not financial-cost ratios; missing telemetry does not establish a low-usage result.

Questions for the review: did a model cause repair passes that a higher tier would have avoided; did a cheaper model cost more
overall through rediscovery; was the cost mostly reasoning or re-reading repository context.
