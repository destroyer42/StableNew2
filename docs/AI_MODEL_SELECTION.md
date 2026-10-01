# StableNew AI Model Selection

Last reviewed: 2026-10-01
Routine review due: 2026-10-31

This is the single canonical authority for choosing a coding model and effort for StableNew work.
Other authorities (`AGENTS.md`, `docs/AGENT_OPERATING_MODEL.md`, `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`,
the `.github/agents` files) point here instead of copying the table. Model names, prices and
benchmarks change quickly; the table below is a **dated baseline and a starting heuristic, not a
routing rule and not authority to act** (capability is separate from owner authorization).
Historical PR, diagnostic and qualification records keep the model recommendations that were
accurate when they were written.

External benchmarks are a prior, not StableNew truth. Weigh independent coding-agent evidence above
vendor promotional claims; use vendor sources for availability, pricing, context limits, effort
semantics and intended positioning. Over time StableNew's own successful-work evidence (see
"Empirical calibration") should outweigh generic rankings.

## Current models (reviewed 2026-10-01)

**Codex / OpenAI:** GPT-6 Luna, GPT-6.1 Sol, GPT-6 Astra; GPT-6 Sol and GPT-5.6
Luna/Terra/Sol remain available during rollout. GPT-6 has no Terra tier. GPT-6.1 Sol supports
Low, Medium (default), High, XHigh and Max, but not None or Minimal. GPT-6 Luna and the older GPT-6
Sol support None through Max; GPT-6 Astra supports Low through Max. Codex availability and the
visible effort controls depend on plan, client, workspace settings and rollout. The
[Codex model guide](https://learn.chatgpt.com/docs/models),
[GPT-6.1 Sol model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol), and
[model-selection guide](https://developers.openai.com/api/docs/guides/model-selection) are the
current official OpenAI sources for this review.

**Claude Code / Anthropic:** Claude Haiku 4.5, Sonnet 5, Opus 5, Fable 5.1, Sonnet 5.5, Opus 5.5.
"Extra High" and `xhigh` are the same effort level.

Historical independent Artificial Analysis Coding Agent Index figures (recorded from the owner's
2026-09-29 review; approximate, in each vendor's own harness; not re-measured by StableNew). No
verified comparable GPT-6.1 Sol benchmark was available for this update; its benchmark calibration
is pending. These rows are a dated baseline, not current comparative evidence for GPT-6.1 Sol:

| Codex model / effort | Index | Cost/task | Time/task | Tokens/task |
|---|---:|---:|---:|---:|
| GPT-6 Astra Max | 62 | $7.47 | 29.4m | 3.3M |
| GPT-6 Sol Max | 57 | $2.99 | 22.3m | 9.8M |
| GPT-5.6 Sol Max | 55 | $6.35 | 20.6m | 10.2M |
| GPT-5.6 Luna Max | 43 | $0.44 | 23.5m | 14.9M |
| GPT-6 Luna Max | 41 | $0.18 | 21.4m | 10.2M |

| Claude Code model / effort | Index | Cost/task | Time/task | Tokens/task |
|---|---:|---:|---:|---:|
| Sonnet 5.5 Max | 68 | $14.19 | ~1.5h | 27.7M |
| Opus 5.5 Max | 66 | $13.04 | ~1.1h | 15.6M |
| Sonnet 5.5 XHigh | 63 | $3.33 | 27.0m | 7.1M |
| Fable 5.1 Max (with fallback) | 62 | $12.39 | 34.8m | 5.7M |
| Opus 5 Max | 60 | $10.79 | 41.9m | 11.4M |
| Sonnet 5.5 High | 55 | $1.24 | 12.3m | 2.7M |
| Sonnet 5.5 Medium | 46 | $0.62 | 8.5m | 1.3M |
| Sonnet 5.5 Low | 42 | $0.48 | 6.3m | ~977K |

What this means for StableNew:

- **GPT-6.1 Sol** is the default substantial-coding Codex model when available. Official OpenAI
  guidance recommends it for complex coding and agentic work where total cost and time matter;
  compare it with Astra on StableNew tasks before making a measured success-rate or cost-per-task
  claim. **GPT-6 Sol** is the available fallback during rollout or where GPT-6.1 Sol is unavailable.
- **GPT-6 Astra** is not ruled out by its per-token price: on difficult coding work it uses far fewer
  tokens than Sol and succeeds more often, so it can lower total successful-work cost where rework
  is expensive.
- **GPT-6 Luna** suits genuinely narrow work. Do not push it to Max to solve a hard package: Max costs
  roughly Sol-like tokens for much lower success.
- **GPT-5.6 Terra** is the intermediate Codex option (GPT-6 has none) when Luna is insufficient but
  GPT-6 Sol is unnecessary.
- **Sonnet 5.5 High** is the normal substantial-PR default in Claude Code; **XHigh** for difficult
  bounded lifecycle, concurrency, persistence and cross-file work.
- **Do not use Max automatically.** Tokens and cost rise steeply from XHigh to Max, and Anthropic has
  documented a coding evaluation where Sonnet 5.5 Max did worse than XHigh (extra agent activity
  caused timeouts or out-of-scope edits).
- **Opus 5.5** is for genuine architecture ambiguity, open-ended judgment and high cost of error.
- **Fable 5.1** is a specialist for very large, long-running, well-specified autonomous work; it is
  token-efficient but pricier and unnecessary for normal PRs.
- **Haiku 4.5** is fine for mechanical/read-only/high-volume work; Sonnet 5.5 Low/Medium can be
  cheaper overall if slightly higher reliability avoids a retry.
- Prefer 5.5 over Sonnet 5 / Opus 5 unless availability, quota, compatibility or StableNew evidence
  says otherwise.

## Selection matrix (starting heuristic)

| StableNew work profile | Codex default | Claude Code default |
|---|---|---|
| Git/status/docs cleanup/mechanical validation | GPT-6 Luna Low/Medium | Haiku 4.5 High, or Sonnet 5.5 Low |
| Narrow known-root-cause bug | GPT-6.1 Sol Medium | Sonnet 5.5 Medium/High |
| Normal substantial known-architecture PR | GPT-6.1 Sol High | Sonnet 5.5 High |
| Difficult bounded lifecycle/persistence/concurrency/cross-file PR | GPT-6.1 Sol High or XHigh | Sonnet 5.5 XHigh |
| Material architecture/ownership ambiguity | GPT-6 Astra High/XHigh | Opus 5.5 High/XHigh |
| Very large well-specified repo-wide autonomous implementation/refactor | GPT-6 Astra XHigh/Max | Fable 5.1 XHigh/Max |
| Exceptional quality-first open-ended architecture + implementation | GPT-6 Astra Max | Opus 5.5 Max |
| Intermediate Codex fallback between Luna and Sol | GPT-5.6 Terra Medium/High | N/A |
| GPT-6.1 Sol unavailable for a substantial Codex package | GPT-6 Sol at the corresponding supported effort | N/A |
| Routine independent verification | GPT-6.1 Sol Medium | Sonnet 5.5 Medium |
| High-risk independent verification / security review | GPT-6 Astra High | Opus 5.5 High |

Also weigh: task size; architecture ambiguity; number of interacting subsystems; cost of a wrong
implementation; cost of another context/discovery pass; need for long autonomous execution;
deterministic/mechanical versus judgment-heavy work; expected token volume; current quota; whether
the current host already holds valuable package context; and observed StableNew results from prior
PRs.

Prefer staying in an already-productive Claude Code or Codex session over switching hosts for a small
theoretical advantage: context continuity has value. When a switch is justified, hand over the
branch/worktree, exact SHA, acceptance contract, accepted evidence, unresolved findings and
authorization boundaries, and do not restart discovery. Every new work-package prompt states the
Codex model + effort and the Claude Code model + effort, and a preferred host only when one
materially fits better.

## Effort selection

Effort matters independently of model tier.

- Start at the lowest effort likely to complete the **whole package** correctly, not just its first edit.
- **Medium** for bounded known work; **High** as the default for substantial StableNew implementation;
  **XHigh** when lifecycle/architecture interactions or failure cost justify deeper verification;
  **Max** only when the task is genuinely that hard or lower-effort evidence has failed.
- If a model is struggling, do not escalate its effort indefinitely. If capability is the constraint,
  move to the next appropriate model.

## Empirical calibration

Every PR/package completion report includes a compact **Model / usage** section:

| Field | Required value |
|---|---|
| Host | Claude Code / Codex |
| Actual model | Exact selected model |
| Effort | Low / Medium / High / XHigh / Max, as applicable |
| Package phase(s) handled | Discovery / implementation / repair / verification / docs / closeout |
| Input tokens | Host-reported delta for this package, if available |
| Cached-input tokens | Host-reported delta, if available |
| Output tokens | Host-reported delta, if available |
| Reasoning/thinking tokens | Host-reported delta, if separately available |
| Total tokens | Host-reported package delta, if available |
| Cost / credits | Host-reported value, if exposed |
| Agent elapsed time | If exposed or reliably measurable |
| Context compactions | Count, if observable |
| Repair passes | Count |
| Result | PASS / FAIL / BLOCKED |
| Efficiency observation | Underpowered, appropriate, or excessive |

Never estimate a missing value from context-window or quota percentage, wall time, API list prices or
benchmark averages; write `unavailable in current host`. When one session spans several
packages, record start/end values or another reliable delta rather than attributing the whole
session to the latest PR. Do not add a commit just to persist a PR's token totals: the completion
report is sufficient. Periodically fold comparable observations into this document.

Questions for periodic review: did a model cause unnecessary repair passes; did a cheaper model use
more total tokens through rediscovery or correction; did higher effort improve first-pass
acceptance; was the main cost model reasoning or repeated repo-context acquisition.

## Review cadence

Review at least every 30 days while development is active (next: 2026-10-31), and sooner when: a new
or materially improved model/family appears in Codex or Claude Code; pricing or quota behavior
changes materially; effort semantics change; a major independent coding-agent benchmark refresh moves
the cost/performance frontier; a recommended model is deprecated or unavailable; or several StableNew
completion reports show token use, repair rate or reliability contradicting the table. A review does
not need its own PR: fold it into the next coherent development/documentation package unless the
guidance is actively causing harmful routing.
