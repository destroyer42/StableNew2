from __future__ import annotations

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord
from tests.helpers.job_helpers import make_test_njr


def test_source_compilers_return_njr_values_before_submission() -> None:
    record = make_test_njr(prompt_source="manual", prompt_pack_id="")
    assert isinstance(record, NormalizedJobRecord)
    assert record.source.kind.value == "cli"
    assert SubmissionPolicy().start_when_idle is False
