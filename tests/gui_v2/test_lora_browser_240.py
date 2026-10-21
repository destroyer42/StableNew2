"""Headless contracts for local LoRA discovery and presentation."""

import json
import queue
import struct
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.assets import AssetRegistry
from src.assets.lora_preview import read_thumbnail
from src.assets.registry import AssetRegistrySnapshot
from src.gui.widgets import lora_browser_dialog as dialog_module
from src.gui.widgets import lora_picker_panel as picker_module
from src.gui.widgets.lora_browser_dialog import LoRABrowserDialog
from src.gui.widgets.lora_picker_panel import LoRAPickerPanel
from src.gui_v2.lora_browser import PAGE_SIZE, browser_page, project_adapter, visible_resource
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1
from src.image_backends.model_policy import policy_for_profile, resolve_model_policy
from src.utils.lora_scanner import LoRAResource, LoRAScanner


class Value:
    def __init__(self, value=""):
        self.value, self.updates = value, []

    def set(self, value):
        self.value = value
        self.updates.append(threading.get_ident())

    def get(self):
        return self.value


class Invoker:
    def __init__(self, *_):
        self.callbacks, self.closed = queue.Queue(), False

    def invoke(self, callback):
        if not self.closed:
            self.callbacks.put(callback)

    def drain(self):
        while not self.callbacks.empty():
            self.callbacks.get_nowait()()

    def dispose(self):
        self.closed = True


class Workers:
    def __init__(self):
        self.targets = []

    def spawn(self, **kwargs):
        assert kwargs["daemon"] is False
        self.targets.append(kwargs["target"])

    def run(self):
        thread = threading.Thread(target=self.targets.pop(0))
        thread.start()
        thread.join(5)
        assert not thread.is_alive()


def resource(name="style", **kwargs):
    return LoRAResource(name, Path("/unused") / (name + ".safetensors"), 12, [], "none", **kwargs)


@pytest.fixture
def panel(monkeypatch):
    workers = Workers()
    monkeypatch.setattr(picker_module, "GuiInvoker", Invoker)
    monkeypatch.setattr(picker_module, "get_thread_registry", lambda: workers)
    panel = LoRAPickerPanel.__new__(LoRAPickerPanel)
    panel._init_discovery()
    panel.__dict__.update(
        webui_root="unused",
        scanner=None,
        _browser=None,
        _keyword_dialog=None,
        _policy=None,
        _initial_scan=None,
        _content_visibility_mode="nsfw",
        _resources={},
        _available_loras=[],
        _visible_loras=[],
        _verified=False,
        _entry_widgets={},
        _annotations={},
        _lora_entries=[],
        selection_listener=None,
        on_change_callback=None,
        discovery_status=Value(),
        lora_name_var=Value(),
        lora_name_combo={},
        workers=workers,
    )
    panel.after = lambda *_: "pending"
    panel.after_cancel = lambda *_: None
    return panel


def scanner_stub(callback):
    return SimpleNamespace(
        scan_loras=callback, registry=SimpleNamespace(snapshot=AssetRegistrySnapshot(()))
    )


def test_refresh_never_scans_on_tk_thread(panel):
    """The original after(100, _scan_loras) ran the entire scan on Tk."""
    caller = threading.get_ident()
    reads = []
    panel.scanner = scanner_stub(lambda **_: reads.append(threading.get_ident()) or {})
    panel._scan_loras()
    assert reads == []
    panel.workers.run()
    assert caller not in reads, "LoRA scan ran synchronously in the Tk callback"
    assert reads and not panel._verified
    panel._invoker.drain()
    assert panel._verified and set(panel.discovery_status.updates) == {caller}


def test_refresh_latest_wins_and_coalesces(panel):
    results = [{"old": resource("old")}, {"new": resource("new")}]
    panel.scanner = scanner_stub(lambda **_: results.pop(0))
    for _ in range(30):
        panel.refresh_loras()
    assert len(panel.workers.targets) == 1
    panel.workers.run()
    panel._invoker.drain()
    assert panel._resources == {} and len(panel.workers.targets) == 1
    panel.workers.run()
    panel._invoker.drain()
    assert list(panel._resources) == ["new"]


def test_failure_is_visible_and_preserves_inventory_and_weights(panel):
    panel._resources = {"retained": resource("retained")}
    panel._available_loras = ["retained"]
    panel._lora_entries = [("missing", Value(1.23), None)]

    def fail(**_):
        raise OSError("nsfw hidden-secret-file")

    panel.scanner = scanner_stub(fail)
    panel.refresh_loras()
    panel.workers.run()
    panel._invoker.drain()
    assert "failed" in panel.discovery_status.get()
    assert "hidden-secret" not in panel.discovery_status.get()
    assert not panel._verified and list(panel._resources) == ["retained"]
    assert panel.get_loras() == [("missing", 1.23)]


