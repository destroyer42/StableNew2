"""Deterministic read-only fixture for GUI-PORT-742; importing this starts nothing and opens no database.

Records use the real read models (``JobHistoryEntry``, ``UnifiedJobSummary``) so both toolkits render the shared
contracts. ``fixture_matches`` applies the *semantics* of a ``HistoryQuery`` to in-memory entries so the proof never
needs a repository; ``tests/tools/test_gui_port_742.py`` checks it against a disposable ``JobRepository`` and it must
never grow beyond that bounded matcher (it is not a history engine).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from src.pipeline.job_models_v2 import JobStatusV2, UnifiedJobSummary
from src.queue.history_query import HistoryQuery
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus

FIXTURE_VERSION = "gui-port-742.v1"
BASE_TIME = datetime(2026, 10, 1, 8, 0, 0)

SUBJECTS = (
    "a red dragon over snowy hills",
    "a blue dragon above the harbor",
    "a quiet harbor at dawn",
    "snowy harbor with fishing boats",
    "a red fox in an autumn forest",
    "neon city street in the rain",
    "portrait of an astronaut",
    "misty mountain temple at sunrise",
)
LONG_TAIL = (
    " with intricate volumetric lighting, extremely detailed ornamental foreground elements and a"
    " deliberately over-long description that must never be clipped without a discoverable full text"
)
MODELS = (
    "juggernautXL_v9.safetensors",
    "cyberrealisticXL_v60.safetensors",
    "flux2-klein-4b-fp8.safetensors",
    "zImageTurbo_fp8.safetensors",
)
PACKS = (
    "pack-landscapes",
    "pack-portraits",
    "pack-city-night-with-a-very-long-identifier-for-clipping-checks",
    None,
)
_HISTORY_STATUSES = (
    JobStatus.COMPLETED,
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.COMPLETED,
    JobStatus.CANCELLED,
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.COMPLETED,
    JobStatus.RUNNING,
    JobStatus.QUEUED,
)
_FAIL_MESSAGE = (
    "WebUI returned HTTP 500: CUDA out of memory while allocating a tensor for the base sampler"
    " (requested 2.4 GiB, 1.1 GiB free). The job was marked failed and no retry was queued; the"
    " original request is preserved in the job snapshot for replay."
)

HISTORY_PREFIX = "job-"
QUEUE_PREFIX = "queue-"


def window_start(revision: int) -> int:
    """Revision 0 is the initial window; each later revision slides it by three jobs (3 removed, 3 added)."""

    return 0 if revision <= 0 else 3 * revision


def summary_text(index: int) -> str:
    subject = SUBJECTS[index % len(SUBJECTS)]
    if index % 7 == 0:
        subject += LONG_TAIL
    return f"{subject} | {MODELS[index % len(MODELS)]}"


def history_entry(index: int, revision: int = 0) -> JobHistoryEntry:
    status = _HISTORY_STATUSES[(index + revision // 2) % len(_HISTORY_STATUSES)]
    created = BASE_TIME + timedelta(minutes=index)
    done = status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
    duration_ms = 4000 + (index % 13) * 1700 if done else None
    return JobHistoryEntry(
        job_id=f"{HISTORY_PREFIX}{index:05d}",
        created_at=created,
        status=status,
        payload_summary=summary_text(index),
        started_at=created + timedelta(seconds=10) if status != JobStatus.QUEUED else None,
        completed_at=created + timedelta(milliseconds=10_000 + duration_ms) if done else None,
        error_message=_FAIL_MESSAGE if status == JobStatus.FAILED else None,
        run_mode="queue",
        prompt_source="pack",
        prompt_pack_id=PACKS[index % len(PACKS)],
        duration_ms=duration_ms,
    )


def history_entries(
    count: int = 500, revision: int = 0, drop: frozenset[str] = frozenset()
) -> tuple[JobHistoryEntry, ...]:
    """Newest first (``created_at`` descending), the order the real history query returns."""

    start = window_start(revision)
    indexes = range(start + count - 1, start - 1, -1)
    return tuple(
        entry for entry in (history_entry(i, revision) for i in indexes) if entry.job_id not in drop
    )


def queue_summary(index: int, revision: int = 0) -> UnifiedJobSummary:
    running = (index + revision) % 9 == 0
    subject = SUBJECTS[index % len(SUBJECTS)]
    return UnifiedJobSummary(
        job_id=f"{QUEUE_PREFIX}{index:05d}",
        prompt_pack_id=PACKS[index % len(PACKS)] or "",
        prompt_pack_name=(PACKS[index % len(PACKS)] or "manual").replace("pack-", ""),
        prompt_pack_row_index=index,
        positive_prompt_preview=subject,
        negative_prompt_preview=None,
        lora_preview="",
        embedding_preview="",
        base_model=MODELS[index % len(MODELS)],
        sampler_name="DPM++ 2M",
        cfg_scale=5.0,
        steps=24,
        width=1024,
        height=1024,
        stage_chain_labels=["txt2img"],
        randomization_enabled=False,
        matrix_mode=None,
        matrix_slot_values_preview="",
        variant_index=0,
        batch_index=0,
        config_variant_label="",
        config_variant_index=0,
        estimated_image_count=1,
        status=(JobStatusV2.RUNNING if running else JobStatusV2.QUEUED).value,
        created_at=BASE_TIME + timedelta(minutes=index),
        completed_at=None,
    )


def queue_summaries(count: int = 500, revision: int = 0) -> tuple[UnifiedJobSummary, ...]:
    start = window_start(revision)
    return tuple(queue_summary(i, revision) for i in range(start, start + count))


def _ascii_lower(value: str) -> str:
    # SQLite's lower() folds ASCII only; the real query folds the needle the same way.
    return "".join(char.lower() if char.isascii() else char for char in value)


def fixture_matches(query: HistoryQuery, entry: JobHistoryEntry) -> bool:
    """The semantics of ``HistoryQuery`` filters (status, pack, text terms, created range) for one entry."""

    if query.statuses and entry.status not in query.statuses:
        return False
    if query.pack_id and entry.prompt_pack_id != query.pack_id:
        return False
    if query.created_from is not None and entry.created_at < query.created_from:
        return False
    if query.created_before is not None and entry.created_at >= query.created_before:
        return False
    haystack = _ascii_lower(entry.payload_summary)
    return all(term in haystack for term in query.terms)


def filter_entries(
    query: HistoryQuery, entries: tuple[JobHistoryEntry, ...]
) -> tuple[JobHistoryEntry, ...]:
    return tuple(entry for entry in entries if fixture_matches(query, entry))


def fixture_fingerprint(count: int = 500) -> str:
    """Stable digest of every shared input; both children report it so equal inputs are provable."""

    digest = hashlib.sha256(FIXTURE_VERSION.encode())
    for revision in (0, 1, 2, 3):
        for entry in history_entries(count, revision):
            digest.update(
                json.dumps(
                    [
                        entry.job_id,
                        entry.status.value,
                        entry.created_at.isoformat(),
                        entry.payload_summary,
                        entry.error_message,
                        entry.prompt_pack_id,
                        entry.duration_ms,
                    ]
                ).encode()
            )
        for summary in queue_summaries(count, revision):
            digest.update(f"{summary.job_id}|{summary.status}|{summary.base_model}".encode())
    return digest.hexdigest()
