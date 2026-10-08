"""Exact checkpoint refresh and overlapping registry writer transactions."""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.assets import AssetKind, AssetRegistry
from src.learning.model_evidence_readiness import prepare_comparison_evidence
from tests.assets.checkpoint_fixtures import checkpoint


@pytest.fixture
def local(tmp_path):
    root = tmp_path / "webui"
    cache = tmp_path / "cache.json"
    paths = [
        checkpoint(
            root / "models" / "Stable-diffusion" / f"{name}.safetensors",
            metadata={"ss_base_model_version": "sdxl"},
            payload=name.encode(),
        )
        for name in ("first", "second")
    ]
    entries = [{"name": path.stem, "filename": str(path)} for path in paths]
    return root, cache, paths, entries


def prepare(local, **kwargs):
    root, cache, _paths, entries = local
    return prepare_comparison_evidence(
        list(dict.fromkeys(entry["name"] for entry in entries)),
        entries,
        registry=AssetRegistry(root, cache_path=cache),
        **kwargs,
    )


def test_selected_only_warm_has_no_scan_or_rehash(local, monkeypatch):
    root, cache, paths, _entries = local
    unselected = checkpoint(root / "models" / "Stable-diffusion" / "personal.safetensors")
    monkeypatch.setattr(type(root), "rglob", lambda *a, **k: pytest.fail("checkpoint scan"))
    evidence = prepare(local)
    assert evidence.policy_lookups == 2
    assert (
        evidence.model_identities["first"]["sha256"]
        == hashlib.sha256(paths[0].read_bytes()).hexdigest()
    )
    assert not any(
        loc.path == unselected
        for record in AssetRegistry(root, cache_path=cache).cached_snapshot().records
        for loc in record.locations
    )
    monkeypatch.setattr(
        AssetRegistry, "refresh", lambda *a, **k: pytest.fail("redundant warm refresh")
    )
    assert prepare(local).policy_for("first").family == "sdxl"


@pytest.mark.parametrize(
    "metadata, sidecar, phrase",
    [
        ({}, None, "metadata missing"),
        ({"modelspec.architecture": "unknown derivative"}, None, "unclassified"),
        ({"ss_base_model_version": "sdxl"}, '{"baseModel":"SD 1.5"}', "conflicting"),
        ({"ss_base_model_version": "sd_v1.5"}, None, "not qualified"),
    ],
)
def test_metadata_rejections_are_specific(local, metadata, sidecar, phrase):
    _root, _cache, paths, _entries = local
    checkpoint(paths[0], metadata=metadata)
    if sidecar:
        paths[0].with_suffix(".civitai.info").write_text(sidecar)
    with pytest.raises(ValueError, match=f"Model 1: .*{phrase}"):
        prepare(local)


@pytest.mark.parametrize(
    "change, phrase",
    [
        ("mismatch", "disagree"),
        ("missing", "unavailable"),
        ("relative", "not absolute"),
        ("ambiguous", "ambiguous"),
        ("hash", "hash disagrees"),
    ],
)
def test_runtime_identity_failures_never_borrow_evidence(local, change, phrase):
    _root, _cache, paths, entries = local
    if change == "mismatch":
        entries[0]["filename"] = str(paths[1])
    elif change == "missing":
        entries[0]["filename"] = str(paths[0].parent / "external" / paths[0].name)
    elif change == "relative":
        entries[0]["filename"] = paths[0].name
    elif change == "ambiguous":
        entries.append(dict(entries[0]))
    else:
        entries[0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match=phrase):
        prepare(local)


def test_explicit_served_file_outside_configured_root_is_registry_owned(local, tmp_path):
    root, cache, _paths, entries = local
    external = checkpoint(
        tmp_path / "actual-forge-data" / "first.safetensors",
        metadata={"ss_base_model_version": "sdxl"},
    )
    entries[0]["filename"] = str(external)
    evidence = prepare(local)
    assert (
        evidence.model_identities["first"]["sha256"]
        == hashlib.sha256(external.read_bytes()).hexdigest()
    )
    assert any(
        location.path == external
        for record in AssetRegistry(root, cache_path=cache).cached_snapshot().records
        for location in record.locations
    )


def test_exact_path_ignores_different_same_name_asset(local, tmp_path):
    root, cache, paths, _entries = local
    wrong = checkpoint(
        root / "models" / "Stable-diffusion" / "other" / paths[0].name,
        metadata={"ss_base_model_version": "sd_v1.5"},
    )
    AssetRegistry(root, cache_path=cache).refresh(kinds={AssetKind.CHECKPOINT})
    assert wrong.exists()
    assert prepare(local).policy_for("first").family == "sdxl"


def test_sidecar_freshness_does_not_rehash_checkpoint(local, monkeypatch):
    root, cache, paths, _entries = local
    prepare(local)
    paths[0].with_suffix(".civitai.info").write_text('{"baseModel":"SD 1.5"}')
    monkeypatch.setattr(
        "src.assets.registry.hashlib.sha256", lambda: pytest.fail("unchanged model rehash")
    )
    with pytest.raises(ValueError, match="conflicting"):
        prepare(local)


