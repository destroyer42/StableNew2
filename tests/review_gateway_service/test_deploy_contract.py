"""D1 / S10: a separate deployable with a hash-pinned, minimal dependency set and no runtime downloads."""

from __future__ import annotations

import ast
import re
import sys

from tests.review_gateway_service.conftest import GATEWAY_ROOT, ROOT

PACKAGE = GATEWAY_ROOT / "review_gateway"
RUNTIME = {"starlette", "uvicorn", "jsonschema"}


def pins(text: str) -> dict[str, str]:
    return dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", text, re.MULTILINE))


def read(name: str) -> str:
    return (GATEWAY_ROOT / name).read_text(encoding="utf-8")


def test_the_gateway_imports_only_itself_the_standard_library_and_its_pins() -> None:
    allowed = set(sys.stdlib_module_names) | RUNTIME
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in allowed, f"{path.name} imports {name}"


def _imported_modules(source: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def test_the_application_never_imports_the_gateway() -> None:
    # Checks imports, not text: the PC side (RG-120) legitimately names its own modules after the gateway, e.g.
    # `src.gui.review_gateway_dialog`. What must never happen is the app importing the separate deployable.
    for path in (ROOT / "src").rglob("*.py"):
        for name in _imported_modules(path.read_text(encoding="utf-8")):
            top = name.split(".")[0]
            assert top != "review_gateway" and not name.startswith("services"), (
                f"{path} imports {name}"
            )


def test_the_import_check_catches_a_real_gateway_import() -> None:
    real = "import review_gateway.app\nfrom services.review_gateway import x\n"
    assert _imported_modules(real) == ["review_gateway.app", "services.review_gateway"]
    pc_side = "from src.gui.review_gateway_dialog import install\n"
    assert _imported_modules(pc_side) == ["src.gui.review_gateway_dialog"]


def test_every_locked_requirement_is_pinned_and_hashed() -> None:
    lock = read("requirements.txt")
    entries = re.split(r"\n(?=[A-Za-z0-9])", lock[lock.index("\nanyio") :].strip())

    assert len(entries) >= len(RUNTIME)
    for entry in entries:
        first = entry.splitlines()[0]
        assert re.match(r"^[A-Za-z0-9_.-]+==\S+", first), first
        assert "--hash=sha256:" in entry, first
    assert pins(read("requirements.in")).keys() == RUNTIME
    assert pins(read("requirements.in")).items() <= pins(lock).items()


def test_ci_tests_the_versions_the_gateway_deploys() -> None:
    development = pins((ROOT / "requirements-dev.txt").read_text(encoding="utf-8"))

    for name, version in pins(read("requirements.in")).items():
        assert development.get(name) == version, name


def test_the_application_environment_does_not_gain_the_gateway() -> None:
    for name in ("requirements.txt", "constraints/windows-py314-cu130.txt"):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "starlette" not in text and "uvicorn" not in text, name


def test_the_installer_installs_only_hash_verified_wheels() -> None:
    script = read("install.sh")
    installs = [line for line in script.splitlines() if "pip" in line and " install " in line]

    assert installs
    for line in installs:
        assert "--require-hashes" in line and "--only-binary" in line, line
    assert not re.search(r"\b(curl|wget|git clone)\b", script)
    assert "init-secret" in script and 'cat "$SECRET' not in script


def test_linux_files_keep_unix_line_endings() -> None:
    attributes = read(".gitattributes")

    for pattern in ("*.sh", "*.service", "requirements.txt"):
        assert f"{pattern} text eol=lf" in attributes
    for name in ("install.sh", "review-gateway.service"):
        assert b"\r\n" not in (GATEWAY_ROOT / name).read_bytes(), name


def test_the_service_runs_unprivileged_and_restarts() -> None:
    unit = read("review-gateway.service")

    for line in ("User=review-gateway", "NoNewPrivileges=yes", "UMask=0077", "Restart=on-failure"):
        assert line in unit
    assert "/opt/review-gateway/current/venv/bin/python" in unit


def position(script: str, fragment: str) -> int:
    assert fragment in script, fragment
    return script.index(fragment)


def test_the_installer_creates_a_certificate_once_and_prints_its_fingerprint() -> None:
    script = read("install.sh")

    assert 'if [ ! -s "$TLS_CERT" ] || [ ! -s "$TLS_KEY" ]; then' in script
    assert "openssl req -x509" in script and "umask 077" in script
    assert "fingerprint" in script
    assert 'sync_tls_cert = "$ETC/sync.crt"' in script and "# sync_tls_cert" not in script


def test_the_installer_installs_the_whole_page_tree() -> None:
    script = read("install.sh")

    # The page has directories, which a flat "install static/*" would stop on.
    assert any(path.is_dir() for path in (PACKAGE / "static").iterdir())
    assert 'cp -R "$SOURCE/review_gateway/static/." "$APP/review_gateway/static/"' in script
    assert 'find "$APP/review_gateway/static" -type d -exec chmod 0755 {} +' in script
    assert 'find "$APP/review_gateway/static" -type f -exec chmod 0644 {} +' in script
    assert "static/*" not in script


def test_an_upgrade_is_built_and_checked_before_the_running_service_is_touched() -> None:
    script = read("install.sh")

    switch = position(script, 'ln -sfn "$RELEASE" "$PREFIX/current"')
    for earlier in ("--require-hashes", "check-config", "systemctl stop review-gateway"):
        assert position(script, earlier) < switch, earlier
    assert position(script, "check-config") < position(script, "systemctl stop review-gateway")
    assert 'rm -rf "$APP"' not in script


def test_the_root_installer_does_not_follow_paths_the_service_could_replace() -> None:
    script = read("install.sh")

    check = position(script, '[ ! -L "$directory" ] || fail')
    assert check < position(script, 'install -d -m 0700 -o "$SERVICE_USER"')
    assert position(script, "umask 022") < position(script, "install -d")
    assert "MEDIA_DIR must be an absolute path" in script


def test_the_installer_leaves_an_empty_owner_only_place_for_the_immich_key() -> None:
    script = read("install.sh")

    assert 'immich_key_file = "$IMMICH_KEY_FILE"' in script
    assert 'immich_url = "${IMMICH_URL:-}"' in script
    placeholder = 'install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" /dev/null "$KEY_PATH"'
    assert placeholder in script
    assert position(script, 'if [ ! -e "$KEY_PATH" ]; then') < position(script, placeholder)
    assert 'chmod 0600 "$KEY_PATH"' in script
    # The key is typed into the file on the gateway: never passed in, echoed or read by the installer.
    assert "IMMICH_API_KEY" not in script and 'cat "$KEY_PATH' not in script
    assert "immich-check" in script


def test_the_installer_refuses_an_immich_address_it_could_not_correct_later() -> None:
    script = read("install.sh")

    assert '"" | http://* | https://*) ;;' in script
    assert position(script, "IMMICH_URL must start with") < position(script, 'cat > "$CONFIG"')


def test_the_installer_and_the_service_agree_where_the_key_is() -> None:
    script = read("install.sh")

    assert 'os.path.join(os.path.dirname(c["secret_file"]), "immich_api_key")' in script
