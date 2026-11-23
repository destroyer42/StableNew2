"""PR-VID-STORY-380 B2: the Tk-free storyboard view contract and the frame cache."""

from __future__ import annotations

import ast
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from src.gui.view_contracts.storyboard_tree_contract import StoryboardTreeContract
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_cut import CutFrame
from src.video.storyboard_frame_cache import FrameCache
from src.video.storyboard_projection import TakeView
from src.video.storyboard_tree import StoryboardTree, Take, TreeRoot

NOW = "2026-11-21T10:00:00+00:00"
ROOT_LENGTH = 81
OWN = 80  # 81 frames minus the one overlap frame every take drops


@dataclass(frozen=True)
class _Row:
    prompt: str
    seed: str = ""


def _row(prompt: str, seed: str = "") -> _Row:
    return _Row(prompt, seed)


def _root() -> TreeRoot:
    return TreeRoot(
        kind="clip",
        job_id="j0",
        image_path="",
        image_sha256="",
        manifest_path="x",
        manifest_sha256="",
        settings=(("frame_count", 81), ("workflow_id", "wan22_i2v"), ("workflow_version", "1.0.0")),
        fps=16,
        width=832,
        height=480,
        smoothing_text="",
    )


def _take(
    take_id: str,
    parent: str,
    handoff: int | None,
    *,
    mark: str = "none",
    prompt: str = "p",
    position: int = 0,
) -> Take:
    return Take(
        take_id=take_id,
        parent_id=parent,
        handoff_index=handoff,
        mode="sequential" if position else "parallel",
        batch_id="b",
        chain_position=position,
        segment_index=position,
        prompt=prompt,
        negative_prompt="",
        seed_intent="",
        attempts=("j",),
        replay_of=None,
        mark=mark,
        created_at=NOW,  # type: ignore[arg-type]
    )


def _view(take_id: str, *, ok: bool = True, state: str = "completed") -> TakeView:
    return TakeView(
        take_id=take_id,
        state=state,
        status_text=state,
        shown_job_id="j",  # type: ignore[arg-type]
        manifest=CutFrame("m.json", "0" * 64),
        stitched_path=None,
        clip_path=None,
        encoded=True,
        frames_ok=ok,
        problem="" if ok else "frames missing or changed: C:/x/frame_0002.png",
        can_resume=False,
        can_replay=True,
    )


def _diner(missing: tuple[str, ...] = ()) -> tuple[StoryboardTree, dict[str, TakeView]]:
    # A; A1 A2(dropped) A3 A4 from A @ f78; A1a A1b from A1 @ f80
    tree = StoryboardTree.new("Diner", _root())
    takes = [
        _take("t1", ROOT_PARENT, 77, prompt="A1 orders"),
        _take("t2", ROOT_PARENT, 77, mark="dropped"),
        _take("t3", ROOT_PARENT, 77, prompt="a very long prompt " * 6),
        _take("t4", ROOT_PARENT, 77),
        _take("t1a", "t1", 79),
        _take("t1b", "t1", 79),
    ]
    for take in takes:
        tree = tree.with_take(take)
    views = {take.take_id: _view(take.take_id, ok=take.take_id not in missing) for take in takes}
    return tree, views


def _chain() -> tuple[StoryboardTree, dict[str, TakeView]]:
    tree = StoryboardTree.new("Chain", _root())
    for take in (
        _take("c1", ROOT_PARENT, 77),
        _take("c2", "c1", None, position=1),
        _take("c3", "c2", None, position=2),
    ):
        tree = tree.with_take(take)
    return tree, {t: _view(t) for t in ("c1", "c2", "c3")}


def test_columns_follow_depth_and_hide_dropped():
    c = StoryboardTreeContract(*_diner())
    titles = [col.title for col in c.columns(show_dropped=False)]
    assert titles == ["Shot 1", "Shot 2 · from A @ f78", "Shot 3 · from A1 @ f80"]
    assert [card.label for card in c.columns(show_dropped=False)[1].cards] == ["A1", "A3", "A4"]
    assert [card.label for card in c.columns(show_dropped=True)[1].cards] == [
        "A1",
        "A2",
        "A3",
        "A4",
    ]
    assert c.dropped_count() == 1


def test_cards_carry_excerpt_status_and_path_highlight():
    c = StoryboardTreeContract(*_diner())
    c.select("t1b")
    columns = c.columns(show_dropped=False)
    cards = {card.take_id: card for col in columns for card in col.cards}
    assert cards["t1b"].selected and cards["t1b"].on_path and not cards["t1a"].on_path
    assert cards["t1"].on_path and not cards["t1"].selected and cards[ROOT_PARENT].on_path
    assert len(cards["t3"].excerpt) <= 40 and cards["t3"].excerpt.endswith("…")
    assert cards["t4"].status_text == "completed"


def test_frame_in_a_middle_chain_take_branches_from_it():
    c = StoryboardTreeContract(*_chain())
    c.select("c3")
    cut = (ROOT_LENGTH - 3) + OWN * 3  # 78 root frames, then three takes
    owners = c.selected_cut_owners(cut, {ROOT_PARENT: ROOT_LENGTH, "c1": OWN, "c2": OWN, "c3": OWN})
    inside_c1 = 78 + 5
    assert owners[inside_c1] == "c1"
    assert c.continue_target(inside_c1) == ("c1", inside_c1)
    assert c.continue_target(78 + OWN + 3)[0] == "c2"
    assert c.joins() == (78, 78 + OWN, 78 + 2 * OWN)


