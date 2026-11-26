# DEPLOY-110FW — Firewall for the AI worker (CT 110): owner-run steps

Status: **approved, not run.** Decision 9 of [DEPLOY-PROXMOX](DEPLOY-PROXMOX_containers.md) (PR #453) (owner, 2026-11-26: "All
others approved"). Finding F6 there: CT 110 has no `110.fw`, so its firewall is off and everything it listens on is open
to the whole home LAN. This package turns it on and allows SSH from the PC only. Every step below is run by the owner on
the Proxmox host. Nothing in the repository runs it.

This repository is public, so addresses are placeholders, as in
[Proxmox preparation](../runbooks/proxmox_review_gateway_setup.md#placeholders): `<pc-ip>`, `<ct110-ip>`,
`<lan-cidr>`.

## Objective

- **Outcome:** CT 110 accepts inbound connections only from the PC on TCP 22 (the `ai-tunnel` SSH forward that AI
  Assist uses, and the owner's own SSH from the PC), plus ping from the PC. The AI tunnel and AI Assist's Remote
  Preview keep working.
- **Exclusions:** outbound traffic stays open. Ollama and later Forge need model and package downloads; restricting
  outbound is a separate decision. No change to the `ai-tunnel` account, its key, Ollama's settings, the GPU devices or
  CT 120. No Forge port (RG-145 adds its own forward through the same SSH connection, so it needs no inbound rule).

## Threat and control

| Threat | Before | After |
|---|---|---|
| A compromised LAN device (TV, guest laptop, IoT) brute-forces or exploits SSH on CT 110 | Reachable | Dropped |
| Ollama or a later service accidentally listens on all interfaces (`OLLAMA_HOST=0.0.0.0`, Forge `--listen`) | Open to the LAN | Dropped; reachable only through the PC's SSH forward (S13) |
| The PC itself is compromised | Can use the tunnel key | Unchanged (the forward-only key is the control) |

Residual: anything the PC can reach over SSH is unchanged. The rule matches the PC by its LAN address, so the router
reservation for `<pc-ip>` matters (the open item in the Proxmox runbook).

## Steps (Proxmox host shell, as root)

### 1. Look before changing anything

```bash
pct config 110 | grep -E '^net[0-9]+:'
pct exec 110 -- ss -tlnup
ls -l /etc/pve/firewall/
```

Check:

- The `net0` line. The rules apply only to a NIC with `firewall=1`. Note whether it is there.
- What CT 110 listens on. Expect `sshd` on `0.0.0.0:22` (or `*:22`) and Ollama on `127.0.0.1:11434`. If anything else
  listens on a non-loopback address (for example a web UI used from another device), stop and decide about it first:
  these rules would cut it off.
- That `cluster.fw` exists with `enable: 1` (Proxmox runbook step 6) and that there is no `110.fw` yet.

Also from the PC, confirm the tunnel works now. In a StableNew checkout at or after the DEPLOY-3 merge, which adds the
read-only check, run in PowerShell:

```powershell
python -m tools.ai_worker_check
```

Any outcome other than `unreachable` means the tunnel works. `unrecorded` is expected until the model digests are
recorded.

### 2. Write the rules

```bash
cat > /etc/pve/firewall/110.fw <<'EOF'
[OPTIONS]
enable: 1
policy_in: DROP
policy_out: ACCEPT

[RULES]
IN ACCEPT -source <pc-ip> -p tcp -dport 22 # AI tunnel (ai-tunnel) and SSH from the PC
IN Ping(ACCEPT) -source <pc-ip> # ping from the PC for troubleshooting
EOF
pve-firewall compile >/dev/null && echo compiled
```

Replace `<pc-ip>` with the PC's address before running it. `pve-firewall compile` must print `compiled` and no error.

### 3. Turn the firewall on for CT 110's NIC (only if step 1 showed no `firewall=1`)

Copy the `net0` value exactly as `pct config 110` printed it and add `,firewall=1`:

```bash
pct set 110 --net0 '<the existing net0 value>,firewall=1'
```

For example, `name=eth0,bridge=vmbr0,hwaddr=<mac>,ip=<ct110-ip>/24,gw=<router-ip>,type=veth` becomes the same with
`,firewall=1` at the end. Keep the `hwaddr`, so the router sees the same device. The container's network drops for
about a second while the NIC is recreated. Do this while no AI Assist request is running.

### 4. Check

From the PC (PowerShell):

```powershell
python -m tools.ai_worker_check
```

It must not say `unreachable`. If the tunnel task reconnects slowly, wait a minute and run it again.

From the Proxmox host, which is not `<pc-ip>`, so it is refused like any other LAN device (expect `blocked`):

```bash
timeout 5 bash -c '</dev/tcp/<ct110-ip>/22' && echo "OPEN (wrong)" || echo "blocked from the host (right)"
pve-firewall status
```

Then in StableNew, open **Prompt → AI Preview…** and check that the Remote Ollama model shows ready.

### 5. Record

Add a step to `docs/runbooks/proxmox_review_gateway_setup.md` (after step 6) with the `110.fw` above (placeholders
only), the date, the `pct set` change if made, and the check results. Close finding F6 in
`docs/work_packages/DEPLOY-PROXMOX_containers.md`.

## Rollback

```bash
sed -i 's/^enable: 1/enable: 0/' /etc/pve/firewall/110.fw && pve-firewall compile >/dev/null
```

This turns CT 110's rules off and leaves the file in place. To remove them fully, delete `/etc/pve/firewall/110.fw`. The
`firewall=1` flag on the NIC can stay: with no enabled rules, it filters nothing.

## Execution class and model recommendation

Narrow, documentation only. Owner-run physical steps. Claude Code Sonnet 5.5 Medium; Codex GPT-6.1 Sol Medium.
