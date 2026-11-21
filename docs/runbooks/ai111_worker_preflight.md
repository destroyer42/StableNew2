# AI-111 remote worker preflight

This runbook covers CT 110 on `pve-g16` and the qualification-owned Ollama
runtime. The production Ollama service stays under its existing operator
ownership. The input freeze and qualification verdict remain with AI-111.

## Execution profile

Architectural. Claude Code Opus 5.5 High or Codex GPT-6 Astra High for
implementation and independent security review. Develop locally and use an
approved Proxmox console for installation-specific validation.

**Controller Surface Assessment.** The work is confined to qualification
tools, tests and the runbook. It does not touch application coordination,
provider selection, job submission or production Ollama lifecycle.

## Firewall candidate

Render the three proposed files on a development machine.

```powershell
python -m tools.qualification.ai111.worker_firewall 192.168.1.182
```

The address is the desktop source recorded in the operator transcript. Verify
the address for the approved session. The output is a JSON representation of
candidate file contents. Review it with the installed Proxmox version before
putting any candidate into pmxcfs, which may cause immediate rule changes.

The discovered baseline has no cluster, node or CT 110 firewall file, no loaded
nftables tables, legacy enforcement disabled and CT 110's active interface
flagged for firewalling. Datacenter enablement and backend selection are
global/node-level prerequisites. The candidate opts out of host rules and gives
datacenter host policy ACCEPT in both directions. The proposed guest policy
defaults to DROP and allows IPv4 SSH from the single approved desktop.
No guest outbound rule is added. Loopback remains inside the guest.

### Approved DHCP scope

The owner approved a scoped DHCP exception on 2026-11-21 to preserve the
router reservation for CT 110 at 192.168.1.22. Apply it only to the guest
interface associated with that reservation. The scope is IPv4 DHCP client
traffic from UDP 68 to 67, including the local limited broadcast needed for
address acquisition and rebinding and unicast renewal to the identified
router DHCP server. Permit replies from that server from UDP 67 to 68 to
the reserved address or the local limited broadcast. Verify the interface,
reservation MAC and DHCP server identity before constructing any candidate
that enables the exception. DHCPv6 and broader UDP destinations are outside
the approval.

### Supplemental CT 110 filter

