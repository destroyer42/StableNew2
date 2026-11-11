"""Component contracts of the golden-path suite: media validation, evidence, fakes and the Windows driver's diagnosis.

No model runtime, GPU or real input: the Windows driver is exercised against an injected fake Win32 on a withdrawn Tk
root (skipped when Tk is unavailable, like the repository's other Tk tests).
"""

from __future__ import annotations

import json
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

import pytest

from tools.operator_journey.evidence import FAIL, HOLD, NO_GO, PASS, JourneyEvidence
from tools.operator_journey.golden.media import inspect_image, inspect_video, sha256_file
from tools.operator_journey.golden.suite import EXIT_CODES, summary_markdown, write_run_evidence
from tools.operator_journey.tk_driver import ActionTrace, TkDriver, WidgetNotFound

# --- media validation (14-15 artifact and media checks) ------------------------------------------------------------


def test_image_inspection_decodes_fully_and_reports_geometry(tmp_path: Path) -> None:
    from PIL import Image

    good = tmp_path / "a.png"
    Image.new("RGB", (48, 32), (10, 20, 30)).save(good)
    info = inspect_image(good)
    assert (
        info["valid"]
        and (info["width"], info["height"]) == (48, 32)
        and info["sha256"] == sha256_file(good)
    )


def test_corrupt_missing_and_truncated_images_are_invalid(tmp_path: Path) -> None:
    from PIL import Image

    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    cut = tmp_path / "cut.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(cut)
    cut.write_bytes(cut.read_bytes()[:40])
    for path in (junk, cut, tmp_path / "missing.png"):
        assert inspect_image(path)["valid"] is False


def test_video_inspection_counts_decoded_frames(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (64, 48))
    if not writer.isOpened():  # pragma: no cover - codec availability
        pytest.skip("no mp4v encoder")
    for i in range(9):
        writer.write(np.full((48, 64, 3), i * 20, dtype=np.uint8))
    writer.release()
    info = inspect_video(path)
    assert (
        info["valid"]
        and info["decoded_frames"] == 9
        and (info["width"], info["height"]) == (64, 48)
    )
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00" * 64)
    assert inspect_video(bad)["valid"] is False


# --- evidence model (9, 11 observations vs simulated fixtures; verdict semantics) -----------------------------------


def test_verdicts_cover_pass_fail_hold_and_no_go() -> None:
    ev = JourneyEvidence(journey_id="X", backend_mode="simulated")
    assert ev.verdict == PASS
    ev.hold_reason = "waiting on a prerequisite"
    assert ev.verdict == HOLD
    ev.no_go_reason = "unsafe"
    assert ev.verdict == NO_GO
    failing = JourneyEvidence(journey_id="Y", backend_mode="simulated")
    failing.abort_reason = "boom"
    assert failing.verdict == FAIL
    assert (EXIT_CODES[PASS], EXIT_CODES[FAIL], EXIT_CODES[HOLD], EXIT_CODES[NO_GO]) == (0, 1, 2, 3)


def test_observations_are_labelled_observed_or_simulated_fixture() -> None:
    ev = JourneyEvidence(journey_id="X", backend_mode="simulated")
    ev.observe("job_row", {"status": "completed"})
    ev.observe("fixture_backend", "FakeA1111", source="simulated_fixture")
    sources = {o["name"]: o["source"] for o in ev.observations}
    assert sources == {"job_row": "observed", "fixture_backend": "simulated_fixture"}
    assert ev.as_dict()["observations"] == ev.observations


def test_run_folder_has_every_documented_file_and_separates_fixture_values(tmp_path: Path) -> None:
    ev = JourneyEvidence(journey_id="IMG-01", backend_mode="simulated")
    ev.observe("image_media", {"path": "x.png", "valid": True, "sha256": "ab"})
    ev.observe("fixture_backend", "FakeA1111", source="simulated_fixture")
    ev.action_trace.append({"t": 0.1, "action": "click", "driver": "tk"})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    overall = write_run_evidence(
        run_dir, plan={"suite": "golden-paths"}, results=[ev], mode="simulated", driver="tk"
    )
    assert overall == PASS
    for name in (
        "plan.json",
        "evidence.json",
        "summary.md",
        "actions.jsonl",
        "artifacts.json",
        "logs",
    ):
        assert (run_dir / name).exists(), name
    artifacts = json.loads((run_dir / "artifacts.json").read_text())
    assert artifacts[0]["sha256"] == "ab" and artifacts[0]["journey"] == "IMG-01"
    action = json.loads((run_dir / "actions.jsonl").read_text().splitlines()[0])
    assert action["driver"] == "tk" and action["journey"] == "IMG-01"
    assert "Simulated fixture values" in summary_markdown(PASS, "simulated", "tk", [ev], None)


