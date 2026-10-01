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

Never push directly to `main`, merge a pull request, publish a release, deploy
externally, mutate secrets, or make a material architecture decision without
explicit owner approval. Ordinary scoped implementation, tests, refactors
needed for correctness, feature-branch commits, and PR preparation do not
require repeated approval when already authorized by the user's end state.

Keep completion reports concise: outcome, branch/SHA, evidence, architecture
effect, unresolved risk, and next decision if one remains, plus the `Model / usage`
section from `docs/AI_MODEL_SELECTION.md` (report unavailable metrics as
unavailable; never estimate them).
