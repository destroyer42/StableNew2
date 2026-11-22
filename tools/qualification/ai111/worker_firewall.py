"""Render an inert Proxmox candidate for the discovered CT 110 baseline."""

from __future__ import annotations

import argparse
import ipaddress
import json

STATIC_IPV4 = ipaddress.IPv4Interface("192.168.1.22/24")
GATEWAY = ipaddress.IPv4Address("192.168.1.1")
STATIC_NET0 = (
    "name=eth0,bridge=vmbr0,firewall=1,gw=192.168.1.1,"
    "hwaddr=BC:24:11:41:59:B1,ip=192.168.1.22/24,type=veth"
)


# Compilation and review on the installed backend are separate from rendering.
# Global enablement is admissible only on the single-node baseline documented
# in the runbook. These are candidate contents, never destinations to write.
def candidate(ssh_source: str) -> dict[str, str]:
    address = ipaddress.IPv4Address(ssh_source)
    if (
        address not in STATIC_IPV4.network
        or address in (STATIC_IPV4.network.network_address, STATIC_IPV4.network.broadcast_address)
        or address in (STATIC_IPV4.ip, GATEWAY)
    ):
        raise ValueError("expected the approved desktop's on-link IPv4 address")
    return {
        "cluster.fw": "[OPTIONS]\nenable: 1\npolicy_in: ACCEPT\npolicy_out: ACCEPT\n",
        "host.fw": "[OPTIONS]\nenable: 0\nnftables: 1\n",
        "110.fw": (
            "[OPTIONS]\nenable: 1\npolicy_in: DROP\npolicy_out: DROP\n"
            "dhcp: 0\nndp: 0\nradv: 0\nmacfilter: 1\nipfilter: 1\nlog_level_out: info\n"
            f"\n[RULES]\nIN ACCEPT -i net0 -source {address}/32 -dest {STATIC_IPV4.ip}/32 -p tcp -dport 22\n"
        ),
    }


def console_step(
    *,
    net0: str,
    rollback: bool,
    console_verified: bool,
    admission_closed: bool,
    path_disconnected: bool,
    exact_files_verified: bool,
    effective_policy_verified: bool,
) -> str:
    """Advisory sequence for an already authorized window. It executes no commands."""
    if not isinstance(net0, str):
        return "STOP"
    fields = [
        f"hwaddr={field[7:].upper()}" if field.startswith("hwaddr=") else field
        for field in net0.split(",")
    ]
    actual = set(fields)
    baseline = set(STATIC_NET0.split(","))
    fenced = {*baseline, "link_down=1"}
    if len(fields) != len(actual) or actual not in (baseline, fenced):
        return "STOP"
    if type(rollback) is not bool or console_verified is not True or admission_closed is not True:
        return "STOP"
    if path_disconnected is not True:
        return "DISCONNECT_CT_NET0"
    if actual != fenced or exact_files_verified is not True:
        return "STOP"
    if rollback is True:
        return "RESTORE_BASELINE_WHILE_DISCONNECTED"
    if effective_policy_verified is not True:
        return "KEEP_DISCONNECTED"
    return "PRESENT_SEPARATE_RECONNECT_DECISION"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ssh_source", help="operator-verified desktop source IPv4 address")
    args = parser.parse_args()
    try:
        proposal = candidate(args.ssh_source)
    except ValueError:
        parser.error("expected the approved desktop's on-link IPv4 address")
    print(json.dumps(proposal, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
