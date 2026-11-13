"""P4-2A canonical queue admission, one check per route family.

Each family's real compiler output crosses the real ``JobService.submit_njrs`` into the SQLite queue and repository
(no runner, no backend, no network), and the queued job must carry exactly the record that was submitted.  The CLI is
absent on purpose: it calls ``runner.run_njr`` directly and never crosses ``submit_njrs`` (assessment finding X14).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.golden.route_records import ROUTES, RouteEnv, admit, real_job_service


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_route_record_is_admitted_through_job_service_unchanged(
    route: str,
    tmp_path: Path,
    copy_asset: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ROUTES[route](RouteEnv(tmp_path, copy_asset, monkeypatch))
    with real_job_service(tmp_path / "queue") as service:
        assert admit(service, record) == {"outcome": "accepted"}
        job = service.job_queue.get_job(record.job_id)
        assert job is not None
        assert job._normalized_record.to_dict() == record.to_dict()
        assert job.status.value == "queued"
