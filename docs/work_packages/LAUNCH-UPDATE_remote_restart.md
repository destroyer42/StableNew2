# LAUNCH-UPDATE — Remote update and restart: design, threat model and owner decisions

Status: **built, not yet run on the owner's checkout.** The owner accepted decisions D1–D10 as recommended on
2026-11-26 ("Accept all ten"), including D7's automatic local rollback. LAUNCH-UPDATE-1 (PC side, PR #445) and
LAUNCH-UPDATE-2 (gateway and phone) are implemented; the phone side is described in
`docs/Subsystems/ReviewGateway/REVIEW_GATEWAY.md` section 8. LAUNCH-UPDATE-2 keeps `schema_version` at v1 with
additive changes, as RG-140 did, instead of D8's version bump: a bump would stop every older PC and gateway from
syncing until both were updated, while every addition is refused or ignored by an older peer. The desktop shortcut and sign-in
autostart (LAUNCH-AUTOSTART-440) shipped separately and are not part of this package.

## Objective

- **Owner outcome:** away from the desk, the owner taps one button on the phone and the PC fast-forwards its live
  `main` checkout to the merged `origin/main`, restarts StableNew when the running job is done, and resumes the queue.
  The phone then shows the old and new commit, or why the PC refused.
- **Why now:** PRs are merged to `main` under the owner's delegation while the owner is away. They reach the running app
  only after someone at the desk fast-forwards the `StableNew-main` checkout and restarts the app. On 2026-11-26 the
  live checkout was clean and 13 commits behind `origin/main`.
- **In scope (this package):** this document. **Exclusions:** no code, no schema change, no change to the owner's PC,
  gateway or checkout.

## Verified start state and evidence

Repository `destroyer42/StableNew2`, branch `claude/launch-autostart-remote-update-385cf1` from `origin/main` at
`29fc22c5`, isolated worktree. Session `claude:2b543a8e-f0ca-4d58-8b20-7c3ab2310227`. Evidence read:

| Fact | Evidence |
|---|---|
| The app starts only as `<repo>\.venv\Scripts\python.exe -m src.main` through the canonical launcher, which runs a read-only environment check (exact pins) and refuses a drifted `.venv` with exit 11, never installing. | `scripts/launch_stablenew.ps1`; `tools/runtime/check_launch_environment.py` (accepts `--constraints <file>`) |
| One instance at a time. | `src/main.py` (`SingleInstanceLock`) |
| Queued jobs persist and the runner auto-starts after a restart when `auto_run_enabled` was on and the queue was not paused. The paused flag itself is persisted. | `src/controller/job_execution_controller.py` (`_restore_queue_state`, `_persist_queue_state`) |
| One centralized shutdown with a time budget. | `AppController.shutdown_app`, `src/controller/app_controller_services/shutdown_coordinator.py` |
| Every gateway record is a request the PC may refuse. The PC checks the device against **its own** ledger: a device is bound only to an offer this PC issued, and its scopes come from that offer, not from the gateway. | `src/app/review_gateway_apply.py` (`_authorize`), `src/app/review_gateway_store.py` (`bind_device`) |
| Pairing scopes are `review` and `queue`. Every `outbox_record` requires an item `target`. | `docs/schemas/stablenew.review-gateway-sync.v1.json` (`pairing_offer.scopes`, `outbox_record.required`) |
| Live checkout: `main` tracking `origin/main`, origin `https://github.com/destroyer42/StableNew2.git`, no `core.hooksPath`, no submodules. | read-only `git --no-optional-locks` on 2026-11-26 |

RG-100 invariants apply unchanged: no inbound listener on the PC (1), outbox records are requests the PC may refuse (4),
the gateway's only side effect is the Immich upload (5).

## Alternatives

| Option | Summary | Verdict |
|---|---|---|
| A. Do nothing in code; use a remote-desktop tool | The owner signs in to the PC remotely and runs the two commands. Zero code. Inbound remote-control path, full desktop exposure, awkward on a phone. | Fallback the owner already has; does not meet "one tap". |
| B. Scheduled auto-update | A per-user Scheduled Task fast-forwards and restarts whenever the queue is idle. No phone involvement. | Rejected: removes the owner's per-update consent; merged code runs on the PC with no human step at all. |
| **C. Gateway admin request, pulled by the PC (recommended)** | Phone tap → outbox record under a separate admin grant → the PC's sync worker pulls it outbound, checks it, drains, and hands off to a small updater that fast-forwards and relaunches. | Meets the outcome inside RG-100's invariants. |
| D. Inbound HTTP endpoint or SSH command on the PC | Phone or gateway calls the PC directly. | Rejected: breaks RG-100 invariant 1. |
| E. Windows service as SYSTEM supervising the app | A machine-wide watchdog that updates and restarts. | Rejected: machine-wide privilege for a per-user app. |

