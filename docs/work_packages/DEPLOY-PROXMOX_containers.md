# DEPLOY-PROXMOX — Reproducible deploys to the Proxmox containers: design, threat model and owner decisions

Status: **design proposed, owner decisions open.** Nothing in this package changes Proxmox, a firewall, an SSH key or a
container. Every step that does is an owner-run step with exact commands, listed per slice.

## Objective

- **Owner outcome:** one simple, reproducible, auditable command deploys a named `origin/main` commit to each Proxmox
  container, checks that it works and goes back by itself if it does not. The owner can run it with one line, and a
  session can start it from the PC after a merge, within a switch the owner controls.
- **Why now:** every gateway change since RG-110 (RG-130, RG-140) needed the owner at the Proxmox console for about
  twelve hand-typed lines (`docs/runbooks/proxmox_review_gateway_setup.md` section 9). The installer only checks
  `systemctl is-active` three seconds after the restart and does not roll back. More gateway work (LAUNCH-UPDATE-2,
  RIFE duplicates) and the AI-worker work (RG-145) are queued.
- **In scope (this package):** this document. **Exclusions:** no code, no change to Proxmox, CT 110, CT 120, the PC's
  tunnel, the firewall or any key.

## Verified start state and evidence

Repository `destroyer42/StableNew2` (public), branch `claude/proxmox-deploy-tooling-0a4c28` at `48708c37`, equal to
`origin/main` on 2026-11-26, isolated worktree. A single-model assessment (Claude Opus 5.5) using the
`stablenew-design-review` and `security-review` procedures.

