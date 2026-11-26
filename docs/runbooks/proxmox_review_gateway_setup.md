# Proxmox preparation for the phone review gateway (RG-100)

What was set up on the owner's Proxmox server on 2026-11-26 for the phone review gateway, how it was checked, and how
to undo each step. Installing, upgrading, pairing and troubleshooting the gateway itself is in
[`review_gateway.md`](review_gateway.md); this page records this particular server. It holds no passwords, auth
keys, API keys, tokens or the sync secret.

This repository is public, so home-network details are replaced by placeholders in angle brackets: LAN addresses,
the router, the sync certificate fingerprint and storage findings. The owner keeps the full version outside the
repository.

The owner ran every command and click himself. Forge on Proxmox (RG-145) is not part of this.

## Placeholders

| Placeholder | Stands for |
|---|---|
| `<lan-cidr>` | The home LAN, a private /24 |
| `<router-ip>` | The home router (DHCP and DNS) |
| `<proxmox-ip>` | The Proxmox host; its web UI is `https://<proxmox-ip>:8006`, home LAN only |
| `<pc-ip>` | The PC that runs StableNew, reserved in the router |
| `<truenas-ip>` | TrueNAS SCALE, reserved in the router |
| `<immich-url>` | Immich on TrueNAS, `http://<truenas-ip>:<immich-port>` |
| `<ct110-ip>` | CT 110, the GPU AI container |
| `<gateway-ip>` | CT 120, the gateway, static |
| `<tailnet>` | The owner's Tailscale tailnet name |
| `<owner-login>` | The owner's Tailscale login |

## The server

| Item | Value |
|---|---|
| Proxmox VE | 9.2, 15 GiB RAM |
| Immich | 3.4.2 at `<immich-url>` |
| Backup storage | `truenas-backup`: an NFS share on TrueNAS |

| Container | Role | Address | Notes |
|---|---|---|---|
| CT 110 | GPU AI container (Ollama, reached by the PC through the `ai-tunnel` SSH tunnel) | `<ct110-ip>` | GPU devices passed through; untouched apart from step 7 |
| CT 120 `review-gateway` | Phone review gateway | `<gateway-ip>` (static) | Created in step 3 |

## 1. CT 110 start warning

Starting CT 110 printed `WARN: Systemd 255 detected. You may need to enable nesting.` The container worked anyway;
nesting was turned on in step 7. The SSH tunnel, the `ai-tunnel` account and Ollama's configuration were not
changed at any point. The tunnel check (`OK` from the PC) passed after every step that could affect it.

## 2. Tailscale account and phone

The owner's existing Tailscale account was reused, and the Android phone shows in the Machines list. In the DNS
settings MagicDNS and HTTPS certificates are on. Stale nameserver entries for a DNS server that no longer exists
were removed.

Rollback: re-add nameservers in the Tailscale DNS page; turning MagicDNS or HTTPS off breaks the phone address.

## 3. CT 120 `review-gateway`

Template `debian-13-standard_13.6-1_amd64.tar.zst`. On the Proxmox host:

```bash
pct create 120 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst \
  --hostname review-gateway --unprivileged 1 --features nesting=1 \
  --cores 2 --memory 2048 --swap 512 --rootfs local-lvm:8 \
  --mp0 local-lvm:200,mp=/srv/review-cache,backup=0 \
  --net0 name=eth0,bridge=vmbr0,ip=<gateway-ip>/24,gw=<router-ip>,firewall=1 \
  --nameserver <router-ip> --dev0 /dev/net/tun --ostype debian --onboot 1
pct start 120
```

- Unprivileged, with nesting, so systemd works. `/dev/net/tun` is passed in for Tailscale.
- Root disk 8 GB (`vm-120-disk-0`). Media cache 200 GB (`vm-120-disk-1`) at `/srv/review-cache`, excluded from
  backups because it is a cache the PC can refill.
- No root password: the console is `pct enter 120` from the host shell.
- Starts on boot. It is in the nightly backup job (about 260 MB without the cache disk).

Rollback: `pct stop 120 && pct destroy 120 --purge` (deletes both disks).

## 4. Tailscale in CT 120, placeholder and phone check

In the container, after `apt update && apt full-upgrade -y && apt install -y curl ca-certificates python3`:

```bash
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg -o /usr/share/keyrings/tailscale-archive-keyring.gpg
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list -o /etc/apt/sources.list.d/tailscale.list
apt update && apt install -y tailscale
tailscale up --hostname=review-gateway --advertise-tags=tag:review-gateway --accept-dns=false
```

The owner approved the login in his browser. The device is tagged `tag:review-gateway`, so its key does not expire.
Its address is `https://review-gateway.<tailnet>.ts.net`. Perl locale warnings during `apt` are harmless.

A placeholder page on `127.0.0.1:8080` (a `review-placeholder` systemd unit) was published with
`tailscale serve --bg --https=443`. The phone on mobile data, with Wi-Fi off, showed it. The placeholder was removed
in step 9.

