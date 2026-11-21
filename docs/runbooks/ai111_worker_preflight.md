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

**Block activation pending the address and restart decision.** CT 110 uses
DHCP. The router reserves 192.168.1.22 for the guest MAC when it obtains a lease.
The candidate blocks DHCP, so a guest restart can take away the existing
IPv4 address and SSH path. Proxmox documents that guests must restart when the
backend changes. A recorded maintenance window, a console recovery path, an
approved stable address or scoped address-acquisition exception, and explicit
authorization for any affected guest restart are required. If another guest
would require changes or a restart, this candidate cannot be deployed under
the CT 110 scope. A live lease that lasts through the window does not resolve
the restart case. See the [Proxmox firewall guide](https://pve.proxmox.com/pve-docs/chapter-pve-firewall.html).

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
