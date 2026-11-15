# StableNew AI model selection

Last reviewed: 2026-11-15

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

This matrix is a prior, not a mandatory routing rule. Verify actual
model availability and supported effort levels in the chosen host.

| StableNew work profile | Codex default | Claude Code default |
|---|---|---|
| Git/status/docs cleanup/mechanical validation | GPT-6 Luna Low/Medium | Haiku 5.5 Medium/High, or Sonnet 5.5 Low |
| Narrow known-root-cause bug | GPT-6.1 Sol Medium | Sonnet 5.5 Medium/High |
| Normal substantial known-architecture PR | GPT-6.1 Sol High | Sonnet 5.5 High |
| Difficult bounded lifecycle/persistence/concurrency/cross-file PR | GPT-6.1 Sol High/XHigh | Sonnet 5.5 XHigh or Opus 5.5 High, based on risk |
| Material architecture/ownership ambiguity | GPT-6 Astra High/XHigh | Opus 5.5 High; optional Fable 5.2 High assessment when justified and available |
| Very large well-specified repo-wide autonomous work | GPT-6 Astra XHigh; Max only after evidence of need | Opus 5.5 High/XHigh; Fable 5.2 is an optional exception, not the default |
| Routine independent verification | GPT-6.1 Sol Medium | Sonnet 5.5 Medium |
| High-risk verification/security review | GPT-6 Astra High | Opus 5.5 High |

## Orchestration and frontier escalation

Use one primary session per coherent package. When orchestration materially helps, prefer Opus 5.5 and the [orchestrator prompt](ai/prompts/OPUS_ORCHESTRATOR.md).
For known architecture, prefer Sonnet 5.5 or the least costly tier likely to finish the whole package, counting retries, rediscovery, delegation and verification.
For exceptional design questions, the [shared review](ai/workflows/DESIGN_REVIEW.md) supports a bounded Fable 5.2 High assessment when available and authorized.
Temporary access can expire. Keep Opus as the ordinary frontier design option and honor owner decision boundaries. Paid credits require explicit authorization.
Cross-host work needs a supported mechanism or operator handoff with exact SHA, scope, accepted evidence, unresolved findings and authorization limits.
These are provisional recommendations. Provider benchmarks and limited trials can justify experiments. StableNew comparison uses PR outcomes below.
See [Anthropic’s supported models and effort levels](https://platform.claude.com/docs/en/build-with-claude/effort).

## Effort and delegation

Start at the lowest effort likely to complete the package. Use High for substantial work and consider XHigh for expensive lifecycle,
concurrency or persistence failures. Use Max only with evidence of need. Move up a model if capability is the constraint.
Delegate a separable hard part only when the benefit justifies fresh context. Prefer the productive session when switching offers little gain.

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