def test_destroy_while_discovering_discards_completion(panel):
    panel.scanner = scanner_stub(lambda **_: {"late": resource("late")})
    panel.refresh_loras()
    panel._on_destroy(SimpleNamespace(widget=panel))
    panel.workers.run()
    panel._invoker.drain()
    panel._finish_refresh(panel._request_id, {"late": resource("late")}, False)
    assert panel._resources == {} and panel._cancel_scan.is_set()


def write_adapter(path, metadata=None):
    header = json.dumps({"__metadata__": metadata or {}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + b"fake-weights")


def scanner_at(tmp_path):
    root = tmp_path / "webui"
    return root, LoRAScanner(root, registry=AssetRegistry(root, cache_path=tmp_path / "cache.json"))


def test_registry_keywords_off_tk_and_browsing_writes_nothing(panel, tmp_path, monkeypatch):
    root, scanner = scanner_at(tmp_path)
    asset = root / "models/Lora/sub/style.safetensors"
    write_adapter(asset, {"ss_base_model_version": "sdxl"})
    asset.with_suffix(".civitai.info").write_text(
        json.dumps({"trainedWords": ["sunlit"], "baseModel": "SDXL 1.0"})
    )
    original, reads = Path.open, []

    def opened(path, *args, **kwargs):
        reads.append(threading.get_ident())
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    panel.scanner = scanner
    panel.refresh_loras()
    panel.workers.run()
    panel._invoker.drain()
    assert reads and threading.get_ident() not in reads
    assert panel._resources["style"].keywords == ["sunlit"]
    assert panel._resources["style"].source == "civitai"
    assert not scanner.registry.cache_path.exists()


def test_existing_cache_is_byte_identical_after_read_only_refresh(tmp_path):
    root, scanner = scanner_at(tmp_path)
    write_adapter(root / "models/Lora/style.safetensors")
    scanner.registry.refresh()
    before = scanner.registry.cache_path.read_bytes()
    write_adapter(root / "models/Lora/another.safetensors")
    assert len(scanner.scan_loras(read_only=True)) == 2
    assert scanner.registry.cache_path.read_bytes() == before


def test_slow_discovery_does_not_block_callback(panel, tmp_path, monkeypatch):
    root, scanner = scanner_at(tmp_path)
    write_adapter(root / "models/Lora/style.safetensors")
    entered, release = threading.Event(), threading.Event()

    def slow(_):
        entered.set()
        assert release.wait(3)
        return scanner

    monkeypatch.setattr(picker_module, "get_lora_scanner", slow)
    panel.refresh_loras()
    thread = threading.Thread(target=panel.workers.targets.pop())
    thread.start()
    assert entered.wait(2)
    panel.refresh_loras()
    assert panel._request_id == 2
    release.set()
    thread.join(4)
    assert not thread.is_alive()


def test_missing_corrupt_metadata_and_missing_root(tmp_path):
    root, scanner = scanner_at(tmp_path)
    with pytest.raises(FileNotFoundError):
        scanner.scan_loras(read_only=True)
    for name in ("missing", "corrupt"):
        write_adapter(root / f"models/Lora/{name}.safetensors")
    (root / "models/Lora/corrupt.civitai.info").write_text("[invalid")
    resources = scanner.scan_loras(read_only=True)
    assert not resources["missing"].keywords
    assert project_adapter(resources["missing"], None).compatibility.startswith("Unknown")
    assert resources["corrupt"].errors and not visible_resource(resources["corrupt"], "sfw")


def test_filtering_precedes_search_and_bounded_paging():
    resources = {f"safe-{i}": resource(f"safe-{i}") for i in range(37)}
    resources["neutral"] = resource("neutral", description="nude")
    resources["private"] = resource("private", visibility={"nsfw": True})
    page, number, count = browser_page(resources, "sfw", "", 0)
    assert len(page) == PAGE_SIZE and number == 0 and count == 10
    assert browser_page(resources, "sfw", "neutral", 0)[0] == []
    assert browser_page(resources, "sfw", "private", 0)[0] == []
    assert browser_page(resources, "nsfw", "NEUTRAL", 0)[0][0].name == "neutral"
    assert len(browser_page(resources, "sfw", "", 100)[0]) == 1


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"ss_base_model_version": "sdxl"}, "Possibly compatible"),
        ({"ss_base_model_version": "sd_v1.5"}, "Incompatible"),
        ({}, "Unknown"),
        (
            {"ss_base_model_version": "sdxl", "modelspec.architecture": "stable-diffusion-v1"},
            "Unknown",
        ),
    ],
)
def test_sdxl_projection_uses_evidence_not_filename(tmp_path, metadata, expected):
    root, scanner = scanner_at(tmp_path)
    write_adapter(root / "models/Lora/sdxl-label.safetensors", metadata)
    value = scanner.scan_loras(read_only=True)["sdxl-label"]
    target = AssetRegistry._build_record(
        "a" * 64, [], ({"ss_base_model_version": "sdxl"}, "safetensors_header", None)
    )
    policy = resolve_model_policy("target", family_lookup=lambda _: target.compatibility)
    projection = project_adapter(value, policy, target.compatibility)
    assert projection.compatibility.startswith(expected)
    if expected.startswith("Possibly"):
        assert "not physically qualified" in projection.compatibility


