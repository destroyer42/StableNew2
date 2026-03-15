from __future__ import annotations

from src.video.svd_service import SVDService


def test_is_available_returns_actionable_message_for_missing_torch(monkeypatch) -> None:
    def _import_module(name: str):
        if name == "torch":
            raise ModuleNotFoundError("No module named 'torch'", name="torch")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("src.video.svd_service.importlib.import_module", _import_module)

    available, reason = SVDService().is_available()

    assert available is False
    assert reason is not None
    assert "requirements-svd.txt" in reason
    assert "torch" in reason