def test_overall_verdict_is_the_worst_journey(tmp_path: Path) -> None:
    good = JourneyEvidence(journey_id="A", backend_mode="simulated")
    bad = JourneyEvidence(journey_id="B", backend_mode="simulated")
    bad.no_go_reason = "unsafe"
    run_dir = tmp_path / "r"
    run_dir.mkdir()
    assert (
        write_run_evidence(run_dir, plan={}, results=[good, bad], mode="simulated", driver="tk")
        == NO_GO
    )


def test_empty_suite_evidence_is_held(tmp_path: Path) -> None:
    verdict = write_run_evidence(tmp_path, plan={}, results=[], mode="simulated", driver="tk")
    assert verdict == HOLD
    assert json.loads((tmp_path / "evidence.json").read_text())["overall_verdict"] == HOLD


# --- fake backends (loopback only) ------------------------------------------------------------------------------------


def test_fake_comfy_serves_the_wan_contract_on_loopback() -> None:
    from src.video.workflow_registry import build_default_workflow_registry
    from tools.operator_journey.fake_comfy import FakeComfy

    spec = build_default_workflow_registry().get("wan22_ti2v_5b_i2v_v1", "1.3.0")
    with FakeComfy(spec) as fake:
        assert fake.base_url.startswith("http://127.0.0.1:")
        stats = json.load(urllib.request.urlopen(f"{fake.base_url}/system_stats", timeout=5))
        assert stats["devices"][0]["vram_total"] > 0
        info = json.load(urllib.request.urlopen(f"{fake.base_url}/object_info", timeout=5))
        assert isinstance(info, dict) and info
        assert fake.prompts == []  # nothing was generated by merely probing


# --- scripted dialogs (tk driver only; physical runs answer real dialogs) ----------------------------------------------


def test_dialog_seam_answers_are_consumed_in_order_and_recorded() -> None:
    from tools.operator_journey.dialogs import DialogSeam, scripted_dialogs

    seam = DialogSeam()
    seam.strings.append("pack_one")
    seam.files.append("C:/x/pack_one.json")
    with scripted_dialogs(seam):
        from tkinter import filedialog, simpledialog

        assert simpledialog.askstring("New Pack", "name?") == "pack_one"
        assert filedialog.asksaveasfilename(title="Save") == "C:/x/pack_one.json"


# --- the Windows driver's diagnosis against a fake Win32 (no real input) ----------------------------------------------


class FakeWin32:
    """Stands in for Win32: a 1000x800 screen, the app window filling it, nothing else on top."""

    def __init__(self) -> None:
        self.hwnd = 1234
        self.under_pointer = 1234
        self.clicks: list[tuple[int, int]] = []
        self.size = (1000, 800)

    def screen_size(self) -> tuple[int, int]:
        return self.size

    def rect(self, _hwnd: int) -> tuple[int, int, int, int]:
        return 0, 0, 1000, 800

    def root_of(self, hwnd: int) -> int:
        return hwnd if hwnd == 777 else self.hwnd  # 777 stands for some other application's window

    def window_from_point(self, _x: int, _y: int) -> int:
        return self.under_pointer

    def foreground(self) -> int:
        return self.hwnd

    def pid_of(self, _hwnd: int) -> int:
        return 1

    def raise_window(self, _hwnd: int) -> bool:
        return True

    def click(self, x: int, y: int, **_kw: Any) -> tuple[int, int]:
        self.clicks.append((x, y))
        return x, y

    def move(self, *_a: Any) -> None:
        pass


@pytest.fixture
def desktop():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - environment specific
        pytest.skip(f"Tk unavailable: {exc}")
    root.geometry("600x400+0+0")
    fake = FakeWin32()
    from tools.operator_journey.desktop import WindowsDesktopDriver

    driver = WindowsDesktopDriver(root, ActionTrace(driver="windows"), win32=fake)  # type: ignore[arg-type]
    root.update()

    def containing(x: int, y: int) -> tk.Misc | None:
        """Deterministic hit test (the real one depends on what else is on this desktop): topmost child at a point."""

        hit: tk.Misc | None = None
        for child in root.winfo_children():  # children are in stacking order, last is topmost
            if (
                child.winfo_ismapped()
                and child.winfo_rootx() <= x < child.winfo_rootx() + child.winfo_width()
                and child.winfo_rooty() <= y < child.winfo_rooty() + child.winfo_height()
            ):
                hit = child
        return hit or root

    root.winfo_containing = containing  # type: ignore[method-assign]
    yield SimpleNamespace(root=root, driver=driver, fake=fake)
    root.destroy()


