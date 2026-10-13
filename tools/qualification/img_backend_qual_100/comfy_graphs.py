"""Qualification-only ComfyUI API-format graphs for the frozen workloads (pure; no I/O except source scanning).

These graphs are not registered in the production workflow catalog and are not an execution contract for StableNew: they
exist so the comparison has an exact, hashable definition of what the Comfy leg would run. ``validate_graph`` is the
fail-closed check the runner performs against the live ``/object_info`` before any generation request.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .spec import (
    K1,
    K2,
    K3,
    S1,
    S2,
    S3,
    SAMPLER_MAP,
    SCHEDULER_MAP,
    Workload,
    digest,
)

Graph = dict[str, dict[str, Any]]


def _link(node: str, index: int = 0) -> list[Any]:
    return [node, index]


def _sdxl_graph(
    settings: Mapping[str, Any],
    *,
    lora: bool = False,
    openpose: bool = False,
    prefix: str,
    filenames: Mapping[str, str],
) -> Graph:
    def name(logical: str) -> str:
        return filenames.get(logical, logical)

    graph: Graph = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": name(settings["checkpoint"])},
        },
    }
    model, clip = _link("1", 0), _link("1", 1)
    if lora:
        graph["2"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": model,
                "clip": clip,
                "lora_name": name(settings["lora_name"]),
                "strength_model": float(settings["lora_strength"]),
                "strength_clip": float(settings["lora_strength"]),
            },
        }
        model, clip = _link("2", 0), _link("2", 1)
    graph["3"] = {
        "class_type": "CLIPSetLastLayer",
        "inputs": {"clip": clip, "stop_at_clip_layer": -int(settings["clip_skip"])},
    }
    graph["4"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": settings["prompt"], "clip": _link("3")},
    }
    graph["5"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": settings["negative_prompt"], "clip": _link("3")},
    }
    positive, negative = _link("4"), _link("5")
    if openpose:
        graph["6"] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": name(settings["controlnet_model"])},
        }
        graph["7"] = {"class_type": "LoadImage", "inputs": {"image": settings["pose_image_name"]}}
        graph["8"] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": positive,
                "negative": negative,
                "control_net": _link("6"),
                "image": _link("7"),
                "strength": float(settings["controlnet_weight"]),
                "start_percent": float(settings["controlnet_guidance_start"]),
                "end_percent": float(settings["controlnet_guidance_end"]),
            },
        }
        positive, negative = _link("8", 0), _link("8", 1)
    graph["9"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": int(settings["width"]),
            "height": int(settings["height"]),
            "batch_size": 1,
        },
    }
    graph["10"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model,
            "seed": int(settings["seed"]),
            "steps": int(settings["steps"]),
            "cfg": float(settings["cfg_scale"]),
            "sampler_name": SAMPLER_MAP[settings["sampler_name"]],
            "scheduler": SCHEDULER_MAP[settings["scheduler"]],
            "positive": positive,
            "negative": negative,
            "latent_image": _link("9"),
            "denoise": 1.0,
        },
    }
    graph["11"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _link("10"), "vae": _link("1", 2)},
    }
    graph["12"] = {
        "class_type": "SaveImage",
        "inputs": {"images": _link("11"), "filename_prefix": prefix},
    }
    return graph


def _klein_graph(settings: Mapping[str, Any], *, prefix: str) -> Graph:
    assets = settings["assets"]
    edit = "reference" in settings
    graph: Graph = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": assets["transformer"]["filename"], "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": assets["text_encoder"]["filename"], "type": "flux2"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": assets["vae"]["filename"]}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": settings["prompt"], "clip": _link("2")},
        },
    }
    conditioning = _link("4")
    if edit:
        graph["5"] = {"class_type": "LoadImage", "inputs": {"image": "qual_reference.png"}}
        graph["6"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": _link("5"), "vae": _link("3")},
        }
        graph["7"] = {
            "class_type": "ReferenceLatent",
            "inputs": {"conditioning": conditioning, "latent": _link("6")},
        }
        conditioning = _link("7")
    graph["8"] = {
        "class_type": "BasicGuider",
        "inputs": {"model": _link("1"), "conditioning": conditioning},
    }
    graph["9"] = {
        "class_type": "KSamplerSelect",
        "inputs": {"sampler_name": SAMPLER_MAP[settings["sampler_name"]]},
    }
    graph["10"] = {
        "class_type": "BasicScheduler",
        "inputs": {
            "model": _link("1"),
            "scheduler": SCHEDULER_MAP[settings["scheduler"]],
            "steps": int(settings["steps"]),
            "denoise": 1.0,
        },
    }
    graph["11"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(settings["seed"])}}
    graph["12"] = {
        "class_type": "EmptyFlux2LatentImage",
        "inputs": {
            "width": int(settings["width"]),
            "height": int(settings["height"]),
            "batch_size": 1,
        },
    }
    graph["13"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": _link("11"),
            "guider": _link("8"),
            "sampler": _link("9"),
            "sigmas": _link("10"),
            "latent_image": _link("12"),
        },
    }
    graph["14"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _link("13", 0), "vae": _link("3")},
    }
    graph["15"] = {
        "class_type": "SaveImage",
        "inputs": {"images": _link("14"), "filename_prefix": prefix},
    }
    return graph


def build_graph(
    workload: Workload, *, prefix: str | None = None, filenames: Mapping[str, str] | None = None
) -> Graph:
    """The exact Comfy graph for one workload (deterministic for a frozen workload).

    ``filenames`` maps a logical model name (Forge's extension-less name) to the file name the Comfy runtime lists; a
    name without an entry is emitted unchanged and will fail ``validate_graph`` rather than be guessed.
    """

    name = prefix or f"qual100_{workload.workload_id.lower()}"
    wid = workload.workload_id
    if wid in (S1, S3, S2):
        return _sdxl_graph(
            workload.settings,
            lora=wid == S3,
            openpose=wid == S2,
            prefix=name,
            filenames=filenames or {},
        )
    if wid in (K1, K2, K3):
        return _klein_graph(workload.settings, prefix=name)
    raise ValueError(f"no Comfy graph is defined for {wid!r}")


def graph_digest(graph: Graph) -> str:
    return digest(graph)


def required_models(graph: Graph) -> dict[str, list[str]]:
    """Model-like file names the graph loads, grouped by Comfy model folder (for the read-only inventory)."""

    keys = {
        "CheckpointLoaderSimple": ("ckpt_name", "checkpoints"),
        "LoraLoader": ("lora_name", "loras"),
        "ControlNetLoader": ("control_net_name", "controlnet"),
        "UNETLoader": ("unet_name", "diffusion_models"),
        "CLIPLoader": ("clip_name", "text_encoders"),
        "VAELoader": ("vae_name", "vae"),
        "LoadImage": ("image", "input"),
    }
    found: dict[str, list[str]] = {}
    for node in graph.values():
        spec = keys.get(node["class_type"])
        if spec:
            found.setdefault(spec[1], []).append(str(node["inputs"][spec[0]]))
    return found


# ---- validation ------------------------------------------------------------------------------------------------------
def _is_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and type(value[1]) is int
    )


def validate_graph(graph: Graph, object_info: Mapping[str, Any]) -> list[str]:
    """Problems found by checking ``graph`` against a ``/object_info`` document (empty = acceptable).

    Checks: every class exists; every required input is present; every supplied input is declared; an enumerated input's
    value is one of its options; every link names an existing node. Nothing is guessed or repaired.
    """

    problems: list[str] = []
    for node_id, node in graph.items():
        cls = node.get("class_type")
        info = object_info.get(cls) if isinstance(cls, str) else None
        if not isinstance(info, Mapping):
            problems.append(f"node {node_id}: class {cls!r} is not served by this runtime")
            continue
        declared = info.get("input") or {}
        required = declared.get("required") or {}
        optional = declared.get("optional") or {}
        supplied = node.get("inputs") or {}
        for name in required:
            if name not in supplied:
                problems.append(f"node {node_id} ({cls}): required input {name!r} is missing")
        for name, value in supplied.items():
            spec = required.get(name, optional.get(name))
            if spec is None:
                problems.append(f"node {node_id} ({cls}): input {name!r} is not declared")
                continue
            if _is_link(value):
                if value[0] not in graph:
                    problems.append(
                        f"node {node_id} ({cls}): input {name!r} links to missing node {value[0]!r}"
                    )
                else:
                    upstream = object_info.get(str(graph[value[0]].get("class_type")), {})
                    outputs = upstream.get("output", ())
                    if value[1] < 0 or value[1] >= len(outputs):
                        problems.append(
                            f"node {node_id} ({cls}): input {name!r} uses an invalid output index"
                        )
                    elif (
                        spec
                        and isinstance(spec[0], str)
                        and spec[0] not in ("*", outputs[value[1]])
                    ):
                        problems.append(
                            f"node {node_id} ({cls}): input {name!r} has an incompatible linked type"
                        )
                continue
            options = spec[0] if isinstance(spec, list | tuple) and spec else None
            if isinstance(options, list) and value not in options:
                problems.append(
                    f"node {node_id} ({cls}): {name}={value!r} is not an available option"
                )
            elif isinstance(options, str):
                literals: dict[str, type | tuple[type, ...]] = {
                    "INT": int,
                    "FLOAT": (int, float),
                    "STRING": str,
                    "BOOLEAN": bool,
                }
                expected = literals.get(options)
                if expected is None:
                    problems.append(f"node {node_id} ({cls}): input {name!r} requires a typed link")
                elif not isinstance(value, expected) or (
                    options in ("INT", "FLOAT") and isinstance(value, bool)
                ):
                    problems.append(
                        f"node {node_id} ({cls}): input {name!r} has an invalid literal type"
                    )
                elif options in ("INT", "FLOAT") and len(spec) > 1 and isinstance(spec[1], Mapping):
                    limits = spec[1]
                    if value < limits.get("min", float("-inf")) or value > limits.get(
                        "max", float("inf")
                    ):
                        problems.append(
                            f"node {node_id} ({cls}): input {name!r} is outside the declared range"
                        )
    return problems


_CLASS = re.compile(r"^class\s+(\w+)\s*[(:]", re.MULTILINE)
_NODE_ID = re.compile(r"node_id\s*=\s*[\"'](\w+)[\"']")


def scan_source_node_ids(source_root: Path) -> set[str]:
    """Node class ids the Comfy source defines (read-only text scan; a superset of what is registered)."""

    root = Path(source_root)
    found: set[str] = set()
    files = [root / "nodes.py", *sorted((root / "comfy_extras").glob("*.py"))]
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(_CLASS.findall(text))
        found.update(_NODE_ID.findall(text))
    return found


def validate_graph_classes(graph: Graph, node_ids: set[str]) -> list[str]:
    return [
        f"node {node_id}: class {node['class_type']!r} not defined in the Comfy source"
        for node_id, node in graph.items()
        if node["class_type"] not in node_ids
    ]