## Recommended design (option C)

### Flow

1. **Status (PC → gateway).** Each sync cycle the PC publishes a small `pc_status`: the live `HEAD` SHA, the last fetched
   `origin/main` SHA and how many commits ahead it is, whether its pinned constraints still pass against the current
   `.venv`, the queue state (idle / running / N queued), and the last update receipt. The PC fetches `origin` at most every
   15 minutes for this (plain `git fetch origin main`, anonymous HTTPS, public repository). No paths, no commit text beyond
   SHAs and counts (decision 3).
2. **Request (phone → gateway).** On a device holding the `admin` scope, the phone shows "Update to `<short sha>`
   (N commits)" and, on tap and a confirmation, creates an outbox record of a new kind `admin_request`:
   `{action: "update_and_restart", expected_sha: <the origin/main SHA it was shown>}`. No item target.
3. **Preflight on the PC (sync worker, before anything changes).** The record is refused, with a reason code
   acknowledged to the phone, unless every check passes:
   - the device is bound to an offer this PC issued, not revoked, holding `admin` (existing `_authorize`);
   - the PC-local switch **Allow remote update** is on (desktop setting, off by default);
   - no other update is in progress, and none completed in the last 10 minutes (rate limit);
   - the running app's own checkout is the configured live checkout, on branch `main`, whose upstream is `origin/main`,
     and `origin`'s URL equals the expected repository URL;
   - no staged or modified tracked files (`git status --porcelain --untracked-files=no` empty); untracked files are
     allowed because Git itself refuses a fast-forward that would overwrite one;
   - after `git fetch origin main`, `origin/main` equals `expected_sha` and `HEAD` is an ancestor of it
     (`git merge-base --is-ancestor HEAD expected_sha`); an equal SHA is answered `already_current`;
   - the **target's** constraints pass the read-only environment check against the current `.venv`
     (`check_launch_environment.py --constraints <the target's constraints file extracted with git show>`), so an update
     that needs new packages is refused as `environment_drift` with the failing pins, and nothing is installed.
4. **Drain.** The PC holds queue dispatch with an in-memory update hold (not the persisted pause flag, which would leave
   the queue paused after the restart). The running job, if any, finishes normally. It is never cancelled or interrupted.
   If it is still running after the maximum wait (decision 5), the hold is released, the queue continues, and the record
   is refused `busy_timeout`.
5. **Hand-off.** The PC writes a durable update intent (record id, old SHA, expected SHA, whether to resume the queue)
   under `data/`, leaves the record unacknowledged in the ledger as `in_progress`, starts the updater as a detached child
   process, then calls the normal `shutdown_app("remote-update")` on the Tk thread. The queue's persisted state is
   unchanged, so queued jobs and `auto_run_enabled` come back after the restart as they would after any clean exit.
6. **Updater** (`scripts/update_and_restart.ps1`, started with explicit arguments by the app it replaces):
   waits up to 120 s for the old process to exit (by PID; it never kills it), repeats the checkout checks (clean, branch,
   upstream, origin URL, `origin/main == expected_sha`, ancestry), runs `git merge --ff-only <expected_sha>`, and starts
   `scripts\launch_stablenew.bat` minimized, the same launcher the shortcuts use. All git calls are argument lists, never a
   shell string, with `GIT_TERMINAL_PROMPT=0` and a timeout. It writes a result file next to the intent.
7. **Health and rollback.** The new app writes a started marker once its sync worker is running. If the launcher exits
   with 10, 11 or 12, or the app exits within 180 s without the marker, the updater moves local `main` back to the old SHA
   with `git reset --keep <old>` (origin is never touched; the tree was clean) and relaunches the old code (decision 7).
8. **Receipt.** On start, the app that is now running reads the result file, records the outcome in the sync ledger and
   acknowledges the record through the existing acknowledgement path: `applied` with `{old_sha, new_sha}`, or `refused`
   with a reason (`rolled_back`, `checkout_changed`, `old_app_did_not_exit`, …). The desktop shows the same line. The
   phone sees it on the next sync.

