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

## Install or upgrade

From a checkout on the PC, copy only what the installer needs:

```powershell
git archive --format=tar -o review-gateway.tar HEAD services/review_gateway docs/schemas/stablenew.review-gateway-sync.v1.json
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
the settings, the sync secret, the certificate and the data. The previous release is kept: to go back, point `current`
at it and `systemctl restart review-gateway`.

Publish the phone app on the tailnet (HTTPS name and certificate come from Tailscale):

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8443
```

Never serve port 9443 through Tailscale or any proxy.

## Sync secret and certificate

The installer creates `/etc/review-gateway/sync_secret` (mode 0600) and a self-signed certificate
(`sync.crt`, `sync.key`) once. It prints the secret's path, never its value, and the certificate's SHA-256 fingerprint.
Enter the address, the secret (`cat /etc/review-gateway/sync_secret`) and the fingerprint in StableNew's pairing
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