def test_readout_counts_the_trimmed_overlap_frame():
    c = StoryboardTreeContract(*_diner())
    c.select("t1b")
    # root[:78] + A1[:2] + A1b(80 kept) = 160 frames
    c.selected_cut_owners(160, {ROOT_PARENT: ROOT_LENGTH, "t1": OWN, "t1b": OWN})
    assert c.readout(157) == "frame 158 / 160 · A1b frame 79 of 81"
    assert c.readout(0) == "frame 1 / 160 · A frame 1 of 81"
    assert c.joins() == (78, 80)
    assert c.continue_title(157) == "Continue A1b from its frame 158"


def test_a_replay_with_different_manifest_labels_still_owns_by_the_tree():
    c = StoryboardTreeContract(*_diner())
    c.select("t1a")
    owners = c.selected_cut_owners(160, {ROOT_PARENT: ROOT_LENGTH, "t1": OWN, "t1a": OWN})
    assert owners[-1] == "t1a" and owners[79] == "t1"


def test_a_length_mismatch_is_refused():
    c = StoryboardTreeContract(*_diner())
    c.select("t1")
    with pytest.raises(ValueError, match="accounts for"):
        c.selected_cut_owners(10, {ROOT_PARENT: ROOT_LENGTH, "t1": OWN})


def test_row_validation_and_labels():
    c = StoryboardTreeContract(*_diner())
    assert c.validate_rows([_row(""), _row("x", seed="12x")]) == [
        "Row 1 needs a positive prompt.",
        "Row 2 seed must be blank, random or a whole number 0-2147483647.",
    ]
    assert c.validate_rows([_row("a", "random"), _row("b", "2147483647"), _row("c", " 0 ")]) == []
    assert c.validate_rows([_row("a", "2147483648")]) != []
    assert c.validate_rows([]) == ["A Continue has 1 to 6 rows."]
    assert len(c.validate_rows([_row("x")] * 7)) == 1
    assert c.queue_label("sequential", 2) == "Queue chain of 2"
    assert c.queue_label("parallel", 3) == "Queue 3 takes"
    assert c.ai_button() == (False, "AI Assist is not set up")
    reasoned = StoryboardTreeContract(*_diner(), ai_reason=lambda: "No local model is installed.")
    assert reasoned.ai_button() == (False, "No local model is installed.")


def test_continue_is_refused_from_missing_frames():
    c = StoryboardTreeContract(*_diner(missing=("t1", "t1b")))
    allowed, reason = c.continue_allowed("t1b")
    assert allowed is False and reason.startswith("frames missing or changed")
    assert c.continue_allowed("t4") == (True, "")
    assert c.continue_allowed(ROOT_PARENT) == (True, "")


def test_pending_takes_cannot_be_continued():
    tree, views = _diner()
    views["t4"] = TakeView(
        "t4", "pending", "pending", None, None, None, None, False, True, "", False, False
    )
    assert StoryboardTreeContract(tree, views).continue_allowed("t4")[0] is False


def test_engine_line_is_the_inherited_settings():
    assert StoryboardTreeContract(*_diner()).engine_line() == (
        "Engine: wan22_i2v 1.0.0 · 832×480 · 81 f · 16 fps (inherited)"
    )


def test_contract_and_cache_modules_do_not_import_tk():
    for module in (
        "src/gui/view_contracts/storyboard_tree_contract.py",
        "src/video/storyboard_frame_cache.py",
    ):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "tkinter" not in imported, module


# ---------------------------------------------------------------------------------------------- frame cache


def _png(path: Path, size: tuple[int, int] = (1664, 960), color: str = "red") -> str:
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_cache_downscales_and_keeps_the_aspect_ratio(tmp_path):
    cache = FrameCache(viewer_size=(960, 540), thumb_size=(92, 52))
    path = _png(tmp_path / "f.png")
    assert cache.frame(path).size == (936, 540)
    assert cache.thumbnail(path).size[1] <= 52 and cache.thumbnail(path).size[0] <= 92
    small = _png(tmp_path / "s.png", (40, 20))
    assert cache.frame(small).size == (40, 20)  # never enlarged


def test_cache_is_bounded_and_reloads_changed_files(tmp_path):
    cache = FrameCache(max_frames=2, max_thumbnails=1)
    paths = [_png(tmp_path / f"{n}.png", (64, 64)) for n in range(3)]
    for path in paths:
        cache.frame(path)
        cache.thumbnail(path)
    assert cache.sizes() == (2, 1)
    before = cache.frame(paths[2]).getpixel((0, 0))
    _png(tmp_path / "2.png", (64, 64), "blue")
    after = cache.frame(paths[2]).getpixel((0, 0))
    assert before != after


def test_cache_is_thread_safe(tmp_path):
    cache = FrameCache(max_frames=4)
    paths = [_png(tmp_path / f"{n}.png", (64, 64)) for n in range(6)]
    errors: list[Exception] = []

    def work() -> None:
        try:
            for _ in range(20):
                for path in paths:
                    cache.frame(path)
        except Exception as exc:  # noqa: BLE001 - the test reports any failure
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and cache.sizes()[0] <= 4


def test_cache_raises_oserror_for_a_missing_file(tmp_path):
    with pytest.raises(OSError):
        FrameCache().frame(str(tmp_path / "gone.png"))


def test_cards_say_replay_of_and_not_encoded():
    from dataclasses import replace

    tree, views = _diner()
    tree = tree.with_take(replace(_take("r1", ROOT_PARENT, 77), replay_of="t1"))
    views["r1"] = replace(_view("r1"), encoded=False)
    views["t4"] = replace(_view("t4", state="cancelled"), can_resume=True, can_replay=True)
    cards = {
        c.take_id: c
        for col in StoryboardTreeContract(tree, views).columns(False)
        for c in col.cards
    }
    assert cards["r1"].status_text == "completed · not encoded · replay of A1"
    assert cards["t4"].can_resume and cards["t4"].can_replay and not cards["t3"].can_resume