Only the live checkout's tracked source changes. Output, logs, packs, presets, `data/`, the `.venv` and every other
untracked or ignored file are not touched: a fast-forward changes only files that differ between the two commits.

### Reason codes (receipt to the phone)

`not_granted`, `revoked_device`, `remote_update_disabled`, `update_in_progress`, `rate_limited`, `not_live_checkout`,
`wrong_branch`, `wrong_upstream`, `origin_mismatch`, `dirty_checkout`, `target_moved` (origin/main is not
`expected_sha`), `not_github_signed`, `github_unavailable`, `not_fast_forward`, `already_current`, `fetch_failed`, `environment_drift`, `busy_timeout`,
`old_app_did_not_exit`, `checkout_changed`, `merge_failed`, `rolled_back`, `rollback_failed`.

## Threat model

Assets: code execution on the owner's PC as the owner; the owner's outputs, packs and history; availability of the
running app and queue. Actors: a lost or stolen phone holding a grant; a compromised gateway container; a tailnet device
that is not the owner's phone; anyone able to land a commit on `origin/main`.

| ID | Threat | Precondition | Control | Residual |
|---|---|---|---|---|
| U1 | Arbitrary code execution chosen by the requester | Any request field reaching git or a shell | The request carries only `expected_sha` (40 hex, validated). The PC accepts it only if it equals what `origin/main` resolves to after its own fetch and is a descendant of `HEAD`. Fixed argument lists; no ref names, paths or URLs from the request. | None beyond U4. |
| U2 | Forged admin request from a compromised gateway | The attacker controls the gateway container | The gateway can impersonate an enrolled admin device (records are not signed by the phone). It still cannot choose code (U1), the PC-local switch can stay off, the rate limit holds, and every run is reported on the desktop. | A compromised gateway can make the PC update to the current merged `main` and restart when idle. Owner decision 4. |
| U3 | Lost or stolen phone | The phone holds an `admin` grant | `admin` is a separate grant issued only from a dedicated desktop pairing offer; revocation on the gateway and the desktop (S11); the app confirms the tap; Tailscale membership is the outer layer (D9). | Same as U2 until revoked. |
| U4 | Malicious or broken code on `origin/main` | A bad merge | Unchanged trust anchor: only merged `main` is ever run. Remote update removes the owner's desk checkpoint between merge and execution, which the owner accepts by using the feature. Optional: require GitHub's signature on the target commit (decision 4). | Equal to what the next manual restart would run. |
| U5 | Update leaves the app down while the owner is away | Dependency change, crash on start | Preflight refuses environment drift before touching the tree; never installs; automatic local rollback on a failed start (decision 7). | A new build that starts, then fails later, is not rolled back. |
| U6 | Lost work or outputs | Restart during generation | Never interrupts a running job; drains first; queue state persists; fast-forward touches only tracked files that changed. | A job submitted in the seconds between drain and shutdown is queued, not lost. |
| U7 | Replay or duplicate taps | A record re-sent | Existing idempotency key and ledger outcome; one update at a time; 10-minute rate limit. | None. |
| U8 | Process ownership | The updater outlives the app | The updater is the one detached child the app starts for this purpose; it waits for the old PID and never kills it; it starts the app only through the canonical launcher. No adoption of any other process. | None. |
| U9 | Local tampering (hooks, remote URL) | Attacker already able to write the checkout's `.git` | Out of scope: such an attacker already runs code as the owner. The preflight still refuses an unexpected `origin` URL. | Accepted. |

## Owner decisions

All ten accepted as recommended, 2026-11-26 ("Accept all ten"). D4's optional GitHub-signature check was chosen
later (SAFE-UPDATE, owner approval 2026-11-27). The PC preflight, for the desktop button and the phone alike, asks
GitHub's public commit API about the target, the same rule as the gateway deployer's `verify_target`:
`verification.verified` true and committer `web-flow` (on `main` and forward only are the existing Git checks). It
replaces the `git verify-commit` idea in decision 4: no key is kept on the PC. Refusals are `not_github_signed` and,
when GitHub gives no usable answer, `github_unavailable`. Only the target commit is checked, not each commit behind it.