| Fact | Evidence |
|---|---|
| The installer builds `/opt/review-gateway/releases/<UTC stamp>-<pid>/` with its own venv (hash-pinned wheels, `--only-binary`), runs `check-config` as the service user, stops the service, switches `current`, reinstalls the unit file and the `review-gateway-admin` wrapper from the new release, restarts, keeps the new and previous releases, then fails if the service is not active after 3 s. It does not roll back and does not record which commit a release came from. | `services/review_gateway/install.sh` |
| The service runs as `review-gateway` with `NoNewPrivileges`, an empty capability set and no write access to `/opt`, `/etc/systemd` or `/usr/local`. It cannot upgrade itself. | `services/review_gateway/review-gateway.service`, `install.sh` (directory modes) |
| The sync API is a separate listener on the LAN address, port 9443, behind `Authorization: Bearer <sync secret>` for every path, and it answers `GET /sync/v1/health` with the schema version. The phone app is a separate application on `127.0.0.1:8443` with no sync routes. | `review_gateway/sync_app.py` (`_SyncSecret`, `health`), `review_gateway/phone_app.py` |
| Database changes are additive and run when the store opens (`ALTER TABLE ... ADD COLUMN`). An older release works with a migrated database until a phone action is recorded (RG-140 rollback note). | `review_gateway/store.py` (`_migrate`); the RG-140 redeploy note |
| On the PC, the gateway address, pinned certificate fingerprint and sync secret are in `%LOCALAPPDATA%\StableNew\review-gateway\settings.dpapi`, encrypted for the Windows user, so a tool run from any worktree as the owner can use them without touching the live checkout. | `src/app/review_gateway_store.py` (`_local_state_dir`, `GatewaySettingsStore`), `src/app/review_gateway_client.py` (`PinnedHttpsTransport`) |
| CT 120's firewall allows only PC→9443 and ping inbound; outbound DNS, Immich, and internet TCP 80/443. CT 110 has no `110.fw`, so its firewall is off. The PC has no SSH route to Proxmox or CT 120. | `docs/runbooks/proxmox_review_gateway_setup.md` sections 6 and 9 |
| The PC reaches CT 110 by SSH as the restricted `ai-tunnel` user, forwarding `127.0.0.1:11435` to Ollama on `127.0.0.1:11434` (an operator-managed Windows task). The runbook expects Ollama 0.40.16 with `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, prompt logging off, and the models `qwen3.5:4b-q4_K_M` and `lfm3:1.7b`, each approved by its manifest digest. No file in the repository records that desired state; the digests live only in the PC's approvals. | `docs/runbooks/ai_assist_preview_activation.md` (Remote Preview) |
| Forge on CT 110 (RG-145, D8) needs about 16 GB; CT 110 has 11 GB of a 15 GiB host. | `docs/runbooks/proxmox_review_gateway_setup.md` (Open items) |
| `main` requires the `required`, `full-suite` and `windows` checks. Merges are committed by GitHub and carry GitHub's signature (`git log --format=%G?` gives `E`, a signature without the key locally); required signatures are not enforced. | `gh api .../branches/main/protection`; `git log -1 origin/main` |
| Python on the containers: Debian 13 (CT 120) ships 3.13; Debian 12 ships 3.11.2, which predates `tarfile` extraction filters (3.11.4). The gateway stays 3.11-compatible. | Debian package versions; Python 3.11.4 changelog |

Not verified (no access from this session): CT 110's Ollama version, its systemd override, its installed model
digests, whether `sshd` runs in CT 120, and the Proxmox host's packages.

## Security review of the current procedure

| ID | Severity | Finding | Precondition | Minimal required fix |
|---|---|---|---|---|
| F1 | Medium | A commit SHA does not prove the commit is on `main`. GitHub serves commits that exist only in a fork through the parent repository's URLs, including `codeload.github.com/destroyer42/StableNew2/tar.gz/<sha>` (cross-fork object references; the repository allows forking). The manual route installs whatever tree that SHA names, as root. | Someone hands the owner, or a session, a fork-only SHA (a PR comment, a pasted note). | Before installing, check that the target is `main` or an ancestor of it, and refuse otherwise. Required for every route below; mandatory for any remote trigger. |
| F2 | Medium | No health check beyond "active after 3 s" and no automatic rollback. A release that binds but refuses every sync request, or crashes after 5 s, stays live. | Any broken release. | A health check of both listeners and the schema version, then automatic rollback. |
| F3 | Low | Nothing records which commit a release came from, or who deployed what when; rollback means reading release stamps. | Always. | A per-release `source.json` and an append-only deploy log. |
| F4 | Low | Rolling back after a database migration can break the older release (RG-140 note); today the owner must decide whether to restore a backup by hand. | A release that adds columns or tables. | Take an online SQLite backup before every switch; on rollback, restore it only when the table definitions changed. |
| F5 | Low | On Debian 12 (Python 3.11.2) `tarfile` has no extraction filter, so a deployer that extracts an archive must validate members itself. | Any extraction by a deployer on 3.11. | Member allowlist: regular files and directories only, under the two expected prefixes, no absolute paths, no `..`, no links or devices; use `filter="data"` as well where available. |
| F6 | Info (separate job) | CT 110's firewall is off, so its SSH and anything else it listens on are open to the whole LAN. | A compromised LAN device. | Propose a `110.fw` that allows SSH from the PC only (owner decision 9). |

The archive's integrity rests on TLS to GitHub in every option; no option below adds a weaker trust anchor.

## Alternatives for CT 120 (review gateway)

All three share one target-side deployer (below), because the hard part — verify, install, health-check, roll back,
record — must run as root inside the container in every case. They differ in who starts it.

| Option | Summary | New attack surface | Friction | Verdict |
|---|---|---|---|---|
| **A. Console pull** | `pct exec 120 -- /usr/local/sbin/review-gateway-deploy <sha>`, one line in the Proxmox web shell. | None. | The owner at a browser with the Proxmox UI (LAN only). | **Recommended as the base**, and always the fallback. |
| B. Push from the PC over SSH | A deploy key on the PC, `restrict,command="review-gateway-deploy --ssh",from="<pc-ip>"` on a root or sudo-limited account in CT 120; a firewall rule PC→CT 120:22; `sshd` exposed. | A second network service running as root, a new inbound port against RG-100's "9443 only" design, a new private key on the PC usable by any process running as the owner. | Low once set up; key and host-key management. | Not recommended for CT 120: the sync channel already gives an authenticated PC→gateway path. Works when the service is broken, but option A covers that. |
| **C. Over the sync channel** | The PC posts `{target_sha}` to a new sync route; the service drops a request file; a root `systemd` path unit runs the same deployer, which re-verifies everything itself. Mirrors LAUNCH-UPDATE. | A request crosses from the unprivileged, network-facing service user to a root action. It carries only a SHA, and the root deployer trusts nothing in it. | Lowest: a session runs one tool on the PC. | **Recommended as the remote trigger**, behind a switch that only the console can turn on. |
| D. Auto-follow `main` | A root timer deploys whenever `main` moves. | Removes per-deploy consent; can upgrade the gateway before the PC app in a schema change. | None. | Rejected (same reason as LAUNCH-UPDATE option B). |
| E. Proxmox host runs `pct exec` for the PC | A forced-command SSH key on the Proxmox host. | Root on the host for anything that escapes the forced command: every container, the GPU, the backups. | Low. | Rejected. |
| F. Self-hosted GitHub Actions runner | A runner deploys on merge. | A public repository with a self-hosted runner lets fork PRs run code on the LAN. | Low. | Rejected. |

## Recommended design

### The deployer (both containers share the core)

`services/deploy/stablenew_deploy.py`: Python standard library only, 3.11-compatible, run by the system `python3 -I`
as root. The container's entry point is a two-line wrapper installed by the component's installer:
`/usr/local/sbin/review-gateway-deploy` (CT 120) and, later, `/usr/local/sbin/ai-worker-deploy` (CT 110). It ships in
each release, so the deployer upgrades and rolls back with the code it installs.

Commands (CT 120):

```
review-gateway-deploy <sha>            deploy a commit (console)
review-gateway-deploy status           deployed commit, release, previous release, switch state, last result
review-gateway-deploy rollback         switch back to the previous release (console)
review-gateway-deploy remote on|off    the switch for option C (console only)
review-gateway-deploy --from-request   run by the path unit; reads the one request file
```

`deploy <sha>`, in order, stopping with a reason code at the first failure, before anything live changes:

1. Lock (`flock` on a root-owned file); a second deploy is refused `deploy_in_progress`.
2. The SHA is 40 lowercase hexadecimal characters.
3. **On `main`** (F1): `GET https://api.github.com/repos/destroyer42/StableNew2/compare/<sha>...main` reports
   `identical` or `ahead`; otherwise `not_on_main`. Fixed URL; the SHA is the only variable part.
