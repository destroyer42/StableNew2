"""DEPLOY-3: the AI worker's desired state in the repository and the read-only check through the tunnel."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ai_assist import remote_preview
from src.ai_assist.remote_transport import TransportFailure
from tools import ai_worker_check as check

QWEN = "a" * 64
LFM = "b" * 64


def write_manifest(
    path: Path, *, qwen: str | None = QWEN, lfm: str | None = LFM, version: str = "0.40.16"
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "stablenew.ai-worker-manifest.v1",
                "ollama": {
                    "version": version,
                    "environment": {"OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1"},
                },
                "models": [
                    {"name": "qwen3.5:4b-q4_K_M", "digest": qwen},
                    {"name": "lfm3:1.7b", "digest": lfm},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class Worker:
    """What Ollama answers through the tunnel; records every request so the test sees nothing but two GETs."""

    def __init__(self, version: str = "0.40.16", models: list[dict] | None = None) -> None:
        self.version = version
        self.models = (
            models
            if models is not None
            else [
                {"name": "qwen3.5:4b-q4_K_M", "digest": QWEN},
                {"name": "lfm3:1.7b", "digest": f"sha256:{LFM}"},
            ]
        )
        self.requests: list[tuple[str, bytes | None]] = []
        self.down = False
        self.status = 200

    def __call__(self, path, body, token, timeout, limit):
        self.requests.append((path, body))
        assert timeout > 0 and limit > 0 and not token.cancelled
        if self.down:
            raise TransportFailure("disconnected")
        if path == "/api/version":
            return self.status, json.dumps({"version": self.version}).encode()
        if path == "/api/tags":
            return self.status, json.dumps({"models": self.models}).encode()
        raise AssertionError(path)


def run(tmp_path: Path, worker: Worker, **manifest) -> check.Report:
    return check.check(
        check.load_manifest(write_manifest(tmp_path / "m.json", **manifest)), transport=worker
    )


def test_the_repository_manifest_matches_what_ai_assist_approves() -> None:
    manifest = check.load_manifest(check.MANIFEST)

    assert manifest.version == remote_preview.RUNTIME_VERSION
    assert [model.name for model in manifest.models] == list(remote_preview.MODELS)
    assert manifest.environment == {"OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1"}


def test_a_matching_worker_passes_with_two_read_only_requests(tmp_path: Path) -> None:
    worker = Worker()

    report = run(tmp_path, worker)

    assert report.code == "match" and report.exit_code == 0
    assert worker.requests == [("/api/version", None), ("/api/tags", None)]
    assert any(
        "pct exec 110 -- systemctl show ollama --property=Environment" in line
        for line in report.lines
    )


def test_a_different_ollama_version_is_drift(tmp_path: Path) -> None:
    report = run(tmp_path, Worker(version="0.41.0"))

    assert report.code == "drift" and report.exit_code == 1
    assert any("0.41.0" in line and "0.40.16" in line for line in report.lines)


def test_a_replaced_model_digest_is_drift(tmp_path: Path) -> None:
    worker = Worker(
        models=[
            {"name": "qwen3.5:4b-q4_K_M", "digest": "c" * 64},
            {"name": "lfm3:1.7b", "digest": LFM},
        ]
    )

    report = run(tmp_path, worker)

    assert report.code == "drift"
    assert any("qwen3.5:4b-q4_K_M" in line and "c" * 64 in line for line in report.lines)


def test_a_missing_model_is_drift(tmp_path: Path) -> None:
    report = run(tmp_path, Worker(models=[{"name": "qwen3.5:4b-q4_K_M", "digest": QWEN}]))

    assert report.code == "drift"
    assert any("lfm3:1.7b" in line and "not installed" in line for line in report.lines)


def test_model_names_compare_without_case_as_ai_assist_does(tmp_path: Path) -> None:
    worker = Worker(
        models=[{"name": "QWEN3.5:4B-Q4_K_M", "digest": QWEN}, {"name": "lfm3:1.7b", "digest": LFM}]
    )

    assert run(tmp_path, worker).code == "match"


def test_an_unrecorded_digest_prints_the_installed_one_to_record(tmp_path: Path) -> None:
    report = run(tmp_path, Worker(), lfm=None)

    assert report.code == "unrecorded" and report.exit_code == 3
    assert any("lfm3:1.7b" in line and LFM in line and "record" in line for line in report.lines)


def test_drift_wins_over_an_unrecorded_digest(tmp_path: Path) -> None:
    assert run(tmp_path, Worker(version="0.41.0"), lfm=None).code == "drift"


def test_other_models_on_the_worker_are_listed_but_are_not_drift(tmp_path: Path) -> None:
    worker = Worker()
    worker.models.append({"name": "llama3:8b", "digest": "d" * 64})

    report = run(tmp_path, worker)

    assert report.code == "match"
    assert any("llama3:8b" in line for line in report.lines)


@pytest.mark.parametrize("down", [True, False])
def test_an_unreachable_worker_is_its_own_outcome(tmp_path: Path, down: bool) -> None:
    worker = Worker()
    worker.down = down
    worker.status = 200 if down else 503

    report = run(tmp_path, worker)

    assert report.code == "unreachable" and report.exit_code == 2


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m["ollama"].update(version=""),
        lambda m: m["models"][0].update(digest="ABC"),
        lambda m: m["models"][0].update(name=""),
        lambda m: m["ollama"]["environment"].update(OLLAMA_HOST="0.0.0.0:11434"),
        lambda m: m.update(schema="other"),
        lambda m: m["models"].append(dict(m["models"][0])),
    ],
)
def test_a_malformed_manifest_is_refused(tmp_path: Path, change) -> None:
    path = write_manifest(tmp_path / "m.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    change(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError):
        check.load_manifest(path)


def test_the_command_line_prints_json_and_exits_with_the_outcome(tmp_path: Path, capsys) -> None:
    path = write_manifest(tmp_path / "m.json")

    code = check.main(["--manifest", str(path), "--json"], transport=Worker(version="0.41.0"))

    assert code == 1
    document = json.loads(capsys.readouterr().out)
    assert document["outcome"] == "drift" and document["ollama"]["installed"] == "0.41.0"
