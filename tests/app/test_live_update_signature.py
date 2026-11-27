"""SAFE-UPDATE: the PC asks GitHub whether it signed the commit an update would install.

GitHub is a fake everywhere here; no test reaches the network. The rule matches the gateway deployer's
``verify_target``: ``verification.verified`` true and committer ``web-flow``.
"""

from __future__ import annotations

import http.client
import io
import shutil
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from src.app import live_update as lu
from src.app.runtime_stack import build_live_update_service
from tests.helpers.live_update_repos import make_repos

SHA = "c" * 40


def answer(*, sha=SHA, verified=True, login="web-flow"):
    return {
        "sha": sha,
        "commit": {"verification": {"verified": verified}},
        "committer": None if login is None else {"login": login},
    }


def ask(status=200, body=None, sha=SHA):
    urls = []

    def fetch(url):
        urls.append(url)
        return status, answer() if body is None else body

    return lu.github_signature_check(fetch_json=fetch)(sha), urls


def test_a_merge_github_signed_passes():
    result, urls = ask()

    assert result == ("", "")
    assert urls == [f"https://api.github.com/repos/destroyer42/StableNew2/commits/{SHA}"]


@pytest.mark.parametrize(
    "body",
    [
        answer(verified=False),
        answer(verified="true"),
        answer(login="someone-else"),
        answer(login=None),
        answer(sha="d" * 40),
        {"sha": SHA},
        {"sha": SHA, "commit": "x", "committer": "web-flow"},
    ],
)
def test_anything_else_github_says_about_the_commit_is_not_signed(body):
    (reason, detail), _urls = ask(body=body)

    assert reason == lu.NOT_GITHUB_SIGNED and detail


@pytest.mark.parametrize("status", [404, 422])
def test_a_commit_github_does_not_know_is_not_signed(status):
    assert ask(status=status)[0][0] == lu.NOT_GITHUB_SIGNED


@pytest.mark.parametrize(("status", "body"), [(403, {}), (429, {}), (500, {}), (200, ["x"])])
def test_no_usable_answer_is_github_unavailable(status, body):
    assert ask(status=status, body=body)[0][0] == lu.GITHUB_UNAVAILABLE


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("no route"),
        TimeoutError("timed out"),
        ValueError("not JSON"),
        http.client.IncompleteRead(b""),
    ],
)
def test_a_network_failure_is_github_unavailable(error):
    def fetch(_url):
        raise error

    assert lu.github_signature_check(fetch_json=fetch)(SHA)[0] == lu.GITHUB_UNAVAILABLE


def test_a_malformed_sha_never_reaches_github():
    result, urls = ask(sha="main")

    assert result[0] == lu.NOT_GITHUB_SIGNED and urls == []


class _Response(io.BytesIO):
    status = 200

    def __init__(self, body: bytes, url: str) -> None:
        super().__init__(body)
        self._url = url

    def geturl(self) -> str:
        return self._url


def test_the_real_request_is_an_anonymous_https_get(monkeypatch):
    seen = []

    def urlopen(request, **kwargs):
        seen.append((request, kwargs))
        return _Response(b'{"sha": "x"}', request.full_url)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert lu._github_json("https://api.github.com/repos/o/r/commits/x") == (200, {"sha": "x"})
    request, kwargs = seen[0]
    assert request.get_method() == "GET" and request.data is None
    assert sorted(key.lower() for key in request.headers) == ["accept", "user-agent"]
    assert kwargs["timeout"] > 0 and kwargs["context"].check_hostname


def test_an_http_error_status_is_returned_and_a_redirect_off_github_is_refused(monkeypatch):
    url = "https://api.github.com/repos/o/r/commits/x"

    def refused(request, **_kwargs):
        raise urllib.error.HTTPError(request.full_url, 403, "rate limited", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    assert lu._github_json(url) == (403, None)

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda r, **k: _Response(b"{}", "https://elsewhere.example/x")
    )
    with pytest.raises(OSError):
        lu._github_json(url)


class _Queue:
    def __init__(self) -> None:
        self.held = False

    def hold_dispatch_for_update(self, *, reason: str) -> bool:
        self.held = True
        return True

    def release_update_hold(self) -> bool:
        self.held = False
        return True

    def list_jobs(self, status_filter=None):
        return []


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
@pytest.mark.parametrize(
    ("github", "reason"),
    [("unsigned", "not_github_signed"), ("down", "github_unavailable"), ("signed", "")],
)
@pytest.mark.parametrize("source", ["desktop", "remote"])
def test_the_composed_service_checks_the_signature_for_the_desktop_and_the_phone(
    tmp_path, monkeypatch, source, github, reason
):
    repos = make_repos(tmp_path, {"a.txt": "a\n"})
    old = repos.head
    new = repos.merge_upstream({"b.txt": "b\n"})

    def fetch(url):
        if github == "down":
            raise urllib.error.URLError("offline")
        return 200, answer(sha=new, verified=github == "signed")

    monkeypatch.setattr(lu, "_github_json", fetch)
    monkeypatch.setattr(lu, "EXPECTED_ORIGIN", str(repos.origin))
    monkeypatch.setattr(lu, "environment_check", lambda *a, **k: lambda sha: (True, ""))
    queue = _Queue()
    launched = []
    service = build_live_update_service(
        SimpleNamespace(job_service=SimpleNamespace(job_queue=queue, runner=None)),
        state_dir=tmp_path / "state",
        repo_root=repos.live,
        launch_updater=launched.append,
    )
    service.set_allow_remote(True)

    assert service.check().reason == reason
    outcome = service.update(
        source=source, expected_sha=new if source == "remote" else None, record_id="r1"
    )

    if reason:
        assert (outcome.status, outcome.reason) == ("refused", reason)
        assert service.last_result()["reason"] == reason
    else:
        assert outcome.status == "restarting"
    assert repos.head == old  # only the updater moves the checkout, and it never ran here
    assert bool(launched) == (not reason) and queue.held == (not reason)