def test_overlapping_old_instances_preserve_both_refreshes(local):
    root, cache, paths, _entries = local
    lora = checkpoint(root / "models" / "Lora" / "adapter.safetensors")
    checkpoints = AssetRegistry(root, cache_path=cache)
    adapters = AssetRegistry(root, cache_path=cache)
    checkpoints.cached_snapshot()
    adapters.cached_snapshot()
    entered, release = threading.Event(), threading.Event()

    def pause(*args):
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(checkpoints.refresh, checkpoint_paths=paths, progress=pause)
        assert entered.wait(3)
        b = pool.submit(adapters.refresh, kinds={AssetKind.LORA, AssetKind.EMBEDDING})
        # The adapter writer completes while checkpoint hashing is paused;
        # its cache commit must survive the later checkpoint transaction.
        b.result(3)
        release.set()
        a.result(3)
    locations = {
        loc.path
        for record in AssetRegistry(root, cache_path=cache).cached_snapshot().records
        for loc in record.locations
    }
    assert locations == {*paths, lora}


def test_cancelled_hash_publishes_nothing_and_changes_no_checkpoint(local):
    root, cache, paths, _entries = local
    before = {path: path.read_bytes() for path in paths}
    cancel = threading.Event()
    with pytest.raises(InterruptedError):
        AssetRegistry(root, cache_path=cache).refresh(
            checkpoint_paths=paths,
            cancelled=cancel.is_set,
            progress=lambda *args: cancel.set(),
        )
    assert not cache.exists()
    assert {path: path.read_bytes() for path in paths} == before


def test_missing_runtime_filename_never_guesses_from_configured_root(local):
    _root, _cache, _paths, entries = local
    entries[0].pop("filename")
    with pytest.raises(ValueError, match="Model 1: .*filename is missing"):
        prepare(local)


def test_changed_checkpoint_refreshes_metadata_and_invalidates_previous_family(local):
    _root, _cache, paths, _entries = local
    prepare(local)
    checkpoint(paths[0], metadata={"ss_base_model_version": "sd_v1.5"}, payload=b"changed")
    with pytest.raises(ValueError, match="not qualified"):
        prepare(local)


def test_nested_webui_runtime_name_is_bound_to_exact_title_and_path(local):
    root, _cache, _paths, entries = local
    nested = checkpoint(
        root / "models" / "Stable-diffusion" / "folder" / "first.safetensors",
        metadata={"ss_base_model_version": "sdxl"},
    )
    entries[0].update(
        name="folder_first", filename=str(nested), title="folder/first.safetensors [1234567890]"
    )
    assert prepare(local).policy_for("folder_first").family == "sdxl"
    entries[0]["title"] = "other/first.safetensors [1234567890]"
    with pytest.raises(ValueError, match="disagree"):
        prepare(local)


def test_webui_legacy_hash_is_not_mistaken_for_sha256(local):
    local[3][0]["hash"] = "deadbeef"
    assert prepare(local).policy_for("first").family == "sdxl"


def test_registry_writer_lock_is_cross_process(local, tmp_path):
    import subprocess
    import sys
    import time

    from src.assets.cache_lock import registry_cache_lock

    root, cache, _paths, _entries = local
    started, done = tmp_path / "started", tmp_path / "done"
    script = (
        "import sys; from pathlib import Path; from src.assets import AssetRegistry; "
        "Path(sys.argv[3]).write_text('started'); "
        "AssetRegistry(sys.argv[1], cache_path=sys.argv[2]).refresh(); "
        "Path(sys.argv[4]).write_text('done')"
    )
    with registry_cache_lock(cache):
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(root), str(cache), str(started), str(done)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert started.exists()
            assert not done.exists()
        except BaseException:
            process.kill()
            process.communicate()
            raise
    output, error = process.communicate(timeout=10)
    assert process.returncode == 0, output + error
    assert done.exists()


def test_changed_file_during_hash_is_never_published(local):
    root, cache, paths, _entries = local
    changed = set()

    def change(path, *args):
        if path not in changed:
            changed.add(path)
            path.write_bytes(path.read_bytes() + b"changed during read")

    with pytest.raises(ValueError, match="changed during"):
        AssetRegistry(root, cache_path=cache).refresh(checkpoint_paths=paths, progress=change)
    assert not cache.exists()


def test_unreadable_metadata_is_distinct_from_absent_and_unknown(local):
    _root, _cache, paths, _entries = local
    paths[0].write_bytes(b"broken header")
    with pytest.raises(ValueError, match="unreadable checkpoint metadata"):
        prepare(local)


def test_read_failure_has_arm_guidance_without_local_path(local, monkeypatch):
    _root, _cache, paths, _entries = local

    def denied(*args, **kwargs):
        raise PermissionError(13, "denied", str(paths[1]))

    monkeypatch.setattr(AssetRegistry, "refresh", denied)
    with pytest.raises(ValueError, match="Model 2: .*unavailable") as error:
        prepare(local)
    assert str(paths[1]) not in str(error.value)


def test_worker_deadline_rejects_even_a_returned_result():
    from src.gui.model_comparison_readiness import ComparisonEvidenceTask

    task = ComparisonEvidenceTask(lambda **kwargs: object(), timeout=0)
    task.thread.join(3)
    assert not task.thread.is_alive()
    kind, message = task.messages.get_nowait()
    assert kind == "error" and "timed out" in message
