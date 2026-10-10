"""PR-IMG-MODELS-154B T79-T95: the execution boundary of the 154B harness.

* Source/AST guards: which module may hold which authority (network, process lifecycle, native libraries, filesystem
  creation, the physical authority) and that nothing writes an owner authorization.
* Import-time purity (audit-hooked subprocess), the default CLI surface, the activation gates, and the HTTP client's
  no-retry/budget behavior against a loopback server that the test itself starts.
"""

from __future__ import annotations

import ast
import http.server
import importlib
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from tools.qualification.img154 import manifest as mf
from tools.qualification.img154b import cli
from tools.qualification.img154b import physical as ph

PACKAGE = Path(ph.__file__).parent
MODULES = tuple(sorted(p.stem for p in PACKAGE.glob("*.py") if p.name != "__init__.py"))
REPO_ROOT = PACKAGE.parents[2]

NETWORK_IMPORTS = {
    "http",
    "socket",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "websocket",
    "websockets",
    "ssl",
    "ftplib",
}
PROCESS_IMPORTS = {"subprocess", "multiprocessing", "pty", "signal", "_winapi"}
NATIVE_IMPORTS = {"ctypes", "cffi", "winreg"}
DYNAMIC_IMPORTS = {"importlib", "runpy"}
FORBIDDEN_ATTRS = {"kill", "terminate", "send_signal", "killpg", "TerminateProcess", "startfile"}
FORBIDDEN_CALLS = {
    "os.kill",
    "os.killpg",
    "os.system",
    "os.popen",
    "os.startfile",
    "eval",
    "exec",
    "compile",
    "__import__",
}
FORBIDDEN_PREFIXES = (
    "src.pipeline",
    "src.controller",
    "src.gui",
    "src.gui_v2",
    "src.queue",
    "src.history",
    "src.learning",
    "src.video",
    "src.api.webui_process_manager",
    "src.api.client",
)
FILE_WRITERS = {
    "mkdir",
    "write_text",
    "write_bytes",
    "unlink",
    "rename",
    "replace",
    "rmdir",
    "touch",
    "chmod",
}
OS_WRITERS = {
    "os.open",
    "os.replace",
    "os.unlink",
    "os.rename",
    "os.remove",
    "os.mkdir",
    "os.makedirs",
    "os.fdopen",
}

#: Which modules may hold each authority. Everything else must hold none of it.
ALLOWED = {
    "network": {"physical"},
    "native": {"sampler"},
    "psutil": {"runtime"},
    "file_writes": {"bundle", "runtime", "fence", "physical", "cli"},
    "img115_lifecycle": {"runtime"},
    "img115_image_validation": {"adjudication"},
}


def _trees():
    for name in MODULES:
        yield name, ast.parse((PACKAGE / f"{name}.py").read_text(encoding="utf-8"))


