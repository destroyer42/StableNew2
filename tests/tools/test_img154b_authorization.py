"""PR-IMG-MODELS-154B T96-T103: the owner authorization record, its binding and the owner passphrase verifier.

Synthetic data only. The passphrase is a secret only the owner holds: the record stores a salted verifier, and no code path in
this package prints, logs or writes the passphrase itself.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.qualification.img154 import manifest as mf
from tools.qualification.img154b import authorization as au
from tools.qualification.img154b import cli
from tools.qualification.img154b import physical as ph
from tools.qualification.img154b import request as rq

CODE = au.CodeRevision("clean", "a" * 40, "b" * 64)
NOW = "2026-01-01T12:00:00+00:00"
PASSPHRASE = "owner chosen long passphrase"
SALT = "00112233445566778899aabbccddeeff"
ITERATIONS = 100_000


@pytest.fixture(scope="module")
def plan():
    return mf.build_manifest()


@pytest.fixture(scope="module")
def payload(plan):
    return rq.build_txt2img_payload(plan)


def record(plan, payload, **overrides):
    base = {
        "schema": au.AUTHORIZATION_SCHEMA,
        "attempt_identity": plan.attempt_identity(),
        "manifest_digest": plan.digest(),
        "payload_digest": payload.payload_digest,
        "semantics_revision": rq.SEMANTICS_REVISION,
        "policy_revision": plan.policy_revision,
        "evidence_contract_revision": plan.evidence_contract_revision,
        "git_sha": CODE.sha,
        "source_sha256": CODE.source_sha256,
        "accepted_risks": [au.RISK_ID],
        "cases": 1,
        "retries": 0,
        "authorized_by": "owner",
        "authorized_utc": "2026-01-01T11:00:00+00:00",
        "expires_utc": "2026-01-01T23:00:00+00:00",
        "statement": au.REQUIRED_STATEMENT,
        "challenge": au.authorization_challenge(plan, payload, CODE),
        "passphrase_salt": SALT,
        "passphrase_verifier": au.derive_verifier(PASSPHRASE, SALT, ITERATIONS),
        "passphrase_iterations": ITERATIONS,
    }
    base.update(overrides)
    return base


def test_t96_a_complete_bound_record_verifies(plan, payload):
    auth = au.parse_authorization(record(plan, payload))
    assert (
        au.verify_authorization(auth, manifest=plan, payload=payload, code=CODE, now_utc=NOW) == []
    )


def test_t97_only_the_exact_passphrase_verifies(plan, payload):
    auth = au.parse_authorization(record(plan, payload))
    assert au.verify_passphrase(auth, PASSPHRASE) is True
    for wrong in (
        None,
        "",
        "short",
        PASSPHRASE.upper(),
        PASSPHRASE + " ",
        " " + PASSPHRASE,
        "x" * 40,
    ):
        assert au.verify_passphrase(auth, wrong) is False, repr(wrong)  # type: ignore[arg-type]


def test_t97_the_verifier_is_salted_slow_and_not_the_passphrase(plan, payload):
    one = au.derive_verifier(PASSPHRASE, SALT, ITERATIONS)
    other_salt = au.derive_verifier(PASSPHRASE, "ff" * 16, ITERATIONS)
    other_work = au.derive_verifier(PASSPHRASE, SALT, ITERATIONS + 1)
    assert len({one, other_salt, other_work}) == 3 and len(one) == 64
    assert PASSPHRASE not in json.dumps(record(plan, payload))
    assert au.PASSPHRASE_ITERATIONS >= 600_000 and au.MIN_PASSPHRASE_ITERATIONS >= 100_000
    assert (
        len(au.new_passphrase_salt()) == 32 and au.new_passphrase_salt() != au.new_passphrase_salt()
    )


def test_t97_the_comparison_is_constant_time():
    source = Path(au.__file__).read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compare_digest"
    ]
    assert calls  # hmac.compare_digest, never ==


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"passphrase_salt": "xyz"}, "AUTHORIZATION_PASSPHRASE_SALT"),
        ({"passphrase_salt": "00"}, "AUTHORIZATION_PASSPHRASE_SALT"),
        ({"passphrase_verifier": "not-hex"}, "AUTHORIZATION_PASSPHRASE_VERIFIER"),
        ({"passphrase_verifier": "ab" * 31}, "AUTHORIZATION_PASSPHRASE_VERIFIER"),
        ({"passphrase_iterations": 1}, "AUTHORIZATION_PASSPHRASE_WORK_FACTOR"),
    ],
)
def test_t98_a_malformed_or_weak_verifier_refuses_the_record(plan, payload, overrides, code):
    auth = au.parse_authorization(record(plan, payload, **overrides))
    codes = {
        f.code
        for f in au.verify_authorization(
            auth, manifest=plan, payload=payload, code=CODE, now_utc=NOW
        )
    }
    assert code in codes
    assert au.verify_passphrase(auth, PASSPHRASE) is False


@pytest.mark.parametrize(
    "missing", ["passphrase_salt", "passphrase_verifier", "passphrase_iterations"]
)
def test_t98_a_record_without_the_verifier_does_not_parse(plan, payload, missing):
    data = record(plan, payload)
    del data[missing]
    with pytest.raises(au.AuthorizationError):
        au.parse_authorization(data)


def test_t98_the_record_digest_covers_the_verifier(plan, payload):
    one = au.parse_authorization(record(plan, payload))
    two = replace(one, passphrase_verifier="cd" * 32)
    assert one.record_digest() != two.record_digest()


# --- reading the record --------------------------------------------------------------------------------------------------


def test_t99_the_record_is_read_with_a_bom_and_an_unreadable_one_is_simply_absent(
    tmp_path, plan, payload
):
    records = tmp_path / "records"
    records.mkdir()
    path = records / f"{plan.attempt_identity()}{ph.AUTHORIZATION_SUFFIX}"
    text = json.dumps(record(plan, payload))
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))  # an editor-added BOM
    assert ph.read_authorization(records, plan) is not None
    path.write_bytes(text.encode("utf-16"))  # not UTF-8 at all: unusable, never a crash
    assert ph.read_authorization(records, plan) is None
    path.write_text("{not json", encoding="utf-8")
    assert ph.read_authorization(records, plan) is None
    path.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert ph.read_authorization(records, plan) is None
    path.unlink()
    assert ph.read_authorization(records, plan) is None


# --- the verifier command -----------------------------------------------------------------------------------------------


def test_t100_the_verifier_command_prints_a_verifier_and_never_the_passphrase(monkeypatch, capsys):
    answers = iter([PASSPHRASE, PASSPHRASE])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    assert cli.main(["passphrase-verifier"]) == 0
    printed = capsys.readouterr().out
    assert PASSPHRASE not in printed
    data = json.loads(printed)
    assert (
        au.derive_verifier(PASSPHRASE, data["passphrase_salt"], data["passphrase_iterations"])
        == data["passphrase_verifier"]
    )


@pytest.mark.parametrize(
    "answers",
    [["a long enough phrase one", "a long enough phrase two"], ["short", "short"]],
)
def test_t100_a_mismatched_or_short_passphrase_is_refused_without_output(
    monkeypatch, capsys, answers
):
    iterator = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(iterator))
    with pytest.raises(SystemExit):
        cli.main(["passphrase-verifier"])
    assert "passphrase_verifier" not in capsys.readouterr().out


@pytest.mark.parametrize("change", ["content", "delete", "replace", "invalid", "risk", "policy"])
def test_r2_authorization_snapshot_refuses_file_changes(tmp_path, change):
    import json
    from dataclasses import asdict

    from tests.tools.test_img154b_case import Harness

    h = Harness(tmp_path)
    path = tmp_path / "synthetic-authorization.json"
    data = {"schema": au.AUTHORIZATION_SCHEMA, **asdict(h.authorization)}
    path.write_text(json.dumps(data), encoding="utf-8")
    record = au.read_authorization_record(path)
    assert record is not None and record.is_current(h.authorization)
    if change == "delete":
        path.unlink()
    elif change == "replace":
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    elif change == "invalid":
        path.write_text("broken", encoding="utf-8")
    else:
        data[
            "authorized_by"
            if change == "content"
            else "accepted_risks"
            if change == "risk"
            else "policy_revision"
        ] = "changed"
        path.write_text(json.dumps(data), encoding="utf-8")
    assert not record.is_current(h.authorization)
