"""PR-LEARN-COMPARE-145: checkpoint SHA-256 evidence must survive a StableNew restart.

Each "process" below is a genuine ``python -c`` child, so nothing is shared except the persisted registry cache and the
checkpoint files. The child instruments the only places that can pay for byte identity: ``hashlib.sha256`` and
binary reads on the checkpoint path. Fixtures are tiny temporary safetensors files; no installed model is touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.assets.checkpoint_fixtures import checkpoint, tensor_checkpoint

REPO = Path(__file__).resolve().parents[2]

# Runs Model Comparison evidence readiness the way the operator's Build Preview does, in a fresh interpreter.
CHILD = textwrap.dedent(
    """
    import hashlib, json, pathlib, sys
    cache, model_paths = sys.argv[1], sys.argv[2:]

    import src.assets.registry as registry_module
    counters = {"sha256_calls": 0, "payload_bytes_read": 0}
    real_sha256 = hashlib.sha256

    def counting_sha256(*args, **kwargs):
        counters["sha256_calls"] += 1
        return real_sha256(*args, **kwargs)

    registry_module.hashlib.sha256 = counting_sha256
    targets = {str(pathlib.Path(item).resolve()) for item in model_paths}
    real_open = pathlib.Path.open

    class Counting:
        def __init__(self, stream):
            self._stream = stream

        def read(self, *args):
            data = self._stream.read(*args)
            counters["payload_bytes_read"] += len(data)
            return data

        def __getattr__(self, name):
            return getattr(self._stream, name)

        def __enter__(self):
            self._stream.__enter__()
            return self

        def __exit__(self, *exc):
            return self._stream.__exit__(*exc)

    def counting_open(self, mode="r", *args, **kwargs):
        stream = real_open(self, mode, *args, **kwargs)
        if "b" in mode and str(self.resolve()) in targets and "r" in mode:
            return Counting(stream)
        return stream

    pathlib.Path.open = counting_open

    from pathlib import Path
    from src.assets import AssetRegistry
    from src.learning.model_evidence_readiness import prepare_comparison_evidence

    registry = AssetRegistry(cache_path=cache)
    names = [Path(item).stem for item in model_paths]
    resources = [
        {"model_name": name, "title": f"{name}.safetensors [1234567890]", "filename": item}
        for name, item in zip(names, model_paths)
    ]
    evidence = prepare_comparison_evidence(names, resources, registry=registry)
    print(json.dumps({"counters": counters, "identity": evidence.model_identities}))
    """
)


def run_process(cache: Path, *models: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(REPO)!r})\n" + CHILD,
         str(cache), *map(str, models)],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def models(tmp_path: Path) -> tuple[Path, Path]:
    # Payloads far larger than the header, so "payload bytes read" is unambiguous.
    folder = tmp_path / "webui" / "models" / "Stable-diffusion"
    metadata = {"modelspec.architecture": "stable-diffusion-xl-v1-base"}
    return (
        checkpoint(folder / "alpha.safetensors", metadata=metadata, payload=b"\x07" * (3 * 1024 * 1024)),
        checkpoint(folder / "bravo.safetensors", metadata=metadata, payload=b"\x09" * (3 * 1024 * 1024)),
    )


def test_two_process_lifecycle_warm_process_does_not_hash_or_read_payload(
    tmp_path: Path, models: tuple[Path, Path]
) -> None:
    cache = tmp_path / "state" / "asset_registry_v1.json"

    first = run_process(cache, *models)
    assert first["counters"]["sha256_calls"] == 2
    assert first["counters"]["payload_bytes_read"] >= 6 * 1024 * 1024
    digests = {name: item["sha256"] for name, item in first["identity"].items()}

    second = run_process(cache, *models)
    assert {name: item["sha256"] for name, item in second["identity"].items()} == digests
    assert second["counters"]["sha256_calls"] == 0
    # Only bounded safetensors headers (a few hundred bytes each) may be read; never the 3 MiB payloads.
    assert second["counters"]["payload_bytes_read"] < 64 * 1024


def test_two_process_lifecycle_with_structure_evidence_checkpoints(tmp_path: Path) -> None:
    folder = tmp_path / "webui" / "models" / "Stable-diffusion"
    pair = (tensor_checkpoint(folder / "s1.safetensors"), tensor_checkpoint(folder / "s2.safetensors", metadata={"x": "y"}))
    cache = tmp_path / "state" / "asset_registry_v1.json"
    first = run_process(cache, *pair)
    second = run_process(cache, *pair)
    assert {n: i["sha256"] for n, i in second["identity"].items()} == {
        n: i["sha256"] for n, i in first["identity"].items()
    }
    assert second["counters"]["sha256_calls"] == 0


# --- In-process registry behaviour: each new AssetRegistry over the same cache file is a restart ----------------

import hashlib  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402

from src.assets import AssetRegistry  # noqa: E402
from src.assets.cache_diagnostics import CacheState, CheckpointMiss  # noqa: E402
from src.assets.checkpoint_structure import STRUCTURE_CONTRACT  # noqa: E402

SDXL_META = {"modelspec.architecture": "stable-diffusion-xl-v1-base"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def world(tmp_path: Path):
    folder = tmp_path / "webui" / "models" / "Stable-diffusion"
    first = checkpoint(folder / "first.safetensors", metadata=SDXL_META, payload=b"1" * 4096)
    second = checkpoint(folder / "second.safetensors", metadata=SDXL_META, payload=b"2" * 4096)
    cache = tmp_path / "state" / "asset_registry_v1.json"

    def open_registry() -> AssetRegistry:
        return AssetRegistry(tmp_path / "webui", cache_path=cache)

    return type("World", (), {"first": first, "second": second, "cache": cache, "open": staticmethod(open_registry)})


def test_cold_refresh_hashes_then_a_new_registry_instance_reuses_the_digest(world) -> None:
    cold = world.open().refresh(checkpoint_paths=[world.first])
    assert (cold.hashes_computed, cold.counters.hashes_computed) == (1, 1)
    assert cold.counters.bytes_hashed == world.first.stat().st_size
    assert cold.counters.reasons == {"no_entry": 1}

    warm = world.open().refresh(checkpoint_paths=[world.first])
    assert (warm.hashes_computed, warm.hash_cache_hits) == (0, 1)
    assert warm.counters.bytes_hashed == 0 and warm.counters.hash_seconds == 0.0
    assert warm.counters.reasons == {"current": 1}
    assert world.open().verified_sha256(world.first) == sha(world.first)


def test_size_change_requires_a_new_hash_and_says_so(world) -> None:
    world.open().refresh(checkpoint_paths=[world.first])
    checkpoint(world.first, metadata=SDXL_META, payload=b"1" * 5000)
    registry = world.open()
    status = registry.checkpoint_status(world.first)
    assert (status.reason, status.needs_hash, status.current) == (CheckpointMiss.SIZE_CHANGED, True, False)
    result = registry.refresh(checkpoint_paths=[world.first])
    assert result.counters.hashes_computed == 1 and result.counters.reasons == {"size_changed": 1}
    assert world.open().verified_sha256(world.first) == sha(world.first)


def test_modification_time_change_requires_a_new_hash(world) -> None:
    world.open().refresh(checkpoint_paths=[world.first])
    stat = world.first.stat()
    os.utime(world.first, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    registry = world.open()
    assert registry.checkpoint_status(world.first).reason is CheckpointMiss.MTIME_CHANGED
    assert registry.refresh(checkpoint_paths=[world.first]).counters.hashes_computed == 1


def test_same_size_same_mtime_replacement_is_not_detected_by_documented_design(world) -> None:
    """The cache trusts a size+mtime_ns fingerprint (PR-LEARN-142). Pin that trust model so a change is deliberate."""

    world.open().refresh(checkpoint_paths=[world.first])
    before = world.first.stat()
    original_digest = world.open().verified_sha256(world.first)
    data = bytearray(world.first.read_bytes())
    data[-1] ^= 0xFF  # same length, different bytes
    world.first.write_bytes(bytes(data))
    os.utime(world.first, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert sha(world.first) != original_digest
    registry = world.open()
    assert registry.checkpoint_status(world.first).current
    assert registry.refresh(checkpoint_paths=[world.first]).counters.hashes_computed == 0
    assert registry.verified_sha256(world.first) == original_digest


@pytest.mark.parametrize(
    ("content", "state"),
    [
        (None, CacheState.MISSING),
        ("{not json", CacheState.UNREADABLE),
        ("[1, 2, 3]", CacheState.UNREADABLE),
        (json.dumps({"version": 99, "entries": {}}), CacheState.UNSUPPORTED_VERSION),
        (json.dumps({"version": 2, "entries": ["x"]}), CacheState.UNREADABLE),
    ],
)
def test_missing_malformed_or_future_caches_rehash_safely_and_unreadable_ones_are_kept(
    world, content: str | None, state: CacheState
) -> None:
    if content is not None:
        world.cache.parent.mkdir(parents=True, exist_ok=True)
        world.cache.write_text(content, encoding="utf-8")
    registry = world.open()
    assert registry.checkpoint_status(world.first).reason is CheckpointMiss.NO_ENTRY
    assert registry.cache_state is state
    assert registry.checkpoint_status(world.first).cache_state is state
    result = registry.refresh(checkpoint_paths=[world.first])
    assert result.counters.hashes_computed == 1
    assert json.loads(world.cache.read_text(encoding="utf-8"))["version"] == 2
    backup = world.cache.with_suffix(".unreadable")
    if state in (CacheState.UNREADABLE, CacheState.UNSUPPORTED_VERSION):
        assert backup.read_text(encoding="utf-8") == content  # never silently destroyed
    else:
        assert not backup.exists()


def test_old_version_one_cache_keeps_its_digest_and_only_acquires_structure(world) -> None:
    world.open().refresh(checkpoint_paths=[world.first])
    document = json.loads(world.cache.read_text(encoding="utf-8"))
    document["version"] = 1
    for entry in document["entries"].values():
        entry.pop("structure", None)
    world.cache.write_text(json.dumps(document), encoding="utf-8")
    registry = world.open()
    assert registry.checkpoint_status(world.first).reason is CheckpointMiss.STRUCTURE_STALE
    result = registry.refresh(checkpoint_paths=[world.first])
    assert result.counters.hashes_computed == 0 and result.counters.bytes_hashed == 0
    assert result.counters.header_reads == 1 and result.counters.reasons == {"structure_stale": 1}
    assert registry.checkpoint_is_current(world.first)


def test_structure_contract_bump_refreshes_the_header_without_a_hash(world) -> None:
    world.open().refresh(checkpoint_paths=[world.first])
    document = json.loads(world.cache.read_text(encoding="utf-8"))
    for entry in document["entries"].values():
        entry["structure"]["contract"] = "checkpoint_structure/0"
    world.cache.write_text(json.dumps(document), encoding="utf-8")
    registry = world.open()
    assert registry.checkpoint_status(world.first).digest_reusable
    result = registry.refresh(checkpoint_paths=[world.first])
    assert result.counters.hashes_computed == 0
    assert json.loads(world.cache.read_text(encoding="utf-8"))["entries"][str(world.first.resolve())]["structure"][
        "contract"
    ] == STRUCTURE_CONTRACT


def test_sidecar_only_change_rereads_the_sidecar_but_never_the_checkpoint_bytes(world) -> None:
    sidecar = world.first.with_name("first.civitai.info")
    sidecar.write_text(json.dumps({"baseModel": "SDXL 1.0"}), encoding="utf-8")
    world.open().refresh(checkpoint_paths=[world.first])
    assert world.open().checkpoint_is_current(world.first)

    sidecar.write_text(json.dumps({"baseModel": "SDXL 1.0", "note": "edited"}), encoding="utf-8")
    registry = world.open()
    status = registry.checkpoint_status(world.first)
    assert (status.reason, status.needs_hash, status.digest_reusable) == (CheckpointMiss.SIDECAR_CHANGED, False, True)
    result = registry.refresh(checkpoint_paths=[world.first])
    assert result.counters.hashes_computed == 0 and result.counters.bytes_hashed == 0
    assert result.counters.sidecar_reads == 1 and result.counters.reasons == {"sidecar_changed": 1}

    sidecar.unlink()
    removed = world.open()
    assert removed.checkpoint_status(world.first).reason is CheckpointMiss.SIDECAR_CHANGED
    assert removed.refresh(checkpoint_paths=[world.first]).counters.hashes_computed == 0
    assert world.open().checkpoint_is_current(world.first)


def test_an_entry_with_an_invalid_digest_is_hashed_again(world) -> None:
    world.open().refresh(checkpoint_paths=[world.first])
    document = json.loads(world.cache.read_text(encoding="utf-8"))
    for entry in document["entries"].values():
        entry["sha256"] = "not-a-digest"
    world.cache.write_text(json.dumps(document), encoding="utf-8")
    registry = world.open()
    assert registry.checkpoint_status(world.first).reason is CheckpointMiss.DIGEST_INVALID
    assert registry.refresh(checkpoint_paths=[world.first]).counters.hashes_computed == 1
    assert registry.verified_sha256(world.first) == sha(world.first)


def test_concurrent_registry_writers_both_persist_their_checkpoint(world) -> None:
    registries = [world.open(), world.open()]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def work(registry: AssetRegistry, path: Path) -> None:
        try:
            barrier.wait(3)
            registry.refresh(checkpoint_paths=[path])
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [
        threading.Thread(target=work, args=(registries[0], world.first)),
        threading.Thread(target=work, args=(registries[1], world.second)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors
    fresh = world.open()
    assert fresh.verified_sha256(world.first) == sha(world.first)
    assert fresh.verified_sha256(world.second) == sha(world.second)
    assert json.loads(world.cache.read_text(encoding="utf-8"))["version"] == 2


def test_cancelled_hash_leaves_the_existing_cache_byte_identical_and_parseable(world) -> None:
    world.open().refresh(checkpoint_paths=[world.first])
    before = world.cache.read_bytes()
    cancel = threading.Event()
    registry = world.open()
    with pytest.raises(InterruptedError):
        registry.refresh(
            checkpoint_paths=[world.first, world.second],
            cancelled=cancel.is_set,
            progress=lambda *args: cancel.set(),
        )
    assert world.cache.read_bytes() == before
    assert json.loads(world.cache.read_text(encoding="utf-8"))["version"] == 2
    assert not world.cache.with_suffix(".tmp").exists()
    # The interrupted refresh still reports what it cost before stopping.
    assert registry.last_refresh.hashes_computed == 0 or registry.last_refresh.bytes_hashed > 0


def test_diagnostics_carry_counts_but_no_paths_names_or_digests(world) -> None:
    registry = world.open()
    result = registry.refresh(checkpoint_paths=[world.first, world.second])
    text = json.dumps(result.counters.as_dict()) + json.dumps(registry.describe_cache().as_dict())
    for secret in (str(world.first.parent), world.first.name, world.second.name, sha(world.first)):
        assert secret not in text
    description = registry.describe_cache()
    assert (description.state, description.version, description.entries) == (CacheState.OK, 2, 2)
    assert (description.checkpoint_entries, description.checkpoints_with_digest) == (2, 2)


def test_describe_cache_is_read_only_and_does_not_load_state(world) -> None:
    registry = world.open()
    missing = registry.describe_cache()
    assert missing.state is CacheState.MISSING and registry.cache_state is CacheState.UNLOADED
    assert not world.cache.exists()


def test_a_transient_read_failure_is_retried_instead_of_being_treated_as_an_empty_cache(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.open().refresh(checkpoint_paths=[world.first])
    real = Path.read_text
    failures = {"left": 2}

    def flaky(self, *args, **kwargs):
        if self == world.cache and failures["left"]:
            failures["left"] -= 1
            raise PermissionError("another process holds the cache")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    registry = world.open()
    assert registry.checkpoint_status(world.first).current
    assert registry.cache_state is CacheState.OK


def test_replace_is_retried_when_the_cache_is_briefly_held_open(world, monkeypatch: pytest.MonkeyPatch) -> None:
    real = Path.replace
    failures = {"left": 2}

    def flaky(self, target):
        if self.suffix == ".tmp" and failures["left"]:
            failures["left"] -= 1
            raise PermissionError("held open")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    world.open().refresh(checkpoint_paths=[world.first])
    assert failures["left"] == 0
    assert world.open().verified_sha256(world.first) == sha(world.first)
