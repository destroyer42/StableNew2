"""PR-044: Test Job variant metadata fields."""

from __future__ import annotations

from src.queue.job_model import Job, JobStatus
from src.pipeline.pipeline_runner import PipelineConfig


def _make_pipeline_config() -> PipelineConfig:
    """Create a minimal PipelineConfig."""
    return PipelineConfig(
        prompt="test prompt",
        model="test_model",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
    )


def _make_job(**kwargs) -> Job:
    """Create a Job with minimal required fields."""
    defaults = {
        "job_id": "test-default",
        "status": JobStatus.QUEUED,
        "pipeline_config": _make_pipeline_config(),
    }
    defaults.update(kwargs)
    return Job(**defaults)


class TestJobVariantMetadata:
    """Test that Job model carries variant_index and variant_total."""

    def test_job_has_variant_fields(self) -> None:
        """Job should have variant_index and variant_total fields."""
        job = _make_job(job_id="test-001")
        # Fields should exist with default None
        assert hasattr(job, "variant_index")
        assert hasattr(job, "variant_total")
        assert job.variant_index is None
        assert job.variant_total is None

    def test_job_variant_fields_assignable(self) -> None:
        """Variant fields should be assignable."""
        job = _make_job(
            job_id="test-002",
            variant_index=0,
            variant_total=5,
        )
        assert job.variant_index == 0
        assert job.variant_total == 5

    def test_job_to_dict_includes_variant_fields(self) -> None:
        """to_dict should include variant fields."""
        job = _make_job(
            job_id="test-003",
            variant_index=2,
            variant_total=10,
        )
        d = job.to_dict()
        assert "variant_index" in d
        assert "variant_total" in d
        assert d["variant_index"] == 2
        assert d["variant_total"] == 10

    def test_variant_fields_default_none_in_dict(self) -> None:
        """Default None values should serialize to None in dict."""
        job = _make_job(job_id="test-004")
        d = job.to_dict()
        assert d["variant_index"] is None
        assert d["variant_total"] is None

    def test_first_of_many_variants(self) -> None:
        """First variant should have index 0."""
        job = _make_job(
            job_id="test-005",
            variant_index=0,
            variant_total=3,
        )
        assert job.variant_index == 0
        assert job.variant_total == 3

    def test_last_of_many_variants(self) -> None:
        """Last variant index should be total - 1."""
        total = 5
        job = _make_job(
            job_id="test-006",
            variant_index=total - 1,
            variant_total=total,
        )
        assert job.variant_index == 4
        assert job.variant_total == 5
