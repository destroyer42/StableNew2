# StableNew Claude instructions

`AGENTS.md` is the repository operating authority. Follow it.

For each bounded task, use current repository evidence rather than old chat
history. Start with `STATUS.md`, the relevant row in `docs/CODEX_MAP.md`, and
only the architecture/testing/subsystem sections needed for the task.

Preserve the canonical execution path:

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

Do not create a second queue, runner, history authority, compiler authority, or
direct GUI-to-backend execution path.

Prefer action over a long advisory response when the user clearly asks for a
change. Use subagents when work is independently researchable, benefits from
isolated context, or can run in parallel. Do not spawn subagents for trivial
searches, single-file edits, or tightly sequential work.

Use the repository skills when their narrow workflow matches the task. Reuse
already-green exact-SHA evidence while relevant source is unchanged.

Protected actions (push to `main`, merge, publish, deploy, secrets, material architecture decisions) need explicit owner
approval as defined in `AGENTS.md` section 5; ordinary scoped implementation, tests, refactors needed for correctness,
feature-branch commits and PR preparation do not need repeated approval when the user's end state already authorizes them.

The owner's local settings pre-allow `git push`, `gh pr create` and `gh pr merge` so they run without a prompt. That is
capability only: act on it when the owner has explicitly told you in chat to push, publish or merge the named branch or
PR, and then do not ask again. Never force-push, push to `main`, or use `--admin`, `--auto` or `[skip ci]`; a docs-only PR
still runs the cheap required checks, which must pass before merge (`AGENTS.md` section 5).

Completion reports follow `AGENTS.md` section 8.
