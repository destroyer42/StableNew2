"""PR-IMG-FORGE-100: operator cancellation reaches Forge's /sdapi/v1/interrupt (fakes only).

Real ``PipelineRunner`` + ``Pipeline`` executor + ``ForgeWebUIClient``; the fake transport holds the
generation POST open until Forge's interrupt route is called, so the test can only pass when
cancellation propagates through the canonical path to the Forge transport.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import Mock

from src.api.forge_client import ForgeWebUIClient
from src.controller.runtime_state import CancelToken
from src.image_backends import (
    A1111WebUIImageBackend,
    ForgeWebUIImageBackend,
    ImageBackendRegistry,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr


def _ready_transition() -> Mock:
    transition = Mock()
    transition.prepare_for.return_value = Mock(ready=True)
    return transition


def _runner(monkeypatch, tmp_path: Path, client: ForgeWebUIClient) -> PipelineRunner:
    registry = ImageBackendRegistry()
    registry.register(A1111WebUIImageBackend(transition=_ready_transition()))
    registry.register(ForgeWebUIImageBackend(transition=_ready_transition()))
    runner = PipelineRunner(
        api_client=client,
        structured_logger=StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "runs"),
        image_backend_registry=registry,
    )
    executor = runner._pipeline
    monkeypatch.setattr(executor, "_ensure_webui_true_ready", lambda: None)
    monkeypatch.setattr(executor, "_check_webui_health_before_stage", lambda _stage: None)
    monkeypatch.setattr(executor, "_ensure_model_and_vae", lambda *_args: None)
    monkeypatch.setattr(executor, "_apply_webui_defaults_once", lambda: None)
    monkeypatch.setattr(executor, "_assess_stage_pressure", lambda **_kwargs: {})
    monkeypatch.setattr(executor, "_mitigate_stage_pressure", lambda _assessment: None)
    monkeypatch.setattr(executor, "_maybe_apply_workload_launch_policy", lambda **_kwargs: None)
    monkeypatch.setattr(
        executor,
        "_ensure_runtime_admissible",
        lambda **_kwargs: {"status": "healthy", "reasons": []},
    )
    return runner


def test_cancelling_a_forge_job_posts_to_sdapi_interrupt_and_never_replays(
    monkeypatch, tmp_path: Path
) -> None:
    transport = FakeWebUITransport(flavor="forge", block_generation_until_interrupt=True)
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    runner = _runner(monkeypatch, tmp_path, client)
    token = CancelToken()
    record = make_pipeline_njr(
        job_id="forge-cancel",
        positive_prompt="cancel during forge txt2img",
        path_output_dir=str(tmp_path / "runs"),
        backend_options={"image": {"backend_id": "forge_webui"}},
    )
    outcome: dict[str, object] = {}

    def _run() -> None:
        try:
            outcome["result"] = runner.run_njr(record, cancel_token=token)
        except BaseException as exc:  # noqa: BLE001 - cancellation may surface as an exception
            outcome["error"] = exc

    thread = threading.Thread(target=_run, name="forge-cancel-run")
    thread.start()
    assert transport.generation_started.wait(timeout=10.0), "generation POST never started"
    token.cancel()
    thread.join(timeout=15.0)

    assert not thread.is_alive()
    assert transport.interrupted.is_set(), "cancellation never reached Forge's interrupt route"
    assert ("POST", "/sdapi/v1/interrupt") in [(verb, path) for verb, path, _ in transport.calls]
    # one generation POST only: cancellation must not trigger a replay
    assert [path for _, path, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    result = outcome.get("result")
    if result is not None:
        assert getattr(result, "success", None) is False
