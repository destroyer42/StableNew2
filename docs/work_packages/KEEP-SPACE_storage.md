# KEEP-SPACE: recycle week-old video frames, store repeated result records once, and a `.git` cleanup plan

Status: parts 1 and 2 built 2026-11-28 with deterministic tests; part 3 is a plan that has **not been run**.
Source: the 2026-11-27 value assessment. Base `origin/main` 841f9b49, branch `claude/keep-space-9190ca`.
Owner decision (2026-11-28): "7 days; delete merged". Frames wait 7 days after the finished clip exists and then go to
the Recycle Bin, not a hard delete. Deleting already-merged branches on GitHub is the orchestrating session's step and
is not part of this package.

Execution class: Standard. Model recommendation: Claude Code Sonnet 5.5 at high effort, or Codex equivalent.
Controller surface: none touched. Validation: focused tests, `tests/video`, `tests/queue`, `tests/system`,
`tests/tools`, ratchets, code-map check and `python tools/ci/run_pr_gate.py`. No GPU, no physical generation.

## 1. Frame retention (changes VID-FRAME, `VID-FRAME_full_picture_clips.md` section d2)

Unchanged: which frames are candidates, every protection (clip, recorded outputs, first and last frame, cut manifests
and Storyboard files, sequence runs, evaluations, archive; an unreadable manifest stops everything), the empty-queue
condition, the setting, and the one-time confirmation.

Changed:

- Age: 7 days after the clip exists (was 1).
- Frames go to the Windows Recycle Bin (`SHFileOperationW` with `FOF_ALLOWUNDO`, through ctypes, no new dependency;
  `src/utils/recycle_bin.py`), at most 200 files per shell call, one run folder at a time. The queue and the setting are
  re-checked before each run folder.
- A pass first finds everything, then checks that each drive's bin can take all of it (size plus 4 KB per file), and only
  then moves. Otherwise nothing moves: a window explains why (once per start) and offers **Not now** and **Turn off**
  only. Refused cases: not a local fixed drive, bin turned off for the drive or by policy, limit not recorded, the bin
  cannot be queried, or not enough free room. A move Windows reports as incomplete stops the pass.
- The move also sets `FOF_WANTNUKEWARNING`, so Windows asks before permanently destroying a file. There is no `unlink`
  fallback.
- A path longer than 259 characters is left where it is (the shell cannot take it).
- The confirmation says frames are recoverable from the Recycle Bin until it is emptied, that disk space is freed only
  then, that Windows permanently deletes items too large for the bin's limit, and the bin's free room and limit. The
  buttons are **Move now**, **Not now**, **Turn off**.

