"""AI-VL-240: the read-only Review label export, on synthetic fixtures only.

No image here is real, no prompt is real and nothing starts a process or touches the network. The fixtures are tiny solid-colour
PNGs, a throwaway SQLite job table and a throwaway Learning record file built in a temporary directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.utils.image_metadata import build_contract_kv, write_png_metadata
from tools.qualification.vl240 import __main__ as cli
from tools.qualification.vl240 import contract, export, sources
from tools.qualification.vl240.contract import Refused

PROMPT_SENTINEL = "zz sentinel prompt words zz"
NAME_SENTINEL = "zzsentinelname"
NOTE_SENTINEL = "zz sentinel note zz"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class World:
    root: Path
    records: Path
    repository: Path
    images: Path

    def image(
        self, name: str, shade: int, *, rating: str | None = None, size: tuple[int, int] = (16, 12)
    ) -> tuple[Path, str]:
        path = self.images / f"{NAME_SENTINEL}_{name}.png"
        Image.new("RGB", size, (shade, 40, 90)).save(path)
        payload: dict[str, Any] = {
            "generation": {"prompt": PROMPT_SENTINEL, "negative_prompt": NOTE_SENTINEL}
        }
        if rating:
            payload["content_visibility"] = {"rating": rating}
        write_png_metadata(
            path, build_contract_kv(payload, job_id=f"job-{name}", run_id="r", stage="txt2img")
        )
        return path, _sha(path)

    def job(
        self,
        job_id: str,
        *,
        parent_job_id: str | None = None,
        parent_artifact_id: str | None = None,
        correction: dict[str, Any] | None = None,
        result_paths: tuple[Path, ...] = (),
        request_paths: tuple[Path, ...] = (),
        kind: str = "reprocess",
        stages: tuple[str, ...] = ("img2img",),
    ) -> None:
        provenance: dict[str, Any] = {"positive_prompt": PROMPT_SENTINEL}
        if correction is not None:
            provenance[contract.GUIDED_CORRECTION_KEY] = correction
        snapshot = {
            "normalized_job": {
                "source": {
                    "kind": kind,
                    "parent_job_id": parent_job_id,
                    "parent_artifact_id": parent_artifact_id,
                },
                "stages": [{"stage_type": stage, "enabled": True} for stage in stages],
                "provenance": {"metadata": provenance},
                "request": {"source_path": [str(path) for path in request_paths]},
            }
        }
        with sqlite3.connect(self.repository) as connection:
            connection.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                (
                    job_id,
                    parent_job_id,
                    parent_artifact_id,
                    "completed",
                    json.dumps(snapshot),
                    json.dumps(
                        {"artifact": {"output_path": str(result_paths[0])}} if result_paths else {}
                    ),
                    json.dumps([str(path) for path in result_paths]),
                ),
            )

    def judgment(
        self,
        run_id: str,
        job_id: str,
        source_sha: str,
        result_sha: str,
        rows: list[dict[str, Any]],
        *,
        preference: str = "prefer result",
        timestamp: str = "2026-11-01T10:00:00+00:00",
        source: str = "operator_review",
    ) -> None:
        record = {
            "run_id": run_id,
            "timestamp": timestamp,
            "metadata": {
                "source": "review_tab",
                "user_notes": NOTE_SENTINEL,
                "review_context": {
                    contract.GUIDED_IMPROVEMENT_KEY: {
                        "schema": contract.GUIDED_IMPROVEMENT_SCHEMA,
                        "source": source,
                        "source_sha256": source_sha,
                        "result_sha256": result_sha,
                        "result_job_id": job_id,
                        "result_size": [16, 12],
                        "judgments": rows,
                        "overall_preference": preference,
                    }
                },
            },
        }
        with self.records.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def correction(
    category: str = "Hands", action: str = "ADetailer hand pass", region: Any = (0, 0, 8, 8)
) -> dict[str, Any]:
    return {
        "schema": contract.GUIDED_CORRECTION_SCHEMA,
        "action": action,
        "category": category,
        "region": list(region) if region is not None else None,
        "source_size": [16, 12],
    }


def row(
    category: str = "Hands", outcome: str = "improved", region: Any = (0, 0, 8, 8)
) -> dict[str, Any]:
    return {
        "category": category,
        "after_region": list(region) if region else None,
        "outcome": outcome,
    }


@pytest.fixture
def world(tmp_path: Path) -> World:
    (tmp_path / "images").mkdir()
    repository = tmp_path / "state" / "jobs.sqlite3"
    repository.parent.mkdir()
    with sqlite3.connect(repository) as connection:
        connection.execute(
            "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, parent_job_id TEXT, parent_artifact_id TEXT, status TEXT, "
            "njr_snapshot TEXT, result_json TEXT, artifact_references TEXT)"
        )
    records = tmp_path / "learning" / "learning_records.jsonl"
    records.parent.mkdir()
    records.write_text("", encoding="utf-8")
    return World(tmp_path, records, repository, tmp_path / "images")


@pytest.fixture
def populated(world: World) -> World:
    before1, b1 = world.image("a_before", 10)
    after1, a1 = world.image("a_after", 20)
    world.job(
        "job-1",
        parent_artifact_id=f"sha256:{b1}",
        correction=correction(),
        result_paths=(after1,),
        request_paths=(before1,),
    )
    world.judgment(
        "rec-1", "job-1", b1, a1, [row("Hands", "improved"), row("Face", "worsened", None)]
    )
    before2, b2 = world.image("b_before", 30)
    world.job(
        "job-2",
        parent_artifact_id=f"sha256:{b2}",
        correction=correction("Face", "Edit mask", None),
        request_paths=(before2,),
    )
    return world


def collect(world: World, mode: str = "sfw") -> export.Collected:
    return export.collect(world.records, world.repository, visibility_mode=mode)


def snapshot_of(*folders: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(folder)) + str(folder): (path.stat().st_size, path.stat().st_mtime_ns)
        for folder in folders
        for path in folder.rglob("*")
        if path.is_file()
    }


# --------------------------------------------------------------------------------------------------- schema, manifest


def test_export_document_and_manifest(populated: World, tmp_path: Path) -> None:
    out = tmp_path.parent / f"{tmp_path.name}_out"
    folder = export.write_export(collect(populated), out)
    document = json.loads((folder / contract.DOCUMENT_NAME).read_text(encoding="utf-8"))
    manifest = json.loads((folder / contract.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert document["schema"] == "stablenew.vl240.review_export/1"
    assert set(document) == {"schema", "images", "pairs", "provenance"}
    assert len(document["images"]) == 3 and len(document["pairs"]) == 1
    for image in document["images"]:
        assert set(image) == {
            "image_id",
            "sha256",
            "file",
            "width",
            "height",
            "model_family",
            "clean_confirmed",
            "findings",
            "subject_count",
            "roles",
            "record_ids",
        }
        assert (
            image["image_id"].startswith("img-")
            and image["file"] == f"images/{image['sha256']}.png"
        )
        assert (image["width"], image["height"]) == (16, 12)
        assert (
            image["clean_confirmed"] is False
            and image["subject_count"] is None
            and image["model_family"] is None
        )
    assert {f["path"]: f["sha256"] for f in manifest["files"]} == {
        i["file"]: i["sha256"] for i in document["images"]
    }
    assert (
        manifest["document"]["sha256"]
        == hashlib.sha256((folder / contract.DOCUMENT_NAME).read_bytes()).hexdigest()
    )
    assert sorted(p.name for p in (folder / "images").iterdir()) == sorted(
        f"{i['sha256']}.png" for i in document["images"]
    )
    pair = document["pairs"][0]
    assert set(pair) == {
        "pair_id",
        "before_image_id",
        "after_image_id",
        "intervention",
        "judgment",
        "region_judgments",
        "overall_preference",
        "record_ids",
    }
    assert (
        document["provenance"]["labeler"] == "human"
        and document["provenance"]["contains_prompt_text"] is False
    )
    assert export.verify_export(folder) == {"ok": True, "problems": {}, "images": 3}
    # tampering is caught
    victim = next((folder / "images").iterdir())
    victim.write_bytes(victim.read_bytes() + b"x")
    assert export.verify_export(folder)["problems"] == {"file_hash_mismatch": 1}


def test_ids_are_opaque_and_deterministic(populated: World) -> None:
    first = export.build_document(collect(populated))
    second = export.build_document(collect(populated))
    assert first["images"] == second["images"] and first["pairs"] == second["pairs"]
    assert [i["image_id"] for i in first["images"]] == ["img-0001", "img-0002", "img-0003"]


# ----------------------------------------------------------------------------------------------- confirmed-only export


def test_findings_come_only_from_a_queued_guided_correction(populated: World) -> None:
    document = export.build_document(collect(populated))
    by_sha = {i["sha256"]: i for i in document["images"]}
    found = [
        (i["findings"][0]["category"], i["findings"][0]["region"])
        for i in by_sha.values()
        if i["findings"]
    ]
    assert sorted(found, key=lambda item: item[0]) == [
        ("Face", None),
        ("Hands", {"left": 0, "top": 0, "right": 8, "bottom": 8}),
    ]
    for item in by_sha.values():
        assert item["clean_confirmed"] is False
        assert all(f["severity"] is None for f in item["findings"])
    # the "after" image carries no finding: nobody confirmed a defect in it
    assert [i["findings"] for i in document["images"] if i["roles"] == ["after"]] == [[]]


def test_pair_judgment_vocabulary_and_mixed(populated: World) -> None:
    pair = export.build_document(collect(populated))["pairs"][0]
    assert pair["judgment"] == "mixed"  # improved hands, worsened face
    assert {item["judgment"] for item in pair["region_judgments"]} == {"helped", "worse"}
    assert pair["overall_preference"] == "prefer_result"
    assert pair["intervention"] == {
        "kind": "guided_correction",
        "stages": ["img2img"],
        "action": "ADetailer hand pass",
        "category": "Hands",
        "region": {"left": 0, "top": 0, "right": 8, "bottom": 8},
    }
    assert set(contract.OUTCOME_TO_JUDGMENT.values()) == {
        "helped",
        "no_benefit",
        "worse",
        "inconclusive",
    }


def test_latest_judgment_per_job_wins(world: World) -> None:
    before, b = world.image("x_before", 1)
    after, a = world.image("x_after", 2)
    world.job(
        "job-x",
        parent_artifact_id=f"sha256:{b}",
        correction=correction(),
        result_paths=(after,),
        request_paths=(before,),
    )
    world.judgment(
        "old", "job-x", b, a, [row(outcome="worsened")], timestamp="2026-11-01T00:00:00+00:00"
    )
    world.judgment(
        "new", "job-x", b, a, [row(outcome="uncertain")], timestamp="2026-11-02T00:00:00+00:00"
    )
    pairs = export.build_document(collect(world))["pairs"]
    assert [p["judgment"] for p in pairs] == ["inconclusive"] and pairs[0]["record_ids"][
        "learning_record"
    ] == "new"


def test_unconfirmed_and_non_operator_records_are_never_labels(world: World) -> None:
    before, b = world.image("y_before", 3)
    after, a = world.image("y_after", 4)
    world.job(
        "job-y",
        parent_artifact_id=f"sha256:{b}",
        correction=correction(),
        result_paths=(after,),
        request_paths=(before,),
    )
    world.judgment("not-human", "job-y", b, a, [row()], source="model_suggestion")
    world.judgment("unreviewed", "job-y2", b, a, [row(outcome="unreviewed")])
    # a pixel-difference or ADetailer-pass record with paths but no digest is not a guided judgment and is ignored
    with world.records.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "run_id": "legacy",
                    "timestamp": "t",
                    "metadata": {
                        "review_context": {
                            "adetailer_outcome_review": {
                                "face": "improved",
                                "reviewed_pair": {"input_image": "a.png", "output_image": "b.png"},
                            }
                        }
                    },
                }
            )
            + "\n"
        )
        handle.write("not json guided_improvement_review\n")
    collected = collect(world)
    document = export.build_document(collected)
    assert document["pairs"] == []
    assert sorted(item.code for item in collected.refused) == [
        "malformed_judgment",
        "not_an_operator_judgment",
    ]
    assert collected.unparseable_lines == 1
    # the finding behind the queued correction is still exported once
    assert [len(i["findings"]) for i in document["images"]] == [1]


def test_malformed_corrections_are_refused(world: World) -> None:
    img, digest = world.image("z", 5)
    claim = f"sha256:{digest}"
    world.job(
        "bad-category",
        parent_artifact_id=claim,
        correction=correction("Eyebrows"),
        request_paths=(img,),
    )
    world.job(
        "bad-region",
        parent_artifact_id=claim,
        correction=correction(region=(0, 0, 99, 99)),
        request_paths=(img,),
    )
    world.job("no-digest", parent_artifact_id=None, correction=correction(), request_paths=(img,))
    collected = collect(world)
    assert {(i.record_id, i.code) for i in collected.refused} == {
        ("bad-category", "malformed_correction"),
        ("bad-region", "malformed_correction"),
        ("no-digest", "no_recorded_source_digest"),
    }
    assert collected.images == {}


# ----------------------------------------------------------------------------------------------------------- visibility


def test_visibility_rules(world: World) -> None:
    before, b = world.image("v_before", 6)
    after, a = world.image("v_after", 7, rating="nsfw")
    world.job(
        "job-v",
        parent_artifact_id=f"sha256:{b}",
        correction=correction(),
        result_paths=(after,),
        request_paths=(before,),
    )
    world.judgment("rec-v", "job-v", b, a, [row()])
    hidden = export.collect(world.records, world.repository, visibility_mode="sfw")
    assert hidden.pairs == [] and hidden.withheld["pair"] == 1
    assert list(hidden.images) == [
        b
    ]  # the visible original keeps its confirmed finding, the restricted result is absent
    shown = export.collect(world.records, world.repository, visibility_mode="nsfw")
    assert len(shown.pairs) == 1 and set(shown.images) == {a, b}
    corrupt_before, c = world.image("v_c", 8, rating="nsfw")
    world.job(
        "job-c",
        parent_artifact_id=f"sha256:{c}",
        correction=correction(),
        request_paths=(corrupt_before,),
    )
    assert c not in export.collect(world.records, world.repository, visibility_mode="sfw").images
    assert (
        export.collect(world.records, world.repository, visibility_mode="nsfw").images[c].findings
    )
    with pytest.raises(Refused, match="unknown_visibility_mode"):
        export.collect(world.records, world.repository, visibility_mode="all")


# --------------------------------------------------------------------------------------------- hash binding and refusal


def test_records_that_cannot_bind_to_a_hash_are_refused(world: World) -> None:
    before, b = world.image("h_before", 9)
    after, a = world.image("h_after", 10)
    world.job(
        "changed",
        parent_artifact_id=f"sha256:{b}",
        correction=correction(),
        result_paths=(after,),
        request_paths=(before,),
    )
    world.judgment("r-changed", "changed", b, a, [row()])
    after.write_bytes(after.read_bytes() + b"\0")  # the result changed after the review
    world.job(
        "gone",
        parent_artifact_id=f"sha256:{'1' * 64}",
        correction=correction(),
        result_paths=(),
        request_paths=(world.images / "missing.png",),
    )
    world.judgment("r-missing-job", "no-such-job", b, a, [row()])
    world.judgment("r-bad-digest", "changed", "not-a-digest", a, [row()])
    other, o = world.image("h_other", 11)
    world.job(
        "mismatch",
        parent_artifact_id=f"sha256:{o}",
        correction=correction(),
        result_paths=(after,),
        request_paths=(other,),
    )
    world.judgment("r-mismatch", "mismatch", b, a, [row()])
    collected = collect(world)
    codes = {item.record_id: item.code for item in collected.refused}
    assert codes["r-changed"] == "image_changed_since_review"
    assert codes["gone"] == "image_unavailable"
    assert codes["r-missing-job"] == "job_not_found"
    assert codes["r-bad-digest"] == "malformed_digest"
    assert codes["r-mismatch"] == "judgment_source_mismatch"
    assert collected.pairs == []


def test_refuses_to_read_what_is_missing_without_creating_it(tmp_path: Path) -> None:
    with (
        pytest.raises(Refused, match="job_repository_unreadable"),
        sources.open_repository(tmp_path / "absent.sqlite3"),
    ):
        pass
    assert not (tmp_path / "absent.sqlite3").exists()
    with pytest.raises(Refused, match="learning_records_unreadable"):
        sources.read_judgment_records(tmp_path / "absent.jsonl")
    assert not (tmp_path / "absent.jsonl").exists()


# ----------------------------------------------------------------------------------------------- content and logs


def test_no_content_reaches_output_stdout_or_errors(
    populated: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    populated.judgment("rec-bad", "no-such-job", "0" * 64, "1" * 64, [row()])
    out = tmp_path.parent / f"{tmp_path.name}_content"
    argv = [
        "export",
        "--learning-records",
        str(populated.records),
        "--job-repository",
        str(populated.repository),
        "--out",
        str(out),
    ]
    assert cli.main(argv) == 0
    assert cli.main(["describe", *argv[1:5]]) == 0
    printed = capsys.readouterr().out
    exported = b"".join(p.read_bytes() for p in out.rglob("*.json"))
    haystack = printed.encode() + exported
    for sentinel in (PROMPT_SENTINEL, NOTE_SENTINEL, NAME_SENTINEL):
        assert sentinel.encode() not in haystack
    assert not [p for p in out.rglob("*") if NAME_SENTINEL in p.name]
    err = Refused("image_unavailable", "rec-1")
    assert str(err) == "image_unavailable" and NAME_SENTINEL not in repr(err)
    # a refusal from the CLI is a code only
    assert (
        cli.main(
            [
                "describe",
                "--learning-records",
                str(populated.records),
                "--job-repository",
                str(tmp_path / "no.sqlite3"),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out) == {"refused": "job_repository_unreadable"}


def test_describe_counts_progress_and_no_ids(populated: World) -> None:
    report = export.describe(collect(populated), targets="full")
    assert report["counts"]["images"] == 3 and report["counts"]["pairs"] == 1
    assert (
        report["counts"]["defect_images_by_category"]["Hands"] == 1
        and report["counts"]["defect_images_by_category"]["Face"] == 1
    )
    assert report["counts"]["pairs_by_judgment"]["mixed"] == 1
    progress = report["progress"]
    assert progress["defect_images"] == {
        "have": 2,
        "target": 30,
        "remaining": 28,
        "met": False,
        "recordable_in_review": True,
    }
    assert progress["clean_confirmed_images"]["recordable_in_review"] is False
    assert progress["judged_pairs"]["target"] == 12
    assert (
        export.describe(collect(populated), targets="pilot")["progress"]["judged_pairs"]["target"]
        == 6
    )
    text = json.dumps(report)
    assert "img-" not in text and "pair-" not in text
    assert not any(
        len(token) == 64 and set(token) <= set("0123456789abcdef")
        for token in text.replace('"', " ").split()
    )


# --------------------------------------------------------------------------------------------- read-only guarantees


def test_zero_writes_to_review_history_or_queue_stores(populated: World, tmp_path: Path) -> None:
    folders = (populated.records.parent, populated.repository.parent, populated.images)
    for path in (populated.records, populated.repository):
        os.chmod(path, 0o444)  # a write attempt on either store would fail loudly
    before = snapshot_of(*folders)
    listing = {folder: sorted(p.name for p in folder.iterdir()) for folder in folders}
    export.describe(collect(populated))
    export.write_export(collect(populated), tmp_path.parent / f"{tmp_path.name}_ro")
    assert snapshot_of(*folders) == before
    assert {
        folder: sorted(p.name for p in folder.iterdir()) for folder in folders
    } == listing  # no -wal, -shm, journal or temp file


def test_repository_connection_cannot_write(populated: World) -> None:
    with sources.open_repository(populated.repository) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO jobs(job_id) VALUES ('x')")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM jobs")


def test_live_wal_repository_is_read_from_a_snapshot_without_touching_it(world: World) -> None:
    before, b = world.image("w_before", 12)
    live = sqlite3.connect(
        world.repository
    )  # stands in for the running app: WAL mode, recent rows only in the -wal file
    live.execute("PRAGMA journal_mode = WAL")
    live.execute("PRAGMA wal_autocheckpoint = 0")
    live.commit()
    try:
        world.job(
            "job-w",
            parent_artifact_id=f"sha256:{b}",
            correction=correction(),
            request_paths=(before,),
        )
        assert world.repository.with_name("jobs.sqlite3-wal").exists()
        fingerprint = {
            p.name: (p.stat().st_size, p.stat().st_mtime_ns)
            for p in world.repository.parent.iterdir()
        }
        assert list(collect(world).images) == [b]
        assert {
            p.name: (p.stat().st_size, p.stat().st_mtime_ns)
            for p in world.repository.parent.iterdir()
        } == fingerprint
    finally:
        live.close()


def test_snapshot_is_removed(world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live = sqlite3.connect(world.repository)
    live.execute("PRAGMA journal_mode = WAL")
    live.execute("PRAGMA wal_autocheckpoint = 0")
    live.execute("INSERT INTO jobs(job_id, njr_snapshot) VALUES ('j', '{}')")
    live.commit()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    try:
        with sources.open_repository(world.repository):
            assert any(scratch.iterdir())
        assert not any(scratch.iterdir())
    finally:
        live.close()


def test_no_network_and_no_process(
    populated: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the exporter must not use the network or start a process")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    export.describe(collect(populated))
    export.write_export(collect(populated), tmp_path.parent / f"{tmp_path.name}_np")
    package = Path(contract.__file__).parent
    text = "\n".join(p.read_text(encoding="utf-8") for p in package.glob("*.py"))
    for forbidden_import in (
        "import subprocess",
        "import socket",
        "import urllib",
        "import requests",
        "import http",
        "import ctypes",
    ):
        assert forbidden_import not in text


# ----------------------------------------------------------------------------------------------------- output safety


def test_output_inside_git_is_refused_and_folders_are_not_reused(
    populated: World, tmp_path: Path
) -> None:
    repo_root = Path(contract.__file__).resolve().parents[3]
    with pytest.raises(Refused, match="output_inside_git"):
        export.write_export(collect(populated), repo_root / "scratch_export_must_not_exist")
    assert not (repo_root / "scratch_export_must_not_exist").exists()
    inside = tmp_path / "work"
    (inside / ".git").mkdir(parents=True)
    with pytest.raises(Refused, match="output_inside_git"):
        export.write_export(collect(populated), inside / "out")
    out = tmp_path.parent / f"{tmp_path.name}_reuse"
    stamp = export.datetime(2026, 11, 15, 12, 0, 0, tzinfo=export.UTC)
    export.write_export(collect(populated), out, exported_at=stamp)
    with pytest.raises(Refused, match="output_unwritable"):
        export.write_export(collect(populated), out, exported_at=stamp)


def test_empty_evidence_exports_nothing(world: World, tmp_path: Path) -> None:
    with pytest.raises(Refused, match="nothing_to_export"):
        export.write_export(collect(world), tmp_path.parent / f"{tmp_path.name}_empty")


def test_hard_link_option_keeps_hash_names(populated: World, tmp_path: Path) -> None:
    folder = export.write_export(
        collect(populated), tmp_path.parent / f"{tmp_path.name}_link", link=True
    )
    assert export.verify_export(folder)["ok"] is True


# --------------------------------------------------------------------------------------------------- pin to Review


def test_vocabulary_is_pinned_to_review() -> None:
    from src.pipeline.adetailer_effectiveness import VISUAL_OUTCOMES
    from src.review.findings import CORRECTION_KEY, Action, Category

    assert contract.CATEGORIES == tuple(item.value for item in Category)
    assert contract.ACTIONS == tuple(item.value for item in Action)
    assert set(contract.OUTCOME_TO_JUDGMENT) == set(VISUAL_OUTCOMES) - {"unreviewed"}
    assert contract.GUIDED_CORRECTION_KEY == CORRECTION_KEY
    source = (
        Path(__file__).resolve().parents[2] / "src" / "review" / "improvement_evidence.py"
    ).read_text(encoding="utf-8")
    assert (
        contract.GUIDED_IMPROVEMENT_SCHEMA in source
        and f'"{contract.GUIDED_IMPROVEMENT_KEY}"' in source
    )
    from src.review.improvement_evidence import OVERALL_PREFERENCES

    assert set(contract.PREFERENCE_TO_VALUE) == set(OVERALL_PREFERENCES)


def test_default_paths_are_the_checkouts_stores_and_create_nothing(tmp_path: Path) -> None:
    records, repository = cli._default_paths(tmp_path)
    assert records == (tmp_path / "data" / "learning" / "learning_records.jsonl").resolve()
    assert repository.name == "jobs.sqlite3" and tmp_path.resolve() in repository.parents
    assert not any(tmp_path.iterdir())