def _imports(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _top(names):
    return {name.split(".")[0] for name in names}


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_t79_modules_are_discovered_and_the_expected_set_exists():
    assert {
        "request",
        "fence",
        "adjudication",
        "runtime",
        "sampler",
        "case",
        "authorization",
        "bundle",
        "collector",
        "physical",
        "cli",
    } <= set(MODULES)


def test_t80_only_the_physical_module_holds_network_authority():
    offenders = {
        name: sorted(_top(_imports(tree)) & NETWORK_IMPORTS)
        for name, tree in _trees()
        if name not in ALLOWED["network"] and _top(_imports(tree)) & NETWORK_IMPORTS
    }
    assert offenders == {}
    physical_imports = _top(_imports(dict(_trees())["physical"]))
    assert physical_imports & NETWORK_IMPORTS == {
        "http"
    }  # stdlib http.client only: no pooling, retries or redirects


def test_t80_no_module_imports_a_process_creation_or_signal_facility():
    offenders = {
        name: sorted(_top(_imports(tree)) & PROCESS_IMPORTS)
        for name, tree in _trees()
        if _top(_imports(tree)) & PROCESS_IMPORTS
    }
    assert (
        offenders == {}
    )  # the one launcher is WebUIProcessManager, reached only through img115's OwnedForge


def test_t81_native_libraries_psutil_and_dynamic_imports_are_confined():
    for name, tree in _trees():
        tops = _top(_imports(tree))
        if name not in ALLOWED["native"]:
            assert not tops & NATIVE_IMPORTS, name
        if name not in ALLOWED["psutil"]:
            assert "psutil" not in tops, name
        assert not tops & DYNAMIC_IMPORTS, name


def test_t81_no_import_of_production_pipeline_gui_queue_history_or_the_process_manager_itself():
    for name, tree in _trees():
        for module in _imports(tree):
            assert not module.startswith(FORBIDDEN_PREFIXES), (name, module)
            # lazy, function-level imports of the img115 lifecycle adapter and image validator are the only crossings
            if module.startswith("tools.qualification.img115"):
                allowed = ALLOWED["img115_lifecycle"] | ALLOWED["img115_image_validation"]
                assert name in allowed, (name, module)


def test_t82_no_kill_terminate_signal_or_dynamic_execution_call_exists():
    for name, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = _dotted(node.func)
                assert called not in FORBIDDEN_CALLS, (name, called)
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in FORBIDDEN_ATTRS, (name, node.func.attr)
                    # the stop request goes through the manager's own method, which is the one allowed ``.stop()``
    # the only ``stop`` attribute calls are the manager-owned stop, the sampler's own stop and threading primitives
    allowed_stop_owners = {"runtime", "case", "sampler", "physical"}
    for name, tree in _trees():
        stops = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "stop"
        ]
        if stops:
            assert name in allowed_stop_owners, name


def test_t83_filesystem_creation_is_confined_to_the_modules_that_own_it():
    for name, tree in _trees():
        if name in ALLOWED["file_writes"]:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = _dotted(node.func)
                assert called not in OS_WRITERS, (name, called)
                if isinstance(node.func, ast.Attribute):
                    string_replace = (
                        node.func.attr == "replace" and len(node.args) == 2
                    )  # str.replace(old, new)
                    assert string_replace or node.func.attr not in FILE_WRITERS, (
                        name,
                        node.func.attr,
                    )
                if (
                    called == "open"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                ):
                    assert not set(str(node.args[1].value)) & set("wax+"), (
                        name,
                        node.args[1].value,
                    )


def test_t84_nothing_in_the_package_can_write_an_owner_authorization():
    for name, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                lowered = node.name.lower()
                assert not any(
                    word in lowered
                    for word in ("write_auth", "create_auth", "grant", "issue_auth", "save_auth")
                ), (name, node.name)
    # the suffix constant is only used by a read_* function
    physical = (PACKAGE / "physical.py").read_text(encoding="utf-8")
    tree = ast.parse(physical)
    users = []
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if any(
            isinstance(n, ast.Name) and n.id == "AUTHORIZATION_SUFFIX" for n in ast.walk(function)
        ):
            users.append(function.name)
    assert users == ["read_authorization"]
    for name, module_tree in _trees():
        for node in ast.walk(module_tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "owner-authorization.json" in node.value
            ):
                assert name == "physical", name


def test_t85_the_physical_authority_is_minted_only_by_the_physical_activation_path():
    for name, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in (
                "mint_physical_authority",
                "_PHYSICAL_KEY",
            ):
                assert name in ("case", "physical"), (name, node.id)
    users = [
        name
        for name, tree in _trees()
        if any(
            isinstance(n, ast.Call) and _dotted(n.func) == "mint_physical_authority"
            for n in ast.walk(tree)
        )
    ]
    assert users == ["physical"]


