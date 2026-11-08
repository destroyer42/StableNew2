# MEC-900 — Model Evidence Catalog: research report, correction plan and first slice

Status: first slice implemented on `fix/model-evidence-catalog-usability` (this PR). Later slices need owner
decisions (section 6). Date: 2026-11-08.

## 1. What the owner expected, and what happened

**Expected.** Open the catalog and see every model in the library with a durable profile: what it is (identity,
family/lineage), what outside sources say about it, what past runs showed, and which gaps remain. Then run a proposed
experiment that closes a gap ("this was really an SD 1.5 / Pony model", "it runs in Forge with these settings", "it
needs a different sampler/VAE"), inspect the output, and record what was learned, so later experiments start from
compatibility, feasibility and usability before moving on to optimization and preference.

**Observed** (owner screenshots and report, reproduced below against the code and the owner's real data):

1. The catalog reports **0 eligible experiments** for the whole library.
2. The **Evidence…** menu gives no idea of what each item does or the order to use them.
3. Every session the owner runs **Observe**, then **Verify identities (bounded)**, which re-scans everything, and the
   app still shows nothing useful. Knowledge from earlier scans seems to be lost.
4. Each row has to be clicked one at a time. Each then says **Unavailable**.
5. **What Should I Test Next?** says "verify this checkpoint's identity", which is the step just done, and never
   proposes, sets up or runs an experiment.
6. **What Should I Test Next?** from the Learning tab opens a **second catalog window** with a dialog on top. Closing
   the dialog hides the catalog behind the main window while it is still running. Repeating this stacks several catalog
   windows, each starting from scratch.

## 2. Root causes (evidence)

Investigated at `origin/main` `75842f7b` (no `src/` or `tests/` change since `d05d4a2d`). Real-data checks were
read-only, run on the owner's registry cache (`state/asset_registry_v1.json`) and copies of `state/jobs.sqlite3`.

| # | Symptom | Root cause | Evidence |
|---|---|---|---|
| R1 | "Unavailable" on almost every row; Verify seems to forget | **Hash-cache path-key mismatch.** `C:\Users\rob\stable-diffusion-webui\models\Stable-diffusion` now resolves to `D:\StableNew-Assets\a1111-models\Stable-diffusion` (the library was moved behind a link). The registry keys entries by the *resolved* path. The 66 entries hashed before the move are keyed by the old `C:` path, so every lookup misses and the file counts as unverified. | 86 checkpoint entries: 66 `C:` keys, 20 `D:` keys; 50 of 70 files on disk had no `D:` entry. With the fix, **65 of 70 verify with no hashing** (the other 5 were never hashed). |
| R2 | Verify "re-scans everything", never finishes | `refresh_census` default budget is **120 s / 64 GiB per click**. The library is 521 GB. Each click hashed about two files, then stopped "Partial". The file being hashed at the 120 s mark was thrown away. | `src/assets/evidence_census.py` `CensusBudget`; the owner's screenshot shows `pending` rows after `jibMix…`. |
| R3 | Clicking rows breaks scans | `_selected_model_changed` **cancels whatever is running and discards its result**. So clicking a row during Verify killed the verify. Drafts being saved or batches being prepared were also cancelled by a click. | `model_evidence_window.py` (old lines 405–421). |
| R4 | Must click each row; columns say "Check selection / Not planned" | Rows were rendered with placeholder text. Identity, family, coverage and eligibility were computed **only for the selected row**. Cached rows also listed the same file twice (once through the link, once at its real path). | Old `_render_assets` and `_load_cached_assets`. |
| R5 | "0 eligible" | Planning needs a verified identity (P0 gap otherwise) and a policy-compatible baseline. With R1 nothing was verified. Unqualified families (sd1, flux, "unknown") are `metadata_only` by design. Sampler and scheduler rows stay blocked when the source pairs them as one recipe. | Read-only planner run: a verified SDXL model with a `forge_webui` baseline yields 2 ready experiments (CFG, steps). |
| R6 | Next step repeats "verify identity" | The `resolve_identity` action routed to `WORKFLOW_IDENTITY_VERIFICATION`, but the window had **no handler** for it. It only printed the guidance "Choose Evidence… > Verify identities (bounded)", which pointed back at the broken R1/R2 path. | `_route_next` had no branch for that workflow. |
| R7 | Multiple windows, hidden window | `open_model_evidence()` **always created a new window**. `_on_test_next` opened another one each time. Dialogs were not `transient`, so closing one handed focus to the main window. | `learning_tab_frame_v2.py` `_on_test_next`; `next_test_dialog.py`. |
| R8 | "Look at evidence from past runs" never happens | The catalog **never read the job repository**. The owner has **38,544 jobs** across 122 model names, including outcomes for every "Not Working" model. | Read-only count from `jobs.sqlite3`. |
| R9 | Outside information is thin | Only 17 curated catalog records, mostly family and variant scope. Civitai/HF lookup is manual, one model at a time, and needs a verified hash (blocked by R1). | `evidence_baseline.py`; the window's lookup menu. |

Example of what R8 hides: `Not Working/sd_xl_turbo_1.0_fp16` **completed 32 runs at 36 steps / CFG 8.1 with
DPM++ 2M Karras**. The catalog's own publisher recipe for SDXL Turbo is **4 steps / CFG 0**. That mismatch likely
explains the artifacts that put it in "Not Working". `flux-2-klein-4b-fp8` failed 807 of 1,116 attempts, almost all
because a LoRA unverified for Klein was attached. That is a configuration problem, not a broken model.

## 3. First slice (this PR): make what is already known visible and durable

No new generation authority, no network use, no change to qualification or recommendation rules.

1. **Durable identity across moved/linked folders** (`src/assets/registry.py`). A cache entry stored under the
   unresolved path is reused when it names the same file and still matches its size/mtime fingerprint (the same trust
   rule as before). The next refresh re-keys it under the resolved path and retires the alias.
2. **One-click whole-library verification.** **Scan & Verify Library** hashes everything in one cancellable pass.
   Each finished file is persisted as it completes. **Verify Selected** hashes just the selected checkpoint. Progress
   is shown in GB.
3. **Whole-library status on open.** Rows come from the persisted cache, one per real file, with the saved identity.
   A background, read-only pass assesses every row: identity, family, past runs, last run, experiments ready, and a
   plain-language **Next step**. A **summary line** gives totals. Columns sort by heading.
4. **Past runs** (`src/learning/model_run_history.py`, `JobRepository.read_run_evidence_page`). Per checkpoint:
   completed, failed and cancelled counts, last run, the sampler/scheduler/steps/CFG/size those runs used, and the top
   failure messages (paths stripped). Shown next to the catalog's claims as "catalog says X; your runs mostly used Y".
   This is observational only (Learning invariant 5). It never feeds recommendations, proposals or publication.
5. **A readable details pane** for the selected model: next step, identity, family/policy, catalog-derived
   experiments with *why not* for each blocked one, past runs, catalog claims, and a "Not Working" folder hint. Raw
   JSON stays one button away.
6. **Clicks no longer cancel library work.** Scans, verification, saves, previews, queue preparation, lookups and
   import/export run to completion when a row is clicked. The click is planned once that work finishes. Only stale
   per-selection planning is superseded.
7. **One window.** `open_model_evidence` returns the open window, with its state, and brings it forward. Child dialogs
   are `transient` and return focus to the catalog. **What Should I Test Next?** follows the selection instead of
   going stale.
8. **The identity step does the step.** The *Verify this checkpoint* action now runs Verify Selected for that file.
9. **Clear actions.** The toolbar shows Scan & Verify Library, Verify Selected, Cancel, Refresh and Experiment
   Library, plus a three-step "how to use" line. Advanced items moved to **More…**, with descriptive labels (for
   example, "Look up selected model on Civitai (sends its SHA-256)…").

Measured on the owner's data (read-only smoke on copies): **65 checkpoints, 65 verified, 52 with experiments ready,
38,087 past jobs linked**, all shown on open without clicking a row.

## 4. Gaps the first slice does not close

- **Experiments only vary settings of already-qualified SDXL models.** Nothing yet answers "what is this model?" or
  "does it work here?". sd1, flux, Pony/Illustrious lineages and "unknown" families get no experiment (the planner
  marks them `metadata_only` or `blocked`).
- Nothing records an operator's verdict after looking at the output ("it's SD 1.5", "works, artifacts at CFG > 6").
- Outside sources are manual and one model at a time.
- History is shown, but not turned into claims the catalog can reason with.
- Files never hashed (the 5 above, including `.gguf`) appear only after a Scan & Verify.

## 5. Proposed plan for the follow-up slices

| Slice | Outcome | Main changes | Needs owner decision |
|---|---|---|---|
| **MEC-901 Compatibility probe** | For any verified checkpoint, especially "unknown", unqualified-family or "Not Working" ones, propose a small **probe experiment**: 1 prompt × 2 seeds × 2–4 candidate *family recipes* (for example SD1.5 512² / Euler a 25 / CFG 7; SDXL 1024² / DPM++ 2M 30 / CFG 6; Turbo 512² / 4 steps / CFG 0; Pony with score tags). It is queued through the canonical Learning → JobService path after the normal confirmation. | New P0 proposal type in `evidence_proposals.py`/`evidence_autopilot.py`; a probe recipe table in the catalog (source-cited); a probe study type that is experiment-local like Two-Axis Grid. | **D1, D2** |
| **MEC-902 Probe verdict → profile** | After the probe, a short review form records *Runs here: yes/no/with artifacts*, *Looks like: SD1.5 / SDXL / Pony / Illustrious / Flux / other*, *Best recipe of those tried*, and notes. Saved as an `operator_observation` claim bound to the exact SHA-256, visible in the catalog. | New claim classification + review dialog; catalog revision write via the existing content-addressed store. | **D3** |
| **MEC-903 Civitai batch enrichment** | One confirmed batch lookup of verified hashes on Civitai: base model, version, trigger words, publisher-stated sampler/steps/CFG. Stored as **unreviewed candidates**; accepting them makes reviewed claims (existing rule). | Batch wrapper over `EvidenceRefresh`, rate limit, disclosure listing every hash sent. | **D4** |
| **MEC-904 "Not Working" triage** | For each model in "Not Working": a likely cause from header structure (9-channel inpaint UNet, turbo/lightning variant, multi-component Flux/Klein, missing text encoder), history failure messages and catalog-vs-runs mismatch. Then a proposed probe with the right recipe, or a note on what to install. | Pure diagnosis module reusing `checkpoint_structure` and run history. | — |
| **MEC-905 History-derived hints** | Turn run history into advisory "observed working envelope" claims (for example "completed 489× at DPM++ 2M Karras, 30–36 steps, CFG 6–7.5"). Probes and proposals can use these as their control values instead of an arbitrary baseline. | Observational claim class excluded from recommendations, as invariant 5 requires. | **D5** |

Suggested order: **MEC-901 → 902** (they deliver the "run it, look, learn what it is" loop), then 904, 903 and 905.

## 6. Decisions for the owner

- **D1 — Probe generation for unqualified families.** May the catalog propose and (after your normal confirmation)
  queue small probe batches for families StableNew has not qualified (sd1, flux variants, "unknown")? They would be
  labeled *exploratory* and never publish a profile. Recommended: yes, limited to txt2img with no LoRA/ADetailer/upscale.
- **D2 — Probe size.** Recommended default: 1 prompt × 2 seeds × up to 4 recipes = 8 images per model. A "probe all
  unknown models" batch action would need its own confirmation showing the total image count.
- **D3 — Effect of an operator verdict.** Should "Looks like: SD 1.5 (operator-confirmed)" change how StableNew
  treats the model (its ModelPolicy family), or stay advisory in the catalog? Changing policy is an architecture
  decision: today only the registry/ModelPolicy decides family (Learning invariant 4). Recommended: advisory first,
  with policy integration as a separate decision once probes prove reliable.
- **D4 — Sending hashes to Civitai.** A batch lookup reveals which models you own to Civitai. Allow a one-time
  confirmed batch? Use an API key? Recommended: yes to batch with a full disclosure list; no key unless rate-limited.
- **D5 — History as control values.** May probes and proposals use your most-used settings from history as their
  control/baseline (instead of the current Learning baseline)? Recommended: yes, shown explicitly, never applied
  silently.
- **D6 — Moving files out of "Not Working".** Recommended: never automatic. The catalog only suggests.

## 7. Acceptance for this slice

- Opening the catalog shows every cached checkpoint once, with its saved identity, without hashing or a click.
- A file hashed before its folder moved behind a link verifies without re-reading its bytes, and is re-keyed.
- Scan & Verify Library hashes the remaining files in one cancellable pass that persists each finished file.
- Clicking rows while a scan, verification or save runs does not cancel it.
- A second open request reuses the same window. Child dialogs stay with it.
- The identity next-step verifies the selected checkpoint.
- Rows show past-run counts and the details pane shows run history next to catalog claims. History never feeds a
  recommendation, proposal or publication.

Tests: `tests/assets/test_registry_linked_library_900.py`, `tests/learning_v2/test_model_run_history_900.py`,
`tests/gui_v2/test_model_evidence_catalog_900.py`, plus the existing 760/800/810/830 suites (updated where the
intended UI changed).
