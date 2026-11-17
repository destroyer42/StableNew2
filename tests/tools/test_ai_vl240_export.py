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
    before3, b3 = world.image("c_before", 40)
    after3, a3 = world.image("c_after", 50)
    world.job(
        "job-3",
        parent_artifact_id=f"sha256:{b3}",
        correction=correction("Anatomy", "Reprocess with img2img", None),
        result_paths=(after3,),
        request_paths=(before3,),
        stages=("img2img",),
    )
    world.judgment(
        "rec-3", "job-3", b3, a3, [row("Anatomy", "worsened", None)], preference="prefer original"
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
    assert set(document) == {"schema", "images", "pairs", "mixed_pairs", "provenance"}
    assert len(document["images"]) == 5 and len(document["pairs"]) == 1
    assert len(document["mixed_pairs"]) == 1 and document["pairs"][0]["judgment"] == "worse"
    assert {p["judgment"] for p in document["pairs"]} <= {
        "helped",
        "no_benefit",
        "worse",
        "inconclusive",
    }
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
    assert export.verify_export(folder) == {"ok": True, "problems": {}, "images": 5}
    # tampering is caught
    victim = next((folder / "images").iterdir())
    victim.write_bytes(victim.read_bytes() + b"x")
    assert export.verify_export(folder)["problems"] == {"file_hash_mismatch": 1}


def test_ids_are_opaque_and_deterministic(populated: World) -> None:
    first = export.build_document(collect(populated))
    second = export.build_document(collect(populated))
    assert first["images"] == second["images"] and first["pairs"] == second["pairs"]
    assert [i["image_id"] for i in first["images"]] == [f"img-000{n}" for n in range(1, 6)]


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
        ("Anatomy", None),
        ("Face", None),
        ("Hands", [0, 0, 8, 8]),
    ]
    for item in by_sha.values():
        assert item["clean_confirmed"] is False
        assert all(f["severity"] is None for f in item["findings"])
    # the "after" image carries no finding: nobody confirmed a defect in it
    assert [i["findings"] for i in document["images"] if i["roles"] == ["after"]] == [[], []]


