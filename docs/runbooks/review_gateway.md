# Runbook: phone review gateway

Behavior and the sync contract: [Review Gateway](../Subsystems/ReviewGateway/REVIEW_GATEWAY.md). The owner's first
real install, on Proxmox, is recorded in [Proxmox preparation](proxmox_review_gateway_setup.md).

## Prerequisites

- A Debian 12 or newer unprivileged LXC (`review-gateway`), no GPU, Python 3.11 or newer.
- Its LAN address reserved in DHCP (the service binds to that exact address).
- Optional media disk (about 200 GB) mounted in the container and writable by the `review-gateway` user. In an
  unprivileged container the mount's host ownership must map to that user's id.
- Tailscale in the container and on the phone.
- Immich 2.0 or newer, reachable from the container.
- Proxmox firewall: TCP 9443 from the PC's LAN address only; no other inbound LAN port is needed.

## First install

The first install (and the one-time install of a version that brings `review-gateway-deploy`) copies the source by
hand. Later versions use [Deploy a commit](#deploy-a-commit). From a checkout on the PC, copy only what the installer
needs:

```powershell
git archive --format=tar -o review-gateway.tar HEAD services/review_gateway services/deploy docs/schemas/stablenew.review-gateway-sync.v1.json
```

```powershell
scp review-gateway.tar root@review-gateway:/root/
```

Then in the container:

```bash
mkdir -p /root/review-gateway-src && tar -xf /root/review-gateway.tar -C /root/review-gateway-src
SYNC_HOST=<container LAN address> MEDIA_DIR=<media mount> IMMICH_URL=<http://immich-address:port> bash /root/review-gateway-src/services/review_gateway/install.sh
```

The installer needs network access to PyPI (or a configured mirror) once, to fetch the hash-pinned wheels; the running
service downloads nothing. `SYNC_HOST`, `MEDIA_DIR` and `IMMICH_URL` apply only when
`/etc/review-gateway/config.toml` is first written.
Each install builds a new directory under `/opt/review-gateway/releases/` with its own virtual environment, checks it,
and only then points `/opt/review-gateway/current` at it; a failed build leaves the running version alone. Upgrades keep
the settings, the sync secret, the certificate and the data. The previous release is kept, with a copy of the database
taken just before the switch (`/var/lib/review-gateway-deploy/backups/`). The installer requires `services/deploy/`
beside the service and installs `/usr/local/sbin/review-gateway-deploy`.

Publish the phone app on the tailnet (HTTPS name and certificate come from Tailscale):

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8443
```

Never serve port 9443 through Tailscale or any proxy.

## Turn on deploys from the PC (one paste, once)

An existing gateway needs one console install of a commit that has DEPLOY-2. After that, the PC deploys every later
commit and the console is only the fallback. In the Proxmox host's web shell, set `S` to the full merge commit and paste
both lines:

```bash
S=<merge sha>
pct exec 120 -- sh -c "set -e; mkdir -p /root/gw-$S; curl -fsSL https://codeload.github.com/destroyer42/StableNew2/tar.gz/$S | tar -xz -C /root/gw-$S --strip-components=1 StableNew2-$S/services StableNew2-$S/docs/schemas; SOURCE_COMMIT=$S bash /root/gw-$S/services/review_gateway/install.sh; /usr/local/sbin/review-gateway-deploy $S"
```

The installer keeps the settings, the secrets, the certificate and the data, takes a database copy before switching,
turns remote deploy on (owner decision 2), and enables `review-gateway-deploy.path`. The last command must end with
`outcome: already_current`: that shows the deployer reaches GitHub from the container, finds the commit on `main` and
signed by GitHub, and sees it recorded as deployed. These two lines trust the SHA you paste, like every manual install,
so take it from the merged pull request. The checks apply from then on.

## Deploy a commit

Once `review-gateway-deploy` is installed, one line in the Proxmox host's shell deploys a commit of `main`. Use the
merge commit's full SHA (40 characters):

```bash
pct exec 120 -- /usr/local/sbin/review-gateway-deploy <sha>
```

Inside the container (`pct enter 120`) the same command works without `pct exec 120 --`. In order, it:

1. checks with GitHub that the commit is on `main`, is newer than the deployed one and is a merge GitHub signed. A SHA
   alone proves none of this: GitHub serves commits that exist only in a fork under this repository's addresses. A
   commit on `main` that is not the merge itself (a commit from inside a PR branch) is refused;
2. downloads that commit's archive and extracts only `services/review_gateway/`, `services/deploy/` and the sync schema,
   refusing links, devices and paths that leave the archive;
3. runs that commit's `install.sh`, which records the commit in the release's `source.json`;
4. checks the result for up to 45 seconds: the service is active; the sync API answers on the LAN address with the
   pinned certificate and the schema version of the new release; the phone app answers on loopback;
   `review-gateway-admin status` works;
5. if a check fails, switches back to the previous release. It restores the database copy only when the new release
   changed the tables.

Every attempt is a line in `/var/lib/review-gateway-deploy/history.jsonl`. The last line ends with `outcome: <code>`,
and the exit code names it:

| Outcome | Exit | Meaning |
|---|---|---|
| `deployed` | 0 | The new release is live and healthy. A line says if the sync schema changed: update StableNew on the PC to the same commit. |
| `already_current` | 0 | That commit is already deployed. |
| `bad_sha` | 3 | Not 40 lowercase hexadecimal characters. |
| `deploy_in_progress` | 4 | Another deploy is running. |
| `github_unavailable` | 5 | GitHub did not answer (network, rate limit). Nothing changed. |
| `not_on_main` | 6 | The commit is not on `main` (a fork, a typo or an unmerged PR). |
| `downgrade` | 7 | Older than the deployed commit. At the console: `review-gateway-deploy deploy --allow-downgrade <sha>`. |
| `not_github_signed` | 8 | Not a merge GitHub signed. Use the merge commit. |
| `download_failed` / `bad_archive` | 9 / 10 | The archive could not be fetched, or failed a check. A commit from before the deployer existed is refused as `bad_archive`. |
| `install_failed` | 11 | The installer stopped before switching. The old release runs. |
| `rolled_back` | 12 | The new release failed a check; the previous one is live again. |
| `rollback_failed` | 13 | The previous release failed its check as well: `journalctl -u review-gateway`. |
| `not_installed` | 15 | No current release or settings: do a first install. |

```bash
review-gateway-deploy status                         # deployed commit, previous release, last outcome
review-gateway-deploy rollback                       # back to the previous release; the database is kept
review-gateway-deploy rollback --restore-database    # also restore the copy taken before the current release
```

### From the PC

With remote deploy on, a session or the owner deploys from any StableNew checkout on the PC (PowerShell):

```powershell
python -m tools.review_gateway_deploy request <merge sha>
```

```powershell
python -m tools.review_gateway_deploy status
```

The tool uses the address, pinned certificate and sync secret saved in StableNew's Phone review gateway dialog for this
Windows user, and nothing else on the PC. It sends only the commit id over the sync port. The gateway writes it to
`/var/lib/review-gateway-deploy/inbox/request.json`, the only place the service may write for the deployer. The root
path unit `review-gateway-deploy.path` then runs `review-gateway-deploy from-request`. That command reads the file
without following links, deletes it, re-reads the switch, and runs the same checks as the console. A request can never
downgrade. The tool waits for the result and prints the same outcome (exit 0 deployed or already current, 1 refused or
rolled back, 3 still running after the time limit, 4 unreachable).

The console switch decides whether the PC may do this:

```bash
pct exec 120 -- /usr/local/sbin/review-gateway-deploy remote off    # or: remote on
```

An upgrade never turns it back on. While it is off, the gateway answers `remote_deploy_disabled` and writes nothing.

After `rollback`, keep the database unless the older release fails on it. Restoring it drops every decision made since
the current release started. The container needs `api.github.com` and `codeload.github.com` on TCP 443, which CT 120's
firewall already allows.

## Sync secret and certificate

The installer creates `/etc/review-gateway/sync_secret` (mode 0600) and a self-signed certificate
(`sync.crt`, `sync.key`) once. It prints the secret's path, never its value, and the certificate's SHA-256 fingerprint.
Enter the address (`host:port`, or the `https://host:port` sync URL the installer prints), the secret
(`cat /etc/review-gateway/sync_secret`) and the fingerprint in StableNew's pairing
settings (RG-120). The PC sends the secret only to a server showing that certificate.

```bash
review-gateway-admin fingerprint
```

To rotate either, delete the file (both certificate files together), run the installer again and re-enter it on the PC.

## Immich

Keepers upload from the gateway (living document section 5). Setting it up:

1. In Immich, signed in as the account that should own the photos: Account Settings, API Keys, New API Key. Tick only
   `asset.upload`, `asset.update`, `album.read`, `album.create` and `albumAsset.create`. If your Immich offers no
   per-permission choice, stop: do not use a full-access key (RG-100 stop condition).
2. Check `immich_url` in `/etc/review-gateway/config.toml`. After an upgrade from a version without Immich, add the line
   (`immich_url = "http://<immich address>:<port>"`); the key file path defaults to `/etc/review-gateway/immich_api_key`.
3. Paste the key into that file with an editor, so it stays out of shell history. The installer made it empty, mode 0600
   and owned by the service user; an editor keeps both.

```bash
nano /etc/review-gateway/immich_api_key
```

```bash
systemctl restart review-gateway && review-gateway-admin immich-check
```

`immich-check` prints the Immich version and any missing or extra permission, never the key. Only a changed `immich_url`
needs a restart; a replaced key is picked up by the next upload. Allow the container to reach Immich's port.

Deleting a phone Keep afterwards does not remove it from Immich: delete it there.

## Pair and revoke phones

Pairing starts on the desktop (RG-120): it shows a single-use code that lasts five minutes. Open the phone app and enter
it. Revoke from the desktop, or on the gateway while the PC is off:

```bash
review-gateway-admin devices
review-gateway-admin revoke <device_id>
```

A revoked phone is refused from its next request. Decisions it had already made stay in the outbox for the PC to judge:
after losing a phone, check the archive on the desktop for anything it deleted (a phone Delete is always a move).

## Operate

```bash
systemctl status review-gateway
journalctl -u review-gateway -n 100
review-gateway-admin status
review-gateway-admin purge
```

Logs carry no request paths, prompts or secrets. `status` also counts Immich uploads: `immich_waiting`, `immich_failing`
and `immich_uploaded`.

## Retention and backup

Retention runs hourly (rules: living document section 4). Undecided items are never purged; watch `status` for size.

Back up `data_dir` (default `/var/lib/review-gateway/data`): it holds unanswered decisions and enrolled devices. Use the
SQLite online backup, not a file copy of a running database:

```bash
python3 -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d)' /var/lib/review-gateway/data/gateway.sqlite3 /root/gateway-backup.sqlite3
```

Media is a cache and needs no backup: after a loss, the PC publishes again.

After restoring a database backup, and before starting the service, drop the receipt cursor's database name so the PC
reads the Immich receipts from the start (a new name is made at the next start):

```bash
python3 -c 'import sqlite3; d=sqlite3.connect("/var/lib/review-gateway/data/gateway.sqlite3"); d.execute("DELETE FROM gateway_meta WHERE key=?", ("receipt_epoch",)); d.commit()'
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Service will not start | `journalctl`; the LAN address changed, the media mount is missing, or the secret file mode is not 0600 |
| PC gets 401 | Secret differs; the installer printed the path of the one in use |
| PC refuses the certificate | `review-gateway-admin fingerprint` differs from the one entered on the PC |
| Uploads get 507 | The media or data disk is nearly full |
| Phone shows pairing again | The device was revoked, or the browser dropped its cookie: pair again |
| Keepers do not reach Immich | `review-gateway-admin immich-check`, then `journalctl` (`Immich ...` lines name a code) |
| `immich_waiting` only grows | `immich_url` is empty or the key file is empty |
| `immich_asset_trashed` | The same file is in Immich's trash: restore it there |
| Items never appear | `review-gateway-admin status`; the PC has not uploaded every declared file |
