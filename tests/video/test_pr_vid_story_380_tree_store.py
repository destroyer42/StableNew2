"""PR-VID-STORY-380: the storyboard tree file model and its store."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_tree import (
    MAX_ROWS,
    TREE_SCHEMA,
    StoryboardTree,
    StoryboardTreeError,
    Take,
    TreeRoot,
)
from src.video.storyboard_tree_store import StoryboardTreeStore, default_root

NOW = "2026-11-21T10:00:00+00:00"
SHA = "a" * 64


def _root() -> TreeRoot:
    return TreeRoot(
        kind="clip",
        job_id="job-1",
        image_path="",
        image_sha256="",
        manifest_path="C:/out/root/cut.json",
        manifest_sha256=SHA,
        settings=(("loras", ("x", "y")), ("steps", 20), ("workflow_id", "wan22")),
        fps=16,
        width=832,
        height=480,
        smoothing_text="",
    )


def _take(take_id: str, parent_id: str, **over: Any) -> Take:
    base: dict[str, Any] = {
        "take_id": take_id,
        "parent_id": parent_id,
        "handoff_index": 12,
        "mode": "parallel",
        "batch_id": "b1",
        "chain_position": 0,
        "segment_index": 0,
        "prompt": f"prompt {take_id}",
        "negative_prompt": "",
        "seed_intent": "random",
        "attempts": (),
        "replay_of": None,
        "mark": "none",
        "created_at": NOW,
    }
    base.update(over)
    return Take(**base)


def _tree(edges: list[tuple[str, str]] | None = None) -> StoryboardTree:
    tree = StoryboardTree(
        storyboard_id="1" * 32,
        title="Test",
        revision=0,
        created_at=NOW,
        updated_at=NOW,
        root=_root(),
        takes=(),
    )
    for take_id, parent in edges if edges is not None else [("t1", ROOT_PARENT)]:
        tree = tree.with_take(_take(take_id, parent))
    return tree


def _huge(tree: StoryboardTree) -> StoryboardTree:
    takes = tuple(_take(f"h{i}", ROOT_PARENT, prompt="x" * 60000) for i in range(40))
    return replace(tree, takes=takes)


def test_labels_alternate_digits_and_letters() -> None:
    tree = _tree(edges=[("a", "root"), ("b", "root"), ("c", "a"), ("d", "a"), ("e", "d")])
    assert tree.label(ROOT_PARENT) == "A"
    assert [tree.label(t) for t in "abcde"] == ["A1", "A2", "A1a", "A1b", "A1b1"]
    assert [tree.depth(t) for t in "abcde"] == [1, 1, 2, 2, 3]
    assert tree.depth(ROOT_PARENT) == 0
    assert [t.take_id for t in tree.children("a")] == ["c", "d"]
    assert [t.take_id for t in tree.children(ROOT_PARENT)] == ["a", "b"]


def test_letters_run_past_z() -> None:
    edges = [("p", "root")] + [(f"c{i}", "p") for i in range(1, 29)]
    tree = _tree(edges=edges)
    assert tree.label("c1") == "A1a"
    assert tree.label("c26") == "A1z"
    assert tree.label("c27") == "A1aa"
    assert tree.label("c28") == "A1ab"


def test_unknown_take_is_refused() -> None:
    with pytest.raises(StoryboardTreeError):
        _tree().label("nope")
    with pytest.raises(StoryboardTreeError):
        _tree().depth("nope")


def test_round_trip_and_cas(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    saved = store.save(_tree())
    assert store.load(saved.storyboard_id) == saved and saved.revision == 1
    with pytest.raises(StoryboardTreeError, match="Revision conflict"):
        store.save(replace(saved, revision=0))
    again = store.save(saved)
    assert again.revision == 2 and store.load(saved.storyboard_id) == again


def test_missing_file_with_revision_is_refused(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    with pytest.raises(StoryboardTreeError, match="missing"):
        store.save(replace(_tree(), revision=3))


def test_malformed_and_future_files_are_preserved(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    path = tmp_path / ("f" * 32 + ".json")
    path.write_text('{"schema": "stablenew.storyboard-tree.v9"}', encoding="utf-8")
    with pytest.raises(StoryboardTreeError):
        store.load("f" * 32)
    assert path.read_text(encoding="utf-8") == '{"schema": "stablenew.storyboard-tree.v9"}'
    assert ("f" * 32, "(unreadable)") == store.list_trees()[0][:2]
    with pytest.raises(StoryboardTreeError):
        store.save(replace(_tree(), storyboard_id="f" * 32))
    assert path.read_text(encoding="utf-8") == '{"schema": "stablenew.storyboard-tree.v9"}'


def test_garbage_and_duplicate_key_files_are_preserved(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    bad = tmp_path / ("e" * 32 + ".json")
    bad.write_text("{not json", encoding="utf-8")
    dup = tmp_path / ("d" * 32 + ".json")
    dup.write_text('{"schema": "x", "schema": "y"}', encoding="utf-8")
    for storyboard_id in ("e" * 32, "d" * 32):
        with pytest.raises(StoryboardTreeError):
            store.load(storyboard_id)
    assert bad.read_text(encoding="utf-8") == "{not json"
    assert {row[0] for row in store.list_trees()} == {"e" * 32, "d" * 32}


def test_size_cap_refuses_without_writing(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    saved = store.save(_tree())
    with pytest.raises(StoryboardTreeError, match="exceeds the 2 MB limit"):
        store.save(_huge(saved))
    assert store.load(saved.storyboard_id) == saved


def test_no_status_or_output_paths_are_stored() -> None:
    assert not {"status", "output_path", "plan"} & set(json.dumps(_tree().to_dict()).split('"'))


def test_list_trees_orders_newest_first_and_ignores_strangers(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path / "missing")
    assert store.list_trees() == []
    store = StoryboardTreeStore(tmp_path)
    first = store.save(replace(_tree(), storyboard_id="1" * 32, title="One"))
    second = store.save(replace(_tree(), storyboard_id="2" * 32, title="Two"))
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    rows = store.list_trees()
    assert [r[0] for r in rows] == [second.storyboard_id, first.storyboard_id]
    assert rows[0][1] == "Two" and rows[0][2] == second.updated_at


def test_path_escape_and_bad_ids_are_refused(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    with pytest.raises(StoryboardTreeError):
        store.load("../" + "1" * 29)
    with pytest.raises(StoryboardTreeError):
        store.load("short")


def test_a_stale_lock_refuses_the_save(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    lock = tmp_path / ("1" * 32 + ".lock")
    lock.write_text("", encoding="utf-8")
    with pytest.raises(StoryboardTreeError, match="being saved elsewhere"):
        store.save(_tree())
    assert lock.exists()


def test_lock_is_released_after_save_and_after_refusal(tmp_path: Path) -> None:
    store = StoryboardTreeStore(tmp_path)
    saved = store.save(_tree())
    with pytest.raises(StoryboardTreeError):
        store.save(replace(saved, revision=0))
    assert not list(tmp_path.glob("*.lock"))


def test_default_root_is_under_stablenew(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_root() == tmp_path / "StableNew" / "storyboard_trees"


def test_from_dict_is_strict() -> None:
    data = _tree().to_dict()
    assert data["schema"] == TREE_SCHEMA
    assert StoryboardTree.from_dict(data) == StoryboardTree.from_dict(json.loads(json.dumps(data)))
    mutations: list[Any] = [
        lambda d: d.update(extra=1),
        lambda d: d.pop("title"),
        lambda d: d["root"].update(extra=1),
        lambda d: d["takes"][0].update(extra=1),
        lambda d: d["takes"][0].pop("prompt"),
        lambda d: d.update(schema="stablenew.storyboard-tree.v2"),
        lambda d: d.update(revision=-1),
        lambda d: d.update(revision=True),
        lambda d: d.update(storyboard_id="nope"),
        lambda d: d.update(created_at="not a date"),
        lambda d: d.update(created_at="2026-11-21T10:00:00"),
        lambda d: d["root"].update(kind="video"),
        lambda d: d["root"].update(manifest_sha256="zz"),
        lambda d: d["root"].update(fps=0),
        lambda d: d["root"].update(width=True),
        lambda d: d["takes"][0].update(mode="serial"),
        lambda d: d["takes"][0].update(mark="starred"),
        lambda d: d["takes"][0].update(handoff_index=-1),
        lambda d: d["takes"][0].update(chain_position="0"),
        lambda d: d["takes"][0].update(attempts="job"),
        lambda d: d["takes"][0].update(attempts=[1]),
        lambda d: d["takes"][0].update(parent_id="missing"),
        lambda d: d["takes"][0].update(take_id="root"),
        lambda d: d["takes"][0].update(replay_of="missing"),
        lambda d: d["takes"][0].update(prompt="x" * 70000),
        lambda d: d["takes"].append(dict(d["takes"][0])),
    ]
    for mutate in mutations:
        broken = json.loads(json.dumps(data))
        mutate(broken)
        with pytest.raises(StoryboardTreeError):
            StoryboardTree.from_dict(broken)
    with pytest.raises(StoryboardTreeError):
        StoryboardTree.from_dict([])


def test_a_parent_must_precede_its_children() -> None:
    data = _tree(edges=[("a", "root"), ("b", "a")]).to_dict()
    data["takes"].reverse()
    with pytest.raises(StoryboardTreeError):
        StoryboardTree.from_dict(data)


def test_handoff_none_and_replay_round_trip() -> None:
    tree = _tree(edges=[("a", "root")]).with_take(
        _take("b", "a", handoff_index=None, mode="sequential", chain_position=1, replay_of="a")
    )
    again = StoryboardTree.from_dict(json.loads(json.dumps(tree.to_dict())))
    assert again == tree
    assert again.takes[1].handoff_index is None and again.takes[1].replay_of == "a"
    assert dict(again.root.settings)["loras"] == ("x", "y")


def test_edits_return_new_trees_and_validate() -> None:
    tree = _tree(edges=[("a", "root"), ("b", "a")])
    kept = tree.with_mark("a", "kept")
    assert kept.takes[0].mark == "kept" and tree.takes[0].mark == "none"
    assert kept.with_attempt("a", "job-9").takes[0].attempts == ("job-9",)
    assert kept.with_attempt("a", "job-9").with_attempt("a", "job-9").takes[0].attempts == (
        "job-9",
    )
    with pytest.raises(StoryboardTreeError):
        tree.with_mark("a", "starred")
    with pytest.raises(StoryboardTreeError):
        tree.with_mark("zz", "kept")
    with pytest.raises(StoryboardTreeError):
        tree.with_attempt("zz", "job")
    with pytest.raises(StoryboardTreeError):
        tree.with_attempt("a", "")
    with pytest.raises(StoryboardTreeError):
        tree.with_take(_take("a", "root"))
    with pytest.raises(StoryboardTreeError):
        tree.with_take(_take("c", "missing"))
    assert tree.renamed("New name").title == "New name"
    with pytest.raises(StoryboardTreeError):
        tree.renamed("   ")


def test_without_takes_refuses_to_orphan_children() -> None:
    tree = _tree(edges=[("a", "root"), ("b", "a"), ("c", "root")])
    assert [t.take_id for t in tree.without_takes({"b", "c"}).takes] == ["a"]
    assert [t.take_id for t in tree.without_takes({"a", "b"}).takes] == ["c"]
    with pytest.raises(StoryboardTreeError):
        tree.without_takes({"a"})
    with pytest.raises(StoryboardTreeError):
        tree.without_takes({"zz"})


def test_duplicate_gets_a_new_identity_and_revision_zero() -> None:
    tree = replace(_tree(), revision=4)
    copy = tree.duplicate("Copy")
    assert copy.storyboard_id != tree.storyboard_id and copy.revision == 0
    assert copy.title == "Copy" and copy.takes == tree.takes and copy.root == tree.root
    assert StoryboardTree.from_dict(copy.to_dict()) == copy


def test_max_rows_constant() -> None:
    assert MAX_ROWS == 6
