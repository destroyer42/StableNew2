# N1c: report the remaining dispatch-only real blocks at Queue

## Objective

- Outcome: five real blocks that only fired at dispatch are now refused at `JobService.submit_njrs`. Before, a queued
  batch failed one job at a time after the operator had walked away. Each refusal says what to do. This follows the
  N1 rule in `AGENTS.md` section 2: "A block is reported as early as it can be known. Dispatch re-checks only what can
  change while a job waits."
- In scope: the five blocks that `N1_warn_dont_block.md` lists as "not moved to Queue":

  | Block | Queue check | Dispatch copy (kept) |
  | --- | --- | --- |
  | Klein / Z-Image / FLUX.1 profile on a host below 32 GB of total RAM (owner Q3: it stays a block) | `image_admission._require_backend_intent`, through the backend's own `read_host_memory` seam | `ForgeWebUIImageBackend._before_dispatch` |
  | Hypernetworks on Forge Neo | `image_admission._require_backend_intent` (`requested_hypernetworks_for_njr`) | `ForgeWebUIImageBackend.validate_njr_intent` |
  | Localized-only ADetailer on a WebUI backend without the companion extension (A1111) | `image_admission._require_no_localized_adetailer` | `WebUIFamilyImageBackend._require_adetailer_mode_supported` |
  | FFmpeg missing for Movie Clips assembly | `movie_assembly_engine.require_movie_assembly_admission` | `run_movie_assembly` (through the shared `require_ffmpeg`) |
  | RIFE smoothing requested on a workflow that declares no frame rate | `workflow_admission._require_interpolation_rate` | `ComfyWorkflowVideoBackend` (through the shared `interpolation_source_fps`) |

- Explicit exclusions:
  - Whether the RIFE executable is present stays a dispatch check, because it can change while a job waits. The
    builder already refuses a missing runtime at Preview.
  - No Preview-surface changes. The refusals reach the operator through the existing `submit_njrs` error path.
  - The four ratcheted controllers are unchanged, and so are the dispatch copies, apart from the two shared helpers.

## Execution class and model recommendation

- Execution class: Standard. This applies an existing `AGENTS.md` section 2 rule, with no architecture change.
- Execution location: Local.
- Model recommendation: Claude Code Opus 5.5 High; Codex GPT-6 Astra High.

## Exact start state and authorities

- Task start: 2026-11-26T05:59:43-05:00.
- Sessions:
  - this work: `claude:672b2eb4-4b76-4e0c-80fe-037535045964`;
  - started by `local_3c210c34-814e-484a-99f8-98a9bc18072b` (N1).
- Branch: `claude/n1c-early-real-blocks`, cut from `claude/ecstatic-turing-1267bc` at `4d4057c0` (N1, PR #436, not yet
  merged). It is to be rebased onto `main` after #436 merges.
- Canonical docs consulted: `AGENTS.md` sections 2, 4, 5 and 8; `docs/work_packages/N1_warn_dont_block.md`.

## Surface assessment

- Controller surface touched: No. `JobService` is unchanged; `require_execution_admission` gains one call.
- Architecture authority changed: No. There is no second queue, runner, compiler or history authority.
- Import-time behavior: none added. The host-RAM and FFmpeg probes run per submission and are read-only. The RAM probe
  is one `psutil` call; the FFmpeg probe is the same file lookup that dispatch does.

## Token-efficient validation plan

- Focused tests:
  - `tests/controller/test_n1c_queue_real_blocks.py`: each block is refused at `submit_njrs`, leaves the queue empty and
    is admitted once its cause is gone, and the FFmpeg and RIFE dispatch copies still refuse;
  - the updated Klein canonical-path test: refused at Queue, and the dispatch refusal is still exercised for work
    admitted earlier.
- A simulated CI host (16 GB of RAM, no FFmpeg at Queue) over every test that mentions the touched features, 197
  files. It checks that no test depended on this machine's RAM or FFmpeg.
  - Seven tests that submit exact-profile jobs depended on the host's RAM. They would now be refused on a 16 GB CI
    runner.
  - Fix: `tests/conftest.py` gains the autouse `_hermetic_forge_host_memory`, which substitutes a qualified host.
    Tests about the minimum still patch their own reading. This mirrors the existing
    `_hermetic_video_preflight_probes`.
  - The only remaining simulated failure is `@needs_ffmpeg`. It is skipped on a host without FFmpeg.
- `python tools/ci/run_pr_gate.py`.
