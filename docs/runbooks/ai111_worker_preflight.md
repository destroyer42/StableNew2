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

### Static baseline and containment scope

The operator verified the static conversion on 2026-11-21. CT 110 has
`192.168.1.22/24` with permanent lifetime, gateway `192.168.1.1`, and no
reported IPv6 default route. Windows reached guest SSH and the persistent
forward at `127.0.0.1:11435`. Ollama 0.40.16 was active and both models
were listed through the tunnel. This is connectivity evidence from before
containment activation.

```text
net0: name=eth0,bridge=vmbr0,firewall=1,gw=192.168.1.1,hwaddr=BC:24:11:41:59:B1,ip=192.168.1.22/24,type=veth
```

The static design keeps native `dhcp: 0` for DHCPv4 and DHCPv6. The
supplemental DHCP guard is retired. Its reviewed implementation and tests
remain in Git at `99fdab51ffe6cd5c75c745cdea2851bca26bec29`.

The native guest candidate applies DROP in both directions, uses MAC and IP
filtering, disables DHCP, NDP, and router advertisements, and explicitly
allows TCP/22 only from the approved on-link desktop to the static guest
address on `net0`. Established SSH responses rely on the installed
conntrack path. The worker API remains on guest loopback. The host opts out
of host firewall rules and retains ACCEPT defaults at datacenter scope.
Verify from the compiled output that enabling the backend leaves all
unrelated guests and global rules unaffected.

**Native-policy blocker.** Upstream Proxmox evaluates ICMP error
acceptance before guest dispatch. Its guest defaults can also accept
established and related traffic before custom rules. Check the exact
installed compiler and skeleton before presenting activation. Any
outbound exception outside the approved SSH return and necessary local
Ethernet address resolution must be resolved. The absence of an IPv6 default
route does not prove IPv6 denial. A guest DROP default cannot prove that a
packet reached the guest chain. Verify worker-to-host and link-local paths
as well as routed IP. The upstream guest compiler permits outgoing ARP
before custom rules.
[Upstream Proxmox guest hooks](https://github.com/proxmox/proxmox-firewall/blob/master/proxmox-firewall/resources/proxmox-firewall.nft#L337)
[Guest options and ARP](https://github.com/proxmox/proxmox-firewall/blob/master/proxmox-firewall/src/firewall.rs#L646-L713)

### Console activation proposal and rollback

This proposal is for separate authorization. Use the rendered file contents
as a proposed change set, with the exact installed backend package and
kernel reproduced in an isolated environment for compile, packet-path, and
rollback review. Review the Proxmox skeleton and generated JSON together.
Confirm all physical CT interfaces are covered, SSH reply attribution and
unapproved conntrack state are resolved, the installed options are valid,
and no other guests or host paths acquire new policy. Proxmox documents a
guest restart for the backend switch. Stop if that requires changing any
guest outside CT 110.
[Proxmox firewall guide](https://pve.proxmox.com/pve-docs/chapter-pve-firewall.html)

1. From the verified host console, close qualification admission and any
   evidence window. Record exact before-state bytes and hashes or verified
   absence for `/etc/pve/firewall/cluster.fw`,
   `/etc/pve/nodes/pve-g16/host.fw`, `/etc/pve/firewall/110.fw`, and
   CT 110's configuration. Record the active ruleset, affected net0
   identity, and controller/observer epochs. The absence baseline must
   match the earlier discovery. Stop for drift or unexpected scope.
2. In the separately approved maintenance window, use the CT-specific
   `net0 link_down=1` transition, preserving the rest of the static
   definition byte-for-byte where supported. Rehearse the installed
   operation and prove the path is disconnected even across any required
   CT restart. Observe the host veth down and detached from the bridge.
   Verify the Proxmox management console remains available.
   Keep the link disconnected if that proof is unavailable.
   [CT network options](https://github.com/proxmox/pve-docs/blob/master/generated/pct.conf.5-opts.adoc)
3. With the CT path disconnected, stage the reviewed guest file and node
   file. Apply the datacenter enablement last, only after review of its
   broader effects. If a restart was separately approved, retain the
   link-down fence across it. Verify exact loaded chains, CT interface
   mapping, observation health, and backend identity. Rehearse that reconnect
   cannot attach the port before its policy is established. Present a separate
   decision to lift the fence for the approved physical validation.
4. On any failure, keep the link disconnected. From the console, restore
   only the reviewed changes to the three firewall paths and the backend
   state while the link stays down. Check the candidate hash before
   replacing or removing a file. Preserve unrelated rules and conntrack
   state. Reestablish the static net0 bytes with the link still down, then
   verify the restored state. Reopening the ordinary network path after
   rolling back to an unenforced baseline is a separate explicit recovery
   decision. A stopped or unknown observer never authorizes reopening.
5. After a separately approved reconnect, check guest loopback Ollama,
   Proxmox management, desktop SSH, and the existing forwarded listener.
   Perform authorized negative canaries for IPv4 and IPv6 TCP, UDP/DNS,
   DHCPv4 and DHCPv6, ICMP and other applicable unapproved protocols and
   LAN paths. Correlate every result to the actual CT port, backend
   counters and loss-accounted observations. Rule drift, loss, or
   attribution gaps invalidate evidence. A successful rollback returns the
   worker to its pre-change state and invalidates current-policy readiness.

The decision-table fixture covers disconnect-before-mutation and
no-automatic-reconnect. The matching-version console rehearsal and installed
rule and packet-path tests remain prerequisites. No activation or worker
probe is performed by the renderer.

## Owned runtime and privacy

Prepare a fresh transient unit per request, with an exclusive loopback
listener, a verified staging copy of the exact executable, linked runner and
models, and a namespace unavailable to production clients. Record systemd's
unit invocation and control group, the boot fingerprint and exact runtime/model
identities. Keep the runtime and runners unprivileged and prohibit cgroup
delegation or migration. Confirm these properties on the installed LXC before
admitting anything. The client must have one controlled admission path and
must not retry an ambiguous dispatch.

The recorder enforces one active request at a time and checks the current
systemd invocation around each recursive population read. A wrong terminal
outcome or observer error stops further admissions. The Linux cgroup reader
pins the directory across observations, binds its
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

The static design uses the version 2 bundle schema. Egress checks bind the
static address and require DHCP denial, resolution of pre-guest exceptions,
and SSH-only established-flow evidence. Quiescence events carry the closed
terminal outcome for each authorized lifecycle category. Privacy evidence
records source revision, before/after logging identity, request and response
marker coverage tied to each recorded request identity, and per-sink
content-free scans. Provenance evidence binds
publisher proof, exact executable and linked runtime, selected manifest and
layers, and an explicit license decision. The historical collector snapshot
and logging checks remain reusable evidence of their original scope.

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