| # | Decision | Accepted answer |
|---|---|---|
| 1 | Trigger channel. | Option C (gateway admin request). Also a desktop menu item **Update and restart** that uses the same preflight and updater, for testing and for use at the desk. |
| 2 | Authorization. | A new pairing scope `admin`, issued only by a dedicated desktop offer (separate from review and queue), **and** a PC-local switch **Allow remote update**, off by default. Both must be on. |
| 3 | Approve a named commit. | Yes: the phone shows and sends the `origin/main` SHA it is updating to; the PC refuses `target_moved` if `main` moved meanwhile. This needs the small `pc_status` publish (SHAs and counts only, no commit text). |
| 4 | Accept the compromised-gateway residual (U2/U4). | Accept, because the PC can only ever run merged `main`. Do not build phone-side request signing now. Optional extra: refuse a target commit GitHub did not sign (`git verify-commit` with GitHub's web-flow key, which signs PRs merged through GitHub). |
| 5 | When to restart. | After the running job finishes, with queued jobs resumed after the restart. Maximum wait 60 minutes, then `busy_timeout`. Alternative: only when the queue is empty. |
| 6 | Dependency changes. | Refuse `environment_drift` when the target's pinned constraints do not pass against the current `.venv`; never install remotely. Changed requirement files whose pins still match are allowed. |
| 7 | Failed start after the update. | Automatic local rollback: `git reset --keep <old sha>` on the live `main` (local ref only; origin untouched) and relaunch the old code, reported `rolled_back`. This moves a local branch backwards, so it needs the owner's approval. |
| 8 | Schema change. | Additive record kind `admin_request` (no target), scope `admin` and payload `pc_status`, with one `schema_version` bump that lands after RG-140's schema change so the two do not collide. |
| 9 | Updater form. | A detached PowerShell script started by the app, not a Scheduled Task or service. |
| 10 | Slicing. | LAUNCH-UPDATE-1: PC preflight, drain hold, updater, rollback, receipt, desktop menu item and switch (no schema change; testable end to end at the desk). LAUNCH-UPDATE-2: schema bump, `admin` scope, `pc_status`, phone button and receipt display. |

## Implementation acceptance contract

LAUNCH-UPDATE-1:

- A preflight module under `src/app/` with the checks of step 3, each refusal a reason code; a pure function over an
  injected git runner so tests use a fixture repository, not the live checkout.
- A dispatch hold in the queue owner that is in memory only and never changes `queue_paused` or `auto_run_enabled`.
- `scripts/update_and_restart.ps1`: argument-list git calls, PID wait without kill, re-check, `--ff-only`, launch,
  health wait, `reset --keep` rollback, result file. No `Remove-Item` outside its own intent and result files.
- Tests: a disposable bare `origin` plus a clone, covering every reason code; drain with a fake running job; rollback on
  a launcher exit 11; output, `data/`, logs and an untracked file byte-identical afterwards; the hold never persisted.
- No new queue, runner or history authority; no change to the canonical launcher; no install step anywhere.

LAUNCH-UPDATE-2:

- Schema `admin_request`, `admin`, `pc_status`, with gateway and PC tests that refuse an `admin_request` from a device
  without `admin`, with a malformed SHA, or while the switch is off.
- A gateway test that the phone app cannot create `admin_request` without the `admin` scope, and that the sync API stays
  off the phone port (S2).

Stop conditions: any need for an inbound path; any request field reaching git as a ref, path or option; any install or
`pip` call; any need to terminate a process the updater did not start.

## Execution class and model recommendation

- LAUNCH-UPDATE (this design): Architectural, docs only. Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- LAUNCH-UPDATE-1: Architectural (process lifecycle, trust boundary). Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- LAUNCH-UPDATE-2: Standard within this contract. Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.

The assessment above is a single-model self-critique (Claude Opus 5.5), not an independent second-model review. The
weakest assumption challenged: that a fast-forward to `origin/main` cannot be steered by the requester. It holds only
because the request carries a SHA the PC checks against its own fetch and ancestry; any design that lets the request
name a ref, branch or remote breaks U1.

## Documentation impact

On implementation: the runbook (`docs/runbooks/windows_runtime_bootstrap.md`) gains the update section;
`docs/Subsystems/ReviewGateway/REVIEW_GATEWAY.md` gains the admin grant; `docs/CODEX_MAP.md` and `STATUS.md` when code
exists.