def test_pair_judgment_vocabulary_and_mixed(populated: World) -> None:
    document = export.build_document(collect(populated))
    assert [p["judgment"] for p in document["pairs"]] == ["worse"]
    assert document["pairs"][0]["overall_preference"] == "prefer_original"
    pair = document["mixed_pairs"][0]
    assert (
        pair["judgment"] == "mixed"
    )  # improved hands, worsened face; never forced into one of the four
    assert {item["judgment"] for item in pair["region_judgments"]} == {"helped", "worse"}
    assert pair["overall_preference"] == "prefer_result"
    assert pair["intervention"] == {
        "kind": "guided_correction",
        "stages": ["img2img"],
        "action": "ADetailer hand pass",
        "category": "Hands",
        "region": [0, 0, 8, 8],
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
    assert report["counts"]["images"] == 5
    assert report["counts"]["pairs"] == 1 and report["counts"]["mixed_pairs"] == 1
    assert (
        report["counts"]["defect_images_by_category"]["Hands"] == 1
        and report["counts"]["defect_images_by_category"]["Face"] == 1
    )
    assert report["counts"]["defect_images_by_category"]["Anatomy"] == 1
    assert report["counts"]["pairs_by_judgment"]["mixed"] == 1
    assert report["counts"]["pairs_by_judgment"]["worse"] == 1
    progress = report["progress"]
    assert progress["defect_images"] == {
        "have": 3,
        "target": 30,
        "remaining": 27,
        "met": False,
        "recordable_in_review": True,
    }
    assert (
        progress["clean_confirmed_images"]["recordable_in_review"] is True
    )  # Save inspection (AI-VL-243)
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


# ------------------------------------------------------------------------------- Save inspection (AI-VL-243)


def _save_inspection(
    world: World,
    path: Path,
    verdict: str,
    findings: tuple[tuple[str, Any, Any], ...] = (),
    *,
    subject_count: int | None = None,
) -> None:
    """Write one inspection the way Review does: through ``review_evidence`` and ``LearningRecordWriter``."""

    from src.learning.learning_record import LearningRecordWriter
    from src.review import review_evidence
    from src.review.assist.contracts import SourceIdentity
    from src.review.findings import (
        Category,
        Certainty,
        Confirmation,
        Finding,
        FindingSource,
        Origin,
        Region,
        Severity,
    )

    identity = SourceIdentity(_sha(path), path.stat().st_size, 16, 12, 1, "PNG")
    source = FindingSource(path, identity, (1, 1))
    built = [
        Finding(
            source,
            Region(*box) if box else None,
            Category(category),
            Origin.OPERATOR,
            NOTE_SENTINEL,
            Certainty.CLEAR,
            Confirmation.CONFIRMED,
            severity=Severity(severity) if severity else None,
        )
        for category, box, severity in findings
    ]
    review_evidence.save_inspection(
        LearningRecordWriter(world.records),
        image_path=path,
        verdict=verdict,
        findings=built,
        subject_count=subject_count,
        image_size=(16, 12),
    )


def _images_by_sha(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["sha256"]: item for item in document["images"]}


def test_a_saved_clean_inspection_is_the_only_source_of_clean_confirmed(populated: World) -> None:
    clean, digest = populated.image("clean_one", 60)
    _save_inspection(populated, clean, "no_defect_seen", subject_count=1)
    document = export.build_document(collect(populated))
    images = _images_by_sha(document)
    assert images[digest]["clean_confirmed"] is True
    assert images[digest]["findings"] == [] and images[digest]["subject_count"] == 1
    assert [item["clean_confirmed"] for item in document["images"]].count(True) == 1
    report = export.describe(collect(populated), targets="full")
    assert report["progress"]["clean_confirmed_images"] == {
        "have": 1,
        "target": 20,
        "remaining": 19,
        "met": False,
        "recordable_in_review": True,
    }
    assert report["counts"]["clean_confirmed_images"] == 1
    assert report["counts"]["inspections_by_verdict"]["no_defect_seen"] == 1
    assert (
        document["provenance"]["availability"]["clean_confirmed"]
        == "saved_inspection_no_defect_seen_only"
    )


def test_a_saved_defect_inspection_exports_findings_severity_and_subject_count(
    world: World,
) -> None:
    image, digest = world.image("d1", 61)
    _save_inspection(
        world,
        image,
        "defects_confirmed",
        (
            ("Hands", (0, 0, 8, 8), "major"),
            ("Face", None, None),
            ("Prompt adherence", None, "minor"),
        ),
        subject_count=4,
    )
    entry = _images_by_sha(export.build_document(collect(world)))[digest]
    assert [(f["category"], f["region"], f["severity"]) for f in entry["findings"]] == [
        ("Face", None, None),
        ("Hands", [0, 0, 8, 8], "major"),
        ("Prompt adherence", None, "minor"),
    ]
    assert entry["subject_count"] == 4 and entry["clean_confirmed"] is False
    assert all(set(f) == {"category", "region", "severity", "record_id"} for f in entry["findings"])


def test_an_inspection_merges_with_the_guided_correction_for_the_same_bytes(world: World) -> None:
    image, digest = world.image("m1", 62)
    world.job(
        "job-m",
        parent_artifact_id=f"sha256:{digest}",
        correction=correction("Hands", "ADetailer hand pass", (0, 0, 8, 8)),
        request_paths=(image,),
    )
    _save_inspection(
        world,
        image,
        "defects_confirmed",
        (("Hands", (0, 0, 8, 8), "minor"), ("Anatomy", None, None)),
    )
    entry = _images_by_sha(export.build_document(collect(world)))[digest]
    assert [(f["category"], f["region"], f["severity"]) for f in entry["findings"]] == [
        ("Anatomy", None, None),
        ("Hands", [0, 0, 8, 8], "minor"),
    ]  # one Hands finding, not two: the severity the operator saved fills the correction's


def test_clean_and_confirmed_finding_for_the_same_bytes_is_a_reported_contradiction(
    world: World,
) -> None:
    image, digest = world.image("c1", 63)
    _save_inspection(world, image, "no_defect_seen")
    world.job(
        "job-c1",
        parent_artifact_id=f"sha256:{digest}",
        correction=correction(),
        request_paths=(image,),
    )
    paired, pd = world.image("c2", 64)
    after, ad = world.image("c2_after", 65)
    world.job(
        "job-c2",
        parent_artifact_id=f"sha256:{pd}",
        correction=correction("Face", "Edit mask", None),
        result_paths=(after,),
        request_paths=(paired,),
    )
    world.judgment("rec-c2", "job-c2", pd, ad, [row("Face", "improved", None)])
    _save_inspection(world, paired, "no_defect_seen")
    collected = collect(world)
    codes = sorted(item.code for item in collected.refused)
    assert codes == ["clean_contradicts_confirmed_finding"] * 2
    document = export.build_document(collected)
    images = _images_by_sha(document)
    assert digest not in images  # no pair needs it, and neither label can be trusted
    kept = images[pd]  # part of a judged pair: kept, with no label from either side
    assert kept["clean_confirmed"] is False and kept["findings"] == []
    assert len(document["pairs"]) == 1
    assert export.describe(collected)["counts"]["refused_by_reason"] == {
        "clean_contradicts_confirmed_finding": 2
    }


def test_changed_bytes_exclude_the_inspection_and_are_counted(world: World) -> None:
    changed, digest = world.image("x1", 66)
    kept, kept_digest = world.image("x2", 67)
    _save_inspection(world, changed, "no_defect_seen", subject_count=2)
    _save_inspection(world, kept, "no_defect_seen")
    changed.write_bytes(
        changed.read_bytes() + b"\0"
    )  # the file changed after the operator inspected it
    gone, gone_digest = world.image("x3", 68)
    _save_inspection(world, gone, "no_defect_seen")
    gone.unlink()
    collected = collect(world)
    assert set(collected.images) == {kept_digest}
    assert sorted(item.code for item in collected.refused) == [
        "inspection_image_changed_since_review",
        "inspection_image_unavailable",
    ]
    counts = export.describe(collected)["counts"]
    assert counts["refused_by_reason"]["inspection_image_changed_since_review"] == 1
    assert counts["clean_confirmed_images"] == 1


def test_latest_inspection_per_image_wins_and_a_cleared_row_exports_nothing(world: World) -> None:
    image, digest = world.image("l1", 69)
    _save_inspection(world, image, "no_defect_seen")
    _save_inspection(world, image, "defects_confirmed", (("Hands", None, None),), subject_count=2)
    entry = _images_by_sha(export.build_document(collect(world)))[digest]
    assert entry["clean_confirmed"] is False and entry["subject_count"] == 2
    assert [f["category"] for f in entry["findings"]] == ["Hands"]
    from src.learning.learning_record import LearningRecordWriter
    from src.review import review_evidence

    review_evidence.clear_inspection(
        LearningRecordWriter(world.records), image_path=image, artifact_sha256=digest
    )
    collected = collect(world)
    assert collected.images == {} and collected.refused == []
    assert export.describe(collected)["counts"]["inspections_by_verdict"]["cleared"] == 1


def test_a_malformed_or_unbound_inspection_row_is_refused_with_a_code(world: World) -> None:
    image, digest = world.image("b1", 70)
    _save_inspection(world, image, "defects_confirmed", (("Hands", None, None),))
    row = json.loads(world.records.read_text("utf-8").splitlines()[0])
    bad = json.loads(json.dumps(row))
    bad["run_id"] = "bad-1"
    bad["metadata"]["findings"][0]["observation"] = NOTE_SENTINEL  # free text is never accepted
    bad["metadata"]["artifact_sha256"] = "1" * 64
    unbound = json.loads(json.dumps(row))
    unbound["run_id"] = "bad-2"
    unbound["metadata"]["artifact_sha256"] = "nope"
    with world.records.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(bad) + "\n")
        handle.write(json.dumps(unbound) + "\n")
    collected = collect(world)
    assert [(item.record_id, item.code) for item in collected.refused] == [
        ("bad-1", "malformed_inspection")
    ]
    assert digest in collected.images  # the valid row for the real image is still used


