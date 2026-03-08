"""
Test that build_run_plan_from_njr creates jobs for ALL stages in stage_chain,
not just the first one (PR-047 fix).
"""
from src.pipeline.run_plan import build_run_plan_from_njr
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig

# Create an NJR with 3 stages (minimal required fields)
njr = NormalizedJobRecord(
    job_id="test-001",
    config={},  # Empty config for test
    path_output_dir="./test_output",
    filename_template="test_{index}",
    positive_prompt="beautiful woman portrait",
    stage_chain=[
        StageConfig(stage_type="txt2img", enabled=True),
        StageConfig(stage_type="adetailer", enabled=True),
        StageConfig(stage_type="upscale", enabled=True),
    ],
)

# Build the run plan
plan = build_run_plan_from_njr(njr)

# Verify results
print(f"✅ Total jobs created: {len(plan.jobs)}")
print(f"✅ Stage names: {[j.stage_name for j in plan.jobs]}")
print(f"✅ Enabled stages: {plan.enabled_stages}")
print(f"✅ Total jobs field: {plan.total_jobs}")

# Assertions
assert len(plan.jobs) == 3, f"Expected 3 jobs, got {len(plan.jobs)}"
assert plan.jobs[0].stage_name == "txt2img", f"Expected first stage to be txt2img, got {plan.jobs[0].stage_name}"
assert plan.jobs[1].stage_name == "adetailer", f"Expected second stage to be adetailer, got {plan.jobs[1].stage_name}"
assert plan.jobs[2].stage_name == "upscale", f"Expected third stage to be upscale, got {plan.jobs[2].stage_name}"
assert plan.enabled_stages == ["txt2img", "adetailer", "upscale"], f"Enabled stages mismatch: {plan.enabled_stages}"
assert plan.total_jobs == 3, f"Expected total_jobs=3, got {plan.total_jobs}"

print("\n✅ ALL TESTS PASSED! PR-047 fix is working correctly.")
print("   - build_run_plan_from_njr() now creates jobs for ALL stages")
print("   - Pipeline will execute txt2img → adetailer → upscale")
