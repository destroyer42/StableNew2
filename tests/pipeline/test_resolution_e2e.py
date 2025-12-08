from src.pipeline.job_models_v2 import JobBundleBuilder, JobBundleSummaryDTO, PipelineConfigSnapshot
from src.pipeline.resolution_layer import UnifiedConfigResolver, UnifiedPromptResolver


def test_resolution_layer_flow_updates_summary() -> None:
    builder = JobBundleBuilder(
        PipelineConfigSnapshot.default(),
        global_negative_text="global bad",
        prompt_resolver=UnifiedPromptResolver(),
        config_resolver=UnifiedConfigResolver(),
        stage_flags={"txt2img": True, "img2img": False},
        batch_runs=1,
    )
    builder.add_single_prompt("forest lights", negative_prompt="noise")
    bundle = builder.to_job_bundle(label="resolved", run_mode="queue")
    summary = JobBundleSummaryDTO.from_job_bundle(bundle)
    assert summary.num_parts == 1
    assert "forest lights" in summary.positive_preview
    assert "global bad" in (summary.negative_preview or "")
    assert summary.stage_summary == "txt2img"