def test_visibility_applies_to_inspected_images(world: World) -> None:
    hidden, digest = world.image("n1", 71, rating="nsfw")
    _save_inspection(world, hidden, "no_defect_seen")
    sfw = export.collect(world.records, world.repository, visibility_mode="sfw")
    assert sfw.images == {} and sfw.withheld["inspection_image"] == 1
    nsfw = export.collect(world.records, world.repository, visibility_mode="nsfw")
    assert nsfw.images[digest].clean is True


def test_describe_reports_clean_images_and_subject_counts_against_the_targets(
    world: World,
) -> None:
    for index, count in enumerate((1, 2, 2, 5, 9, None)):
        image, _ = world.image(f"s{index}", 80 + index)
        _save_inspection(world, image, "no_defect_seen", subject_count=count)
    report = export.describe(collect(world), targets="pilot")
    assert report["counts"]["clean_confirmed_images"] == 6
    assert report["counts"]["images_with_subject_count"] == 5
    assert report["counts"]["subject_counts"] == {
        "1": 1,
        "2": 2,
        "3": 0,
        "4": 0,
        "5_or_more": 2,
    }
    assert report["progress"]["clean_confirmed_images"] == {
        "have": 6,
        "target": 10,
        "remaining": 4,
        "met": False,
        "recordable_in_review": True,
    }
    assert report["progress"]["multi_subject_images"] == {
        "have": 4,
        "target": 5,
        "remaining": 1,
        "met": False,
        "recordable_in_review": True,
    }
    text = json.dumps(report)
    assert not any(
        len(token) == 64 and set(token) <= set("0123456789abcdef")
        for token in text.replace('"', " ").split()
    )


