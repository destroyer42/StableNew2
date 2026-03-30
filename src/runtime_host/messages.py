from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

RUNTIME_HOST_PROTOCOL_NAME = "stablenew.runtime_host"
RUNTIME_HOST_PROTOCOL_VERSION = 1
RuntimeHostMessageKind = Literal["command", "event", "snapshot", "response", "error"]


class UnsupportedRuntimeHostProtocolVersion(ValueError):
    """Raised when a runtime-host message uses an unsupported protocol version."""


def ensure_supported_protocol_version(version: int) -> int:
    """Reject unsupported protocol versions early while the transport is still local-only."""

    if int(version) != RUNTIME_HOST_PROTOCOL_VERSION:
        raise UnsupportedRuntimeHostProtocolVersion(
            f"unsupported runtime-host protocol version: {version}"
        )
    return RUNTIME_HOST_PROTOCOL_VERSION


def normalize_json_value(value: Any) -> JSONValue:
    """Normalize payloads to JSON-safe primitives for future IPC transport."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return normalize_json_value(value.value)
    if is_dataclass(value):
        return normalize_json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [normalize_json_value(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except Exception:
            pass
    return str(value)


@dataclass(frozen=True)
class RuntimeHostProtocolMessage:
    """Versioned local protocol envelope for commands, events, and snapshots."""

    kind: RuntimeHostMessageKind
    name: str
    payload: dict[str, JSONValue]
    version: int = RUNTIME_HOST_PROTOCOL_VERSION
    protocol: str = RUNTIME_HOST_PROTOCOL_NAME

    def to_dict(self) -> dict[str, JSONValue]:
        ensure_supported_protocol_version(self.version)
        return {
            "protocol": self.protocol,
            "version": self.version,
            "kind": self.kind,
            "name": self.name,
            "payload": normalize_json_value(self.payload),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeHostProtocolMessage":
        protocol = str(data.get("protocol") or "")
        if protocol != RUNTIME_HOST_PROTOCOL_NAME:
            raise ValueError(f"unsupported runtime-host protocol: {protocol}")
        version = ensure_supported_protocol_version(int(data.get("version", 0)))
        kind = str(data.get("kind") or "")
        name = str(data.get("name") or "")
        payload = data.get("payload") or {}
        if not kind or not name:
            raise ValueError("runtime-host message missing kind or name")
        if not isinstance(payload, Mapping):
            raise ValueError("runtime-host payload must be a mapping")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            name=name,
            payload={str(key): normalize_json_value(item) for key, item in payload.items()},
            version=version,
            protocol=protocol,
        )


def build_protocol_message(
    kind: RuntimeHostMessageKind,
    name: str,
    payload: Mapping[str, Any] | None = None,
) -> RuntimeHostProtocolMessage:
    return RuntimeHostProtocolMessage(
        kind=kind,
        name=name,
        payload={
            str(key): normalize_json_value(value)
            for key, value in (payload or {}).items()
        },
    )


def describe_runtime_host_protocol() -> dict[str, JSONValue]:
    return {
        "protocol": RUNTIME_HOST_PROTOCOL_NAME,
        "version": RUNTIME_HOST_PROTOCOL_VERSION,
        "transport": "local-only",
    }


__all__ = [
    "JSONValue",
    "RUNTIME_HOST_PROTOCOL_NAME",
    "RUNTIME_HOST_PROTOCOL_VERSION",
    "RuntimeHostProtocolMessage",
    "UnsupportedRuntimeHostProtocolVersion",
    "build_protocol_message",
    "describe_runtime_host_protocol",
    "ensure_supported_protocol_version",
    "normalize_json_value",
]