"""Render a CT 110 bridge filter for review. This tool never accesses nftables."""

from __future__ import annotations

import argparse
import ipaddress
import re
from dataclasses import dataclass

TABLE = "stablenew_ai111_ct110"
LINK_TABLE = "stablenew_ai111_ct110_link"
RESERVED = ipaddress.IPv4Address("192.168.1.22")
GUEST_MAC = "bc:24:11:41:59:b1"
BROADCAST = "255.255.255.255"
LAN = ipaddress.IPv4Network("192.168.1.0/24")
IFNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", re.ASCII)
MAC = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", re.ASCII)


@dataclass(frozen=True)
class Port:
    """Operator-verified host-side Linux bridge member for the reserved guest NIC."""

    name: str
    index: int
    bridge: str

    def __post_init__(self) -> None:
        if (
            self.name != "veth110i0"
            or not IFNAME.fullmatch(self.bridge)
            or self.name == self.bridge
            or type(self.index) is not int
            or not 1 <= self.index <= 2**31 - 1
        ):
            raise ValueError("invalid bridge member or interface index")


def _host_ipv4(value: str) -> ipaddress.IPv4Address:
    address = ipaddress.IPv4Address(value)
    if address not in LAN or address in (LAN.network_address, LAN.broadcast_address, RESERVED):
        raise ValueError("expected a distinct on-link DHCP server or SSH client address")
    return address


def render(port: Port, *, server_ipv4: str, server_mac: str, ssh_ipv4: str) -> str:
    """Use a deny-by-default subchain for each direction of the verified port."""
    server = _host_ipv4(server_ipv4)
    desktop = _host_ipv4(ssh_ipv4)
    if server == desktop:
        raise ValueError("DHCP server and SSH client must have distinct identities")
    server_mac = server_mac.lower()
    if (
        not MAC.fullmatch(server_mac)
        or int(server_mac[:2], 16) & 1
        or server_mac in ("00:00:00:00:00:00", GUEST_MAC)
    ):
        raise ValueError("expected the verified DHCP server's unicast MAC")

    return f"""table bridge {TABLE} {{
    chain from_guest {{
        type filter hook prerouting priority -150; policy accept;
        meta iif {port.index} jump guest_egress
        meta iifname "{port.name}" jump guest_egress
    }}
    chain to_guest {{
        type filter hook postrouting priority -150; policy accept;
        meta oif {port.index} jump guest_ingress
        meta oifname "{port.name}" jump guest_ingress
    }}
    chain guest_egress {{
        meta iif != {port.index} counter drop
        meta iifname != "{port.name}" counter drop
        meta ibrname != "{port.bridge}" counter drop
        ether saddr != {GUEST_MAC} counter drop

        ether daddr ff:ff:ff:ff:ff:ff ip saddr {{ 0.0.0.0, {RESERVED} }} ip daddr {BROADCAST} udp sport 68 udp dport 67 counter accept
        ether daddr {server_mac} ip saddr {RESERVED} ip daddr {server} udp sport 68 udp dport 67 counter accept
        ip saddr {RESERVED} ip daddr {desktop} tcp sport 22 ct state established ct direction reply counter accept
        ether type arp arp saddr ether {GUEST_MAC} arp operation request arp saddr ip {{ 0.0.0.0, {RESERVED} }} arp daddr ip {RESERVED} counter accept
        ether type arp arp saddr ether {GUEST_MAC} arp operation {{ request, reply }} arp saddr ip {RESERVED} arp daddr ip {{ {server}, {desktop} }} counter accept
        counter drop
    }}
    chain guest_ingress {{
        meta oif != {port.index} counter drop
        meta oifname != "{port.name}" counter drop
        meta obrname != "{port.bridge}" counter drop
        ether saddr {server_mac} ether daddr {GUEST_MAC} ip saddr {server} ip daddr {RESERVED} udp sport 67 udp dport 68 counter accept
        ether saddr {server_mac} ether daddr ff:ff:ff:ff:ff:ff ip saddr {server} ip daddr {BROADCAST} udp sport 67 udp dport 68 counter accept
        ether daddr {GUEST_MAC} ip saddr {desktop} ip daddr {RESERVED} tcp dport 22 ct direction original ct state {{ new, established }} counter accept
        ether type arp arp operation {{ request, reply }} arp saddr ip {{ {server}, {desktop} }} arp daddr ip {RESERVED} counter accept
        counter drop
    }}
}}

table netdev {LINK_TABLE} {{
    chain from_guest_link {{
        type filter hook ingress device "{port.name}" priority -500; policy drop;
        meta iif != {port.index} counter drop
        ether saddr != {GUEST_MAC} counter drop
        ether daddr & ff:ff:ff:ff:ff:f0 == 01:80:c2:00:00:00 counter drop
        ether type {{ ip, arp }} counter accept
        counter drop
    }}
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--ifindex", required=True, type=int)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--server-ipv4", required=True)
    parser.add_argument("--server-mac", required=True)
    parser.add_argument("--ssh-ipv4", required=True)
    args = parser.parse_args()
    try:
        candidate = render(
            Port(args.port, args.ifindex, args.bridge),
            server_ipv4=args.server_ipv4,
            server_mac=args.server_mac,
            ssh_ipv4=args.ssh_ipv4,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(candidate, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