def test_klein_projection_reuses_exact_authority_and_v1_restriction(tmp_path):
    root, scanner = scanner_at(tmp_path)
    write_adapter(
        root / "models/Lora/explicit.safetensors", {"ss_base_model_version": "flux2_klein_4b"}
    )
    value = scanner.scan_loras(read_only=True)["explicit"]
    policy = resolve_model_policy("flux-2-klein-4b-fp8.safetensors")
    assert project_adapter(value, policy).compatibility.startswith("Possibly compatible")
    assert policy.feature("lora").limit == 1
    assert project_adapter(value, policy_for_profile(KLEIN_PROFILE_V1)).compatibility.startswith(
        "Incompatible"
    )


def test_missing_selection_survives_success_and_browser_changes_existing_control(panel):
    panel._lora_entries = [("offline", Value(1.23), None)]
    panel._finish_refresh(0, {"new": resource("new")}, False)
    assert panel.get_loras() == [("offline", 1.23)] and panel._verified
    panel._visible_loras = ["offline"]
    changes = []
    panel.on_change_callback = lambda: changes.append(panel.get_loras())
    panel.choose_from_browser("offline", 0.7, True)
    assert changes == [[("offline", 0.7)]]
    panel.choose_from_browser("hidden", 0.8, True)
    assert panel.get_loras() == [("offline", 0.7)]


def test_previews_are_bounded_corrupt_missing_safe(tmp_path):
    good = tmp_path / "preview.png"
    Image.new("RGB", (1000, 500)).save(good)
    assert read_thumbnail(good, tmp_path).size == (128, 64)
    good.write_bytes(b"corrupt")
    assert read_thumbnail(good, tmp_path) is None
    assert read_thumbnail(tmp_path / "missing.png", tmp_path) is None
    assert read_thumbnail(good, tmp_path / "outside") is None
    assert read_thumbnail(None, tmp_path) is None


def test_thumbnail_threads_cache_bounds_stale_and_destroyed_completion(monkeypatch):
    workers, invoker = Workers(), Invoker()
    monkeypatch.setattr(dialog_module, "get_thread_registry", lambda: workers)
    decode, photo = [], []
    monkeypatch.setattr(
        dialog_module,
        "read_thumbnail",
        lambda *_: decode.append(threading.get_ident()) or Image.new("RGB", (2, 2)),
    )
    monkeypatch.setattr(
        dialog_module.ImageTk,
        "PhotoImage",
        lambda *a, **k: photo.append(threading.get_ident()) or object(),
    )
    browser = LoRABrowserDialog.__new__(LoRABrowserDialog)
    names = [f"r{i}" for i in range(PAGE_SIZE)]
    browser.__dict__.update(
        closed=False,
        picker=SimpleNamespace(_invoker=invoker),
        _generation=1,
        _thumb_active=False,
        _thumb_cancel=threading.Event(),
        _images={},
        _preview_labels={name: SimpleNamespace(configure=lambda **_: None) for name in names},
        _pending_thumbnails=(1, tuple(resource(name) for name in names)),
    )
    browser._start_thumbnails()
    workers.run()
    assert not photo
    invoker.drain()
    assert set(photo) == {threading.get_ident()} and threading.get_ident() not in decode
    assert len(browser._images) == dialog_module.THUMBNAIL_CACHE_LIMIT
    before = len(photo)
    browser._finish_thumbnails(0, {name: Image.new("RGB", (2, 2)) for name in names})
    assert len(photo) == before
    browser._on_destroy(SimpleNamespace(widget=browser))
    browser._finish_thumbnails(1, {"late": Image.new("RGB", (2, 2))})
    assert browser._images == {}


