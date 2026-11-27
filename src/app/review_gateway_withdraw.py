"""Take eval clips that were already published out of the phone's Review inbox (RG-170).

New eval outputs are never published (``review_gateway_sources.py``). This looks through the publish ledger for ones
sent before that rule and asks the gateway to withdraw them. No decision, evidence or file changes on the PC. Each
leaves the list once the gateway has withdrawn it, so a finished ledger costs no further calls. Blocking work for the
sync worker thread, never Tk.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_protocol import utc_now, utc_text
from src.app.review_gateway_sources import SourceFilter
from src.app.review_gateway_store import SyncLedger

log = logging.getLogger(__name__)

FEATURE = "item_withdrawal"
#: An item the gateway could not withdraw yet (a decision or an Immich upload is owed) is asked again this much later.
INTERVAL_SECONDS = 600.0
WITHDRAWN = "withdrawn"


class EvalWithdrawal:
    def __init__(
        self, ledger: SyncLedger, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._ledger = ledger
        self._monotonic = monotonic
        self._next = 0.0

    def step(self, client: GatewayClient, output_root: Path, cancel: Event) -> None:
        if FEATURE not in client.features or self._monotonic() < self._next:
            return
        sources = SourceFilter(output_root)
        removed = 0
        for row in self._ledger.published_items():
            if cancel.is_set():
                return
            if not sources.is_eval_output(str(row["rel_path"])):
                continue
            if client.withdraw_item(str(row["library_id"]), str(row["sha256"])) == "kept":
                continue
            self._ledger.mark_published(
                str(row["library_id"]),
                str(row["version"]),
                str(row["rel_path"]),
                str(row["sha256"]),
                str(row["kind"]),
                WITHDRAWN,
                utc_text(utc_now()),
            )
            removed += 1
        self._next = self._monotonic() + INTERVAL_SECONDS
        if removed:
            log.info("Withdrew %d eval item(s) from the phone review inbox", removed)