def test_t86_nothing_imports_the_physical_module_and_the_default_cli_cannot_reach_it():
    for name, tree in _trees():
        if name == "physical":
            continue
        for module in _imports(tree):
            assert not module.endswith(".physical") and module != "physical", (name, module)
    assert "physical" not in "".join(sorted(_imports(dict(_trees())["cli"])))
    import argparse

    parser = cli.build_parser()
    commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices
    assert set(commands) == {"request", "layout-plan", "challenge", "dry-run"}
    flags = {opt for p in commands.values() for a in p._actions for opt in a.option_strings}
    assert not {
        f
        for f in flags
        if any(w in f for w in ("execute", "start", "launch", "generate", "run", "force"))
    }


def test_t86_the_physical_cli_has_exactly_three_commands_and_execute_is_gated():
    import argparse

    parser = ph.build_parser()
    commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices
    assert set(commands) == {"preflight", "materialize", "execute"}


# --- activation gates ----------------------------------------------------------------------------------------------------


def request(**overrides):
    base = {
        "platform": "win32",
        "env": {ph.ACTIVATION_ENV: ph.ACTIVATION_VALUE},
        "attempt_identity_arg": "a" * 64,
        "expected_identity": "a" * 64,
        "stdin_tty": True,
        "stdout_tty": True,
        "under_test_runner": False,
        "authorization_present": True,
    }
    base.update(overrides)
    return ph.ActivationRequest(**base)


def test_t87_all_gates_open_is_the_only_empty_refusal_list():
    assert ph.evaluate_activation(request()) == []


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"platform": "linux"}, "PLATFORM_NOT_WINDOWS"),
        ({"under_test_runner": True}, "UNDER_TEST_RUNNER"),
        ({"env": {}}, "ENVIRONMENT_OPT_IN_ABSENT"),
        ({"env": {ph.ACTIVATION_ENV: "1"}}, "ENVIRONMENT_OPT_IN_ABSENT"),
        ({"attempt_identity_arg": None}, "ATTEMPT_IDENTITY_ARGUMENT_MISMATCH"),
        ({"attempt_identity_arg": "b" * 64}, "ATTEMPT_IDENTITY_ARGUMENT_MISMATCH"),
        ({"stdin_tty": False}, "NOT_AN_INTERACTIVE_TERMINAL"),
        ({"stdout_tty": False}, "NOT_AN_INTERACTIVE_TERMINAL"),
        ({"authorization_present": False}, "OWNER_AUTHORIZATION_RECORD_ABSENT"),
    ],
)
def test_t87_every_single_gate_refuses_on_its_own(overrides, reason):
    assert reason in ph.evaluate_activation(request(**overrides))


def test_t88_a_test_runner_is_detected_so_execute_cannot_be_reached_from_a_test():
    assert ph.under_test_runner() is True  # this very process is pytest
    assert ph.under_test_runner(env={}, modules={}) is False
    assert ph.under_test_runner(env={"PYTEST_CURRENT_TEST": "x"}, modules={}) is True


