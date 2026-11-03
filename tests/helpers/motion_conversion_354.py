"""PR-VID-MOTION-354 test harness: synthetic FBX/BVH files and a fake Blender executable.

Nothing here needs Blender, a GPU, a model or a network.  ``write_fbx`` builds a tiny but structurally valid binary FBX (only
the node headers the scanner reads); ``fake_install`` returns a ``BlenderInstall`` whose command words start a Python script
that obeys Blender's command-line contract (``--version``; ``-- probe|render <in.json> <out.json>``), with its behaviour
chosen through ``FAKE_BLENDER_MODE`` so a test can script a crash, a GPU report, a short render or a hang.
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import textwrap
from pathlib import Path

from src.video.motion_conversion.blender import BlenderInstall
from src.video.motion_conversion.fbx_scan import BINARY_MAGIC
from src.video.motion_conversion.rig_compat import CORE_HUMANOID_BONES

MIXAMO_BONES = tuple(f"mixamorig:{name}" for name in CORE_HUMANOID_BONES) + (
    "mixamorig:LeftHandIndex1",
    "mixamorig:RightHandThumb1",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prop(value: object) -> bytes:
    if isinstance(value, int):
        return b"L" + struct.pack("<q", value)
    text = str(value).encode("utf-8")
    return b"S" + struct.pack("<I", len(text)) + text


def _node(name: str, props: list[object], children: list[tuple], offset: int) -> bytes:
    prop_bytes = b"".join(_prop(p) for p in props)
    name_bytes = name.encode("ascii")
    header = 25 + len(name_bytes)
    cursor = offset + header + len(prop_bytes)
    body = b""
    for child in children:
        piece = _node(child[0], child[1], child[2], cursor)
        body += piece
        cursor += len(piece)
    if children:
        body += b"\x00" * 25
    end = offset + header + len(prop_bytes) + len(body)
    return (
        struct.pack("<QQQB", end, len(props), len(prop_bytes), len(name_bytes))
        + name_bytes
        + prop_bytes
        + body
    )


def write_fbx(
    path: Path,
    *,
    mesh: bool = True,
    skin: bool = True,
    bones: tuple[str, ...] = MIXAMO_BONES,
    curves: int = 3,
    version: int = 7500,
) -> Path:
    objects: list[tuple] = []
    ident = 1000
    if mesh:
        objects.append(("Geometry", [ident, "body\x00\x01Geometry", "Mesh"], []))
        objects.append(("Model", [ident + 1, "Body\x00\x01Model", "Mesh"], []))
    for index, bone in enumerate(bones):
        objects.append(("Model", [ident + 10 + index, f"{bone}\x00\x01Model", "LimbNode"], []))
    if skin:
        objects.append(("Deformer", [ident + 500, "Skin\x00\x01Deformer", "Skin"], []))
        objects.append(("Deformer", [ident + 501, "Cluster\x00\x01Deformer", "Cluster"], []))
    if curves:
        objects.append(("AnimationStack", [ident + 600, "Take 001\x00\x01AnimStack", ""], []))
        for i in range(curves):
            objects.append(("AnimationCurve", [ident + 700 + i, "\x00\x01AnimCurve", ""], []))
    head = BINARY_MAGIC + struct.pack("<I", version)
    body = _node("Objects", [], objects, len(head)) + b"\x00" * 25
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + body)
    return path


def write_bvh(path: Path, *, valid: bool = True) -> Path:
    text = (
        "HIERARCHY\nROOT Hips\n{\n OFFSET 0 0 0\n CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\n"
        " End Site\n {\n  OFFSET 0 10 0\n }\n}\nMOTION\nFrames: 2\nFrame Time: 0.0333333\n0 0 0 0 0 0\n0 0 0 0 0 0\n"
        if valid
        else "not a bvh\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


FAKE_BLENDER = textwrap.dedent(
    """
    import json, os, struct, sys, time, zlib

    def png(w, h, value, subject=True):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        edge = w // 4
        plain = b"\\x00" + bytes([value]) * (w * 3)
        figure = (b"\\x00" + bytes([value]) * (edge * 3) + bytes([(value + 120) % 256]) * ((w - 2 * edge) * 3)
                  + bytes([value]) * (edge * 3))
        raw = b"".join(figure if subject and h // 4 <= y < 3 * h // 4 else plain for y in range(h))
        return (b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    mode = os.environ.get("FAKE_BLENDER_MODE", "ok")
    args = sys.argv[1:]
    if "--version" in args:
        print(os.environ.get("FAKE_BLENDER_VERSION", "Blender 4.2.3 LTS"))
        sys.exit(0)
    action, in_path, out_path = args[args.index("--") + 1:]
    request = json.load(open(in_path, encoding="utf-8"))
    target = request.get("path") or request.get("plan", {}).get("source", {}).get("path", "")
    log = os.environ.get("FAKE_BLENDER_LOG")
    if log:  # the command words, then the file the call is about
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps([*args, target]) + "\\n")
    fail_on = os.environ.get("FAKE_BLENDER_FAIL_ON")
    if fail_on and fail_on in target:  # only the named file misbehaves; every other file renders normally
        mode = os.environ.get("FAKE_BLENDER_FAIL_MODE", "crash")
    if mode == "hang":
        time.sleep(600)
    if mode == "crash":
        sys.exit(1)
    if mode == "oom":
        sys.stderr.write("Error: Out of memory in CPU render\\n")
        sys.exit(1)
    if mode in ("badrig", "badfile"):
        error = ("RuntimeError: The animation's rest pose differs from the character's (Hips>Spine by 40 degrees)"
                 if mode == "badrig" else "RuntimeError: The file contains no animation action.")
        json.dump({"ok": False, "error": error, "trace": "Traceback ..."}, open(out_path, "w"))
        sys.exit(3)
    if mode == "chatty":  # a renderer's per-frame progress: far more console output than any fixed cap
        for i in range(30000):
            print("Fra:%d Mem:96.59M (Peak 109.52M) | Time:00:00.07 | Remaining:00:00.09 | Sample 16/16" % i)
        sys.stderr.write("Warning: noisy but harmless\\n" * 20000)
        sys.stdout.flush()
    if action == "probe":
        json.dump({"ok": True, "fps": os.environ.get("FAKE_BLENDER_FPS", "24/1"), "frame_first": "1/1",
                   "frame_last": os.environ.get("FAKE_BLENDER_LAST", "121/1"), "bone_names": ["mixamorig:Hips"],
                   "has_mesh": True}, open(out_path, "w"))
        sys.exit(0)
    plan = request["plan"]
    n = plan["timing"]["output_frames"]
    w, h = plan["geometry"]["width"], plan["geometry"]["height"]
    written = n - 1 if mode in ("short", "lie") else n
    os.makedirs(request["frames_dir"], exist_ok=True)
    for i in range(written):
        with open(os.path.join(request["frames_dir"], "frame_%05d.png" % (i + 1)), "wb") as fh:
            fh.write(png(w, h, 5 if mode == "static" else (sum(target.encode()) + i * 7) % 256, mode != "blank"))
    device = "CUDA" if mode == "gpu" else "CPU"
    json.dump({"ok": mode != "partial", "error": "boom" if mode == "partial" else "", "render_engine": "CYCLES",
               "render_device": device, "frames_written": n if mode == "lie" else written, "bone_names": ["mixamorig:Hips"],
               "mesh_object_count": 1, "facing_estimated": True}, open(out_path, "w"))
    sys.exit(3 if mode == "partial" else 0)
    """
)


def fake_install(directory: Path, version: str = "Blender 4.2.3 LTS") -> BlenderInstall:
    script = directory / "fake_blender.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE_BLENDER, encoding="utf-8")
    return BlenderInstall(
        executable=Path(sys.executable),
        version=(4, 2, 3),
        version_text=version,
        argv_prefix=(sys.executable, str(script)),
    )


def fake_environ(**extra: str) -> dict[str, str]:
    return {**os.environ, **extra}