def test_inspection_content_never_reaches_stdout_the_export_or_errors(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image, _ = world.image("p1", 90)
    _save_inspection(world, image, "defects_confirmed", (("Face", (1, 1, 5, 5), "major"),))
    clean, _ = world.image("p2", 91)
    _save_inspection(world, clean, "no_defect_seen", subject_count=2)
    out = tmp_path.parent / f"{tmp_path.name}_insp"
    argv = ["--learning-records", str(world.records), "--job-repository", str(world.repository)]
    assert cli.main(["export", *argv, "--out", str(out)]) == 0
    assert cli.main(["describe", *argv]) == 0
    printed = capsys.readouterr().out
    exported = b"".join(p.read_bytes() for p in out.rglob("*.json"))
    haystack = printed.encode() + exported
    # the record file holds a path locator (as every Review record does) but never the operator's text
    assert NOTE_SENTINEL.encode() not in world.records.read_bytes()
    for sentinel in (PROMPT_SENTINEL, NOTE_SENTINEL, NAME_SENTINEL):
        assert sentinel.encode() not in haystack
    assert not [p for p in out.rglob("*") if NAME_SENTINEL in p.name]
    for code in (
        "clean_contradicts_confirmed_finding",
        "inspection_image_changed_since_review",
        "inspection_image_unavailable",
        "malformed_inspection",
    ):
        assert str(Refused(code, "rec-1")) == code
        assert NAME_SENTINEL not in repr(Refused(code))


def test_inspections_cause_zero_writes_to_the_stores_the_exporter_reads(
    populated: World, tmp_path: Path
) -> None:
    image, _ = populated.image("z1", 95)
    _save_inspection(
        populated, image, "defects_confirmed", (("Hands", None, None),), subject_count=3
    )
    folders = (populated.records.parent, populated.repository.parent, populated.images)
    for path in (populated.records, populated.repository):
        os.chmod(path, 0o444)
    before = snapshot_of(*folders)
    listing = {folder: sorted(p.name for p in folder.iterdir()) for folder in folders}
    export.describe(collect(populated))
    export.write_export(collect(populated), tmp_path.parent / f"{tmp_path.name}_insp_ro")
    assert snapshot_of(*folders) == before
    assert {folder: sorted(p.name for p in folder.iterdir()) for folder in folders} == listing


def test_inspection_vocabulary_is_pinned_to_review() -> None:
    from src.review import review_evidence
    from src.review.findings import Severity

    assert contract.INSPECTION_SOURCE == review_evidence.INSPECTION_SOURCE
    assert contract.SEVERITIES == tuple(item.value for item in Severity)
    assert review_evidence.SUBJECT_COUNT_MAX == 12


def test_vl242_converter_accepts_the_new_fields_as_they_arrive(world: World) -> None:
    from tools.qualification.vl220 import review_export

    clean, _ = world.image("k1", 100)
    _save_inspection(world, clean, "no_defect_seen", subject_count=2)
    defect, _ = world.image("k2", 101)
    _save_inspection(
        world,
        defect,
        "defects_confirmed",
        (("Hands", (0, 0, 8, 8), "major"), ("Prompt adherence", None, None)),
        subject_count=1,
    )
    document = export.build_document(collect(world))
    summary = review_export.convert(document).summary
    assert (summary["clean"], summary["defective"]) == (1, 1)
    assert summary["subject_count_recorded"] == 2 and summary["multi_subject"] == 1
    assert summary["prompt_findings_dropped"] == 1 and summary["image_cases"] == 2