Rollback: `tailscale logout`, then remove the machine in the Tailscale admin console; `apt purge tailscale`.

## 5. Tailscale access policy

The old allow-all policy was replaced with this one (saved by the owner as `tailscale-policy-old.txt` before the
change):

```jsonc
{
  "tagOwners": {"tag:review-gateway": ["autogroup:admin"]},
  "grants": [
    {"src": ["autogroup:member"], "dst": ["tag:review-gateway"], "ip": ["tcp:443"]}
  ],
  // No ssh section, no subnet router, no exit node, no Funnel.
  "tests": [
    {
      "src": "<owner-login>",
      "accept": ["tag:review-gateway:443"],
      "deny": ["tag:review-gateway:22", "tag:review-gateway:80", "tag:review-gateway:9443"]
    }
  ]
}
```

The policy preview shows the owner's devices reach only port 443 on the gateway, and the gateway reaches no other
device. The old policy's subnet-router tag, its route auto-approval for the LAN and its SSH rule are gone.
Checked from the phone: `http://<gateway tailnet address>:8080` fails; only the HTTPS name works.

Rollback: paste `tailscale-policy-old.txt` back into Access controls and save.

## 6. Proxmox firewall

`/etc/pve/firewall/cluster.fw`. The first two rules keep the web UI and SSH working before the firewall is switched on:

```
[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -source <lan-cidr> -p tcp -dport 8006 # Proxmox web UI from home LAN
IN ACCEPT -source <lan-cidr> -p tcp -dport 22 # SSH to Proxmox from home LAN
IN Ping(ACCEPT) -source <lan-cidr> # ping Proxmox from home LAN
```

`/etc/pve/firewall/120.fw` (first match wins; replies to allowed traffic are let through automatically):

```
[OPTIONS]
enable: 1
policy_in: DROP
policy_out: REJECT

[RULES]
IN ACCEPT -source <pc-ip> -p tcp -dport 9443 # StableNew sync from the PC (RG-120)
IN Ping(ACCEPT) -source <pc-ip> # ping from the PC for troubleshooting
OUT ACCEPT -dest <router-ip> -p udp -dport 53 # DNS via router
OUT ACCEPT -dest <router-ip> -p tcp -dport 53 # DNS via router (TCP)
OUT ACCEPT -dest <truenas-ip> -p tcp -dport <immich-port> # Immich on TrueNAS
OUT REJECT -dest 192.168.0.0/16 # every other home device: CT 110, Proxmox, TrueNAS, PC
OUT REJECT -dest 10.0.0.0/8
OUT REJECT -dest 172.16.0.0/12
OUT REJECT -dest 169.254.0.0/16
OUT REJECT -dest 2000::/3 # no IPv6, gateway is IPv4 only
OUT REJECT -dest fc00::/7
OUT REJECT -dest fe80::/10
OUT ACCEPT -p tcp -dport 80 # Debian package mirrors
OUT ACCEPT -p tcp -dport 443 # Tailscale coordination and relays, package downloads
OUT ACCEPT -p udp # Tailscale direct connections (internet only, LAN rejected above)
```

Applied with `pve-firewall compile` (no errors), then `enable: 1` in `cluster.fw`. CT 110 has no `110.fw`, so its
firewall is off and its traffic is unchanged.

Checked: the Proxmox web UI still opens from the PC in a new tab; from CT 120, CT 110, Proxmox, TrueNAS's web UI and
the PC were all blocked, while Immich and the internet worked; port 9443 opens from the PC; the phone still reaches
the gateway on mobile data; the AI tunnel still works.

Rollback, from the host shell or the Proxmox web console: `sed -i 's/^enable: 1/enable: 0/' /etc/pve/firewall/cluster.fw`
(or `pve-firewall stop`), then delete `120.fw` and `cluster.fw` if they are no longer wanted.

## 7. CT 110 resize and models disk

The owner chose 11 GB RAM and a 400 GB models disk. The original plan (32 GB, 1 TB) does not fit a 15 GiB host and
the free thin pool.

```bash
pct set 110 --memory 11264 --swap 2048 --cores 12 --features nesting=1 \
  --mp0 local-lvm:400,mp=/srv/models,backup=0
pct reboot 110
```

The models disk is `vm-110-disk-1` at `/srv/models`, kept out of backups because models can be downloaded again. The
GPU device pass-through (`dev0` to `dev3`) and the network settings were not touched. After the reboot, the tunnel
check passed.

Rollback: `pct set 110 --memory 8192 --swap 1024 --cores 8 --delete features,mp0`, `pct reboot 110`, then remove
the now-unused `vm-110-disk-1` in the container's Resources page (this deletes the models on it).

## 8. truenas-backup contents (report only, nothing deleted)

The Proxmox backup share holds only `dump/`, with the nightly backups of CT 110 and CT 120; nothing else is on it.
The nightly job backs up all guests with zstd in snapshot mode and prunes with `keep-daily=7,keep-last=3`, which
overrides the storage's `keep-all`. Findings about other TrueNAS datasets are in the owner's private copy.