Where the limit comes from: the Shell API reports what a bin holds (`SHQueryRecycleBinW`) but has no call for its size
limit. The limit is read from the per-volume `MaxCapacity` value Explorer keeps under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume`. An absent value is a refusal.

Observed on the owner's PC (2026-11-28, read-only): the output folder is on `C:`, limit 99,685 MB (104.5 GB), 104.2 GB
free, so a 64.6 GB backlog would fit. A manual check recycled two 5-byte scratch files through the real shell calls;
tests use temp folders and a fake shell.

Consequences to know:

- The live settings already hold `video_frame_cleanup_confirmed: true` (given for the one-day permanent delete). The new
  rule is less destructive, so it does not ask again; the new wording appears only on a machine that never confirmed, or
  as the explanation when the bin cannot take the frames.
- Moving frames to the bin frees no disk space until the bin is emptied (or Windows ages items out).
- Frames sit in the bin's quota. This cleanup never evicts anything, but a later large delete by the operator in a nearly
  full bin can push out older bin items.
- Restoring frames from the bin puts the files back; the run folder keeps its `frames_removed.json` marker and is not
  swept again, and Movie Clips keeps using the clip for it.
- A large backlog is many small bin items; the first move may take a long time (not measured). Explorer's Recycle Bin
  window is slow with about 100,000 items.

## 2. Job database: store each prompt-optimizer record once

Read-only analysis of a copy of the live `jobs.sqlite3` (5.04 GB, 58,192 jobs, opened with `mode=ro`): `result_json`
3.0 GB, `njr_snapshot` 1.8 GB. Repeats in the last two weeks (14-day simulation, saving if stored once):

| Block | Saving | Note |
|---|---|---|
| `result_json` `prompt_optimizer_v3` (about four copies per job) | 276 MB | **implemented** |
| `result_json` `replay_descriptor` (two copies) | 108 MB | not done; 23 MB more on top of the first |
| `result_json` `frame_paths` lists (video jobs, five copies) | 72 MB | not done; operator tools read paths from the raw column |
| `result_json` `prompt_optimizer_analysis` | 34 MB more on top of the first | not done |
| `njr_snapshot` `frozen_experiment.snapshot` | - | already stored once (LEARN-SNAPSHOT-914) |

Implementation (`src/queue/result_blocks.py`, `JobRepository`), following LEARN-SNAPSHOT-914:

- New table `result_blocks(sha256, block_json, created_at)`, `CREATE TABLE IF NOT EXISTS`; no schema-version change, no
  existing row touched, no backfill, nothing deleted.
- On every result write, each `prompt_optimizer_v3` object of 256 characters or more becomes
  `{"$stored_block_sha256": ...}`; the body is inserted once, in the same transaction.
- Every read puts the body back and verifies its SHA-256, so callers see the result they wrote. A missing or altered body
  is reported as a repository integrity error and the reference is left in place; the job still loads.
- Compatibility: a StableNew build from before this change shows the reference instead of the record for jobs written
  afterwards (diagnostic data only; nothing is replayed from it). Tools that read `result_json` directly see the
  reference too; none of them reads this record.
- Undo: `DROP TABLE result_blocks` only while no row refers to it.

**Measured saving** (the shipped functions run over the copy's rows, written to scratch SQLite files and compared; every
result round-tripped equal, 0 mismatches in 29,534 jobs):

| Window | DB growth before | Saved per week |
|---|---|---|
| last 14 days (15,725 jobs) | 596 MB a week | 128 MB (21.5%) |
| last 28 days (29,534 jobs) | 592 MB a week | 136 MB (23.0%) |

## 3. Repository cleanup plan (NOT RUN)

Measured 2026-11-28 (git 2.52.0.windows.1). `StableNew-main` is a **linked worktree** of `StableNew`, so there is one
object store, not two.

| Measure | Value |
|---|---|
| `count-objects -vH` | 3,652 loose (17.5 MiB), 59,471 packed in 40 packs, 19.43 GiB |
| Reachable from all refs, reflogs and worktree indexes | 2.09 GiB |
| Unreachable | 17.18 GiB: 238 dropped commits, 2,066 trees, 1,729 blobs |
| Of that, 17 blobs over 100 MB | 17.11 GiB: SDXL/CLIP model weights, `yolov8x-worldv2.pt`, a December 2025 snapshot zip |
| Worktrees | 55, of which 4 are prunable records; 3 are locked agent worktrees |
| Stash entries | 7 (shared by every worktree; 74.8 MiB of their own) |
| `gc.*` configuration | none |

Findings that shape the commands:

1. All 17 large blobs are held by **8 dropped commits** (December 2025 and 18 March 2026). The other 230 dropped commits,
   some a day old, cost 1.5 MiB, so keep them.
2. The 19 GB pack has a **second hard link**: a scratch clone left by another session on 2026-11-25
   (`%TEMP%\claude\c91786da69ab771c\058f7e2a-7414-4113-8fb2-698a698c9ea6\scratchpad\base-clone`). Until that folder is
   removed, repacking frees nothing and temporarily adds about 2 GB. It has no refs or stashes the main repository
   lacks, 0.08 GiB of its own, and a clean status.
3. A plain `git gc` will not remove the weights: they sit in a pack whose timestamp is recent.
4. **Do not run `git reflog expire`** here. It would free at most about 70 MiB, and
   `git reflog expire --expire=now --expire-unreachable=now --all` would **destroy stash entries 1 to 6**, which live only
   in the stash reflog (explicit expiry flags override the default protection of `refs/stash`). The `gc` command below
   turns reflog expiry off.

Expected saving: about **17.3 GiB** (19.45 GiB to about 2.1 GiB), plus 0.08 GiB for the clone.

Before starting: StableNew closed, no Claude, Codex or editor session working in any worktree, no `git` process running.
`--prune=now` is unsafe while something else writes to the repository. Every other session shares this stash stack:
nobody should push, pop, drop or clear a stash during the cleanup.

Step 1, record the state to compare afterwards:

```powershell
Set-Location "$env:USERPROFILE\projects\StableNew"; & { git stash list --format="%H %gs"; "---"; git worktree list; "---"; git for-each-ref; "---"; git count-objects -vH } | Out-File -Encoding utf8 "$env:USERPROFILE\Documents\keep-space-git-before.txt"
```

Step 2, drop the four records of worktrees whose folders are gone (check the dry run first; their commits are all on
branches):

```powershell
git worktree prune --dry-run --verbose
```

```powershell
git worktree prune --verbose
```

Step 3, keep every dropped commit except the 8 that hold the weights (230 refs on 2026-11-28; a normal push does not
send `refs/keep-space/*`; never `git push --mirror` from this repository):

```powershell
$skip = @('123f565a86df81f63f46eb6d151f88ee6c962112','7e5efc7779b08901c5bfb17044076f60ac7c2855','d2c88a0a0d4ba1331df76e349172d4e49cc08aab','490d49368037d3c5a6eec910508c0798ef235699','969a29305ac465053d54fa3a865555f68fb07c8b','8dc0412f3ddc4ae7423724fe59c7c872f8980249','71fab3552623a25fca2732122b958013ee2e4814','4923aa7d71d46fcda162fffeafbd20763ab1023d')
$reach = New-Object 'System.Collections.Generic.HashSet[string]'
git rev-list --all --reflog | ForEach-Object { [void]$reach.Add($_) }
$keep = @(git cat-file --batch-all-objects "--batch-check=%(objectname) %(objecttype)" --unordered | Where-Object { $_.EndsWith(' commit') } | ForEach-Object { $_.Split(' ')[0] } | Where-Object { -not $reach.Contains($_) -and $skip -notcontains $_ })
"keeping $($keep.Count) dropped commits"
$keep | ForEach-Object { git update-ref "refs/keep-space/dropped/$_" $_ }
```

Step 4, remove the scratch clone that holds the second link (confirm that session is not in use):

```powershell
Remove-Item -Recurse -Force -Confirm:$false "$env:TEMP\claude\c91786da69ab771c\058f7e2a-7414-4113-8fb2-698a698c9ea6\scratchpad\base-clone"
```

Step 5, repack and prune, with every reflog (stash included) kept. This permanently removes the weights and the zip:

```powershell
git -c gc.reflogExpire=never -c gc.reflogExpireUnreachable=never -c gc.refs/stash.reflogExpire=never -c gc.refs/stash.reflogExpireUnreachable=never gc --prune=now
```

Step 6, verify. Expect 7 stashes with the recorded hashes, every worktree still listed (minus the four), no `fsck`
errors, and a pack of about 2.1 GiB:

```powershell
git stash list --format="%H %gs"; git worktree list; git fsck --connectivity-only; git count-objects -vH
```

To keep the December 2025 snapshot zip, export it before step 5 (run in Git Bash, not PowerShell, which corrupts binary
redirects): `git cat-file blob 6abaa8be81e624efa898c9755d7e5386195746bf > snapshot-20251213.zip`.

The `refs/keep-space/*` refs can be deleted later, when nothing dropped is wanted back.

## Not done

- No backfill, prune or deletion of existing job rows (open owner decision 9 in `STATUS.md`).
- The remaining repeated blocks in the table above.
- The cleanup in section 3.
- A real frame sweep of the live output folder, and any check in the live app.