4. **Forward only** (remote requests): `compare/<deployed>...<sha>` reports `identical` or `ahead`; otherwise
   `downgrade`. An identical SHA is answered `already_current`. At the console, `--allow-downgrade` permits an older
   commit on `main`. A release with no recorded commit (every release before this package) skips this check once.
5. **GitHub-merged** (owner decision 4): `GET .../commits/<sha>` reports `verification.verified` true and the
   committer is GitHub; otherwise `not_github_signed`.
6. Download `codeload.github.com/destroyer42/StableNew2/tar.gz/<sha>` into a new root-only staging directory, with a
   size cap; record its SHA-256. Extract only `StableNew2-<sha>/services/review_gateway/`,
   `StableNew2-<sha>/services/deploy/` and the sync schema, validating every member (F5).
7. Online SQLite backup of the gateway database to the deploy state directory (F4).
8. Run the release's own `install.sh` with `SOURCE_COMMIT=<sha>`. The installer writes `source.json`
   (`commit`, `archive_sha256`, `installed_at`) into the release and prints the release path; nothing else in it
   changes, so a manual install keeps working.
9. **Health check** (up to 45 s, retried): the unit is active; `GET https://<sync_host>:9443/sync/v1/health` with the
   secret and the pinned certificate returns `ok` and the schema version the new release's schema file declares;
   `GET http://127.0.0.1:8443/` returns 200; `review-gateway-admin status` exits 0.