## 9. Gateway install (replaces the placeholder)

The scp route in [`review_gateway.md`](review_gateway.md) does not work here: the PC has no SSH key or password for
Proxmox. The source came instead from a GitHub archive pinned to a commit, inside CT 120:

```bash
SHA=<origin/main commit>
cd /root && curl -fsSL -o stablenew-$SHA.tar.gz https://codeload.github.com/destroyer42/StableNew2/tar.gz/$SHA
rm -rf /root/review-gateway-src && mkdir -p /root/review-gateway-src
tar -xzf stablenew-$SHA.tar.gz -C /root/review-gateway-src --strip-components=1 \
  StableNew2-$SHA/services/review_gateway StableNew2-$SHA/docs/schemas/stablenew.review-gateway-sync.v1.json
# First install only:
SYNC_HOST=<gateway-ip> MEDIA_DIR=/srv/review-cache/media bash /root/review-gateway-src/services/review_gateway/install.sh
# Upgrades:
bash /root/review-gateway-src/services/review_gateway/install.sh
```

| Install | Commit | Release directory |
|---|---|---|
| First (RG-110) | `f5f82b035de5b19c4d45d77b986162a3c2a5fa7b` | `20261126T052204Z-9851` |
| Upgrade with Immich (RG-130, device-id fix) | `8c7642a646cdecab5375a7758495c917297f5e36` | `20261126T113149Z-496` |

Then the phone app was published and the placeholder removed:

```bash
tailscale serve --https=443 off
tailscale serve --bg --https=443 http://127.0.0.1:8443
systemctl disable --now review-placeholder   # then removed its unit file and /srv/placeholder
```

- Sync address for the PC: `<gateway-ip>:9443`. It is reachable from the PC only and never published on the tailnet.
  The installer prints it as `https://<gateway-ip>:9443`, but StableNew's Phone review gateway dialog takes only
  `host:port`, without `https://`.
- The sync certificate's SHA-256 fingerprint was unchanged by the upgrade. It is not recorded here; read it on the
  gateway when entering it in StableNew.
- The sync secret is in `/etc/review-gateway/sync_secret` (0600). Read it on the console when entering it in StableNew;
  never copy it into chat, tickets or this file.
- `pct enter 120` gives a shell whose `PATH` lacks `/usr/local/bin`, so call `/usr/local/bin/review-gateway-admin`.

Checked: `review-gateway-admin status` works, and the phone shows the gateway app. After `pct reboot 120`, both
`review-gateway` and `tailscaled` come back active and the serve setting is kept.

Rollback: point `/opt/review-gateway/current` back at the previous release and `systemctl restart review-gateway`
(see [`review_gateway.md`](review_gateway.md)). To remove the gateway: `systemctl disable --now review-gateway` and
`tailscale serve --https=443 off`.

## 10. Immich connection

1. The gateway was upgraded to `8c7642a6` (table above).
2. `immich_url = "<immich-url>"` was appended to `/etc/review-gateway/config.toml`. The settings file predated
   Immich support, so the installer did not write it. The installer created an empty
   `/etc/review-gateway/immich_api_key` (0600, owned by `review-gateway`).
3. In Immich, signed in as the owner's account: Account Settings, API Keys, New API Key `StableNew review gateway`.
   It has exactly `asset.upload`, `asset.update`, `album.read`, `album.create` and `albumAsset.create`.
4. The owner pasted the key with `nano /etc/review-gateway/immich_api_key`. The file stayed 0600 and owned by
   `review-gateway`.
5. `systemctl restart review-gateway`, then `review-gateway-admin immich-check` printed `Immich 3.4.2` and
   `the key has exactly the needed permissions`.

The first real Keep from the phone proves the upload; that had not been done when this was written.

Immich is plain `http` on the LAN, so the key crosses the home network unencrypted. That is accepted for this home
network; HTTPS for Immich would be a separate job.

Rollback: delete the key in Immich (API Keys, bin icon), then empty the file with `: > /etc/review-gateway/immich_api_key`.
Kept items then wait in the gateway's queue.

## Open items

- **Router reservations.** The addresses of CT 120, Proxmox and CT 110 are static but not reserved in the router, so
  the router could hand one of them to another device. Reserve them, or shrink the DHCP range to exclude them.
- **Direct Tailscale path.** The phone reaches the gateway through a Tailscale relay (DERP), not directly. That
  works, but it is slower. On home Wi-Fi a direct path is blocked by the gateway's LAN rule. Allowing UDP to a
  reserved phone address would fix that if speed matters.
- **RAM.** CT 110 has 11 GB of the host's 15 GiB, so there is no room for Forge on Proxmox (D8, about 16 GB) without
  more memory.
- **Storage.** Two TrueNAS storage findings, for separate jobs, are in the owner's private copy.
- **Still to do on the desktop:** pair the phone and enter the sync address, secret and fingerprint in StableNew (RG-120).
- No remote access to Immich was found or added.