def test_keyword_view_has_no_io_and_visibility_change_closes_it(panel, monkeypatch):
    value = resource("style")
    value.keywords = ["sunlight"]
    panel._resources = {"style": value}
    dialogs = []

    class Dialog:
        def __init__(self, *args, **kwargs):
            self.metadata, self.closed = kwargs["metadata"], False
            dialogs.append(self)

        def grab_set(self):
            pass

        def winfo_exists(self):
            return not self.closed

        def destroy(self):
            self.closed = True

    monkeypatch.setattr(picker_module, "LoRAKeywordDialog", Dialog)
    monkeypatch.setattr(Path, "open", lambda *_a, **_k: pytest.fail("Tk performed file I/O"))
    panel._show_keywords("style")
    assert dialogs[0].metadata.keywords == ["sunlight"]
    panel.set_content_visibility_mode("sfw")
    assert dialogs[0].closed


def test_selected_name_tooltip_annotations_redact_on_mode_change(panel):
    class Widget:
        def __init__(self):
            self.text = ""
            self.tooltip = SimpleNamespace(text="secret", _hide=lambda: None)

        def configure(self, **kwargs):
            self.text = kwargs.get("text", self.text)

        def state(self, states):
            self.states = states

        def grid(self):
            pass

        def grid_remove(self):
            pass

    panel._entry_widgets = {
        "neutral": {
            key: Widget()
            for key in (
                "name_label",
                "keywords_button",
                "inventory_label",
                "annotation_label",
            )
        }
    }
    panel._annotations = {"neutral": "nsfw secret annotation"}
    panel._resources = {"neutral": resource("neutral", description="nude")}
    panel.set_content_visibility_mode("sfw")
    widgets = panel._entry_widgets["neutral"]
    assert widgets["name_label"].text == picker_module.REDACTED_TEXT
    assert widgets["name_label"].tooltip.text == picker_module.REDACTED_TEXT
    assert "secret" not in widgets["annotation_label"].text
    assert widgets["keywords_button"].states == ["disabled"]


def test_filename_only_target_cannot_establish_pairing(tmp_path):
    root, scanner = scanner_at(tmp_path)
    write_adapter(root / "models/Lora/style.safetensors", {"ss_base_model_version": "sdxl"})
    value = scanner.scan_loras(read_only=True)["style"]
    from src.assets.registry import AssetKind, AssetLocation

    target = AssetRegistry._build_record(
        "a" * 64,
        [
            AssetLocation(
                AssetKind.CHECKPOINT,
                tmp_path / "sdxl.safetensors",
                tmp_path,
                "sdxl",
                12,
            )
        ],
        ({}, None, None),
    )
    policy = resolve_model_policy("sdxl", family_lookup=lambda _: target.compatibility)
    assert project_adapter(value, policy, target.compatibility).compatibility.startswith("Unknown")


def test_registry_read_only_directory_error_is_not_authoritative_empty(tmp_path, monkeypatch):
    root, scanner = scanner_at(tmp_path)
    write_adapter(root / "models/Lora/style.safetensors")

    def fail_walk(path, **kwargs):
        kwargs["on_error"](PermissionError("private folder"))
        return iter(())

    monkeypatch.setattr(Path, "walk", fail_walk)
    with pytest.raises(PermissionError):
        scanner.scan_loras(read_only=True)


def test_corrupt_utf8_and_oversized_keyword_sidecar_are_explicit(tmp_path):
    root, scanner = scanner_at(tmp_path)
    path = root / "models/Lora/style.safetensors"
    write_adapter(path)
    sidecar = path.with_suffix(".civitai.info")
    for data in (b"\xff", b"x" * (512 * 1024 + 1)):
        sidecar.write_bytes(data)
        value = scanner.scan_loras(read_only=True)["style"]
        assert value.errors


def test_thumbnail_refreshes_coalesce_while_old_decode_is_active(monkeypatch):
    workers, invoker = Workers(), Invoker()
    monkeypatch.setattr(dialog_module, "get_thread_registry", lambda: workers)
    monkeypatch.setattr(dialog_module, "read_thumbnail", lambda *_: None)
    browser = LoRABrowserDialog.__new__(LoRABrowserDialog)
    browser.__dict__.update(
        closed=False,
        picker=SimpleNamespace(_invoker=invoker),
        _generation=1,
        _thumb_active=False,
        _thumb_cancel=threading.Event(),
        _images={},
        _preview_labels={},
        _pending_thumbnails=(1, (resource("old"),)),
    )
    browser._start_thumbnails()
    browser._generation = 2
    browser._thumb_cancel.set()
    browser._pending_thumbnails = (2, (resource("new"),))
    assert len(workers.targets) == 1
    workers.run()
    invoker.drain()
    assert (
        len(workers.targets) == 1
    )  # latest page starts after old completion; no overlapping decoder
    workers.run()
    invoker.drain()
    assert not browser._thumb_active
