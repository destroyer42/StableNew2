# PR-IMG-PHOTO-220 — Photo Optimize settings and workspace

PR-IMG-PHOTO-222 supersedes the original selected-set Pipeline copy and submission-review UI:
see `PR-IMG-PHOTO-222_Scope_Aware_Editing.md` for explicit Single Photo / Batch Edit scope,
per-field copy masks, confirmed draft diffs and complete frozen-target review. Settings,
geometry, grouping, persistence and migration authorities below remain in effect.

Execution Profile + Model/Reasoning Recommendation: Standard/substantial, known
architecture with bounded persistence implications. Codex GPT-6.1 Sol High or Claude
Code Sonnet 5.5 High; retain the productive Local/Desktop session. These recommendations
target total successful-work cost: cross-file state/alias/migration interactions make
underpowered rediscovery and repair more expensive than a coherent High-effort pass.

Controller Surface Assessment: `AppController` retains live Pipeline capture, UI
projection, one admission call and completion association. Photo intent normalization,
geometry and per-stage partitioning move to `src/photo_optimize/`, using the existing
ReprocessJobBuilder. Controller physical lines fall from 7540 to 7427; the ceiling
is lowered to 7427. JobService, runner, cancellation and backend ownership are unchanged.

Token-Efficient Validation Plan: deterministic failing-before tests, focused photo,
controller, reprocess, workspace/routing and scanner tests using temporary images and
fake services; headless form/worker projection tests without a Tk root. Compare serialized
NJRs and metadata with the form/summary. Run the local PR gate once near closeout,
inspect the aggregate scoped diff and `git diff --check`. Hosted Python 3.14 CI remains
pending until publication is separately authorized. No physical generation.

## Settings and geometry contract

| Field/surface | Precedence and behavior |
|---|---|
| Imported dimensions | Decode the managed working image; Pipeline width/height do not become overrides. |
| Auto geometry | Decode current working image; recompute after promotion and when file size/mtime changes. Cache only verified decode results. |
| Custom geometry | Positive integral width/height; survive save/reload, Pipeline copy and promotion. Switching to Auto discards their effective resize. |
| Legacy geometry | Existing positive nested img2img dimensions conservatively mean Custom; absent geometry means Auto. No guess about whether old dimensions came from a previous Pipeline copy. |
| Stored stage settings | Normalize each authority independently, then merge stored values over live Pipeline fallback, then built-in defaults. Nested canonical values win over nested aliases and flat aliases. |
| Zero/False/empty values | Presence decides numeric/boolean precedence; zero denoise/CFG/confidence and False face restoration survive. Empty VAE explicitly means Automatic. Empty sampler resolves through the existing builder's sampler default; the frozen summary shows it. |
| Form edits | Edit the active photo only. Validate before saving; invalid/incomplete edits leave the sidecar unchanged and show an error. Reload/resource projection suspends persistence. Unrelated config/sidecar fields survive. |
| Model/VAE | Stored nonempty model wins; an explicitly cleared model uses live Pipeline identity rather than stale saved config aliases. Empty Pipeline img2img model inherits live txt2img identity. Stored VAE, including Automatic, wins. Exact-profile compatibility is assessed for the complete NJR request without adaptation or omitted stages. |
| Pipeline copy | Capture live Pipeline stage cards and stage toggles, independent of pack-override flag. Copy model/VAE and execution config, including stage-specific settings/overrides; preserve prompts, notes, tags, history and geometry policy. Missing source is actionable and writes nothing. |

The copy button targets the highlighted asset set. The active editor is labeled separately.
Import and submission preparation run off Tk; GUI intent is captured before worker submission
and worker results/summary are marshaled to Tk. The displayed submission summary projects
the frozen NJRs (photos/jobs/groups, target dimensions, model/VAE, stages, sampler/scheduler,
steps/CFG/denoise and upscale factor). The Operator Log retains all job targets when the
header truncates a large selection.

## Selection, batching and completion

Canonical stage order is img2img, adetailer, upscale. Each asset supplies its own enabled
stage list; the method's shared stage list is only the fallback for older callers lacking
per-photo stage defaults. Partition by stage plan, then use the existing builder's full
merged-config/prompt/model/output grouping. Dimensions, VAE and stage overrides participate
through config. Batch size is a 1–64 maximum photos per compatible job, not a repetition count.

