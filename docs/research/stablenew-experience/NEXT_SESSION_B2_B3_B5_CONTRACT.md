# Next execution session: B2 + B3 + B5 acceptance contract

**Status: contract for a future session. Nothing in it has been run.** Approved by the owner on 2026-11-05 (DR-A33) as **one bounded desktop-measurement session**, conditional on the preconditions in section 2. **B4 is not part of this session and is not approved** (section 6). No push, PR, merge, production change, GPU/Forge/SVD activity or prototype is authorized.

## 1. Fixed inputs

| Item | Value |
|---|---|
| Research branch | `research/gui-ux-850-experience-redesign` in the worktree `C:\Users\rob\projects\StableNew.worktrees\research-gui-ux-850` |
| Research SHA | the SHA stated in the owner's kickoff message (also the final commit of the previous session's closeout). The session runs `git rev-parse HEAD` first and **stops if it differs** |
| Code under test | `origin/main` `ed1e989f2149b01d16aef26d5f880326aeb250e0`. The research branch is `ed1e989f` plus documentation only, so `git diff --stat ed1e989f HEAD -- . ':!docs/research'` must be empty (assert it) |
| Harness | `python -m tools.operator_journey` (section 11a/11b of `docs/Subsystems/Testing/TESTING_AND_CI.md`), windows driver, `simulated` mode, loopback fakes only |
| Evidence root | `~\StableNewAcceptance\` (outside the repository; sealed archives; never inside a checkout) |
| Interpreter | the repository's Python 3.14 environment (not the Qt environment) |
| Existing artifacts to reuse, not redo | everything under `docs/research/stablenew-experience/`; B1 results (EV-14); the Qt audit; the independent review; documentation validation |

## 2. Preconditions (all must hold; the session stops at the first one that does not)

1. **The PR gate and every competing pytest/journey/census process have finished.** Check processes (`run_pr_gate`, `census`, `pytest`, `operator_journey`, and `StableNew` windows). *Necessary, not sufficient.*
2. **The owner has confirmed, in chat in this session, that the Windows desktop is free for exclusive automated control** (no work in the foreground, no other automation, mouse and keyboard left alone for the duration). The session asks and waits; it never infers availability from process state. Desktop availability expires when the run ends.
3. **Disposable data only.** The harness's per-run workspace redirects SQLite, Learning, UI state, presets/settings, PromptPacks, outputs and logs, and its guard snapshots the real data and the tracked Git tree before and after, failing the journey on change. No run may point at real operator history or configuration.
4. **No generation, backend start, runtime restart or physical GPU work.** `--mode simulated` only; no `--real-backend`, no `--webui-url`, no `--mode physical|readiness`; no Forge, Comfy, A1111 or SVD process may start.
5. **Branch/SHA verified** (section 1) and a clean tracked tree (`git status --short` empty).
6. Free disk on the evidence drive of at least 10 GiB (38 GiB free at the last check).

## 3. Stop conditions (stop immediately, preserve evidence, report)

- **Interference:** a foreground window change the harness did not cause, any human keyboard/mouse input detected, a new pytest/gate/journey/StableNew process appearing, the harness reporting an obscured control caused by another window, or a screenshot showing foreign desktop content.
- **Unexpected state mutation:** the workspace guard or Git-tree guard reports a change; a real-data snapshot differs; any file appearing under a protected directory (`state`, `data`, `presets`, `config`, `packs`) of a checkout.
- **Unanticipated safety concern:** any attempt to start or contact a real backend; GPU activity attributable to a StableNew child; a child process that survives shutdown; a crash dialog; the harness itself refusing a combination (exit code 4).
- **Resource:** free disk under 10 GiB; a single step exceeding its time-box.
- A stop is a result: record it, do not retry silently, do not "fix" the product or the harness.

## 4. Work items

### B2. Sealed baseline of the existing journeys on `main`

Run each layout for the golden-path journeys and the six advanced journeys, windows driver, simulated mode, sealed archive:

```
python -m tools.operator_journey --suite golden-paths --journey all      --mode simulated --desktop-driver windows --layout normal   --archive
python -m tools.operator_journey --suite golden-paths --journey advanced --mode simulated --desktop-driver windows --layout normal   --archive
(repeat with --layout minimum and --layout maximized)
```

Expected on `ed1e989f` (from the registry, to be **recorded as the baseline, not repaired**): GP832-F1 to F4 reproduce (OPS-01 generic failure message and running-versus-held banner, IMG-03 `parent_job_id` null, VID-03 blank form-level motion prompt refusal); VID-02 is HOLD at conversion (Blender absent); IMG-01, VID-01, LRN-01 and the rest pass. Any other deviation is recorded as a new observation.

Collect per journey and layout: verdict; reachability class; `action_count`; `extra_interaction_count`; `lost_clicks`; `click_retries`; `forced_scroll_or_resize`; tab-switch count (count `select_tab` rows in `actions.jsonl`); duration; display resolution and scaling (from `evidence.json`); archive name and the first 16 hex of the `MANIFEST.json` SHA-256. Verify each archive with `--verify-archive`. Compare the three golden journeys against the PR-831 archives with `--compare` where the comparator accepts them (it marks like-for-unlike inconclusive; keep that verdict).

### B3. Wheel-capture probe on `main`

Not a harness feature. Write it as a **scratch script outside the repository** that reuses the harness's Windows-driver primitives and disposable workspace. At the `minimum` layout, for each target (Review preview canvas, Motion Library tree on the Video tab, Job History tree on Pipeline, Learning Images list): place the pointer over the widget, send fixed wheel notches, and record the page scroll offset and the inner widget offset before and after, then at the inner widget's limit; classify **inner only / chains to page at limit / captured at limit**. Success needs data reachable through the existing fixtures. **If the probe needs a change to `src/`, `tests/` or `tools/`, or reachable data cannot be produced through existing seams, stop that item and record B3 as unavailable with the reason.**

### B5. Large-history load

Disposable temporary repository only (the workspace seam; never the real queue/history database). Populate `JobRepository` (`src/queue/job_repository.py`, a `JobHistoryStore`) with N synthetic rows through its public API for N = 500, 5,000 and 50,000, open the application on that workspace, open Job History, and record time to populated and process working set (three repeats per N). Synthetic rows contain no real prompts, paths or images. **If rows cannot be inserted through a public API without modifying `src/`, stop and record B5 unavailable.** Skip N = 50,000 if the 5,000-row load already exceeds 60 seconds (record the skip and the time).

## 5. Outputs (documentation only; local commit; no push)

1. `docs/research/stablenew-experience/BASELINE_B2_B3_B5_RESULTS.md`: per-item results as tables; **unavailable measurements named with the reason**; assumptions separated from measured values; archive names and manifest hash prefixes; any stop condition that fired.
2. Updates to `EVIDENCE_REGISTER.md` (new EV rows; close open gaps 4 and 6), `VALIDATION_AND_BASELINES.md` (baseline status), `RESEARCH_LOG.md`.
3. One local commit on the research branch, docs only. Report the exact branch/SHA and a `Model / usage` line measured with `tools/usage_report.py` over the whole session window; never estimate a missing value.
4. Run **only** the cheap docs checks for the new files (link check, `git diff --check`, docs-only classification). Do **not** re-run completed validation or reviews.

## 6. B4 (not approved): request template

B4 changes the Windows display scaling and needs **separate approval immediately before it runs**. The request must state, and the owner must approve in chat:

| Field | Content |
|---|---|
| Original setting | the current scale per monitor (for example read `AppliedDPI`/`LogPixels` and the Settings > System > Display value), resolution and refresh rate, recorded in the request before any change |
| Change | the exact scale to apply (125%, then 150%) and for how long |
| Restoration procedure | written steps: Settings > System > Display > Scale set back to the recorded value; sign out/in if Windows requires it; confirm no application was left in a stretched state |
| Verification after restoration | re-read the same values and compare to the recorded original; screenshot of the Display settings page; confirm window sizes and that StableNew starts normally |
| Risk statement | other open applications may re-layout; the owner should close or save work first |

No display setting is changed without that approval, and B4 results are never inferred from simulated Tk scaling.

## 7. Kickoff text for the owner to paste into the next session

> Execute `docs/research/stablenew-experience/NEXT_SESSION_B2_B3_B5_CONTRACT.md` exactly, on branch `research/gui-ux-850-experience-redesign` at SHA `<final SHA from the previous session's closeout>`. Do not repeat completed research, reviews or validation. Before starting, check the preconditions and **ask me to confirm the desktop is free**; wait for my reply. No push, PR, merge, GPU, backend start, runtime restart, B4 or production change.

## 8. Acceptance checklist

- [ ] SHA matched; `src/` identical to `ed1e989f`; tracked tree clean before and after
- [ ] Owner confirmation of an exclusive desktop recorded with the time
- [ ] B2 archives sealed and verified for three layouts (or stops recorded)
- [ ] B3 table, or B3 recorded unavailable with the reason
- [ ] B5 table for the N values attempted, or recorded unavailable
- [ ] Unavailable measurements named; assumptions separated from measurements
- [ ] No real data touched; no backend, runtime or GPU activity; no display setting changed
- [ ] Docs-only local commit; branch/SHA and `Model / usage` line reported
