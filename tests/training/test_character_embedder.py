from __future__ import annotations

from pathlib import Path

from src.training.character_embedder import CharacterEmbedder


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)

    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, *, returncodes: list[int | None]) -> None:
        self._returncodes = list(returncodes)
        self.stdout = _FakeStdout(["training started\n", "training finished\n"])
        self.terminated = False
        self.killed = False

    def poll(self):
        if len(self._returncodes) > 1:
            return self._returncodes.pop(0)
        return self._returncodes[0]

    def terminate(self) -> None:
        self.terminated = True
        self._returncodes = [1]

    def wait(self, timeout=None) -> int:
        return int(self._returncodes[-1] or 0)

    def kill(self) -> None:
        self.killed = True
        self._returncodes = [1]


def test_character_embedder_run_to_completion_returns_weight_path(tmp_path: Path) -> None:
    weight_path = tmp_path / "ada.safetensors"
    weight_path.write_bytes(b"weights")
    process = _FakeProcess(returncodes=[None, 0])
    embedder = CharacterEmbedder(
        popen_factory=lambda *args, **kwargs: process,
        sleep_fn=lambda *_args, **_kwargs: None,
    )

    status = embedder.run_to_completion(
        {
            "character_name": "Ada",
            "image_dir": str(tmp_path),
            "output_dir": str(tmp_path),
            "epochs": 10,
            "learning_rate": 0.0001,
            "trainer_command": "trainer.exe --flag",
            "produced_weight_path": str(weight_path),
        }
    )

    assert status["success"] is True
    assert status["running"] is False
    assert status["weight_path"] == str(weight_path.resolve())
    assert status["command"][:2] == ["trainer.exe", "--flag"]


def test_character_embedder_requires_command(tmp_path: Path) -> None:
    embedder = CharacterEmbedder(env={})

    status = embedder.run_to_completion(
        {
            "character_name": "Ada",
            "image_dir": str(tmp_path),
            "output_dir": str(tmp_path),
            "epochs": 10,
            "learning_rate": 0.0001,
        }
    )

    assert status["success"] is False
    assert "trainer command" in str(status["error"])