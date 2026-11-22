# PR-DEVEX-CONTEXT-100 — Deterministic task router, dependency index, capsules and docstring completion

**State:** Owner-approved proposed implementation outcome; not implemented or authorized for publication by the docs-only roadmap PR.
**Roadmap:** [Agent context and AI-worker roadmap](DEVEX-CONTEXT_AI_WORKER_ROADMAP.md).
**Authority:** Current checkout, \`AGENTS.md\`, \`STATUS.md\`, \`docs/CODEX_MAP.md\` and relevant living architecture/testing docs precede this package.

## Objective and execution profile

Implement an offline, read-only tool for locating relevant current StableNew code, tests and canonical documentation from a scoped natural-language work-package objective, and emitting concise source-grounded context capsules. Complete all **eligible missing module-level docstrings** in \`src/\` and regenerate the existing code map.

- **Execution class:** Standard; escalate only on material new architecture/authority risk, not ordinary AST/indexing choices.
- **Host:** Prefer local/desktop checkout for exact source + dirty-worktree inspection; no application or GPU runtime needed.
- **Claude Code recommendation:** Sonnet 5.5 High.
- **Codex recommendation:** GPT-6.1 Sol High.
- **Expected full-package usage:** planning allowance ~10–30M cached reads and ~50–120k output tokens, including discovery, implementation, tests, repair and closeout. Validate tier and actual usage per current \`docs/AI_MODEL_SELECTION.md\`; these are not measured facts.
- **Specialists:** Optional read-only inventory reviewer if it materially reduces cost; one primary editor and one coherent worktree.

## Exact start state and existing capability

At task start, record ISO 8601 time/timezone and every participating host-qualified session ID **before discovery**. Verify local branch, HEAD, dirty/untracked user work, \`origin/main\` and remote target. Do not substitute this research snapshot for current checkout authority.

Read \`AGENTS.md\`, \`STATUS.md\`, \`docs/CODEX_MAP.md\`, \`docs/AGENT_OPERATING_MODEL.md\`, \`docs/AI_MODEL_SELECTION.md\`, \`docs/CODEX_WORK_PACKAGE_TEMPLATE.md\`, \`tools/generate_code_map.py\`, \`tests/tools/test_code_map.py\` and only relevant testing/subsystem docs.

Current known mechanism: \`docs/CODE_MAP.md\` is generated from first-sentence module docstrings; \`docs/CODEX_MAP.md\` is a short hand-maintained task index. The 2026-11-22 map said 787/942 modules documented; measure actual \`src/**/*.py\` inventory at this package's SHA. Do not add a second code-map authority.

## Workstream A — source and dependency index

Build an implementation-internal static index using \`ast\`, ordinary filesystem inspection and the current tracked checkout. Index:
- Repo-relative module path, package/module identity, source fingerprint and module summary.
- Defined classes/functions and high-value exported symbol names.
- Statically confirmed absolute/relative imports, reverse dependents, resolvable re-exports where practical.
- Candidate source-to-test links, with explicit relationship provenance (import/known path/lexical heuristic).
- Direct canonical task/subsystem references from existing docs.
- Unsupported/dynamic import indicators instead of false certainty.

Avoid import-time execution of application code, network, model installation, GUI, GPU, service startup or user output scanning. Ignore generated/virtualenv/model/user-output trees and enforce path containment. Large shared utility imports may not expand task results indiscriminately.

Use a deterministic schema/version and stable order. Derive identity from exact source contents (including uncommitted relevant files). A stale cached index must be rebuilt or rejected; no silent use against newer source. Prefer an ignored/generated artifact or ephemeral in-memory index over a noisy tracked artifact. The tool is read-only regarding application data and only writes its own safe index cache if explicitly requested.

## Workstream B — task-aware route selection

Accept task text (plus optional affected paths/symbols and result budget) and produce:
1. Ranked current source entrypoints with short factual rationale.
2. Related imports/dependents with evidence versus heuristics distinguished.
3. Relevant tests and living documentation.
4. Potential authority boundaries and unverified/dynamic relationships.
5. Escalation path when results are ambiguous or insufficient.

Use the task map, code map, AST signatures, lexical matching, deterministic graph-neighbor expansion and tests. No LLM, embedding service, network or historical GitHub API requirement. Do not boost a result merely for being highly connected. Any optional local PR co-change signal is a weak tie-breaker only; historical PRs are never current engineering authority.

Keep the default output narrow for narrow tasks while ensuring high-impact cross-cutting ownership is visible when triggered. Do not use summaries to assert unverified behavior. The user-requested task, current source and AGENTS boundaries always win over ranking.

## Workstream C — compact context capsules

Provide a documented simple CLI and machine-readable format (e.g. JSON plus Markdown human view) showing:
- Task and checkout identity; HEAD and dirty relevant file fingerprints; schema/version.
- Ranked reading order with exact repo-relative paths and a short selection reason.
- Confirmed dependencies and credible test candidates, with confidence labels.
- Relevant authority pointers (do not copy all of \`AGENTS.md\`).
- Unknown/dynamic edges and explicit requirement to inspect current source before editing.
- Source freshness failure rather than false current claims.

Default target approximately 1,200 tokens; implement a deterministic bounded output strategy rather than relying exclusively on an unmeasured token estimate. Offer a controlled expansion command or budget for genuine cross-boundary tasks, never an automatic full-repository dump. Escape untrusted task/file content and guard against prompt-injection text in documentation.

No capsule grants permission to edit, run hardware, change runtime ownership, publish or merge.

## Workstream D — fill module docstring gaps

Enumerate every eligible \`src/**/*.py\` lacking a module-level docstring and add a useful concise description grounded in the actual module's responsibilities. Include relevant package \`__init__.py\` files.

**Source-change constraint:** additions are module-docstring-only; preserve shebangs, license/encoding headers, \`from __future__\` rules, line-ending conventions and existing user changes. Do not change imports/functions/classes/control flow/API definitions or unrelated formatting. Use a test/inspection comparing before-vs-after source AST after removing newly introduced top-level docstring nodes. The resulting module \`__doc__\` value is acknowledged as metadata change; flag any module that inspects its own docstring or cannot be proven safe.

Never invent broad ownership claims from filenames. If one file requires behavioral changes or uncertain semantics, hold that exception for report rather than making speculative edits.

Regenerate \`docs/CODE_MAP.md\` with the existing generator; keep \`docs/CODEX_MAP.md\` within its cap and update it only if the new tool needs a compact task pointer. Review the mass docstring diff independently from the tool implementation.

## Tests, benchmark, and evidence

Focused deterministic tests must cover:
- Import graph (absolute, relative, alias, conditional, unresolved/dynamic, cycle, package initialization), exports and reverse links.
- Reproducible outputs, stale/dirty fingerprint handling, symlinks/path traversal exclusions, parse errors and missing source.
- Narrow/ambiguous/cross-subsystem task selection, high-fanout suppression, unknown results and relevant-test discovery.
- Capsule source paths, schema, default bounds, stable ranking, citations, escaping, unsupported claims, and read-only behavior.
- \`docs/CODE_MAP.md\` freshness and module-docstring inventory/equivalence, without importing application modules.

Evaluate a fixed, reviewed set of representative tasks (narrow repair, GUI/queue, NJR, image backend, video, Learning/Review, persistence, CI and negative cases) against the existing \`CODEX_MAP.md\` + \`CODE_MAP.md\` baseline. Source labels must be independently reviewed; PR changed files seed, but do not establish, labels. Prevent future knowledge leakage when replaying historical tasks.

Report top-k recall for primary source areas, irrelevant-result burden, output size, latency and missing relations. A >=90% recall target is a **proposed gate** requiring meaningful precision; if not met, disclose and assess the gap rather than widening results indiscriminately.

Only report agent token savings after comparable actual agent sessions with identical task/checkout/model/effort and full timestamp/session accounting. An index-size or capsule-size reduction is not itself a verified agent cost saving.

## Token-efficient validation

1. Check current repository and baseline once; reuse accepted unchanged SHA evidence.
2. Implement index -> route -> capsule vertical slice and run focused tests.
3. Complete isolated docstring pass, regenerate code map, run AST/no-behavior checks.
4. Run relevant static checks, mapping tests and representative retrieval benchmark.
5. Near completion run the prescribed \`python tools/ci/run_pr_gate.py\` and required hosted CI when feature-branch publication is authorized.
6. Inspect aggregate diff, \`git diff --check\`, unrelated paths and current remote ref.
7. Observe current bounded repair/reverification policy; do not repeat expensive green gates without a source/evidence reason.

No physical generation or qualification claim. A docs-only preplanning PR is not evidence that this implementation passed its future tests.

## Acceptance criteria

- 100% eligible current \`src/\` modules have accurate docstrings, or explicit unresolved exceptions are reported and accepted before claiming completion.
- No application behavior change beyond intentional docstring metadata; no unrelated user edits overwritten.
- Index and routing are deterministic, offline, source-aware, inspectable and scoped.
- Capsules provide useful paths/reasons/tests inside an enforced budget and refuse/flag stale evidence.
- No second architecture, lifecycle, queue or documentation authority introduced.
- Representative retrieval benchmark shows material improvement over baseline without hiding false negatives.
- Focused tests, required gate and applicable CI pass or are correctly qualified; diff is docs/source-tool/test only and within scope.
- Completion includes exact-SHA evidence, limitations, architecture impact and measured usage.

## Exclusions and stop conditions

**Excluded:** embedding models, Ollama/Proxmox integration, vector databases, autonomous code edits, GUI, production AI Assist changes, fine-tuning, model download, image/video generation, live GPU evidence, CI weakening, auth/bypass mechanisms and merging.

**Stop:** material architecture/authority change; unverifiable source edits; need for production network/service or new privileged resource; loss of freshness determinism; missing benchmark validity; repeated materially distinct failure classes beyond the operating model budget; protected publication/integration without explicit authorization.

## PR closeout contract

Provide parent/head SHA, all changed paths and categorized diffs, module-docstring before/after counts, source-index coverage, sample route/capsule, reproducible benchmark, focused and required tests, existing unresolved risks, no-qualification statement, and a \`Model / usage\` line using exact task-start/end timestamps and each participating session via \`tools/usage_report.py\`. Never use \`--since-commit\` to claim a full package total. Stop at accepted outcome or an owner decision boundary.