10. **Rollback** on any health failure: stop the unit, point `current` at the previous release, reinstall that
    release's unit file and admin wrapper, restore the backup from step 7 only if `sqlite_master` table definitions
    differ, start, and run the same health check against the old release: `rolled_back` or `rollback_failed`.
11. Append one JSON line to `/var/lib/review-gateway-deploy/history.jsonl`: time, trigger (`console` or
    `remote:<request id>`), old and new commit, archive SHA-256, release, outcome and reason, and whether the schema
    file changed between the old and new commit (a warning that the PC app needs the same update; it does not block).

Exit codes are fixed per outcome, so the PC tool and scripts can tell them apart.

### The remote trigger for CT 120 (option C)

- **Switch.** `/etc/review-gateway/remote-deploy`, root-owned 0644, `enabled` or absent. Only
  `review-gateway-deploy remote on|off` at the console changes it; off by default. Neither the service user nor the PC
  can turn it on. It mirrors LAUNCH-UPDATE's PC-local "Allow remote update".
- **Route.** `POST /sync/v1/deploy-requests` `{request_id, target_sha}` and `GET /sync/v1/deploy-status`, on the sync
  listener only (same secret, same pinned certificate). The schema gains `deploy_request` and `deploy_status`
  (additive, no version bump; coordinated with LAUNCH-UPDATE-2's bump). The service refuses with
  `remote_deploy_disabled` when the switch file is not `enabled`, without writing anything.
- **Hand-off across the privilege boundary.** The service writes `request.json` atomically (temporary name, then
  rename) into `/var/lib/review-gateway-deploy/inbox/` (root:review-gateway 0770, nothing else in it). A root
  `review-gateway-deploy.path` unit starts the oneshot `review-gateway-deploy.service`, which runs
  `--from-request`: open with `O_NOFOLLOW`, require a regular file of at most 512 bytes, exactly the two keys, then
  delete it and re-check the switch itself. The SHA is the only value that reaches the deploy steps, and steps 2–5
  run unchanged. The root side never writes into the inbox; results go to the root-owned
  `/var/lib/review-gateway-deploy/` (0755), which the service reads for `deploy-status`.
- **PC tool.** `python -m tools.review_gateway_deploy request <sha>` and `... status`: reads the DPAPI settings
  through `GatewaySettingsStore` (read only), uses `PinnedHttpsTransport`, never touches the sync ledger or the live
  checkout, waits through the restart and prints the outcome, the old and new commit and the schema-change warning.
  It does not check ancestry itself; the gateway is the authority, and the PC tool is a convenience.
- **Sessions.** After a merge that changes `services/review_gateway/` or `services/deploy/`, a session runs the tool
  under decision 6 and reports the outcome line.

### CT 110 (AI worker)

**Now** there is no StableNew code on CT 110; "deploy" means keeping Ollama in the state AI Assist was approved
against. The recommendation is a desired-state file plus a read-only check, not a deployer:

- `services/ai_worker/manifest.json`: Ollama version, the expected limits (`OLLAMA_MAX_LOADED_MODELS=1`,
  `OLLAMA_NUM_PARALLEL=1`) and each model tag with its manifest digest. The owner reads the digests once on CT 110
  (`ollama list` / `ollama show`); a PR records them.
- `python -m tools.ai_worker_check` on the PC: through the existing tunnel (`127.0.0.1:11435`), compares
  `/api/version` and `/api/tags` digests with the manifest and reports drift. No new key, port or container change.
  The limits are not visible through the API; the tool prints the one console line that shows them
  (`pct exec 110 -- systemctl show ollama -p Environment`).
- Changing Ollama's version or settings, or pulling a model, stays an owner-run console step from the runbook
  (AI-WORKER-110 requires approval for every model download).

**Later (RG-145, Forge on CT 110):** Forge becomes a second component deployed exactly like the gateway: a release
directory per commit with a hash-pinned venv, a `127.0.0.1:7860` unit (S13), `ai-worker-deploy <sha>` from the same
deployer core with a Forge health check (`/sdapi/v1/options` through loopback) and rollback. The remote trigger is
decided in RG-145; option B fits there, because the PC already reaches CT 110 by SSH and CT 110 has no sync channel.
It needs the RAM decision first.

## Threat model

Assets: root in CT 120 (the phone review data, the sync secret, the Immich key, the sync certificate); the review
gateway's availability; root in CT 110 (GPU, models); the PC is out of scope here (LAUNCH-UPDATE covers it).
Actors: anyone who can land a commit on `main`; anyone able to plant a SHA in front of the owner or a session (fork
commits); a process running as the owner on the PC (holds the sync secret); an attacker with code execution as the
`review-gateway` service user (through the phone API); a LAN device.

| ID | Threat | Control | Residual |
|---|---|---|---|
| T1 | Installing code that never went through `main` (fork SHA, typo) | Steps 2–3 and 5 against GitHub; fixed URLs; the SHA is the only input | GitHub itself is trusted (as today). |
| T2 | Downgrade to an older, vulnerable `main` commit by a remote requester | Step 4 refuses anything that is not a descendant of the deployed commit; downgrades only at the console | None remote. |
| T3 | Command or path injection through the request | The request holds two fields; only a validated 40-hex SHA is used, never as a ref name, path, option or shell string; argument-list process calls; `install.sh` takes no request values | None. |
| T4 | Service user abuses the request file to attack root (symlink, huge file, race) | Root-owned inbox directory, `O_NOFOLLOW`, regular file, 512-byte cap, delete after read, root never writes there; the switch is re-read by root | With service-user code execution and the switch on, an attacker can make the gateway update to the current `main` and restart. Accepted (decision 2). |
| T5 | A process on the PC requests deploys | Same as T4: forward-only merged `main`, switch on the console | Availability (a restart, at most seconds). |
| T6 | Malicious archive content | `tarfile` member allowlist (F5); extraction into a new root-only staging directory | Content is whatever `main` holds; equal to the manual route. |
| T7 | A broken release leaves the phone without a gateway | Health check of both listeners and the schema; automatic rollback with database restore when tables changed | A release that passes the checks and fails later stays live; `review-gateway-deploy rollback` at the console. |
| T8 | Lost phone decisions on rollback | The database is restored only when its table definitions changed, from a backup taken while the service was stopped | Decisions made during the failed release's health window (under 45 s) after a migration can be lost. |
| T9 | PC and gateway on different schema versions | The deploy result warns when the schema file changed; RG-100 contract changes are additive | The owner updates the app (LAUNCH-UPDATE) after such a deploy. |
| T10 | The deployer breaks itself | It ships in each release; rollback restores the previous deployer; the manual archive route (runbook section 9) always works | None. |
| T11 | CT 110 drift unnoticed (version, digest, limits) | Read-only check against the manifest through the tunnel | Limits need a console line. |

## Owner decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | CT 120 route. | The console command (A) as the base, and the sync-channel trigger (C) for the PC. Not SSH into CT 120 (B). |
| 2 | The remote-deploy switch for CT 120. | A root-owned switch only the console can change, off by default. You turn it on once with `review-gateway-deploy remote on`. Accept the residual that, with the switch on, the PC or a compromised gateway service can make the gateway update to the current `main` and restart, never to other code. |
| 3 | Which commits. | Only commits on `main`. Remote requests forward only; downgrades and redeploys of older commits only at the console. |
| 4 | Require GitHub's merge signature on the target commit. | Yes. Every merge through a PR has it, so it costs nothing and shuts out commits pushed straight to `main`. |
| 5 | Automatic rollback. | Yes, after a failed health check, restoring the pre-deploy database backup only when the tables changed (risk T8). |
| 6 | When sessions may deploy the gateway. | A standing OK: while the switch is on, a session may deploy each merged gateway change and reports the outcome to you. Alternative: ask you in chat each time. |
| 7 | Schema changes. | Warn, don't block: the deploy goes ahead and says the PC app needs the same update. |
| 8 | CT 110 now. | A manifest of Ollama's version, limits and model digests in the repository, and a read-only PC check through the existing tunnel. No deployer and no new key until Forge (RG-145); Forge's trigger is decided there. |
| 9 | CT 110's firewall is off (F6). | A separate small package: a `110.fw` allowing SSH from the PC only, with the tunnel check after it. |

## Delivery slices

| Slice | Scope | Owner-run steps |
|---|---|---|
| DEPLOY-1 | `services/deploy/stablenew_deploy.py` (console commands, steps 1–11), `install.sh` records `source.json` and installs the wrapper, the runbook section, tests. | Once: the manual archive install of the DEPLOY-1 merge (today's section 9 lines), then `review-gateway-deploy status`. From then on: `pct exec 120 -- /usr/local/sbin/review-gateway-deploy <sha>`. |
| DEPLOY-2 | Sync routes and schema, the inbox and path unit (installed by `install.sh`, disabled until the switch is on), the PC tool, tests. After LAUNCH-UPDATE-2's schema change or coordinated with it. | `pct exec 120 -- /usr/local/sbin/review-gateway-deploy <DEPLOY-2 sha>`, then `... remote on`. |
| DEPLOY-3 | `services/ai_worker/manifest.json`, `tools/ai_worker_check.py`, runbook, tests. | Read the digests and limits on CT 110 once; a PR records them. |

## Implementation acceptance contract

- One deployer; no second installer. `install.sh` stays usable on its own; its only additions are `SOURCE_COMMIT`
  recording and the wrapper and unit files.
- Python 3.11-compatible, standard library only (the gateway's import test extends to `services/deploy/`).
- Every network call has a fixed host and path and a timeout; the SHA is the only variable; no shell strings.
- Tests on Windows CI with an injected system layer (commands, HTTP, filesystem, clock): every reason code; a fork SHA
  (`diverged`) refused; a downgrade refused remotely and allowed at the console; tarfile members with `..`, absolute
  paths, links and devices refused; health failure → rollback with and without a table change; rollback failure
  reported; the request file as a symbolic link, oversized, with extra keys or a bad SHA refused; the switch off
  refuses both on the route and in the root runner; the sync route is absent from the phone app (S2).
- No change to the PC app's queue, runner, history or sync ledger; the PC tool only reads the DPAPI settings.
- The gateway's existing tests and `tests/system` pass.

Stop conditions: any need for a new inbound port to CT 120; any request field reaching git, a URL, a path or a shell
beyond the validated SHA; any need for the PC to hold root credentials for a container or the Proxmox host; any
deploy that cannot verify `main` ancestry.

## Execution class and model recommendation

- DEPLOY-PROXMOX (this design): Architectural, docs only. Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- DEPLOY-1 and DEPLOY-2: Architectural (root process on a trust boundary). Claude Code Opus 5.5 High; Codex GPT-6
  Astra High. Expected usage per slice: about 10–20M cache-read, 80–150k output.
- DEPLOY-3: Standard. Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.

This is a single-model self-critique, not an independent review. The weakest assumption challenged: that a SHA pins
reviewed code. It does not (F1): GitHub serves fork commits under the parent's URLs, so every route needs the `main`
ancestry check, and a remote route also needs the forward-only check, or a requester could install an older
vulnerable commit.

## Documentation impact

On implementation: `docs/runbooks/review_gateway.md` and `docs/runbooks/proxmox_review_gateway_setup.md` section 9
(the one-line deploy replaces the archive lines, which stay as the bootstrap and fallback);
`docs/Subsystems/ReviewGateway/REVIEW_GATEWAY.md` (deploy routes); `docs/runbooks/ai_assist_preview_activation.md`
(the check); `docs/CODEX_MAP.md` and `STATUS.md` when code exists.