Build every NJR first, then make one `submit_reprocess_njrs` call. Empty/no-stage selections,
missing/malformed inputs, invalid settings and unsupported exact profiles refuse the entire
request. Shared prompt deltas apply independently to each photo's baseline. Source ordering
within each job preserves output-to-asset mapping; metadata freezes the actual config and
stages. Completion records each asset's job/output association, including archived assets.
Repeated completion for the same run/job is idempotent. No queued NJR is rewritten.

Remove Selected and Clear List persist `archived` in sidecars. Show Archived exposes those
rows; Restore Selected unarchives them. Archive controls delete no source or history data.
Selection survives refresh and unrelated completion, including multiple highlighted photos;
an empty selection does not silently submit the displayed asset. Visibility and selected IDs
are included in UI-state persistence.

## Workspace and migration safety

`WorkspacePaths.photo_optimize_root(output_root=...)` normalizes routed output roots and
returns `<base>/PhotoOptimize/workspace`. The photo workspace captures the configured
output root when initialized; changing the output-root setting applies on the next workspace
initialization. Assets, sidecars, copied results/manifests and staging directories live there.
Run enumeration, rebalance/legacy-output moves and recursive artifact scanning skip the
managed workspace, including when it is passed directly as a root.

On normal store initialization, verify-copy recognized legacy `data/photo_optimize/assets`
into unique migration staging. Hash every copied file, check that the source sidecar did not
change, redirect only current managed paths, write migration evidence, then rename into an
absent destination. Repeated migration validates the retained copied files and skips an
already migrated asset. Windows extended I/O paths support long provenance filenames.
PR-IMG-PHOTO-221 supersedes the original fail-fast initialization behavior: collisions,
corrupt/unsupported sidecars, missing current files, links, changed copies and I/O errors
are reported per asset while a writable workspace remains available for new imports.
See `PR-IMG-PHOTO-221_Windows_Migration_Recovery.md`. Failed staging is retained. Unknown files outside
recognized assets are untouched. Originals, historical paths and baseline snapshots remain
at their legacy locations, so existing queued/replay inputs and evidence remain usable.

Migration is per asset: a later failure may leave earlier verified assets copied, while every
legacy asset remains intact. Sidecar updates use atomic replacement. List/copy operations
are not a new transactional database; an I/O failure during a multi-photo save can leave
earlier photos updated and is reported to the operator.

## Evidence and limits

At base `8ded6de055e8826c9c70bd648d7380acebd5607b`, seven initial regressions failed.
Executing the base form loader with zero values produced denoise 0.3 and CFG 7.0; the
repaired loader produces 0.0 and 0.0. Executing the base submission method on img2img and
upscale-only photo intent produced two img2img plans; the repair produces img2img and upscale.
The existing full-config grouping and whole-batch admission were already present, so they
were reused rather than replaced.

Validation covers decoded import/mixed/custom geometry, promotion/revert, zero settings,
alias precedence, reload without writes, invalid edits, Pipeline copy, mixed stage/config
plans, one-call admission, profile refusal, serialized NJR parity, output/history association,
archive/restore, selection retention, worker projection, routing/scanning, migration
idempotence/collision/failure and long Windows names. No actual GPU/backend generation or
interactive visual validation was performed; hosted CI is pending publication.

Local closeout: 114 focused tests pass. Repository completeness, controller ratchet,
repository-wide Ruff and the ten-target mypy smoke pass. The PR-gate wrapper was called
once and initially stopped at untracked new modules; exact-file staging repaired that
check and the remaining gate steps were resumed individually. Collection/smoke run in
an isolated checkout with the same staged Git tree to avoid hashing the live workspace's
65,318 output files (14.7 GB). The fake loopback-server smoke test requires execution
outside the socket sandbox; it does not use a real WebUI. Logs are retained under
`C:/Users/rob/qual/photo220-isolated-{collection,smoke}.log`.

A manual before/after test adapter accidentally retained the production store function and
attempted a legacy copy. It published no assets and submitted no jobs. The Windows path-length
failure was repaired using temporary fixtures. One partial staging copy remains at
`output/PhotoOptimize/workspace/migration_staging/photo_20261012_160257_1652b841_cb28a9072d674757a1a0f516aaa39f5f`.
Legacy inputs/sidecars were not written or deleted; the partial copy is preserved for inspection.
