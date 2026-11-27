"""N1b observed-execution evidence: has this exact checkpoint completed this operation on this backend here?

The owner's rule (2026-11-25): "Experimental evidence should trump anecdotal or registry evidence. If it works, it
works." A completed job in the SQLite ``JobRepository`` for the same checkpoint, with the same operation on the same
backend, counts as verified for that operation (``src/image_backends/sdxl_target.py``).

* **Exact model.** Matched by the canonical checkpoint key (N12 ``src/utils/checkpoint_identity.py``: no directory,
  ``[hash]`` suffix, picker collision wrapper, extension or case). Where a job recorded the checkpoint's SHA-256
  (Learning Model Comparison and Prompt x Model Matrix arms do; ordinary Forge and A1111 jobs record none) and the
  registry knows the current file's SHA-256, a different hash does not count.
* **Operation** is capability level (``OPERATIONS`` in ``sdxl_target``, ControlNet per modality; owner decision Q2,
  2026-11-26), derived from the stored NJR only.
* **Bounded, read-only, off the Tk thread.** ``ObservedExecutionIndex.runs`` never touches the repository: it answers
  from a per-checkpoint cache and, on a miss or a stale entry, schedules one background read (newest jobs first,
  at most ``MAX_ROWS_EXAMINED`` rows and ``MAX_MATCHED_JOBS`` matches, on the repository's read-only connection).
  Until that read finishes it answers 0, so the operator sees the warning (the job still runs), never a delay.
* **Eligibility only.** These counts decide whether a warning is shown. They never feed ``RecommendationEngine``,
  proposals or publication (Learning invariant 5: observational evidence is manual-only).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from src.image_backends.image_backend_types import resolve_image_backend_id
from src.image_backends.sdxl_target import (
    OP_ADETAILER,
    OP_IMG2IMG,
    OP_MASKED_INPAINT,
    OP_OUTPAINT,
    OP_TXT2IMG,
    OP_TXT2IMG_EMBEDDING,
    OP_TXT2IMG_LORA,
    controlnet_operation,
)
from src.utils.checkpoint_identity import checkpoint_key, checkpoint_stem

MAX_ROWS_EXAMINED = 20_000
MAX_MATCHED_JOBS = 200
WINDOW = 2_000
#: Smaller pages for the all-checkpoint count: every snapshot in a page is held in memory at once.
COUNT_WINDOW = 500
#: Seconds a cached answer stays fresh (a job that completes meanwhile is counted on the next read).
TTL_SECONDS = 300.0


@dataclass(frozen=True)
class ObservedRun:
    """One (checkpoint, operation, backend) a completed job performed, with the SHA-256 it recorded (if any)."""

    model_key: str
    operation: str
    backend_id: str
    sha256: str | None = None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _recorded_sha(job: Mapping[str, Any]) -> str | None:
    for metadata in (
        _mapping(_mapping(job.get("workload")).get("metadata")),
        _mapping(_mapping(job.get("provenance")).get("metadata")),
    ):
        for key in ("model_comparison", "prompt_model_matrix_arm"):
            evidence = _mapping(_mapping(metadata.get(key)).get("checkpoint_evidence"))
            sha = str(evidence.get("sha256") or "").strip().lower()
            if len(sha) == 64:
                return sha
    return None


def _controlnet_modalities(config: Mapping[str, Any]) -> tuple[str, ...]:
    """The ControlNet modalities a job conditioned on (ordered units, or the legacy OpenPose slot)."""

    found: list[str] = []
    units = _mapping(config.get("controlnet_units")).get("units")
    if isinstance(units, list):
        for raw in units:
            unit = _mapping(raw)
            if unit.get("enabled", True) is not False and str(unit.get("modality") or "").strip():
                found.append(str(unit["modality"]).strip().lower())
    openpose = config.get("controlnet_openpose")
    if isinstance(openpose, Mapping) and openpose.get("enabled", True) is not False:
        found.append("openpose")
    return tuple(dict.fromkeys(found))


def runs_in_snapshot(snapshot: Mapping[str, Any]) -> tuple[ObservedRun, ...]:
    """Every (checkpoint, operation, backend) one stored NJR envelope performed (pure; empty when unreadable)."""

    job = _mapping(snapshot.get("normalized_job")) or snapshot
    workload = _mapping(job.get("workload"))
    config = _mapping(workload.get("config"))
    provenance = _mapping(job.get("provenance"))
    backend = resolve_image_backend_id(workload.get("backend_options"))
    sha = _recorded_sha(job)
    stages = [
        _mapping(stage)
        for stage in job.get("stages") or ()
        if isinstance(stage, Mapping) and stage.get("enabled", True)
    ]
    found: dict[tuple[str, str], ObservedRun] = {}

    def add(model: Any, operation: str) -> None:
        key = checkpoint_key(model)
        if key:
            found.setdefault((key, operation), ObservedRun(key, operation, backend, sha))

    base = next((stage.get("model") for stage in stages if stage.get("model")), None) or (
        _mapping(config.get("txt2img")).get("model") or config.get("model")
    )
    for stage in stages:
        kind = str(stage.get("stage_type") or "")
        model = stage.get("model") or base
        if kind == "txt2img":
            add(model, OP_TXT2IMG)
            if provenance.get("positive_embeddings") or provenance.get("negative_embeddings"):
                add(model, OP_TXT2IMG_EMBEDDING)
            if provenance.get("lora_tags"):
                add(model, OP_TXT2IMG_LORA)
            for modality in (
                *_controlnet_modalities(config),
                *_controlnet_modalities(_mapping(config.get("txt2img"))),
            ):
                add(model, controlnet_operation(modality))  # owner decision Q2: per modality
        elif kind == "img2img":
            edit = _mapping(config.get("img2img"))
            edit = _mapping(edit.get("extra")) or edit
            if "image_edit_inputs" in edit or "image_edit_inputs" in _mapping(
                config.get("img2img")
            ):
                operation = (
                    OP_OUTPAINT
                    if (
                        edit.get("edit_operation")
                        or _mapping(config.get("img2img")).get("edit_operation")
                    )
                    == "outpaint"
                    else OP_MASKED_INPAINT
                )
                add(model, operation)
            else:
                add(model, OP_IMG2IMG)
        elif kind == "adetailer":
            adetailer = _mapping(config.get("adetailer"))
            add(
                adetailer.get("adetailer_checkpoint_model")
                or adetailer.get("sd_model_checkpoint")
                or model,
                OP_ADETAILER,
            )
    return tuple(found.values())


def needle_for(model_name: str) -> str:
    """The substring every stored NJR naming this checkpoint contains (JSON ``ensure_ascii`` escaped).

    Built from the canonical checkpoint stem (N12), so a picker collision label searches for its internal file; the
    repository matches it ASCII case-insensitively, like the key itself.
    """

    return json.dumps(checkpoint_stem(model_name), ensure_ascii=True)[1:-1]


def read_run_counts(
    reader: PageReader,
    *,
    max_rows: int = MAX_ROWS_EXAMINED,
    window: int = COUNT_WINDOW,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, int]:
    """Completed txt2img jobs per checkpoint key among the newest ``max_rows`` jobs, in one pass (display only).

    One read for a whole model list, never one per model. Blocking: call it on a worker.
    """

    counts: dict[str, int] = {}
    examined = 0
    cursor: int | None = None
    while examined < max_rows:
        if cancelled():
            break
        snapshots, cursor, exhausted = reader("", cursor, window)
        examined += window
        for text in snapshots:
            try:
                snapshot = json.loads(text)
            except (TypeError, ValueError):
                continue
            if not isinstance(snapshot, Mapping):
                continue
            for run in runs_in_snapshot(snapshot):
                if run.operation == OP_TXT2IMG:
                    counts[run.model_key] = counts.get(run.model_key, 0) + 1
        if exhausted:
            break
    return counts


@dataclass
class _Entry:
    runs: tuple[ObservedRun, ...] = ()
    read_at: float = 0.0
    ready: bool = False
    #: The registry's SHA-256 of the current file when the entry was read (``None`` when unknown).
    current_sha: str | None = None


#: ``(needle, before_cursor, window) -> (snapshots, next_cursor, exhausted)``: the repository's bounded reader.
PageReader = Callable[[str, int | None, int], tuple[Iterable[str], int, bool]]


def repository_reader(repository: Any) -> PageReader:
    def read(needle: str, before: int | None, window: int) -> tuple[Iterable[str], int, bool]:
        return cast(
            "tuple[Iterable[str], int, bool]",
            repository.read_completed_snapshots_mentioning(
                needle, before_cursor=before, window=window
            ),
        )

    return read


def read_observed_runs(
    reader: PageReader,
    model_name: str,
    *,
    max_rows: int = MAX_ROWS_EXAMINED,
    max_matches: int = MAX_MATCHED_JOBS,
    window: int = WINDOW,
) -> tuple[ObservedRun, ...]:
    """Completed-job runs of ``model_name`` (newest first, bounded). Blocking: call it on a worker."""

    key = checkpoint_key(model_name)
    needle = needle_for(model_name)
    if not key or not needle:
        return ()
    runs: list[ObservedRun] = []
    matched = examined = 0
    cursor: int | None = None
    while examined < max_rows and matched < max_matches:
        snapshots, cursor, exhausted = reader(needle, cursor, window)
        examined += window
        for text in snapshots:
            try:
                snapshot = json.loads(text)
            except (TypeError, ValueError):
                continue
            if not isinstance(snapshot, Mapping):
                continue
            mine = [run for run in runs_in_snapshot(snapshot) if run.model_key == key]
            if mine:
                matched += 1
                runs.extend(mine)
                if matched >= max_matches:
                    break
        if exhausted:
            break
    return tuple(runs)


@dataclass
class ObservedExecutionIndex:
    """Per-checkpoint cache of observed runs; ``runs`` is non-blocking and safe on the Tk thread."""

    reader: PageReader
    #: Current SHA-256 of a checkpoint from the persisted registry (``None`` when unknown); never computed.
    current_sha: Callable[[str], str | None] | None = None
    #: ``spawn(target)`` runs ``target`` off the calling thread; tests pass a synchronous one.
    spawn: Callable[[Callable[[], None]], Any] | None = None
    clock: Callable[[], float] = time.monotonic
    ttl: float = TTL_SECONDS
    _entries: dict[str, _Entry] = field(default_factory=dict)
    _pending: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def runs(self, model_name: str, operation: str, backend_id: str) -> int:
        key = checkpoint_key(model_name)
        if not key:
            return 0
        with self._lock:
            entry = self._entries.get(key)
            stale = entry is None or not entry.ready or self.clock() - entry.read_at > self.ttl
            schedule = stale and key not in self._pending
            if schedule:
                self._pending.add(key)
            runs = entry.runs if entry is not None else ()
            current = entry.current_sha if entry is not None else None
        if schedule:
            self._schedule(key, str(model_name))
        return sum(
            1
            for run in runs
            if run.operation == operation
            and run.backend_id == str(backend_id or "")
            and (current is None or run.sha256 is None or run.sha256 == current)
        )

    def _current_sha(self, model_name: str) -> str | None:
        if self.current_sha is None:
            return None
        try:
            value = self.current_sha(model_name)
        except Exception:  # noqa: BLE001 - unknown hash is absent evidence
            return None
        text = str(value or "").strip().lower()
        return text if len(text) == 64 else None

    def _schedule(self, key: str, model_name: str) -> None:
        def work() -> None:
            try:
                runs = read_observed_runs(self.reader, model_name)
            except Exception:  # noqa: BLE001 - an unreadable repository is absent evidence
                runs = ()
            current = self._current_sha(model_name) if runs else None
            with self._lock:
                self._entries[key] = _Entry(runs, self.clock(), True, current)
                self._pending.discard(key)

        spawn = self.spawn or _spawn_worker
        try:
            spawn(work)
        except Exception:  # noqa: BLE001 - no worker means no evidence yet, never a block
            with self._lock:
                self._pending.discard(key)

    def forget(self, model_name: str | None = None) -> None:
        """Drop the cached answer for ``model_name`` (or every answer) so the next lookup re-reads."""

        with self._lock:
            if model_name is None:
                self._entries.clear()
            else:
                self._entries.pop(checkpoint_key(model_name), None)


def _spawn_worker(target: Callable[[], None]) -> Any:
    from src.utils.thread_registry import get_thread_registry

    # A tracked, non-daemon thread (PR-THREAD-001): the read is bounded, so shutdown can account for it.
    return get_thread_registry().spawn(
        target=target, name="ObservedExecutionLookup", purpose="N1b observed-execution lookup"
    )


# -- the process-wide index (installed where the application repository is built) ---------------------------------

_INDEX: ObservedExecutionIndex | None = None
_INDEX_LOCK = threading.Lock()


def install_observed_index(index: ObservedExecutionIndex | None) -> None:
    global _INDEX
    with _INDEX_LOCK:
        _INDEX = index


def install_for_repository(repository: Any) -> ObservedExecutionIndex | None:
    """Install the index over a file-backed application repository (an in-memory one stays hermetic)."""

    if getattr(repository, "path", None) is None or not hasattr(
        repository, "read_completed_snapshots_mentioning"
    ):
        return None
    from src.generation_profiles.identity import RegistryShaLookup

    index = ObservedExecutionIndex(repository_reader(repository), current_sha=RegistryShaLookup())
    install_observed_index(index)
    return index


_COUNTS: tuple[float, ObservedExecutionIndex, dict[str, int]] | None = None


def installed_run_counts(*, cancelled: Callable[[], bool] = lambda: False) -> dict[str, int] | None:
    """``read_run_counts`` over the application repository, cached for ``TTL_SECONDS`` (``None``: no repository).

    Blocking: call it on a worker.
    """

    global _COUNTS
    with _INDEX_LOCK:
        index, cached = _INDEX, _COUNTS
    if index is None:
        return None
    if cached is not None and cached[1] is index and index.clock() - cached[0] <= index.ttl:
        return cached[2]
    counts = read_run_counts(index.reader, cancelled=cancelled)
    if cancelled():
        raise InterruptedError("Run count cancelled")
    with _INDEX_LOCK:
        _COUNTS = (index.clock(), index, counts)
    return counts


def observed_runs_lookup() -> Callable[[str, str, str], int] | None:
    """The installed index's ``runs`` (``None`` when no repository is installed: no observed evidence)."""

    with _INDEX_LOCK:
        index = _INDEX
    return None if index is None else index.runs


__all__ = [
    "MAX_MATCHED_JOBS",
    "MAX_ROWS_EXAMINED",
    "ObservedExecutionIndex",
    "ObservedRun",
    "install_for_repository",
    "install_observed_index",
    "installed_run_counts",
    "needle_for",
    "observed_runs_lookup",
    "read_observed_runs",
    "read_run_counts",
    "repository_reader",
    "runs_in_snapshot",
]