def _button(desktop, **kw) -> ttk.Button:
    button = ttk.Button(desktop.root, text="Go", **kw)
    button.place(x=40, y=40, width=80, height=30)
    desktop.root.update()
    return button


def _point(desktop, widget) -> tuple[int, int]:
    return desktop.driver._center(widget)


def test_a_visible_enabled_unobscured_control_is_reachable(desktop) -> None:
    button = _button(desktop)
    assert desktop.driver.diagnose(button, *_point(desktop, button)) is None


def test_disabled_and_unmapped_controls_are_unreachable(desktop) -> None:
    from tools.operator_journey.desktop import ControlUnreachable

    button = _button(desktop)
    button.state(["disabled"])
    assert desktop.driver.diagnose(button, *_point(desktop, button)) == "disabled"
    with pytest.raises(ControlUnreachable, match="disabled"):
        desktop.driver.reach(button, label="Go", patience=0.0)
    button.state(["!disabled"])
    button.place_forget()
    desktop.root.update()
    assert "hidden" in desktop.driver.diagnose(button, 50, 50)


def test_off_screen_outside_window_and_obscured_points_are_reported(desktop) -> None:
    button = _button(desktop)
    assert "off-screen" in desktop.driver.diagnose(button, 5000, 10)
    desktop.fake.size = (30, 30)
    assert "off-screen" in desktop.driver.diagnose(button, *_point(desktop, button))
    desktop.fake.size = (1000, 800)
    desktop.fake.under_pointer = 777  # another application window is on top of the pointer
    assert "obscured by another window" in desktop.driver.diagnose(button, *_point(desktop, button))


def test_a_sibling_widget_covering_the_control_is_reported_as_obscured(desktop) -> None:
    button = _button(desktop)
    cover = tk.Frame(desktop.root, bg="red")
    cover.place(x=30, y=30, width=120, height=60)
    cover.lift()
    desktop.root.update()
    assert "obscured within the application" in desktop.driver.diagnose(
        button, *_point(desktop, button)
    )


def test_the_driver_trace_names_its_driver_and_the_semantic_driver_names_itself(desktop) -> None:
    assert desktop.driver.trace.driver == "windows"
    desktop.driver.trace.record("probe")
    assert desktop.driver.trace.entries[-1]["driver"] == "windows"
    semantic = TkDriver(desktop.root, ActionTrace())
    semantic.trace.record("probe")
    assert semantic.trace.entries[-1]["driver"] == "tk"


def test_semantic_driver_refuses_a_disabled_control(desktop) -> None:
    button = _button(desktop, state="disabled")
    with pytest.raises(WidgetNotFound, match="disabled"):
        TkDriver(desktop.root, ActionTrace()).invoke(button, label="Go")


def test_physical_driver_is_never_constructed_by_the_golden_modules_at_import() -> None:
    import importlib
    import sys

    for name in [m for m in sys.modules if m.startswith("tools.operator_journey.desktop")]:
        del sys.modules[name]
    importlib.import_module("tools.operator_journey.golden.suite")
    assert (
        "tools.operator_journey.desktop" not in sys.modules
    )  # simulated/tk runs never load the input driver


