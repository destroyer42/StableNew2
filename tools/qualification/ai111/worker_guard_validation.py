"""Check CT 110 guard evidence offline. Commands and privilege stay with the operator."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from tools.qualification.ai111.worker_dhcp_guard import GUEST_MAC, LINK_TABLE, TABLE, Port

SHA = re.compile(r"[0-9a-f]{64}")
TABLE_CHAINS = {
    ("bridge", TABLE): frozenset({"from_guest", "to_guest", "guest_egress", "guest_ingress"}),
    ("netdev", LINK_TABLE): frozenset({"from_guest_link"}),
}


def _without_counters(value: object) -> object:
    if isinstance(value, list):
        return [_without_counters(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"counter"}:
            counter = value["counter"]
            if (
                not isinstance(counter, dict)
                or counter.keys() != {"packets", "bytes"}
                or any(type(total) is not int or total < 0 for total in counter.values())
            ):
                raise ValueError("unexpected rule counter")
            return {"counter": None}
        return {key: _without_counters(item) for key, item in value.items()}
    return value


def fingerprint(document: object) -> str:
    """Fingerprint the combined nft -j guard tables, retaining policy and rule order."""
    if not isinstance(document, dict) or document.keys() != {"nftables"}:
        raise ValueError("missing nftables document")
    items = document["nftables"]
    if not isinstance(items, list) or not 1 <= len(items) <= 128:
        raise ValueError("unexpected nftables entry count")
    tables: set[tuple[str, str]] = set()
    chains: set[tuple[str, str, str]] = set()
    rules: set[tuple[str, str, str]] = set()
    entries = []
    for entry in items:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError("unexpected nftables entry")
        kind, data = next(iter(entry.items()))
        if not isinstance(data, dict):
            raise ValueError("unexpected nftables entry body")
        if kind == "metainfo":
            continue
        family = data.get("family")
        table = data.get("name" if kind == "table" else "table")
        if not isinstance(family, str) or not isinstance(table, str):
            raise ValueError("missing table identity")
        owner = (family, table)
        if owner not in TABLE_CHAINS:
            raise ValueError("unexpected guard table")
        if kind == "table":
            if owner in tables:
                raise ValueError("duplicate guard table")
            tables.add(owner)
        elif kind in ("chain", "rule"):
            name = data.get("name" if kind == "chain" else "chain")
            if not isinstance(name, str) or name not in TABLE_CHAINS[owner]:
                raise ValueError("unexpected guard chain")
            key = (*owner, name)
            if kind == "chain":
                if key in chains:
                    raise ValueError("duplicate guard chain")
                chains.add(key)
            else:
                if not isinstance(data.get("expr"), list) or not data["expr"]:
                    raise ValueError("missing rule expressions")
                rules.add(key)
        else:
            raise ValueError("unexpected guard object")
        entries.append({kind: _without_counters({k: v for k, v in data.items() if k != "handle"})})
    expected_chains = {(*owner, name) for owner, names in TABLE_CHAINS.items() for name in names}
    if tables != TABLE_CHAINS.keys() or chains != expected_chains or rules != expected_chains:
        raise ValueError("guard table, chain or rule coverage is incomplete")
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Observation:
    """Values from the independently reviewed host and CT interface inventory."""

    port: Port
    guest_mac: str
    host_boot_sha256: str
    ct_config_sha256: str
    link_epoch_sha256: str
    native_rules_sha256: str
    firewall_observer_epoch_sha256: str
    firewall_reload_sequence: int
    link_change_sequence: int
    observer_event_loss: int

    def valid(self) -> bool:
        return (
            isinstance(self.port, Port)
            and self.guest_mac == GUEST_MAC
            and all(
                SHA.fullmatch(value)
                for value in (
                    self.host_boot_sha256,
                    self.ct_config_sha256,
                    self.link_epoch_sha256,
                    self.native_rules_sha256,
                    self.firewall_observer_epoch_sha256,
                )
            )
            and all(
                type(value) is int and value >= 0
                for value in (self.firewall_reload_sequence, self.link_change_sequence)
            )
            and type(self.observer_event_loss) is int
            and self.observer_event_loss == 0
        )


def verified(
    reviewed_guard_sha256: str, current_rules: object, reviewed: object, current: object
) -> bool:
    """Compare a point observation against independent review. Never authorizes activation."""
    try:
        return (
            isinstance(reviewed, Observation)
            and isinstance(current, Observation)
            and reviewed.valid()
            and current.valid()
            and reviewed == current
            and fingerprint(current_rules) == reviewed_guard_sha256
        )
    except (ValueError, TypeError, RecursionError):
        return False


def rollback_stage(
    *,
    console_verified: bool,
    session_closed: bool,
    native_disabled_verified: bool,
    guard_verified: bool,
    path_quarantined: bool,
) -> str:
    """Return the next safe console step, without executing any state changes."""
    if console_verified is not True or session_closed is not True:
        return "STOP"
    if guard_verified is not True:
        if path_quarantined is not True:
            return "QUARANTINE_CT_PATH"
        return (
            "PRESERVE_QUARANTINE" if native_disabled_verified is True else "VERIFY_NATIVE_DISABLED"
        )
    if native_disabled_verified is not True:
        return "VERIFY_NATIVE_DISABLED"
    return "REMOVE_VERIFIED_GUARD"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("oversize observation")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("expected an observation object")
    return value


def _read_observation(path: Path) -> Observation:
    record = _read_json(path)
    port = record.pop("port")
    if not isinstance(port, dict):
        raise ValueError("missing port identity")
    return Observation(port=Port(**port), **record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    forms = parser.add_subparsers(dest="command", required=True)
    for name in ("fingerprint", "compare"):
        form = forms.add_parser(name)
        form.add_argument("--bridge-rules", type=Path, required=True)
        form.add_argument("--link-rules", type=Path, required=True)
    compare = forms.choices["compare"]
    compare.add_argument("--reviewed-sha256", required=True)
    compare.add_argument("--reviewed-observation", type=Path, required=True)
    compare.add_argument("--current-observation", type=Path, required=True)
    args = parser.parse_args()
    try:
        records = []
        for path in (args.bridge_rules, args.link_rules):
            document = _read_json(path)
            if document.keys() != {"nftables"} or not isinstance(document["nftables"], list):
                raise ValueError("missing nftables data")
            records.extend(document["nftables"])
        rules = {"nftables": records}
        if args.command == "fingerprint":
            print(fingerprint(rules))
            return 0
        if verified(
            args.reviewed_sha256,
            rules,
            _read_observation(args.reviewed_observation),
            _read_observation(args.current_observation),
        ):
            print("SNAPSHOT_MATCH")
            return 0
    except (OSError, KeyError, ValueError, TypeError, RecursionError):
        pass
    print("INCONCLUSIVE")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
