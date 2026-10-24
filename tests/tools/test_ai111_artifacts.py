"""Artifact identity, verified download, quarantine and staging (PR-AI-111, download-only authorization).

No network, no real model and no runtime: files are synthetic and the fetcher is a stand-in.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.qualification.ai111 import __main__ as freeze  # noqa: E402
from tools.qualification.ai111 import download  # noqa: E402
from tools.qualification.ai111 import plan as plan_module  # noqa: E402
from tools.qualification.ai111.artifacts import (  # noqa: E402
    FILE_TYPE,
    Artifact,
    SubstitutionRefused,
    authorized_artifacts,
    crosscheck_freeze_evidence,
    inspect_zip,
    read_gguf_metadata,
    stage,
    verify_identity,
)

REVISION = "a" * 40


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def kv_string(key: str, value: str) -> bytes:
    k, v = key.encode(), value.encode()
    return struct.pack("<Q", len(k)) + k + struct.pack("<I", 8) + struct.pack("<Q", len(v)) + v


def kv_u32(key: str, value: int) -> bytes:
    k = key.encode()
    return struct.pack("<Q", len(k)) + k + struct.pack("<I", 4) + struct.pack("<I", value)


def kv_string_array(key: str, items: list[str]) -> bytes:
    k = key.encode()
    body = b"".join(struct.pack("<Q", len(i.encode())) + i.encode() for i in items)
    return (
        struct.pack("<Q", len(k))
        + k
        + struct.pack("<I", 9)
        + struct.pack("<I", 8)
        + struct.pack("<Q", len(items))
        + body
    )


def gguf(quant: str = "Q4_K_M", arch: str = "qwen35", *, tail: bytes = b"\0" * 64) -> bytes:
    entries = [
        kv_string("general.architecture", arch),
        kv_string_array("tokenizer.ggml.tokens", [f"tok{i}" for i in range(50)]),
        kv_string("general.name", "Qwen3.5 Test"),
        kv_u32("general.file_type", FILE_TYPE[quant]),
    ]
    return (
        b"GGUF"
        + struct.pack("<I", 3)
        + struct.pack("<QQ", 0, len(entries))
        + b"".join(entries)
        + tail
    )


def model_artifact(content: bytes, quant: str = "Q4_K_M") -> Artifact:
    name = f"Model-{quant}.gguf"
    return Artifact(
        key=f"model-{quant}",
        kind="model",
        filename=name,
        url=f"https://huggingface.co/pack/Repo/resolve/{REVISION}/{name}",
        bytes=len(content),
        sha256=sha(content),
        revision=REVISION,
        publisher="pub/Repo",
        packager="pack/Repo",
        quantization=quant,
    )


def fetcher(content: bytes, calls: list | None = None):
    def fetch(url, partial, resume_from, max_bytes):
        if calls is not None:
            calls.append((url, resume_from, max_bytes))
        mode = "ab" if resume_from else "wb"
        with partial.open(mode) as handle:
            handle.write(content[resume_from:])
        return {"final_host": "cdn.example", "status": 200}

    return fetch


# -- the five identities ------------------------------------------------------------------------------------------------------


def test_exactly_the_five_planned_artifacts_are_authorized_and_each_is_pinned() -> None:
    artifacts = authorized_artifacts()
    assert (
        len(artifacts) == 5
        and artifacts[0].kind == "runtime"
        and len({a.key for a in artifacts}) == 5
    )
    for artifact in artifacts:
        verify_identity(artifact)
    plan = plan_module.frozen_plan()
    assert (
        sum(a.bytes for a in artifacts)
        == plan["asset_bytes"]["runtime"] + plan["asset_bytes"]["models"]
    )
    assert [a.quantization for a in artifacts[1:]] == ["Q4_K_M", "Q5_K_M", "Q8_0", "Q4_K_M"]
    assert (
        artifacts[0].url.endswith("/b11840/llama-b11840-bin-win-cpu-x64.zip")
        and "cuda" not in artifacts[0].filename
    )


def test_the_identities_must_equal_the_freeze_evidence_the_owner_was_shown(tmp_path: Path) -> None:
    out = tmp_path / "freeze"
    assert freeze.main(["--out", str(out)]) == 0
    artifacts = authorized_artifacts()
    crosscheck_freeze_evidence(artifacts, out)
    request = json.loads((out / "authorization-request.json").read_text(encoding="utf-8"))
    request["downloads"][2]["sha256"] = "0" * 64
    (out / "authorization-request.json").write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(SubstitutionRefused):
        crosscheck_freeze_evidence(artifacts, out)


@pytest.mark.parametrize(
    "change",
    [
        {"url": "http://huggingface.co/pack/Repo/resolve/" + REVISION + "/Model-Q4_K_M.gguf"},
        {"url": "https://evil.example/pack/Repo/resolve/" + REVISION + "/Model-Q4_K_M.gguf"},
        {"url": "https://huggingface.co/pack/Repo/resolve/main/Model-Q4_K_M.gguf"},
        {
            "url": "https://huggingface.co/pack/Repo/resolve/"
            + REVISION
            + "/Model-Q4_K_M.gguf?download=true"
        },
        {"url": "https://huggingface.co/pack/Repo/resolve/" + "b" * 40 + "/Model-Q4_K_M.gguf"},
        {"url": "https://huggingface.co/other/Repo/resolve/" + REVISION + "/Model-Q4_K_M.gguf"},
        {"url": "https://huggingface.co/pack/Repo/resolve/" + REVISION + "/Other-Q4_K_M.gguf"},
        {"quantization": "Q5_K_M"},
        {"quantization": "Q2_K"},
        {"sha256": "xyz"},
        {"bytes": 0},
        {"revision": "main"},
    ],
)
def test_any_substitution_of_url_revision_host_quantisation_or_pin_is_refused(change) -> None:
    artifact = dataclasses.replace(model_artifact(b"x" * 100), **change)
    with pytest.raises(SubstitutionRefused):
        verify_identity(artifact)


def test_the_runtime_must_be_the_pinned_cpu_release_asset() -> None:
    runtime = authorized_artifacts()[0]
    for change in (
        {"url": runtime.url.replace("b11840", "b11841")},
        {
            "url": runtime.url.replace("win-cpu-x64", "win-cuda-12.4-x64"),
            "filename": runtime.filename.replace("win-cpu-x64", "win-cuda-12.4-x64"),
        },
        {"url": runtime.url.replace("ggml-org", "someone-else")},
        {"revision": "latest"},
    ):
        with pytest.raises(SubstitutionRefused):
            verify_identity(dataclasses.replace(runtime, **change))


# -- GGUF header and archive inspection ----------------------------------------------------------------------------------------


def test_gguf_metadata_is_read_from_the_header_only_including_past_arrays(tmp_path: Path) -> None:
    path = tmp_path / "m.gguf"
    path.write_bytes(gguf("Q5_K_M"))
    meta = read_gguf_metadata(path)
    assert (
        meta["general.architecture"] == "qwen35"
        and meta["general.file_type"] == FILE_TYPE["Q5_K_M"]
    )
    assert meta["general.name"] == "Qwen3.5 Test" and meta["gguf_version"] == 3


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GGML" + b"\0" * 40,
        b"GGUF" + struct.pack("<I", 9) + b"\0" * 32,
        gguf()[:60],
        b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 0),
    ],
)
def test_malformed_or_foreign_gguf_headers_are_rejected(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "bad.gguf"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        read_gguf_metadata(path)


def test_zip_inspection_lists_members_without_extracting(tmp_path: Path) -> None:
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("llama-cli.exe", b"x")
        bundle.writestr("ggml.dll", b"y")
        bundle.writestr("../escape.dll", b"z")
    info = inspect_zip(path)
    assert info["members"] == 3 and info["unsafe_member_paths"] == ["../escape.dll"]
    assert not any(tmp_path.glob("llama-cli*")) and not any(tmp_path.glob("ggml*"))


# -- verified download, quarantine and staging -----------------------------------------------------------------------------------


def test_a_good_download_is_verified_before_it_is_staged_and_nothing_is_left_partial(
    tmp_path: Path,
) -> None:
    content = gguf("Q4_K_M")
    artifact, calls = model_artifact(content), []
    result = stage(artifact, tmp_path / "stage", fetcher(content, calls))
    final = tmp_path / "stage" / artifact.filename
    assert (
        result["result"] == "staged"
        and result["verified"] is True
        and result["observed_sha256"] == artifact.sha256
    )
    assert (
        result["observed_bytes"] == len(content)
        and result["metadata"]["general.file_type"] == FILE_TYPE["Q4_K_M"]
    )
    assert final.read_bytes() == content and not list((tmp_path / "stage").glob("*.partial"))
    assert calls == [(artifact.url, 0, artifact.bytes)], "the fetch was capped at the pinned size"
    assert result["free_bytes_before"] > 0 and result["free_bytes_after"] > 0
    again = stage(artifact, tmp_path / "stage", fetcher(content, calls))
    assert again["result"] == "already_staged" and len(calls) == 1, (
        "a verified file is not fetched twice"
    )


def test_a_hash_or_size_mismatch_is_quarantined_never_staged_or_marked_verified(
    tmp_path: Path,
) -> None:
    good = gguf("Q4_K_M")
    artifact = model_artifact(good)
    tampered = good[:-1] + b"X"
    result = stage(artifact, tmp_path / "stage", fetcher(tampered))
    assert result["result"] == "quarantined" and result["verified"] is False
    assert result["observed_sha256"] == sha(tampered) != artifact.sha256
    assert not (tmp_path / "stage" / artifact.filename).exists()
    assert Path(result["quarantine_path"]).exists() and ".quarantined-" in result["quarantine_path"]
    short = stage(
        dataclasses.replace(artifact, key="short"), tmp_path / "stage2", fetcher(good[:-10])
    )
    assert short["result"] == "quarantined" and short["verified"] is False


def test_a_correctly_hashed_file_of_the_wrong_quantisation_is_still_quarantined(
    tmp_path: Path,
) -> None:
    q5 = gguf("Q5_K_M")
    artifact = model_artifact(
        q5, quant="Q4_K_M"
    )  # the pinned hash matches these bytes, but the file says Q5_K_M
    result = stage(artifact, tmp_path / "stage", fetcher(q5))
    assert (
        result["result"] == "quarantined"
        and "file type" in result["reason"]
        and result["verified"] is False
    )


def test_a_non_gguf_payload_with_a_matching_hash_is_quarantined(tmp_path: Path) -> None:
    junk = b"not a gguf file" * 10
    result = stage(model_artifact(junk), tmp_path / "stage", fetcher(junk))
    assert result["result"] == "quarantined" and "content check failed" in result["reason"]


def test_not_enough_disk_refuses_before_any_byte_is_fetched(tmp_path: Path) -> None:
    content, calls = gguf(), []
    result = stage(
        model_artifact(content),
        tmp_path / "stage",
        fetcher(content, calls),
        free_bytes=lambda _p: 100,
    )
    assert result["result"] == "refused" and "disk" in result["reason"] and calls == []


def test_an_interrupted_download_resumes_and_a_different_file_in_the_way_is_never_overwritten(
    tmp_path: Path,
) -> None:
    content = gguf()
    artifact = model_artifact(content)
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()

    def dies(url, partial, resume_from, max_bytes):
        partial.write_bytes(content[:50])
        raise ConnectionError("network dropped")

    failed = stage(artifact, stage_dir, dies)
    assert (
        failed["result"] == "failed"
        and failed["partial_bytes"] == 50
        and not (stage_dir / artifact.filename).exists()
    )
    calls = []
    resumed = stage(artifact, stage_dir, fetcher(content, calls))
    assert resumed["result"] == "staged" and calls[0][1] == 50

    other = model_artifact(gguf("Q8_0"), quant="Q8_0")
    (stage_dir / other.filename).write_bytes(b"someone else's file")
    refused = stage(other, stage_dir, fetcher(gguf("Q8_0")))
    assert (
        refused["result"] == "refused"
        and (stage_dir / other.filename).read_bytes() == b"someone else's file"
    )


def test_the_runtime_archive_is_verified_and_inspected_but_never_unpacked(tmp_path: Path) -> None:
    source = tmp_path / "src.zip"
    with zipfile.ZipFile(source, "w") as bundle:
        bundle.writestr("llama-cli.exe", b"binary")
    content = source.read_bytes()
    artifact = Artifact(
        key="rt",
        kind="runtime",
        filename="llama-b11840-bin-win-cpu-x64.zip",
        url="https://github.com/ggml-org/llama.cpp/releases/download/b11840/llama-b11840-bin-win-cpu-x64.zip",
        bytes=len(content),
        sha256=sha(content),
        revision="b11840",
        publisher="ggml-org/llama.cpp",
        packager="ggml-org/llama.cpp",
    )
    result = stage(artifact, tmp_path / "stage", fetcher(content))
    assert result["result"] == "staged" and result["metadata"]["loadable_or_script_members"] == [
        "llama-cli.exe"
    ]
    assert sorted(p.name for p in (tmp_path / "stage").iterdir()) == [artifact.filename], (
        "nothing was extracted"
    )


def test_a_substituted_artifact_is_refused_without_any_network_call(tmp_path: Path) -> None:
    content, calls = gguf(), []
    bad = dataclasses.replace(
        model_artifact(content),
        url="https://huggingface.co/pack/Repo/resolve/main/Model-Q4_K_M.gguf",
    )
    result = stage(bad, tmp_path / "stage", fetcher(content, calls))
    assert result["result"] == "refused" and calls == [] and not (tmp_path / "stage").exists()


# -- the command -----------------------------------------------------------------------------------------------------------------


def test_the_download_command_refuses_to_stage_inside_a_git_working_tree(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Git working tree"):
        download.main(
            [
                "--dest",
                str(ROOT / "reports" / "ai111" / "downloads"),
                "--evidence-dir",
                str(tmp_path / "e"),
                "--freeze-evidence",
                str(tmp_path),
            ]
        )
    assert not (ROOT / "reports" / "ai111" / "downloads").exists()


def test_the_download_command_takes_no_url_and_refuses_when_the_freeze_evidence_differs(
    tmp_path: Path,
) -> None:
    assert "--url" not in download.__doc__ and "url" not in {
        a.dest for a in download.argparse.ArgumentParser().__dict__.get("_actions", [])
    }
    out = tmp_path / "freeze"
    freeze.main(["--out", str(out)])
    request = json.loads((out / "authorization-request.json").read_text(encoding="utf-8"))
    request["downloads"][0]["bytes"] += 1
    (out / "authorization-request.json").write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(SubstitutionRefused):
        download.main(
            [
                "--dest",
                str(tmp_path / "stage"),
                "--evidence-dir",
                str(tmp_path / "ev"),
                "--freeze-evidence",
                str(out),
            ]
        )
    assert not (tmp_path / "stage").exists() and not (tmp_path / "ev").exists()


def test_the_download_command_records_each_result_and_stops_nothing_for_one_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "freeze"
    freeze.main(["--out", str(out)])
    results = {"fail": True}

    def fake_stage(artifact, dest):
        failed = results["fail"] and artifact.kind == "runtime"
        return {
            "key": artifact.key,
            "result": "failed" if failed else "staged",
            "verified": not failed,
            "reason": "boom" if failed else "",
        }

    monkeypatch.setattr(download, "stage", fake_stage)
    code = download.main(
        [
            "--dest",
            str(tmp_path / "stage"),
            "--evidence-dir",
            str(tmp_path / "ev"),
            "--freeze-evidence",
            str(out),
        ]
    )
    summary = json.loads((tmp_path / "ev" / "summary.json").read_text(encoding="utf-8"))
    assert code == 1 and summary["all_verified"] is False and len(summary["results"]) == 5
    assert list(summary["results"].values()).count("staged") == 4
    assert (
        len((tmp_path / "ev" / "download-evidence.jsonl").read_text(encoding="utf-8").splitlines())
        == 5
    )


@pytest.mark.parametrize("entry_name", ["Model-Q4_K_M.gguf", "Model-Q4_K_M.gguf.partial"])
def test_redirected_staging_entry_never_changes_unrelated_file(tmp_path, entry_name):
    artifact = model_artifact(gguf())
    outside = tmp_path / "operator-data"
    outside.write_bytes(b"preserve unrelated bytes")
    dest = tmp_path / "stage"
    dest.mkdir()
    link = dest / entry_name
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("host does not permit test symlinks")
    result = stage(artifact, dest, fetch=lambda *_: pytest.fail("no download permitted"))
    assert result["result"] == "refused"
    assert outside.read_bytes() == b"preserve unrelated bytes"


def test_nonregular_partial_is_refused_without_network(tmp_path):
    artifact = model_artifact(gguf())
    (tmp_path / (artifact.filename + ".partial")).mkdir()
    assert stage(artifact, tmp_path, fetch=lambda *_: pytest.fail("network"))["result"] == "refused"


def test_empty_or_unknown_download_selection_is_refused(tmp_path):
    frozen = tmp_path / "freeze"
    freeze.main(["--out", str(frozen)])
    for keys in ([], ["not-authorized"]):
        with pytest.raises(SystemExit, match="authorized artifact keys"):
            download.main(
                [
                    "--dest",
                    str(tmp_path / "stage"),
                    "--evidence-dir",
                    str(tmp_path / "ev"),
                    "--freeze-evidence",
                    str(frozen),
                    "--only",
                    *keys,
                ]
            )
    assert not (tmp_path / "ev").exists()