def test_t88_execute_without_the_opt_in_refuses_before_anything_is_built(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.delenv(ph.ACTIVATION_ENV, raising=False)
    config = ph.HostConfig(
        root=tmp_path / "q",
        install=tmp_path / "install",
        models_root=None,
        record_root=tmp_path / "records",
    )
    assert ph.run_execute(config, None) == 2
    assert "disabled" in capsys.readouterr().err
    assert (
        not (tmp_path / "q").exists() and not (tmp_path / "records").exists()
    )  # nothing was created


def test_t88_even_with_every_environment_gate_a_test_run_still_refuses(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv(ph.ACTIVATION_ENV, ph.ACTIVATION_VALUE)
    config = ph.HostConfig(
        root=tmp_path / "q",
        install=tmp_path / "install",
        models_root=None,
        record_root=tmp_path / "records",
    )
    identity = config.manifest.attempt_identity()
    assert ph.run_execute(config, identity) == 2
    err = capsys.readouterr().err
    assert "UNDER_TEST_RUNNER" in err and "OWNER_AUTHORIZATION_RECORD_ABSENT" in err
    assert not (tmp_path / "q").exists()


def test_t88_materialize_needs_its_own_explicit_confirmation(tmp_path, capsys):
    assert (
        ph.main(
            [
                "materialize",
                "--qualification-root",
                str(tmp_path / "q"),
                "--forge-install",
                str(tmp_path / "i"),
            ]
        )
        == 2
    )
    assert "--confirm-copy" in capsys.readouterr().err
    assert not (tmp_path / "q").exists()


# --- import-time purity --------------------------------------------------------------------------------------------------

AUDIT = textwrap.dedent(
    """
    import json, sys
    events = []
    WATCHED = {"subprocess.Popen", "os.system", "socket.connect", "socket.bind", "socket.getaddrinfo", "ctypes.dlopen",
               "os.remove", "os.mkdir", "os.rename", "os.rmdir", "shutil.copyfile", "os.exec", "os.spawn", "os.fork"}
    def hook(event, args):
        if event == "socket.bind":
            events.append(event + ":" + repr(args[1:]))
        elif event == "ctypes.dlopen":
            events.append(event + ":" + repr(args))
        elif event in WATCHED:
            events.append(event)
        elif event == "open":
            path, mode = args[0], args[1] if len(args) > 1 else None
            if isinstance(mode, str) and any(c in mode for c in "wax+") and "__pycache__" not in str(path):
                events.append(f"open-write:{path}")
    sys.path.insert(0, %(repo)r)
    sys.addaudithook(hook)
    import importlib
    for name in %(modules)r:
        importlib.import_module("tools.qualification.img154b." + name)
    print(json.dumps(events))
    """
)


def test_t89_importing_every_module_has_no_process_network_native_or_write_side_effect():
    script = AUDIT % {"modules": list(MODULES), "repo": str(REPO_ROOT)}
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", script],
        cwd=str(REPO_ROOT),
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    events = json.loads(done.stdout.strip().splitlines()[-1])
    # Two known, third-party/stdlib probes that are not harness actions: ``import ctypes`` loads kernel32 for GetLastError, and
    # urllib3 (reached through the PR-154A probe module's import chain) binds an ephemeral loopback IPv6 socket to test for
    # IPv6 support. Anything else is a side effect of this package.
    tolerated = {"ctypes.dlopen:('kernel32',)", "socket.bind:(('::1', 0),)"}
    assert [event for event in events if event not in tolerated] == []


# --- the HTTP client -----------------------------------------------------------------------------------------------------


class Recorder(http.server.BaseHTTPRequestHandler):
    log: list[tuple[str, str]] = []
    mode = "ok"

    def log_message(self, *args):  # silence
        pass

    def _record(self):
        type(self).log.append((self.command, self.path))

    def do_GET(self):
        self._record()
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._record()
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if type(self).mode == "reset":
            self.connection.close()  # no response at all: the client cannot know whether it was processed
            return
        if type(self).mode == "redirect":
            self.send_response(307)
            self.send_header("Location", "/sdapi/v1/txt2img")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"x" * 5000 if type(self).mode == "large" else b'{"images": []}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    Recorder.log = []
    Recorder.mode = "ok"
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_t90_a_post_is_sent_exactly_once_and_a_dropped_connection_is_never_retried(server):
    Recorder.mode = "reset"
    client = ph.HttpClientPort(server.server_address[1])
    result = client.post_json("/sdapi/v1/txt2img", b"{}", timeout_s=5.0)
    assert result.status is None and result.error
    assert Recorder.log == [
        ("POST", "/sdapi/v1/txt2img")
    ]  # one request reached the server, none was replayed
    with pytest.raises(ph.HttpRefused):
        client.post_json(
            "/sdapi/v1/txt2img", b"{}", timeout_s=5.0
        )  # the budget is spent even though the send failed
    assert len(Recorder.log) == 1


def test_t90_redirects_are_not_followed_and_the_budget_covers_only_the_two_known_posts(server):
    Recorder.mode = "redirect"
    client = ph.HttpClientPort(server.server_address[1])
    result = client.post_json("/sdapi/v1/options", b"{}", timeout_s=5.0)
    assert result.status == 307
    assert Recorder.log == [("POST", "/sdapi/v1/options")]
    for path in (
        "/sdapi/v1/interrupt",
        "/sdapi/v1/img2img",
        "/sdapi/v1/unload-checkpoint",
        "/internal/restart",
    ):
        with pytest.raises(ph.HttpRefused):
            client.post_json(path, b"{}", timeout_s=1.0)
    assert len(Recorder.log) == 1


def test_t90_only_the_observation_paths_may_be_fetched(server):
    client = ph.HttpClientPort(server.server_address[1])
    assert client.get_json("/sdapi/v1/options").body == {"ok": True}
    assert client.get_json("/sdapi/v1/progress?skip_current_image=true").status == 200
    for path in ("/sdapi/v1/interrupt", "/sdapi/v1/skip", "/", "/sdapi/v1/memory"):
        with pytest.raises(ph.HttpRefused):
            client.get_json(path)


def test_t90_a_response_that_is_not_json_or_is_too_large_is_a_result_not_a_crash(
    server, monkeypatch
):
    client = ph.HttpClientPort(server.server_address[1], budget={"/sdapi/v1/options": 2})
    Recorder.mode = "large"
    monkeypatch.setattr(ph, "MAX_RESPONSE_BYTES", 100)
    assert client.post_json("/sdapi/v1/options", b"{}", timeout_s=5.0).error == "response_too_large"
    monkeypatch.setattr(ph, "MAX_RESPONSE_BYTES", 10_000)
    assert client.post_json("/sdapi/v1/options", b"{}", timeout_s=5.0).error == "invalid_json"


def test_t90_the_port_must_be_a_user_port_and_the_host_is_fixed_to_loopback():
    with pytest.raises(ValueError):
        ph.HttpClientPort(80)
    seen = {}

    class Conn:
        def __init__(self, host, port, timeout=None):
            seen["host"], seen["port"] = host, port

        def request(self, *a, **k):
            raise OSError("no network in this test")

        def close(self):
            pass

    client = ph.HttpClientPort(7886, connection_factory=Conn)
    assert client.get_json("/sdapi/v1/options").error == "OSError"
    assert seen == {"host": "127.0.0.1", "port": 7886}


# --- the default CLI -----------------------------------------------------------------------------------------------------


def test_t91_the_default_commands_run_offline_and_report_that_they_execute_nothing(
    tmp_path, capsys
):
    assert cli.main(["dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["executes_anything"] is False and plan["no_retry_no_replay"] is True
    assert plan["stages"][0] == "claimed" and plan["stages"][-1] == "terminal_evidence"
    assert "TECHNICAL_PASS_CONSTRAINED" in plan["result_classes"]

    assert cli.main(["request"]) == 0
    request_report = json.loads(capsys.readouterr().out)
    assert request_report["payload"]["body"]["distilled_cfg_scale"] == 9.0
    assert request_report["frozen_intent_values_changed"] is False

    root = tmp_path / "proposed"
    assert cli.main(["layout-plan", "--qualification-root", str(root)]) == 0
    layout = json.loads(capsys.readouterr().out)
    assert layout["creates_anything"] is False and not root.exists()


def test_t91_the_challenge_command_prints_a_binding_and_writes_no_authorization(tmp_path, capsys):
    assert cli.main(["challenge", "--out", str(tmp_path / "challenge.json")]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["writes_authorization"] is False
    assert printed["binding"]["attempt_identity"] == mf.build_manifest().attempt_identity()
    assert [p.name for p in tmp_path.iterdir()] == ["challenge.json"]


def test_t91_request_reverification_fails_closed_on_an_unreadable_source(tmp_path, capsys):
    assert cli.main(["request", "--forge-source", str(tmp_path / "missing")]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["source_reverified"] is False
    assert report["semantics"]["status"] == "NOT_VERIFIED"


def test_t92_every_module_imports_cleanly_on_any_platform():
    for name in MODULES:
        importlib.import_module(f"tools.qualification.img154b.{name}")
