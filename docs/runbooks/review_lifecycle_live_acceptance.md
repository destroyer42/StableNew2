# Review lifecycle: live-app acceptance runbook (PR-REVIEW-ACCEPT-624)

Purpose: show the loop **Review -> Retain / Discard / Re-work -> Re-work -> Review again** working in the real
application on real outputs, or record each failure with enough evidence to fix it in package 625.

Written from the code at `origin/main` `6c015442` (contains PRs #327, #329, #335, #338), not from memory. Control
labels are the strings in `src/gui/views/review_tab_frame_v2.py` and `src/gui/view_contracts/review_workspace_contract.py`;
record fields are those of `src/review/review_evidence.py`, `src/review/archive.py`, `src/review/review_lineage.py`
and `src/learning/recommendation_engine.py`. Where the code does not establish an expected result, the step says
**not established** and asks you to record what you see. Design background: `docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md`
sections 3.5-3.7.1 and 5.3; `docs/Subsystems/Learning/LEARNING.md` section 3.6.

This is a docs-only deliverable. Part A (this file) was written by an agent. **Part B is yours**: you run the app, you
authorize and perform the Forge generation, and you fill in section 12. Nothing here asks the agent to launch the app.

Automated cross-references (deterministic, fake runner, synthetic images; they are what this runbook goes beyond):
`tests/review/test_review_evidence_620.py`, `tests/gui_v2/test_review_lifecycle_621_gui.py`,
`tests/gui_v2/test_review_archive_623_gui.py`, `tests/review/test_review_disposition_evidence_622.py`, plus
`tests/review/test_review_lineage_621.py`, `test_review_workspace_621.py`, `test_review_archive_623.py`,
`test_review_archive_readers_623.py`, `test_review_archive_session_623.py`.

Out of scope: source changes, image-quality judgments, video, Smart Review and Inspect & Improve, emptying the archive.

---

## 0. How to fill this in

Every step has: **Precondition**, **Do**, **Expected**, **Check** (a read-only command or visible fact) and a result line:

`Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______`

Mark `note` for anything surprising that is not a failure. A step marked **not established** cannot fail on its own;
record what you saw. Any step that would need a source change to be testable is listed in section 11 (known gaps).

## 1. Safety rules (read first)

1. **Never run against the live output folder.** All Review, Discard, Restore and Re-work steps use a **copy** (section 3).
   Exception, single and explicit: step J10b opens one live file view-only; skip it if you do not accept that.
2. **What cannot be isolated by the copy** (decide before starting; these are real writes to live state):
   - Learning evidence rows are appended to the live `data\learning\learning_records.jsonl` (by `LearningRecordWriter`).
     The app never deletes a decision row (Undo appends a clearing row). Back the file up first (section 3.4). Retain and
     Discard rows are observational evidence and will enter Learning recommendations for those images' settings.
     Restoring the backup afterwards is your decision, not a step here.
   - New jobs are added to the live `state\jobs.sqlite3`, so History shows them.
3. **Do not touch the main checkout's files except as stated.** Reading is fine; the only edit is the single setting in
   section 3.2, made through the app's own dialog, and put back in section 13.
4. **Read-only checks only.** Every command below reads. `Get-FileHash`, `Get-ChildItem`, `Get-Content` and a Python
   one-liner opening SQLite with `mode=ro` write nothing. Do not run anything else against the live folders.
5. **Forge steps** (the only ones needing a running backend and a generation) are marked **[FORGE]**. All other steps
   work with Forge stopped. Use one stated model, low steps (about 8-12), small size (for example 512x512), batch 1,
   record them in section 12.

Paths used below (adjust to your machine):

```powershell
$Main  = 'C:\Users\rob\projects\StableNew-main'
$Py    = "$Main\.venv\Scripts\python.exe"
$Live  = "$Main\output"                       # your real output root (check Engine Settings first)
$Copy  = 'D:\accept624\output'                # the copy; MUST be on the same drive as itself (see 3.3)
$Records = "$Main\data\learning\learning_records.jsonl"
$Jobs  = "$Main\state\jobs.sqlite3"
```

## 2. Prerequisites

- The app runs from `$Main` (the live app). Start it yourself; this runbook never does.
- Forge only for **[FORGE]** steps: S1 and J4, J5 (submit), J6, J7. Everything else, including J1, J3, J8, J9 (record
  parts), J10, archive and refusals, runs without it.
- Confirm your live output root first: Engine Settings (`Default output folder:`), or read the setting:

```powershell
(Get-Content "$Main\presets\settings.json" -Raw | ConvertFrom-Json).output_dir   # empty = built-in default "output"
```

Record this value in section 12 (`Original output_dir`).

## 3. Set up the copy and point the app at it

### 3.1 Copy a small slice of real outputs

Pick 8-12 real images from `$Live`: at least **two PNGs and one JPEG**, one image that came from an ADetailer run (if you
have one), and at least one that was produced by StableNew (has an embedded payload). Copy only those files, keeping their
relative folder structure, with a copy command (copying reads the live folder and writes only to `$Copy`):

```powershell
New-Item -ItemType Directory -Force $Copy | Out-Null
# Example: one file; repeat for each chosen file, preserving the relative path
$rel = 'run_20260101_120000\img_0001.png'
New-Item -ItemType Directory -Force (Split-Path "$Copy\$rel") | Out-Null
Copy-Item "$Live\$rel" "$Copy\$rel"
```

Keep `$Copy` on one drive. The archive moves with a same-volume rename (`archive.py`); a file on another drive is refused
(that refusal is tested deliberately in section 9).

### 3.2 Point the app at the copy (and remember how to put it back)

The archive location is `<output root>/_archive/...`, where the output root is the `output_dir` setting from
`presets/settings.json` (`configured_output_root`, `archive.py`). A file outside that root goes to `_archive/_external/...`
instead. So the copy must **be** the output root for the walk-through to exercise the normal archive path.

1. In the app open **Engine Settings**, set **Default output folder:** to `D:\accept624\output`, then **Save & Close**.
2. Verify (read-only):

```powershell
(Get-Content "$Main\presets\settings.json" -Raw | ConvertFrom-Json).output_dir     # expect D:\accept624\output
```

3. Note from the Engine Settings text: changing it does not move or alter queued or finished jobs; new jobs save into the
   new folder unless a PromptPack's saved settings name their own. Put the original value back in section 13.

Not established by the code: whether the app needs a restart for `output_dir` to be read by the archive and Re-work
paths. `configured_output_root` reads the file at the time of use, but the Pipeline may cache it. After Save & Close,
verify with the first Discard in J11-A (the file must land in `D:\accept624\output\_archive\...`); if not, restart the app
and note it.

### 3.3 Hashes of the copy (baseline for J1)

```powershell
Get-ChildItem $Copy -Recurse -File | Get-FileHash -Algorithm SHA256 |
  Select-Object Hash, Path | Export-Csv "$env:TEMP\accept624_baseline.csv" -NoTypeInformation
```

(The CSV is written to your temp folder, not to any repository or output folder.)

### 3.4 Back up the Learning record file and note its size

```powershell
Copy-Item $Records "$env:TEMP\learning_records.before624.jsonl"
(Get-Content $Records | Measure-Object -Line).Lines      # row count before; record it in section 12
```

### 3.5 Read-only helper for counting the new rows (reuse in later steps)

A Python one-liner using the main checkout's venv; it only reads. It prints the last N review rows' key fields:

```powershell
& $Py -I -c "import json,sys;p=sys.argv[1];n=int(sys.argv[2]);rows=[json.loads(l) for l in open(p,encoding='utf-8') if l.strip()];
for r in rows[-n:]:
  m=r.get('metadata') or {}
  print(m.get('source'),m.get('record_kind'),m.get('review_disposition'),m.get('user_rating'),m.get('user_rating_source'),(m.get('artifact_sha256') or '')[:19],m.get('image_path'))" $Records 10
```

Fields it prints are those written by `build_review_rating_record` and `build_disposition_record`:
`source` (`review_tab` for ratings, `review_tab_disposition` for decisions), `record_kind` (`review_tab_feedback`,
`review_disposition`), `review_disposition` (`retain` | `discard` | `rework` | `cleared`), `user_rating`,
`user_rating_source` (`review_disposition_soft_score` for Retain/Discard), `artifact_sha256`, `image_path`.

---

## 4. S1 [FORGE]: one seed run into the copy (needed for History journeys)

Why: History records name the **original** file path of each job. An existing job from your live folder would point at a
live file, and Discard would move it. J2, J9 and the archive-reader checks need a History job whose images are in `$Copy`.
This is one small Pipeline job, separate from the single re-work batch of J4. It is the only generation besides the
re-work children. (If you accept not running History-based checks, skip S1 and mark J2, J9 and the "History reports
archived" checks `not run`.)

- Precondition: Forge running; Default output folder is `D:\accept624\output` (3.2).
- Do: in **Pipeline**, queue one txt2img job: model per section 12, steps 8-12, 512x512, batch 3, no refiner or
  upscaler; if you want J9 coverage, enable ADetailer (face) for this job. **Add to Queue**, let it finish.
- Expected: 3 new images under `$Copy` (a new run folder); the job is Completed in Queue/History.
- Check:

```powershell
Get-ChildItem $Copy -Recurse -File -Include *.png | Sort-Object LastWriteTime -Descending | Select-Object -First 6 FullName, Length
```

Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

---

## 5. Opening the set (used by every journey)

In **Review**: **Open...** menu -> **Folder...** -> choose a folder under `$Copy` (or **Files...**). Never choose a folder
under `$Live`. The header shows the state filter `Show` (values **Active** (default), **To review**, **Retained**,
**Re-work**, **Archived**, **All**) with counts, the selection label, **Clear** and **Help**. Each list row shows the
image's state: **To review**, **Retained**, **Archived**, **Re-work marked**, **Re-work queued**, **Re-work failed**,
**Returned**, **Changed since reviewed**.

---

## 6. J1: ratings never rewrite the file (620)

Cross-ref: `test_review_evidence_620.py`. Uses real PNG and real JPEG; no Forge.

**J1.1** Precondition: baseline CSV (3.3) exists; a PNG and a JPEG from section 3.1 are in the set.
Do: select the PNG. Set **Rating** and **Quality**/**Subscores** as you like (note: the fields exist; values are your
choice, no quality judgment is being tested). Press **Save rating**. Repeat for the JPEG.
Expected: the status line confirms the save; the image row shows a rating; the file is not rewritten.
Check:

```powershell
Get-FileHash -Algorithm SHA256 "$Copy\<png>","$Copy\<jpeg>"   # compare with the baseline CSV: identical
Get-ChildItem $Copy -Recurse -File | Where-Object Name -like '*.review.json'   # none expected
```

Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J1.2** Do: run the helper (3.5) with `10`.
Expected: one new row per save with `source=review_tab`, `record_kind=review_tab_feedback`, `artifact_sha256` equal to
the file's SHA-256 with a `sha256:` prefix (compare to Get-FileHash, case-insensitive), `image_path` = the copy path.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J1.3** Do: select another image, then reselect the PNG.
Expected: the saved rating reappears in the controls; an unrated image shows reset values (3 / 3 / 3, "okay", no notes)
(`PHOTO_REVIEW_REPROCESS.md` 5.3).
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J1.4** (optional, tests the only writer) Do: **Write rating to file...** on the JPEG only.
Expected: a `<image>.review.json` sidecar appears next to the JPEG; the JPEG's bytes are unchanged (never re-encoded).
The code says Review asks first for PNG because embedding changes the PNG's bytes; do **not** do this on the PNG.
Check: `Get-FileHash` the JPEG again; list `*.review.json`.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

## 7. J3: keyboard triage of a real run (621; no Forge)

Precondition: open a folder under `$Copy` with at least 5 images; filter is **Active**; focus is in the image list.

**J3.1** Do: press `R` on image 1, `D` on image 2, `W` on image 3, `R` on image 4, `U` on image 4 (lowercase or uppercase).
Expected: `R` Retain, `D` Discard, `W` Re-work, `U` Undo (code binds `r d w u`, both cases); after each decision
the next undecided image is shown (docstring in `review_tab_frame_v2.py`: "the next undecided image is shown"); the buttons
**Retain (R)**, **Discard (D)**, **Re-work (W)**, **Undo (U)** do the same. After `D` the image leaves the **Active** view and
appears under **Archived**; `W` shows **Re-work marked** and reveals the **Re-work** panel; `U` on image 4 returns it to **To review**.
Check: run the helper with `10`: rows with `review_disposition` `retain`, `discard`, `rework`, then `retain`, then `cleared`
(for Undo of the first decision on that digest, the earlier decision or a clearing row is appended; exact row for Undo
is: not established beyond "appends the earlier decision, or a clearing row"; record what you saw).
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J3.2** Do: use the counts next to the **Show** box and change the filter through each value.
Expected: counts match the states; each filter lists the right images.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

## 8. Learning evidence (622) with J3

**L1** Precondition: J3.1 done; note the Learning Analytics totals **before** J3 if you can (do this step set once, with
this order: open **Learning** -> **View Analytics**, record `Total Experiments` and `Total Ratings`, close it; then run J3).
Do: after J3, open **Learning** -> **View Analytics** again.
Expected: `Total Ratings` unchanged by Retain/Discard/Re-work (dispositions are excluded from analytics:
`learning_analytics.py` skips `record_kind == "review_disposition"`); the explicit **Save rating** rows from J1 do count.
Check: the helper shows the Retain row with `user_rating=4.0`, `user_rating_source=review_disposition_soft_score`, and the
Discard row with `user_rating=2.0`; the Re-work and clearing rows have no `user_rating` (soft scores:
`DISPOSITION_SOFT_SCORES` retain 4.0, discard 2.0; Re-work is not scored).
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**L2** Do: in **Learning**, look at Recommendations for the models/settings of the images you retained and discarded.
Expected: **not established by a visible control**. The recommendation engine counts a disposition only as observational
evidence when it carries settings (`_disposition_is_evidence`) and applies the latest row per digest. Record what you see;
a pass here means only "no error, nothing contradicts the record rows". The deterministic proof is
`test_review_disposition_evidence_622.py`.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

---

## 9. Archive (623; no Forge)

Precondition: the copy is the output root (3.2), image `A` (use a PNG from S1 or section 3.1) is in the **Active** list.

**AR1** Do: select `A`; record `Get-FileHash` and its full path. Press **Discard (D)**.
Expected: `A` leaves **Active**; under **Archived** its row says `(in archive)`; the file is at
`D:\accept624\output\_archive\<path relative to the output root>`; the original path is gone; the hash is identical; a
`<image>.review.json` (if any) moved with it.
Check:

```powershell
Test-Path "$Copy\<rel>"; Test-Path "$Copy\_archive\<rel>"
Get-FileHash -Algorithm SHA256 "$Copy\_archive\<rel>"
```

Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**AR2** [uses S1] Do: with `A` archived, open **History** for the S1 job.
Expected: History's artifact projection says "archived by Review; Restore to use it" (the text is `ARCHIVED_MESSAGE`) and
uses nothing; **Compare with Parent** and Replay on a job whose input is `A` report the same. The archived copy is never
opened. (For History's exact visible placement of the message: not established by this runbook; record the wording.)
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**AR3** Do: **Show** -> **Archived**, select `A`, press **Restore**.
Expected: the file returns to its original path with the same hash; `A` is back in **Active** (as a decided image, by
the Restore rule "records a clearing row"); `_archive` folders stay (nothing deleted).
Check: `Test-Path` both paths; hash; helper shows a new clearing/decision row.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**AR4 Refusal: queued job input.** [FORGE-adjacent, no generation needed] Precondition: `B` is an image whose path is the
input of a job that is **queued or running**. Do: with Forge stopped, from Review mark `B` **Re-work (W)**, **Preview and queue...**,
confirm **Add N jobs to Queue** (jobs stay queued because Forge is not running, so nothing is generated), then select `B`
and press **Discard (D)**.
Expected: `B` is discarded (hidden, listed under **Archived**) but **stays where it is**; the status line says
"A queued or running job uses this file as an input; it was not moved."; the row shows `(not moved)`. Pressing Discard
again after the job leaves the queue retries.
Check: `Test-Path "$Copy\<rel B>"` is True and no `_archive` copy exists.
Cleanup: clear/cancel that queued job from the Queue panel (label not verified here; record what the control is called)
before any [FORGE] step so it does not run.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**AR5 Refusal: another drive.** Precondition: an image `C` on a **different drive** than `$Copy` (copy one file there; it is
outside the output root). Do: **Open...** -> **Files...** to open it, then **Discard (D)**.
Expected: discarded but not moved, status text "The archive is on a different drive than this file; it was not moved."
(`DIFFERENT_VOLUME`); `(not moved)` in the row.
Check: `Test-Path` of `C` is True; no copy exists under `_archive\_external`.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**AR6** (note-only) Behaviour on network drives and cloud-synced folders is documented as not demonstrated
(`PHOTO_REVIEW_REPROCESS.md` 3.7.1 Limits); do not test it here.

---

## 10. Re-work journeys

### J2 [FORGE]: History -> Edit in Review -> rate -> Preview -> Queue -> compare with verified parent (610A, 621, 610B)

Precondition: S1 complete (3 images in `$Copy`), job Completed.
**J2.1** Do: History -> select the S1 job -> **Edit Image in Review** (also reachable as "Edit in Review" in the Queue/Batches hand-off).
Expected: Review opens the recorded image with no stages selected; nothing is queued (loading never queues a job). If
Review already holds unsent work it asks Replace / Cancel; Cancel leaves it untouched.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J2.2** Do: **Save rating**; then **Re-work (W)**; in the **Re-work** panel choose a stage in **Stages and queue** (for
example `img2img`), edit the prompt in **Current Prompts + Edits** (the **Before / After Diff** shows it); press **Preview and queue...**.
Expected: a Preview dialog (`ReviewBatchDialog`) lists the job with its settings; **Cancel** leaves the queue unchanged.
Press **Add 1 jobs to Queue** (label is `Add {N} jobs to Queue`). Steps low, as stated in section 12.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J2.3** Let the child finish. In **Returned** select it.
Expected: the table row shows `Source`, `Returned result`, `State`, `Source link`; the link reads verified
("Verified: the job recorded the SHA-256 of this image as its source."). Press **Compare with source**.
Expected: the compare opens; History's **Compare with Parent** on the child also shows the parent as verified.
Check (read-only; fields are `parent_job_id` and `parent_artifact_id`, stored in the `jobs` table):

```powershell
& $Py -I -c "import sqlite3,sys;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);
for r in c.execute('select job_id,status,parent_job_id,parent_artifact_id from jobs where parent_job_id is not null order by created_at desc limit 5'):print(r)" $Jobs
```

Expected: the child row has `parent_job_id` = the S1 job id and `parent_artifact_id` = `sha256:<hash of the source image>`
(compare to `Get-FileHash` of the source, lowercase).
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

### J4 [FORGE]: batch re-work of 3 images (621)

Precondition: 3 image rows (from S1 or the copy). The **only** Forge batch besides S1: low steps, 512x512.
Do: mark all three **Re-work (W)**; choose one stage; **Preview and queue...**; **Add 3 jobs to Queue**.
Expected: one Preview, one submission; single-image tools (**Edit Mask…**, **Extend Canvas…**, **Smart Review…**,
**Inspect & Improve…**, Klein) are disabled with a reason while more than one image is marked; the three rows become
**Re-work queued**.
Check (read-only): the newest jobs share a batch id and each has `parent_job_id` and `parent_artifact_id`:

```powershell
& $Py -I -c "import sqlite3,sys,json;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);
for r in c.execute('select job_id,status,parent_job_id,parent_artifact_id,payload_summary from jobs where parent_job_id is not null order by created_at desc limit 3'):print(r[0],r[1],r[2],r[3],'batch_id' in r[4])" $Jobs
```

Expected: 3 rows, each `parent_job_id` and `parent_artifact_id` set. Whether the batch id is in `payload_summary`
or only in the frozen snapshot is **not established** by this runbook (the repository searches for the marker
`"batch_id"`); if the column does not show it, say where you found it (Pipeline > Batches lists the batch with its jobs).
"One `submit_njrs` call" is not directly observable in the UI: it is established by the test
`test_review_lifecycle_621_gui.py`; here, confirm the three jobs appear as one Review batch in Pipeline > Batches.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

### J5: individual re-work with a mask edit; Cancel (621)

Precondition: exactly one image marked **Re-work (W)**. No Forge needed until the job is added.
**J5.1** Do: **Edit Mask…**, paint a small region, **Preview frozen job**, then **Close** without pressing
**Add prepared job to Queue**.
Expected: no job was created; the image is still **Re-work marked**; the list shows it in the **Re-work** filter.
Check: the jobs-table count and newest row are unchanged (run the J2 query before and after).
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J5.2** Do: **Preview and queue...**, then **Cancel** in the dialog.
Expected: no job added; the item stays marked. Same check.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J5.3 [FORGE]** Do: repeat, this time **Add prepared job to Queue** (low steps).
Expected: one job; mask source image never overwritten (`Get-FileHash` of the source unchanged).
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

### J6 [FORGE]: the child returns beside its source; Re-work again (621)

Precondition: a finished child from J2 or J4.
**J6.1** Do: open **Returned**, select a child, press **Review result**.
Expected: the child opens in the set, labelled with its verified/unverified link; the source's state is **Returned**
(awaiting a decision); it left the re-work scope.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J6.2** Do: select the child row and press **Re-work again**; **Preview and queue...**; **Add 1 jobs to Queue**.
Expected: the new job names the **child** as its parent (`parent_job_id` = the child's job id,
`parent_artifact_id` = `sha256:` of the child file); the returned table shows the grandchild beside the child. Check with the J2 query.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

### J7 [FORGE]: failed or cancelled child; restart (621)

**J7.1** Precondition: one re-work child **queued**. Do: cancel it from the Queue panel before it runs (control label not
verified here; record it), or stop Forge so it fails.
Expected: the source row shows **Re-work failed**; **Returned** shows the failure reason ("a short, typed reason" for a
failed job; an exact string for a cancelled job: not established); **Open Batches (retry)** points at Pipeline > Batches. It is
never retried automatically.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J7.2** Do: close and restart the app, open the same folder under `$Copy`.
Expected: the same states appear (re-derived from the evidence file and the job repository; nothing else is persisted);
a marked-but-not-queued image is still **Re-work marked**.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

### J8: prompts shown, "not recorded", SFW (621; no Forge)

Do: select (a) an image with a StableNew payload, (b) an image without one (e.g. an old or foreign file from the copy),
(c) an ADetailer output; open **Prompts and provenance**.
Expected: original and final prompts per stage and the ADetailer prompts are shown; anything missing reads
**not recorded**; an image with no payload shows the prompt "as sent" (baseline source `fallback`). In SFW mode all prompt
text is redacted (switch SFW via the app's content-visibility control; its label is not verified here, record it); switch back
and the text is re-rendered.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

### J9: ADetailer pair; missing source (160, 621)

**J9.1** Precondition: an ADetailer output whose source is verified (the S1 job with ADetailer, if you enabled it) is selected.
Do: open the ADetailer before/after (the Compare button's ADetailer mode).
Expected: before/after opens; the **ADetailer outcome (optional)** controls (`Face`, `Hands` comboboxes and a note) are
enabled; they are saved with **Save rating** and do not change the overall rating.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J9.2** Precondition: temporarily rename the **source** image of that pair inside the copy
(`Rename-Item "$Copy\<src>" "<src>.hold"`; restore with the reverse afterwards).
Expected: the outcome controls are disabled with the message "The source image of this ADetailer output is not verified,
so it cannot be judged."; opening the pair reports "No verified ADetailer source image for the selected image."
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

### J10: changed file; legacy rating (620, 621)

**J10a** Precondition: image `X` in the copy is rated (J1). Do: replace `X`'s bytes externally:
`Copy-Item "$Copy\<other>.png" "$Copy\<X>.png" -Force` (copy-folder only). Wait about 5 seconds (the tab re-reads the repository
on a poll; the file-fact cache re-reads a replaced file) and reselect `X`.
Expected: the row shows **Changed since reviewed**, and the rating controls show unrated (identity_status `changed`: the old
rating is reported, not applied). Whether the row updates without reselecting: not established; record what you saw.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

**J10b** (single live-file exception; skip if you do not accept it; mark `not run`) A legacy rating row has a path and no
digest, so it matches only the **original path**; a copy cannot reproduce it. Find one:

```powershell
& $Py -I -c "import json,sys;seen=0
for l in open(sys.argv[1],encoding='utf-8'):
  if not l.strip(): continue
  m=(json.loads(l).get('metadata') or {})
  if m.get('record_kind')=='review_tab_feedback' and not m.get('artifact_sha256') and seen<5: print(m.get('image_path'));seen+=1" $Records
```

Do: record `Get-FileHash` of that live file, open it in Review (**Open...** -> **Files...**) and **only look**: do not press any
decision button, **Save rating**, **Write rating to file...** or `R D W U`. Then `Get-FileHash` it again.
Expected: its old rating appears (matched by path, `identity_status` `path`); the hash is identical before and after;
nothing was written. Use **Clear** afterwards.
Result: [ ] pass  [ ] fail  [ ] note  [ ] not run   Evidence: ______  Notes: ______

### J11: hand-offs behave as before (610, 580; no Forge)

For each: open the entry point, send images to Review, confirm Review opens with them, nothing is queued, and **Cancel** on a
Replace/Cancel prompt leaves the existing work untouched.
- **J11-A Batches** (Pipeline > Batches, **Open in Review**): outputs of a Review or Video batch open; archived ones are
  listed under **Archived**, not previewed.
- **J11-B Photo Optimize** (**Review Selected…**): the selected images open; from Review, **Send to...** -> **Photo Optimize (Managed Photo Set...** (label truncated here; read it on screen) returns them.
- **J11-C History** (**Edit Image in Review**; **Compare with Parent** read-only).
- **J11-D Learning**: **Send to...** -> **Learning (staged curation...** (label truncated here).
Expected for each: as documented in `PHOTO_REVIEW_REPROCESS.md` 3.1a, 3.5 and 6; no behaviour change. This runbook
cannot state more precisely than "as before"; record anything that differs.
Result: [ ] pass  [ ] fail  [ ] note   Evidence: ______  Notes: ______

---

## 11. Known gaps (steps the code does not let this runbook check precisely)

- Whether the app needs a restart after changing `output_dir` (3.2): not established.
- "One `submit_njrs` call" and batch-id placement in the stored row (J4): proven by the 621 tests, only indirectly
  visible here.
- Exact UI text for a cancelled child, and the labels for Queue cancel/remove, the SFW toggle and the exact History
  archived wording: not read for this runbook; record what you see.
- Legacy path-keyed rating (J10b) cannot be reproduced on a copy; it needs a view-only open of one live file.
- Retain and Discard write into the live Learning record file, and Re-work children into the live job repository; the
  copy isolates the output folder only (section 1).
- Whether Recommendations visibly change (L2): not established.

## 12. Evidence (Part B; to be filled in by the owner)

| Item | Value |
|---|---|
| Date / app commit (`git rev-parse HEAD` in `$Main`) | |
| Original `output_dir` | |
| Copy folder | |
| Forge model, steps, size, batch (S1 / J4 / J5.3 / J6.2) | |
| Learning rows before / after (3.4) | |
| Authorization for the generation run (your words) | |

| Journey / step | pass / fail / note | Screenshot or record excerpt | Failure detail for 625 |
|---|---|---|---|
| S1 | | | |
| J1.1-J1.4 | | | |
| J3.1-J3.2 | | | |
| L1-L2 | | | |
| AR1-AR5 | | | |
| J2.1-J2.3 | | | |
| J4 | | | |
| J5.1-J5.3 | | | |
| J6.1-J6.2 | | | |
| J7.1-J7.2 | | | |
| J8 | | | |
| J9.1-J9.2 | | | |
| J10a, J10b | | | |
| J11-A..D | | | |

Every failure: step id, what you did, what you saw, the record row or `Get-FileHash` output, and a screenshot.

## 13. Put everything back

1. Engine Settings -> **Default output folder:** back to the `Original output_dir` recorded in section 12 -> **Save & Close**;
   verify with the `ConvertFrom-Json` one-liner in section 2.
2. Restore any renamed file (J9.2): `Rename-Item "$Copy\<src>.hold" "<src>"`.
3. Cancel any leftover queued job (AR4) in the Queue panel.
4. Keep or delete `$Copy` as you wish (this runbook deletes nothing); the `_archive` folder inside it is yours to empty.
5. Decide about the Learning backup (3.4): the acceptance rows are real evidence; keep them, or restore
   `learning_records.before624.jsonl` yourself. Not an automated step.
6. Send the filled-in section 12 back; failures go to package 625, not into 624.
