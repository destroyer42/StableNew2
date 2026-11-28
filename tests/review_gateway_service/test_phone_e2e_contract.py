"""PHONE-CORE PC-0: the browser e2e suite tests the versions the gateway runs, and it blocks merges through CI.

The suite itself (``tests/phone_e2e``) needs Playwright and runs only in the ``phone-e2e`` job; these cheap checks run
in the ordinary census so its lock and wiring cannot drift unnoticed.
"""

from __future__ import annotations

import re

from tests.review_gateway_service.conftest import GATEWAY_ROOT, ROOT

E2E = ROOT / "tests" / "phone_e2e"


def pins(text: str) -> dict[str, str]:
    return {
        name.lower(): version
        for name, version in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", text, re.MULTILINE)
    }


def test_the_e2e_lock_uses_the_gateways_exact_versions() -> None:
    gateway = pins((GATEWAY_ROOT / "requirements.txt").read_text(encoding="utf-8"))
    e2e = pins((E2E / "requirements-e2e.txt").read_text(encoding="utf-8"))
    shared = gateway.keys() & e2e.keys()
    assert {"starlette", "uvicorn", "jsonschema"} <= shared
    assert {name: e2e[name] for name in shared} == {name: gateway[name] for name in shared}


def test_the_e2e_lock_uses_the_repositorys_pytest_pins() -> None:
    dev = pins((ROOT / "requirements-dev.txt").read_text(encoding="utf-8"))
    e2e = pins((E2E / "requirements-e2e.txt").read_text(encoding="utf-8"))
    for name in ("pytest", "pytest-timeout", "httpx2"):
        assert e2e[name] == dev[name], name


def test_every_e2e_requirement_is_hash_pinned() -> None:
    text = (E2E / "requirements-e2e.txt").read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text.split("\n", 1)[1])
    requirements = [block for block in blocks if re.match(r"[A-Za-z0-9_.-]+==", block)]
    assert requirements, "the lock lists its requirements"
    for block in requirements:
        assert "--hash=sha256:" in block, block.splitlines()[0]


def test_the_suite_only_runs_when_asked() -> None:
    conftest = (E2E / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.get("STABLENEW_PHONE_E2E") == "1"' in conftest
    assert 'collect_ignore_glob = ["test_*.py"]' in conftest


def test_full_suite_waits_for_phone_e2e_and_fails_when_it_failed() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    full_suite = workflow[workflow.index("  full-suite:") : workflow.index("  windows:")]
    job = workflow[workflow.index("  phone-e2e:") :]
    assert "needs: [required, full-suite-shard, phone-e2e]" in full_suite
    assert 'test "$PHONE_E2E" = "success"' in full_suite
    assert "pip install --require-hashes -r tests/phone_e2e/requirements-e2e.txt" in job
    assert 'STABLENEW_PHONE_E2E: "1"' in job
    assert "--confcutdir=tests/phone_e2e" in job
    assert "secrets." not in job
