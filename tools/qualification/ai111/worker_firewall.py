"""Render an inert Proxmox candidate for the discovered CT 110 baseline."""

from __future__ import annotations

import argparse
import ipaddress
import json


# Compilation and review on the installed backend are separate from rendering.
# Global enablement is admissible only on the single-node baseline documented
# in the runbook. These are candidate contents, never destinations to write.
def candidate(ssh_source: str) -> dict[str, str]:
    address = ipaddress.IPv4Address(ssh_source)
    if (
        not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
    ):
        raise ValueError("expected the approved desktop's private IPv4 address")
    return {
        "cluster.fw": "[OPTIONS]\nenable: 1\npolicy_in: ACCEPT\npolicy_out: ACCEPT\n",
        "host.fw": "[OPTIONS]\nenable: 0\nnftables: 1\n",
        "110.fw": (
            "[OPTIONS]\nenable: 1\npolicy_in: DROP\npolicy_out: DROP\n"
            "dhcp: 0\nndp: 0\nradv: 0\nlog_level_out: info\n"
            f"\n[RULES]\nIN ACCEPT -source {address}/32 -p tcp -dport 22\n"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ssh_source", help="operator-verified desktop source IPv4 address")
    args = parser.parse_args()
    try:
        proposal = candidate(args.ssh_source)
    except ValueError:
        parser.error("expected the approved desktop's private IPv4 address")
    print(json.dumps(proposal, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
