"""PHONE-CORE PC-1a: the page's files come from a table read at start, under a version that names their bytes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from review_gateway.static_files import STATIC_DIR, load_static

from tests.review_gateway_service.conftest import Rig, sha

IMMUTABLE = "public, max-age=31536000, immutable"
TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def version_of(rig) -> str:
    index = rig.phone.get("/")
    assert index.status_code == 200
    found = set(re.findall(r"/s/([^/\"]+)/", index.text))
    assert len(found) == 1, found
    return found.pop()


def test_the_page_names_one_version_and_is_itself_never_kept(rig) -> None:
    index = rig.phone.get("/")

    assert index.headers["content-type"].startswith("text/html")
    assert index.headers["cache-control"] == "no-cache"
    assert "{{V}}" not in index.text
    assert re.fullmatch(r"[0-9a-f]{12}", version_of(rig))
    assert f'<script type="module" src="/s/{version_of(rig)}/core/main.js">' in index.text


def test_every_page_file_is_listed_and_served_with_the_listed_bytes(rig) -> None:
    version = version_of(rig)
    listed = rig.phone.get(f"/s/{version}/files.json")

    assert listed.headers["cache-control"] == IMMUTABLE
    assert listed.json()["version"] == version
    published = {
        path.relative_to(STATIC_DIR).as_posix()
        for path in STATIC_DIR.rglob("*")
        if path.is_file() and path.name != "index.html"
    }
    assert set(listed.json()["files"]) == published
    for name, digest in listed.json()["files"].items():
        response = rig.phone.get(f"/s/{version}/{name}")
        assert response.status_code == 200, name
        assert sha(response.content) == digest, name
        assert response.headers["content-type"].split(";")[0] == TYPES[Path(name).suffix], name
        assert response.headers["cache-control"] == IMMUTABLE, name
        assert "script-src 'self'" in response.headers["content-security-policy"], name


@pytest.mark.parametrize(
    "path",
    [
        "/s/000000000000/core/main.js",  # another version's address
        "/s/000000000000/files.json",
        "/s/{v}/index.html",  # the template is only ever served at /
        "/s/{v}/core",
        "/s/{v}/core/",
        "/s/{v}/nothing.js",
        "/s/{v}/static/core/main.js",
        "/s/{v}/../static_files.py",
        "/s/{v}/%2e%2e/static_files.py",
        "/s/{v}/core/%2e%2e/%2e%2e/config.py",
        "/s/{v}/..%2F..%2Fconfig.py",
        "/s/{v}/%2Fetc%2Fpasswd",
        "/s/{v}/core%5Cmain.js",
        "/static/app.js",  # the addresses of the hand-listed table are gone
        "/static/core/main.js",
    ],
)
def test_only_the_table_answers(rig, path) -> None:
    response = rig.phone.get(path.format(v=version_of(rig)))

    assert response.status_code == 404
    assert "immutable" not in response.headers["cache-control"]


def tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, body in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return root


def test_the_page_names_its_features_and_links_their_styles_in_that_order(rig) -> None:
    index = rig.phone.get("/").text

    listed = re.search(r'<meta name="rg-features" content="([a-z,]+)">', index)
    assert listed, "the page names its features"
    names = listed[1].split(",")
    assert sorted(names) == sorted(
        path.name for path in (STATIC_DIR / "features").iterdir() if path.is_dir()
    )
    version = version_of(rig)
    assert re.findall(r'<link rel="stylesheet" href="([^"]+)">', index) == [
        f"/s/{version}/core/core.css",
        *(
            f"/s/{version}/features/{name}/{name}.css"
            for name in names
            if (STATIC_DIR / "features" / name / f"{name}.css").is_file()
        ),
    ]


def test_features_are_listed_by_their_own_order_and_only_with_an_entry(tmp_path) -> None:
    root = tree(
        tmp_path / "static",
        {
            "index.html": b'<meta content="{{FEATURES}}">\n{{STYLES}}',
            "features/late/feature.js": b"export default {\n  id: 'late',\n  order: 90,\n};\n",
            "features/late/late.css": b"a{}",
            "features/early/feature.js": b"export default {\n  id: 'early',\n  order: 5,\n};\n",
            "features/early/early.css": b"b{}",
            "features/helpers/only.js": b"export const x = 1;\n",
        },
    )

    site = load_static(root)

    assert site.index.decode() == (
        '<meta content="early,late">\n'
        f'<link rel="stylesheet" href="/s/{site.version}/features/early/early.css">\n'
        f'  <link rel="stylesheet" href="/s/{site.version}/features/late/late.css">'
    )


def test_the_version_changes_exactly_when_a_published_byte_or_the_template_does(tmp_path) -> None:
    files = {"index.html": b"<a href='/s/{{V}}/core/main.js'>", "core/main.js": b"one"}
    root = tree(tmp_path / "static", files)
    first = load_static(root)

    # Not published, so not part of the version.
    tree(root, {"notes.md": b"x", "core/secret.py": b"y", "core/data.json": b"{}"})
    assert load_static(root).version == first.version
    assert list(load_static(root).files) == ["core/main.js"]
    assert first.index == f"<a href='/s/{first.version}/core/main.js'>".encode()

    seen = {first.version}
    for change in (
        {"core/main.js": b"two"},
        {"features/a/a.css": b"new file"},
        {"index.html": b"<p>{{V}}</p>"},
    ):
        tree(root, change)
        seen.add(load_static(root).version)
    assert len(seen) == 4


def test_the_session_says_which_page_and_commit_it_is_talking_to(rig) -> None:
    rig.pair()

    session = rig.phone.get("/api/session").json()

    assert session["static_version"] == version_of(rig)
    assert session["commit"] == "dev"  # no source.json: not an installed release


@pytest.mark.parametrize(
    ("source", "commit"),
    [
        (json.dumps({"commit": COMMIT, "installed_at": "2026-11-27T00:00:00Z"}), COMMIT),
        (json.dumps({"commit": None}), "dev"),
        (json.dumps({"commit": "<script>"}), "dev"),
        ("not json", "dev"),
    ],
)
def test_the_commit_comes_from_the_releases_source_file(tmp_path, clock, source, commit) -> None:
    release = tmp_path / "release"
    release.mkdir()
    (release / "source.json").write_text(source, encoding="utf-8")
    rig = Rig(tmp_path / "gateway", clock, release_dir=release)
    try:
        rig.pair()
        assert rig.phone.get("/api/session").json()["commit"] == commit
    finally:
        rig.close()
