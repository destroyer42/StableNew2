"""Current-user persistence for the loopback browser's remembered approval."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.app.site_phone_credentials import IDENTIFIER, PhoneFolder, _dpapi
from src.utils.atomic_io import atomic_write_bytes

PROOF = re.compile(r"[a-f0-9]{64}")
MAX_WITNESSES = 8


@dataclass(frozen=True)
class ReceiptWitness:
    receipt_id: str
    preview_id: str
    job_ids: tuple[str, ...]


@dataclass(frozen=True)
class DesktopApproval:
    id: str
    proof_digest: str = field(repr=False)
    deadline_ms: int
    witnesses: tuple[ReceiptWitness, ...] = ()


@dataclass(frozen=True)
class DesktopPreference:
    enabled: bool = True
    approval: DesktopApproval | None = None
    output_mode: str = "configured"
    output_folder: PhoneFolder | None = None


class DesktopApprovalStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        if self._path is not None:
            return self._path
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if not local.is_absolute():
            raise OSError("Windows local application data is unavailable")
        return local / "StableNew" / "operator-desktop.dpapi"

    def load(self) -> DesktopPreference:
        try:
            with self.path.open("rb") as source:
                encrypted = source.read(131073)
        except FileNotFoundError:
            return DesktopPreference()
        if len(encrypted) > 131072:
            raise ValueError("Invalid desktop connection preference")
        try:
            value = json.loads(_dpapi(encrypted, decrypt=True))
            if (
                not isinstance(value, dict)
                or set(value) - {"enabled", "approval", "output_mode", "output_folder"}
                or type(value["enabled"]) is not bool
            ):
                raise ValueError
            raw_approval = value["approval"]
            approval = None
            if raw_approval is not None:
                witnesses = tuple(
                    ReceiptWitness(row["receipt_id"], row["preview_id"], tuple(row["job_ids"]))
                    for row in raw_approval.pop("witnesses", ())
                )
                if len(witnesses) > MAX_WITNESSES or any(
                    not IDENTIFIER.fullmatch(row.receipt_id)
                    or not IDENTIFIER.fullmatch(row.preview_id)
                    or not 0 < len(row.job_ids) <= 250
                    or not all(IDENTIFIER.fullmatch(job) for job in row.job_ids)
                    for row in witnesses
                ):
                    raise ValueError
                approval = DesktopApproval(**raw_approval, witnesses=witnesses)
            if approval is not None and (
                not value["enabled"]
                or not IDENTIFIER.fullmatch(approval.id)
                or not PROOF.fullmatch(approval.proof_digest)
                or type(approval.deadline_ms) is not int
                or approval.deadline_ms < 0
            ):
                raise ValueError
            mode, raw_folder = value.get("output_mode", "configured"), value.get("output_folder")
            folder = PhoneFolder(**raw_folder) if raw_folder is not None else None
            if (
                mode not in {"configured", "private", "specific"}
                or (
                    mode == "specific"
                    and (
                        folder is None
                        or not Path(folder.path).is_absolute()
                        or type(folder.device) is not int
                        or type(folder.inode) is not int
                        or folder.inode <= 0
                    )
                )
                or (mode != "specific" and folder is not None)
            ):
                raise ValueError
        except (AttributeError, TypeError, ValueError, KeyError) as error:
            raise ValueError("Invalid desktop connection preference") from error
        return DesktopPreference(value["enabled"], approval, mode, folder)

    def save(self, preference: DesktopPreference) -> None:
        payload = json.dumps(asdict(preference), ensure_ascii=True).encode()
        atomic_write_bytes(self.path, _dpapi(payload, decrypt=False))