The owner authorized design, implementation and validation preparation for
the supplemental host filter on 2026-11-21. The draft keeps `dhcp: 0`.
The upstream native guest option runs before custom guest rules and its
allowance includes DHCPv6. Activate native DHCP only after independent
verification of the supplemental filter and a separate activation decision.
[Upstream guest rule order](https://github.com/proxmox/proxmox-firewall/blob/master/proxmox-firewall/src/firewall.rs#L328)
[Upstream DHCP chains](https://github.com/proxmox/proxmox-firewall/blob/master/proxmox-firewall/resources/proxmox-firewall.nft#L300)

Render with the measured inputs, then retain the exact bytes and SHA-256 for
review. The tool prints a two-table nftables candidate and performs no writes
to the host.

```powershell
python -m tools.qualification.ai111.worker_dhcp_guard --port veth110i0 --ifindex <observed-index> --bridge <observed-linux-bridge> --server-ipv4 <verified-server-ip> --server-mac <verified-server-mac> --ssh-ipv4 <approved-desktop-ip>
```

The supported topology is CT 110's sole `net0` attached directly to a
Linux bridge, with guest MAC `bc:24:11:41:59:b1`. Reconcile the installed
CT config, guest peer ifindex, host ifindex and bridge master. Verify the
DHCP server IP and MAC from the approved lease and network authority.
The renderer restricts local broadcast and server unicast DHCPv4, permits
SSH only for the approved desktop, and permits ARP needed for address
ownership checks and those neighbors. IP and MAC matching presumes trusted
LAN source identities. If the segment permits source impersonation, show
the applicable anti-spoofing control before accepting server identity.

The netdev ingress chain on the host veth screens guest-originated Ethernet
before the bridge can consume link-local frames. The bridge prerouting and
postrouting chains add direction-specific DHCP, ARP and conntrack policy.
The indexed and named bridge selectors detect a change to either identifier
alone. Unrelated bridge ports use the existing chains. Confirm native
untagged veth traffic, bridge conntrack availability and actual hook ordering
against the installed versions. The candidate deliberately refuses alternate
ports and topologies.
[Linux bridge receive path](https://github.com/torvalds/linux/blob/master/net/bridge/br_input.c)
[Bridge conntrack](https://github.com/torvalds/linux/blob/master/net/bridge/netfilter/nf_conntrack_bridge.c)
[Proxmox guest hooks](https://github.com/proxmox/proxmox-firewall/blob/master/proxmox-firewall/resources/proxmox-firewall.nft#L353)

**Activation interlock.** Establish an independent, console-recoverable
CT-only fence that keeps the path closed when either guard table is absent,
when the veth is replaced, and during firewall or topology transitions.
Prevent simultaneous name/index replacement and second-port attachment
from creating an unguarded path. The renderer does not implement that fence.
A poll or a reload-event alarm cannot stop the first packet during a gap.
The point evidence verifier rejects missing/altered tables, boot or interface
drift, native policy drift, event loss and observed reloads. It supplies no
packet-level interlock.

Before presenting an activation decision, reproduce the exact installed
Proxmox, nftables and kernel versions in an isolated Linux bridge lab. Run
`nft --check --file <reviewed-batch>`, review the compiled native rules
beside both supplemental tables, and rehearse the console sequence there.
Compare the rule-preserving JSON fingerprint from both named table listings
and independently verify the topology and observer epochs. Run
`python -m tools.qualification.ai111.worker_guard_validation fingerprint`
with `--bridge-rules` and `--link-rules` pointing to the separate named
table JSON exports. Use the `compare` subcommand with those two current
exports, `--reviewed-sha256`, `--reviewed-observation` and
`--current-observation`. A snapshot match alone cannot authorize a
transition. Review distinct
approved native-state identities for the DHCP-disabled and enabled stages.
The progress sequence for a later approved activation is to keep native
DHCP disabled and the CT path fenced, install and verify both guard tables,
then verify the independently compiled native allowance before exposing the
path. On any uncertainty keep the CT path fenced and native DHCP disabled.
Neither this runbook nor the evidence checker authorizes a state change.

Proxmox documents a guest restart when switching firewall backends. Record
a maintenance window and console recovery path and obtain separate restart
authorization. If another guest requires a change or restart, stop under
the CT 110 scope. Verify a fresh lease and its renewal, continued SSH
forwarding and denial of DHCPv6 and traffic outside the approved DHCPv4
scope before accepting the policy. A currently valid lease is insufficient.
[Proxmox firewall guide](https://pve.proxmox.com/pve-docs/chapter-pve-firewall.html)

Before an activation decision, use a disposable matching Proxmox environment
or an approved offline copy of the installed compiler and its configuration.
Inspect both the native compiler output and its skeleton. Confirm the node and
host/other guest hook behavior, CT maps and all interface coverage. Verify the
effective default chains, including established and related traffic, ARP, IPv6
discovery, and ICMP error classes. The upstream skeleton has control-protocol
exceptions ahead of guest dispatch. Any installed exception outside the
approved policy must be resolved before activation. Time-bounded, loss-accounted
reconciliation must account for conntrack state already present at activation.
Rule text and a quiet firewall log are insufficient.

### Console recovery plan

Before any authorized activation, use the host console and an operator-owned
evidence location:

1. Record whether each of these paths exists:
   `/etc/pve/firewall/cluster.fw`, `/etc/pve/nodes/pve-g16/host.fw`, and
   `/etc/pve/firewall/110.fw`. Save any
   existing bytes and permissions, the CT network configuration, the backend
   setting and the loaded rule sets. Hash retained artifacts. The proposed
   files assume the recorded absent baseline. Stop if any path has appeared
   or if host/guest scope differs.
2. Review and record a console-only reversal for the exact accepted change
   set. For the absent baseline, it removes only the CT 110, node and cluster
   files created in this operation, in that order. Verify the recorded
   candidate identity before removing each file. If a file changed
   independently, stop and reconcile it from the console. Do not flush
   unrelated rule sets or conntrack state. Include any approved address or
   backend-restart reversal in the same scoped plan.
3. Rehearse recovery before collecting readiness evidence. Verify the
   pre-change configuration and effective policy, the guest address, Proxmox
   administration, guest SSH, and the desktop forward. Record failures and
   stop. Perform restoration only after closing any active evidence session
   and stopping qualification admissions. A change in the effective policy
   invalidates readiness for the current worker until evidence is re-established.

For a later separately authorized network test, confirm a loaded and effective
policy, working loopback and SSH, and explicit denial of the approved IPv4,
IPv6, UDP/DNS and other outbound test classes. Bind each result to the actual
CT interface and observation window. Require loss-accounted event capture and
independent accounting through that window. Treat unexplained loss, rule drift,
attribution gaps or monitor failure as invalidating the evidence. The renderer
and snapshot collector do not provide this observation.

For the supplemental filter, close admission and end any evidence session.
Use the verified host console. With both guards still enforcing, restore
native `dhcp: 0` and independently confirm effective denial of both DHCP
families before removing either guard. If a guard or its interface identity
is missing, quarantine the CT path first and keep it closed until the state
is reconciled. Delete only the reviewed `bridge stablenew_ai111_ct110`
and `netdev stablenew_ai111_ct110_link` tables in one nft transaction after
confirming both identities. Recheck the original firewall baseline, CT
address, administrative path, SSH forward and Ollama availability. A
rollback decision-table fixture exercises this order; the console rehearsal
on the matching Proxmox version remains a prerequisite.

## Owned runtime and privacy

Prepare a fresh transient unit per request, with an exclusive loopback
listener, a verified staging copy of the exact executable, linked runner and
models, and a namespace unavailable to production clients. Record systemd's
unit invocation and control group, the boot fingerprint and exact runtime/model
identities. Keep the runtime and runners unprivileged and prohibit cgroup
delegation or migration. Confirm these properties on the installed LXC before
admitting anything. The client must have one controlled admission path and
must not retry an ambiguous dispatch.

The Linux cgroup reader pins the directory across observations, binds its
identity to boot and invocation, and reads recursive population. The controller
must observe the unit populated, record the request's terminal outcome, stop
the same owned unit and capture zero recursive population before admitting
anything else. For an invalid request, terminal means a demonstrated rejection
by the owned instance. An HTTP response, zero loaded models or a client
disconnect alone cannot close a lifecycle. A missing cgroup before an observed
empty transition, an unbound systemd invocation, or inability to demonstrate
isolation leaves the result inconclusive. Do not restart production Ollama to
collect this evidence.

Review Ollama v0.40.16 at
[commit d63b702](https://github.com/ollama/ollama/commit/d63b702609c4300a2ca07be2bdb0adb9834725e5).
The request replay middleware can retain bodies in a temporary directory when
`OLLAMA_DEBUG_LOG_REQUESTS` is enabled. Inspect the actual enabled normal and
error paths including access logs, validation, load failure, timeout,
cancellation, runner output and crash handling. The historical journal and
syslog searches support the baseline. Review the effective systemd, journald,
rsyslog and rotation configuration again for the live window. Cover any
shipping destinations, replay and scratch directories, crash/core storage,
client history and desktop tunnel diagnostics.

For each separately authorized lifecycle canary, use a unique non-sensitive
marker and check independently detectable content from both directions. Feed
each complete logical sink stream to the privacy scanner and retain only
marker digests, coverage, counts, collection/retention status and observer
identities. An unreadable or partially retained sink is incomplete. A known
content retention path or observed match holds the arm. Do not put marker
text, raw log lines, response text, credentials or model bytes in the evidence
bundle.

## Evidence and validation

Score one model arm at a time. Keep the fixed artifacts in an ignored,
operator-owned run directory. Use `identity.json`, `egress.json`,
`privacy.json`, `quiescence.json` and `provenance.json`. The
`manifest.sha256` contains sorted SHA-256 lines for those five names with two
spaces before each filename. Each observation record is tied to the canonical
JSON digest of identity. The activation window and lifecycle timestamps share
one monotonic clock. The scorer accepts a manifest pin and current bindings
separately and emits a content-free report. Those inputs and observation
references require independent corroboration.

```text
python -m tools.qualification.ai111.worker_preflight <run-dir> --accepted-manifest-sha256 <pin> --current-bindings <identity-file>
```

The offline implementation reports integrity errors, explicit failures and
missing evidence. Until physical collectors are reviewed and integrated, an
otherwise complete aggregate is still INCONCLUSIVE. In particular, the
qualification controller that binds real systemd invocations to continuous
request evidence, loss-accounted network source, and independently accepted
provenance and privacy records remain pending. The scorer never grants
execution authorization.

Verify publisher/build provenance for the executable and linked libraries.
For each arm verify immutable publisher revision, selected manifest and
layer digests, license text identity and explicit acceptance. Preserve
the already verified selected LFM3 child and historical snapshot as distinct
evidence. Any privacy, provenance or identity gap holds the affected arm.

Token-efficient validation starts with deterministic firewall rendering,
evidence validation, cgroup replacement and privacy scanner fixtures. Run one
independent security review and bounded repair, then the required local gate.
Use exact-SHA CI after authorized publication. Live deployment, external
probes and inference each need their corresponding authorization. This
package does not execute the pilot or the full campaign.
