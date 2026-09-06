from __future__ import annotations

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.state.output_routing import (
    OUTPUT_ROUTE_PIPELINE,
    OUTPUT_ROUTE_TESTING,
    classify_existing_output_dir,
    classify_njr_output_route,
    resolve_output_artifact_path,
)


def _build_njr(**kwargs) -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=kwargs.get("job_id", "njr-test"),
        config=kwargs.get("config", {}),
        path_output_dir="output",
        filename_template="{seed}",
        seed=1,
        prompt_pack_name=kwargs.get("prompt_pack_name", ""),
        intent_config=kwargs.get("intent_config", {}),
    )


def test_classify_njr_output_route_uses_testing_under_pytest(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/state/test_output_routing.py::test")

    route = classify_njr_output_route(_build_njr())

    assert route == OUTPUT_ROUTE_TESTING


def test_classify_njr_output_route_uses_testing_under_pytest_even_with_pack_name(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/state/test_output_routing.py::test")

    route = classify_njr_output_route(_build_njr(prompt_pack_name="NamedPack"))

    assert route == OUTPUT_ROUTE_TESTING


def test_classify_njr_output_route_uses_testing_under_explicit_test_mode(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("STABLENEW_TEST_MODE", "1")

    route = classify_njr_output_route(_build_njr(prompt_pack_name="NamedPack"))

    assert route == OUTPUT_ROUTE_TESTING


def test_classify_njr_output_route_uses_testing_for_debug_replay() -> None:
    route = classify_njr_output_route(
        _build_njr(intent_config={"source": "debug_replay"})
    )

    assert route == OUTPUT_ROUTE_TESTING


def test_classify_njr_output_route_uses_testing_for_cfg_check_run_name() -> None:
    route = classify_njr_output_route(
        _build_njr(
            job_id="cfg-check",
            intent_config={"requested_job_label": "cfg-check"},
        )
    )

    assert route == OUTPUT_ROUTE_TESTING


def test_classify_njr_output_route_uses_testing_for_test_pack_label() -> None:
    route = classify_njr_output_route(_build_njr(prompt_pack_name="JT03_Test_Pack"))

    assert route == OUTPUT_ROUTE_TESTING


def test_classify_njr_output_route_preserves_explicit_route_over_testing(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/state/test_output_routing.py::test")

    route = classify_njr_output_route(
        _build_njr(config={"pipeline": {"output_route": OUTPUT_ROUTE_PIPELINE}})
    )

    assert route == OUTPUT_ROUTE_PIPELINE


def test_resolve_output_artifact_path_repairs_absolute_route_move(tmp_path) -> None:
    output_root = tmp_path / "output"
    actual = output_root / OUTPUT_ROUTE_TESTING / "20260329_120000_example" / "image.png"
    actual.parent.mkdir(parents=True, exist_ok=True)
    actual.write_bytes(b"png")

    stale = output_root / OUTPUT_ROUTE_PIPELINE / "20260329_120000_example" / "image.png"

    resolved = resolve_output_artifact_path(stale, base_output_dir=output_root)

    assert resolved == str(actual.resolve())


def test_classify_existing_output_dir_uses_testing_for_cfg_check_name(tmp_path) -> None:
    run_dir = tmp_path / "20260329_120000_cfg-check-model-a-vae-a"
    run_dir.mkdir()

    assert classify_existing_output_dir(run_dir) == OUTPUT_ROUTE_TESTING

def test_classify_existing_output_dir_uses_testing_for_test_pack_name(tmp_path) -> None:
    run_dir = tmp_path / "20260329_120000_Test_Pack-sdxl-none"
    run_dir.mkdir()

    assert classify_existing_output_dir(run_dir) == OUTPUT_ROUTE_TESTING