def test_select_tree_row_scrolls_the_page_to_a_tree_below_the_fold(desktop) -> None:
    """PR-GUI-RELIABILITY-831: a list below the fold is reached by wheel-scrolling its page, as a person would."""

    root, driver, fake = desktop.root, desktop.driver, desktop.fake
    canvas = tk.Canvas(
        root, yscrollcommand=lambda *_a: None, yscrollincrement=20, highlightthickness=0
    )
    canvas.place(x=0, y=0, width=300, height=200)
    inner = tk.Frame(canvas)
    canvas.create_window((0, 0), window=inner, anchor="nw", width=300)
    tk.Frame(inner, height=320).pack()  # the content above the tree
    tree = ttk.Treeview(inner, height=3, show="tree")
    tree.pack()
    tree.insert("", "end", iid="row1", text="row one")
    cover = tk.Frame(root)  # the bottom zone: covers everything below the page's visible area
    cover.place(x=0, y=200, width=600, height=200)
    cover.lift()
    root.update()
    canvas.configure(scrollregion=canvas.bbox("all"))
    root.update()

    def containing(x: int, y: int) -> tk.Misc:
        if y >= cover.winfo_rooty():
            return cover
        inside = (
            tree.winfo_rootx() <= x < tree.winfo_rootx() + tree.winfo_width()
            and tree.winfo_rooty() <= y < tree.winfo_rooty() + tree.winfo_height()
        )
        return tree if inside else canvas

    root.winfo_containing = containing  # type: ignore[method-assign]
    fake.wheel = lambda _x, _y, notches: canvas.yview_scroll(-notches, "units")  # type: ignore[attr-defined]
    assert tree.winfo_rooty() >= cover.winfo_rooty(), "precondition: the tree starts below the fold"

    driver.select_tree_row(tree, "row1", label="History row")

    assert fake.clicks and fake.clicks[-1][1] < cover.winfo_rooty()
    assert any(e["action"] == "scrolled_into_view" for e in driver.trace.entries)


def test_the_page_hiding_a_control_is_scrolled_not_the_box_that_already_shows_it(desktop) -> None:
    """PR-GUI-RELIABILITY-831: with nested scroll boxes, the one whose viewport lacks the control is the one to wheel."""

    root, driver = desktop.root, desktop.driver
    page = tk.Canvas(root, yscrollcommand=lambda *_a: None, highlightthickness=0)
    page.place(x=0, y=0, width=300, height=200)
    body = tk.Frame(page)
    page.create_window((0, 0), window=body, anchor="nw", width=300)
    tk.Frame(body, height=300).pack()  # content above the nested box
    box = tk.Canvas(body, yscrollcommand=lambda *_a: None, height=120, highlightthickness=0)
    box.pack(fill="x")
    box_body = tk.Frame(box)
    box.create_window((0, 0), window=box_body, anchor="nw", width=300)
    button = ttk.Button(box_body, text="rating 3")
    button.pack()
    tk.Frame(box_body, height=400).pack()  # the box has its own overflow, below the button
    root.update()
    page.configure(scrollregion=page.bbox("all"))
    box.configure(scrollregion=box.bbox("all"))
    root.update()
    assert button.winfo_rooty() >= page.winfo_rooty() + page.winfo_height(), (
        "precondition: below the page's fold"
    )

    assert driver._scroll_container(button) is page  # noqa: SLF001


def test_a_short_viewport_is_scrolled_a_notch_at_a_time_so_the_page_does_not_oscillate(
    desktop,
) -> None:
    """PR-GUI-RELIABILITY-831: three 40 px notches overshoot an 80 px viewport; the control is then above, then below, ..."""

    root, driver, fake = desktop.root, desktop.driver, desktop.fake
    page = tk.Canvas(root, yscrollcommand=lambda *_a: None, highlightthickness=0)
    page.place(x=0, y=0, width=300, height=80)
    body = tk.Frame(page)
    page.create_window((0, 0), window=body, anchor="nw", width=300)
    tk.Frame(
        body, height=448
    ).pack()  # the button's centre lands 100 px into a 120 px step: a 3-notch step skips it
    button = ttk.Button(body, text="rating 3")
    button.pack()
    tk.Frame(body, height=300).pack()
    root.update()
    page.configure(scrollregion=page.bbox("all"))
    root.update()

    def containing(x: int, y: int) -> tk.Misc:
        in_viewport = page.winfo_rooty() <= y < page.winfo_rooty() + page.winfo_height()
        inside = (
            button.winfo_rootx() <= x < button.winfo_rootx() + button.winfo_width()
            and button.winfo_rooty() <= y < button.winfo_rooty() + button.winfo_height()
        )
        return (
            button if inside and in_viewport else root
        )  # outside the viewport nothing of the page is there

    root.winfo_containing = containing  # type: ignore[method-assign]
    span = page.bbox("all")[3]

    def wheel(
        _x: int, _y: int, notches: int
    ) -> None:  # one notch is a fixed 40 px, as in ScrollableFrame
        first = page.yview()[0]
        page.yview_moveto(min(max(first - notches * 40 / span, 0.0), 1.0))

    fake.wheel = wheel  # type: ignore[attr-defined]

    _x, y = driver.reach(button, label="rating 3")

    assert page.winfo_rooty() <= y < page.winfo_rooty() + page.winfo_height()
