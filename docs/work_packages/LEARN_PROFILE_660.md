# Evidence-qualified Learning profile publication

Outcome: saved ordinary txt2img controlled ratings produce independently qualified
findings for the frozen exact model. Review and explicit confirmation publish an
immutable revision through the existing profile store/catalog. No automatic apply,
favorite, job submission, runtime work or historical data migration.

Execution Profile: Standard, difficult cross-file evidence/persistence package;
Local/Desktop, one primary session.

Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh.
The cross-model evidence and immutable revision boundaries justify the higher effort
to reduce total retry/review cost. Stay in the current Codex session.
Expected usage: approximately 25M cache-read / 110k output tokens, not a budget.

Start: `612deb1e67f0acd3f152b9abf313fda169476aad`, local main and live remote main
verified equal. Original worktree: `C:/Users/rob/projects/StableNew-main`; its unrelated
untracked GUI assessment is preserved. Implementation worktree:
`C:/Users/rob/qual/StableNew-learn660`, branch
`learning/learn-profile-660-evidence-publication`.
Codex session: `01a17495-32aa-7751-a315-a0d5eeeebbf6`.
Task-start event: `2026-10-25T15:41:38.170-04:00`, recovered from this exact session's
`task_started` event before discovery. The first shell-recorded timestamp was
`2026-10-25T15:41:50.7123858-04:00`. Actual host/model/effort: Codex Desktop,
GPT-6.1 Sol High (session telemetry); the package recommendation remains XHigh.

Authority: AGENTS, STATUS, CODEX_MAP/CODE_MAP, architecture, Learning docs/spec,
MODEL_PROFILES section 17, IMAGE_PIPELINE, GUI style, testing/CI, agent operating
model, model selection and work-package template. Existing owners stay authoritative:
rating JSONL -> publication evaluator -> GenerationProfile -> profile store -> catalog.

Controller Surface Assessment: GUI LearningController begins at 4,068 lines and
GenerationProfileController at 409. Keep evidence/persistence logic in the Learning
domain and a small publication adapter; no controller ceiling increases. Record final
counts at closeout. No queue/runner/NJR ownership or profile schema change.

Final controller surface: existing controllers remain 4,068 and 409 lines; the new
publication adapter is 189 lines. The registry reader verifies cached fingerprints
without hashing. Ordinary snapshot identity is additive; historical evidence stays
unchanged and insufficient historical rows remain ineligible.

Token-Efficient Validation Plan:

1. Focused positive/negative evidence, identity, policy, latest-rating and proposal tests.
2. Temporary-storage publication/revision, duplicate/concurrent/failure and golden catalog tests.
3. Headless confirmation, stale/background result and no-side-effect adapter tests,
   plus relevant existing Learning/profile regressions.
4. One canonical Python 3.14 local gate after focused tests stabilize; no physical work.
5. Aggregate review and one batched in-scope repair/reverification cycle; final diff check,
   affected canonical docs/code-map freshness, exact branch/SHA and local commit.

Stop for a material authority, compatibility or schema decision, physical generation,
independent feature scope or exhausted review/repair budget. No remote publication or merge.

## Accepted local evidence

- Final affected suite: **1,037 passed**, including **68 new publication cases** covering
  per-field evidence, model/policy refusals, rerating/deduplication, immutable/concurrent
  storage, confirmation/cancellation, stale callbacks and catalog/working-state isolation.
- Golden publication/revision checks reload the existing schema through a fresh store,
  list Learning through the existing catalog and preserve ratings, favorites, startup
  defaults, Custom profiles and working settings.
- Python 3.14.8 canonical `tools/ci/run_pr_gate.py`: **PASS**, with 13,581 tests collected
  and 358 required smoke tests passed; repository contents unchanged. The final run used
  loopback permission for its isolated fake backend, with no real backend or GPU.
- Non-blocking smoke warning: `ControlledAsyncRunner` attempted `queued -> completed`
  for `test-dummy`; the queue and test-harness sources are unchanged by this package.
- Strict targeted mypy: no issues in the three new source modules. Lint, controller and
  architecture ratchets, generated code-map freshness and aggregate diff checks passed.
- Primary-session aggregate architecture/data-safety review complete; one local batched
  review/repair cycle, no remaining in-scope blockers. Hosted CI is not run: no push or PR
  is authorized. Actual session usage is reported at closeout, not estimated here.

No profile/rating schema migration, NJR/queue/runner ownership change, physical generation,
real backend startup, historical record mutation, automatic favorite/application/default
change or destructive user-data operation. Main remains at the starting SHA; the original
worktree's unrelated assessment is preserved. Only the short-lived feature branch is committed.
