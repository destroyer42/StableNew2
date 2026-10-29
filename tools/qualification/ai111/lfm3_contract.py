"""Frozen AI-QUAL-115 model/runtime qualification contract for LiquidAI/LFM3-1.7B. Pure: no network, model or process.

This is a separately versioned contract. It does not touch the Qwen corpus, plan or digests (``plan.py``, ``final_plan.py``),
the committed registry or the runtime manifest, and it authorizes nothing: every approval is a separate owner act that must
name this contract's digest and the exact artifacts it covers. LFM3 candidates live here, never in ``config/``, so no
unqualified model is added to production.

Every value below was read from public metadata on 2026-10-29 (Hugging Face repository API at the pinned commit SHAs, the
GitHub release API and tag objects, the model card, ``generation_config.json``, the LICENSE text, and the llama.cpp
``common/arg.cpp`` source at each tag). Nothing was downloaded beyond those small text files and nothing was executed.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from src.ai_assist.argv import (
    ALLOWED_FLAGS,
    FORBIDDEN_FLAGS,
    RunLimits,
    Sampling,
    assert_argv_allowed,
)
from src.ai_assist.manifests import ModelRegistry, load_model_registry
from tools.qualification.ai111 import plan as plan_module
from tools.qualification.ai111.corpus import corpus_digest, stage_a_subset
from tools.qualification.ai111.d12a import flag_in_text
from tools.qualification.ai111.final_plan import evaluate_final_gates, final_corpus, final_plan
from tools.qualification.ai111.plan import digest, frozen_plan

SCHEMA = "stablenew.ai115.lfm3.v1"
CONTRACT_ID = "AI-QUAL-115"
MODEL_PREFIX = "lfm3-"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")

#: Qwen evidence that this contract must leave untouched. ``validate_contract`` recomputes all three from the code.
QWEN_FROZEN: dict[str, str] = {
    "screening_plan_sha256": "17814e4050049323dc4f5206417bac67f94307d7791ce580af2948e2310df338",
    "final_plan_sha256": "3017c427c7f5c15bc900e6e5d1ef2d3e86b45c7bbb30d3a9d0a0d2f58b1eccbf",
    "final_corpus_sha256": "a89297beb3ae86246eb25214738d91ba3f24dc1e2cd8a4f7547ae49c68a774d5",
}

#: The digest of the frozen contract. ``validate_contract`` refuses any document that differs, so editing a value here
#: needs a deliberate second edit of this constant (and fresh owner approvals, which quote it).
FROZEN_CONTRACT_SHA256 = "41e65d6769cd4090dc0e8f978014c97e82fd23c3351261f3ff276efd8a129f60"

PUBLISHER_REPO = "LiquidAI/LFM3-1.7B"
PUBLISHER_REVISION = "ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7"
PACKAGER_REPO = "LiquidAI/LFM3-1.7B-GGUF"
PACKAGER_REVISION = "bad5729bba61d076fff20d2548e62526665af215"

LICENSE: dict[str, Any] = {
    "spdx": "LicenseRef-LFM-Open-License-1.0",  # not an SPDX-listed licence; a custom reference by SPDX syntax
    "name": "LFM Open License v1.0",
    "text_path": "LICENSE",
    "text_bytes": 10574,
    "text_sha256": "4d28ca14dedc0b3d0fcc2b3339f0e79931faa33874f3d24f522183a8fc70068c",
    "identical_in": [PUBLISHER_REPO, PACKAGER_REPO],
    "commercial_use_threshold_usd_annual_revenue": 10_000_000,
    "summary": (
        "Free use, modification and redistribution, but Commercial Use of the Work by a Legal Entity above the Threshold "
        "is not licensed (Section 5). The text is internally inconsistent about the boundary: Section 1 defines the "
        "Threshold as revenue of USD 10,000,000 'or more' while Section 5(b) says 'exceeds the Threshold'; the stricter "
        "reading (at or above) is assumed. A Qualified Non-Profit is exempt for non-commercial or research use."
    ),
    "clauses_that_bind_the_owner": [
        "Legal Entity aggregates the acting entity with every entity that controls, is controlled by or is under common control with it (Section 1)",
        "Commercial Use is any use for direct or indirect commercial advantage or monetary compensation (Section 1)",
        "redistribution must carry the licence and prominent notices of modification (Section 4(a), 4(b))",
        "patent licences terminate if You sue over the Work (Section 3)",
        "the licence terminates automatically on non-compliance; use must cease and every copy be deleted (Section 11)",
    ],
    "redistribution_by_stablenew": "none: weights are operator-imported from local files and are never shipped or committed",
    "owner_acknowledgement_required": True,
    "owner_acknowledged": False,
    "owner_threshold_position": "",  # the owner's own statement about the Threshold; empty until S1
}

#: Registry-shaped candidate entries (``load_model_registry`` accepts this shape). Sizes and hashes are the Hugging Face LFS
#: object ids (SHA-256) and sizes at the packager commit; they are NOT yet verified against local bytes.
_CANDIDATE_FILES: dict[str, dict[str, Any]] = {
    "Q4_K_M": {
        "filename": "LFM3-1.7B-Q4_K_M.gguf",
        "bytes": 1099627808,
        "sha256": "3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4",
    },
    "Q8_0": {
        "filename": "LFM3-1.7B-Q8_0.gguf",
        "bytes": 1846238496,
        "sha256": "8f6b24182258205e9e01e21f1f24a1f208c1e8115578825d202ce39976af20b6",
    },
}


def _candidate(quantization: str) -> dict[str, Any]:
    file = _CANDIDATE_FILES[quantization]
    return {
        "model_id": f"lfm3-1.7b-{quantization.lower()}-liquidai",
        "display_name": f"LFM3-1.7B {quantization} (Liquid AI GGUF)",
        "license_spdx": LICENSE["spdx"],
        "architecture": "lfm3",
        "quantization": quantization,
        "filename": file["filename"],
        "bytes": file["bytes"],
        "sha256": file["sha256"],
        "max_context": 8192,
        "capabilities": ["prompt_rewrite", "target_fit_advice", "workflow_choice"],
        "qualified": False,
        "provenance": {
            "publisher_repo": PUBLISHER_REPO,
            "publisher_revision": PUBLISHER_REVISION,
            "packager_repo": PACKAGER_REPO,
            "packager_revision": PACKAGER_REVISION,
            "converter": "Liquid AI GGUF export (converter build is not stated in the repository metadata)",
            "source_url": (
                f"https://huggingface.co/{PACKAGER_REPO}/resolve/{PACKAGER_REVISION}/{file['filename']}"
            ),
        },
    }


CANDIDATES: tuple[dict[str, Any], ...] = (_candidate("Q4_K_M"), _candidate("Q8_0"))

#: Every loadable member of the b11960 CPU archive and its SHA-256, hashed in memory from the S0 download (nothing was
#: extracted or executed) with the rule of ``physical.derive_runtime_build`` (suffix in the active set). Measured
#: 2026-10-29; the evidence record is outside the repository.
B11960_FILES: dict[str, str] = {
    "ggml-base.dll": "200cd9b6f0a7934c2e1c85e55289d5498332713321b03e83eb2ae3da5eeb6137",
    "ggml-cpu-alderlake.dll": "8ae4c14de9eeb5528e42cff69ed8485e6cd0e3f8601837add873a9d12199ca95",
    "ggml-cpu-cannonlake.dll": "779a9d0ede6215fba8a00fb680c1295dd62836f9d8a124437d48f9c086fc1f07",
    "ggml-cpu-cascadelake.dll": "71f6275d8aa7df86545975e02510e10280abfcc274ae419dee898746a5b2ce1b",
    "ggml-cpu-cooperlake.dll": "c0b3f9445cbd4490504c13d06e89b25bdbe9dea73784fc62c0c10ae7069de6cb",
    "ggml-cpu-haswell.dll": "0bc8209ebe520b43d8549db7d45ca87382df88c3a8b238f3dda42d96e2af178e",
    "ggml-cpu-icelake.dll": "81f86f655c82dfe330f9ee269b97a2b21352e5e876bd385d48bc61d9a6ca230b",
    "ggml-cpu-ivybridge.dll": "52f262a610ac189d0375472c66c46b7b366d618916ed67a2b119e69023c3f943",
    "ggml-cpu-piledriver.dll": "340c9dc4c5618fa4f89e6311c31f2f472d3277a87858c79b3c44890b0e92d1e7",
    "ggml-cpu-sandybridge.dll": "6251d2dc50745bad1d0f16ea95a4484ef5d8c7cb49b5a4a33af85d199c08be61",
    "ggml-cpu-sapphirerapids.dll": "cdfdc20cb7f953f87e61ab90e234c864df4e2c2615f5651bd83a4cf27fdc4e3d",
    "ggml-cpu-skylakex.dll": "da5c7c86df8409c08fb748ed5596eba65285ead7747581daa124a7fff2f65704",
    "ggml-cpu-sse42.dll": "00efeb321bb728616cde5719bab06ea575679f7ca4967367faa70fd5ca1c8ba6",
    "ggml-cpu-x64.dll": "af7233344eec5587d531b4e875ec5bf2b1aa62c2be57b657f69cca503f0db918",
    "ggml-cpu-zen4.dll": "4ebbee0eb0c5a4e9e3c3b437d7a2876ede8f1d3e00526dad33db50f39f46e831",
    "ggml-rpc-server.exe": "8dbeb59b8772d101443f11d1fbe230fd59e98b2d4c1e6eb52d8c0e96e2505eef",
    "ggml-rpc.dll": "c28c2da0de23d39a7aca2dbccf20215087bbab2bd26caea38dc782698f6dc070",
    "ggml.dll": "d2e63157b90c0fd15f010fb2952d032d9f3296b8406b78ff0950211cc144705b",
    "libomp.dll": "a12116ba72d1d6820407cf30be23da04ce79d6bb8a71a5ee71759c5a1faa6f1c",
    "llama-batched-bench-impl.dll": "f826a0ec3f4ea79d19c4c16594bd5e0e1e7941d845b65b6580be926548fff389",
    "llama-batched-bench.exe": "a2b698b5f78e036324b799036fa9f0bf8cead4c2714f4dbe731edf984b9c569d",
    "llama-bench-impl.dll": "a2ce853eaae3c165da85643d6cb92c3bb043f1aab4ac3c3da60bacab3871752e",
    "llama-bench.exe": "b815771c315315b0dd179d5057262112035683308d0cf4eebcf3bf418de39e6c",
    "llama-cli-impl.dll": "2e4aa4b28dffe02fdc1022621e1ce1955bed33f4b2de96732d01992fbc5ae42f",
    "llama-cli.exe": "02c8fcdbf3e89c0c36757ee0cffb091844181a43d15995699bb6f3400f932de0",
    "llama-common.dll": "34370fd48c31112b2ebe4e7bb234747c1a9b39325a29e61302659c525a6049d9",
    "llama-completion-impl.dll": "db9ea9071f4fa4954a05dd91ebb4c70d6294ff359437a2e2fe639c0b17374601",
    "llama-completion.exe": "2b4759ec5f0343d7421cae98fadd6d2de1c9bdae64cb128da52628606ab35090",
    "llama-connect.exe": "9f2bdd778f96971995a80add8d6b2478c156f799933337a19dbf80cdaad21b1d",
    "llama-fit-params-impl.dll": "afaa9591c4112bcd6cc419a323c6d7aed5ec2134e0a2fcf5abf0915beaead2a9",
    "llama-fit-params.exe": "e6682185f02e0bbf00121cc33081fdacdb8db2f79307585de33de21fca39a5de",
    "llama-gemma3-cli.exe": "15c385e5b02617acf9b776d2f376897037e03fc8f94af1b67c8f59fce4e30773",
    "llama-gguf-split.exe": "bc1e7236104fb7afc8bd2594c3dab583b7f251e81eed6ef2fed3b094435b7ad1",
    "llama-imatrix.exe": "c61923126281f1abf6f505123761ea344cdedbaff09cac2c15e8250e7a27e476",
    "llama-llava-cli.exe": "15c385e5b02617acf9b776d2f376897037e03fc8f94af1b67c8f59fce4e30773",
    "llama-minicpmv-cli.exe": "15c385e5b02617acf9b776d2f376897037e03fc8f94af1b67c8f59fce4e30773",
    "llama-mtmd-cli.exe": "5073109b15d7d19fd3cc4c23bdbdc2f3dfdae39a6410d80ea6e7b6929eb30b3a",
    "llama-mtmd-debug.exe": "ee9e0025689fb28a3433e019f98cd57d5eb4f12f97c21795965945cf0a75808d",
    "llama-perplexity-impl.dll": "c74f4c51d927e626528dc14c1a82e488e408478d2cfe506cb55848aaf863d570",
    "llama-perplexity.exe": "a5392a06bb9163caa54b6ccae3f17c6868c6279d2d15a2e8114533aeb159a9d8",
    "llama-quantize-impl.dll": "42a1ac2b1b2d4db4d4cfa389b64e57dc08e3f7f7f0b2bbadf65196696e2b0e9f",
    "llama-quantize.exe": "3c045bd055736deba6713cd577552917e556e90f4de8757beb42396891cb91d0",
    "llama-qwen2vl-cli.exe": "f440829cbea406f0911739bc8c506026d21e7903208ec953103bcda06b4555a0",
    "llama-results.exe": "7b01c2871c209f8e610207bcc6992d551d843603fbc2e78e9117fd4fafc5f23f",
    "llama-server-impl.dll": "0b329dcfdece6a43f34d0554dec5ca0cc2efe6ee23d5aabd8141c51487668564",
    "llama-server.exe": "81f65c6681d66099e5d48757aa2c050ba958dc43816e584f0bb4181eb7c910d8",
    "llama-tokenize.exe": "9b4ab318e9842c08f0a349b7da18108090ff7ee53733b8524df3be0894ff6d90",
    "llama-tts.exe": "eb76a870d616bfd36a21870efabcb93e34d399ab444d2e4e374e881c9856bf68",
    "llama.dll": "af13ed8cb1454a80689dbd390310995b6c4b23333e096152453fe6d0fef17356",
    "llama.exe": "e07130143528e649d08bcbbe191ff630e5f12317b9ea13efd4b95e5c32b627f1",
    "mtmd.dll": "e82d563ae9dad225a3d15d0f189e046909713e26759ae9a046f89430bc845bd3",
}
B11960_MEMBERS: dict[str, str] = {
    "llama-cli.exe": B11960_FILES["llama-cli.exe"],
    "llama-completion.exe": B11960_FILES["llama-completion.exe"],
}

#: llama.cpp CPU x64 Windows builds. ``asset_sha256`` is the GitHub release asset ``digest`` field (computed by GitHub at
#: upload; it is not a signature or attestation). ``files`` maps every loadable archive member to its SHA-256 and ``members``
#: the launchable subset; both are measured for b11960 only, b11938 was never downloaded.
RUNTIME_CANDIDATES: dict[str, dict[str, Any]] = {
    "b11960": {
        "repository": "https://github.com/ggml-org/llama.cpp",
        "tag": "b11960",
        "commit": "8642541b255bfb5dc39cd351a178be09013a55d6",
        "published_utc": "2026-10-28T12:45:39Z",
        "asset": "llama-b11960-bin-win-cpu-x64.zip",
        "bytes": 24407745,
        "sha256": "73f962f82850d244db47eaacb9d913637027b82399124324298576d58c5f4287",
        "license": "MIT",
        "compute": "cpu",
        "source_url": "https://github.com/ggml-org/llama.cpp/releases/download/b11960/llama-b11960-bin-win-cpu-x64.zip",
        "selected": True,
        "members": B11960_MEMBERS,
        "files": B11960_FILES,
        "lfm3_text_support": "yes: the LiquidAI model card names b11960 (v0.8.0) as the minimum for LFM3-1.7B-GGUF",
        "reason": (
            "The publisher's own stated minimum. It also carries the later LFM3-family follow-ups through b11960. "
            "Pre-releases are the only kind this project publishes (every tag is marked prerelease)."
        ),
    },
    "b11938": {
        "repository": "https://github.com/ggml-org/llama.cpp",
        "tag": "b11938",
        "commit": "19cce6919992fdffd92e0ac152caaf1e2b8f254e",
        "published_utc": "2026-10-27T23:57:45Z",
        "asset": "llama-b11938-bin-win-cpu-x64.zip",
        "bytes": 24260998,
        "sha256": "9e2fc62604446d86809ca09094d3c7a7329b723bda636e4bbd23c3ce62cb77dc",
        "license": "MIT",
        "compute": "cpu",
        "source_url": "https://github.com/ggml-org/llama.cpp/releases/download/b11938/llama-b11938-bin-win-cpu-x64.zip",
        "selected": False,
        "members": {},  # never downloaded, so unmeasured
        "files": {},
        "lfm3_text_support": (
            "architecture present: its tag commit is 'model : add LiquidAI/LFM3-1.7B and LiquidAI/LFM3-VL-2B (#31252)', "
            "but it is below the publisher's stated minimum and no one has loaded the shipped GGUFs on it"
        ),
        "reason": (
            "Evaluated and not selected: the earliest build that contains the LFM3 text architecture, older than the "
            "publisher-documented floor. Kept only as a fallback that would need its own owner decision."
        ),
    },
}
SELECTED_RUNTIME = "b11960"
MINIMUM_RUNTIME_TAG = "b11960"
LATER_BUILD_RULE = (
    "b11960 or any later llama.cpp build is acceptable in principle, but only an exact, measured tag is ever run: a later "
    "build needs its own pinned candidate (archive and per-file hashes) in a new frozen contract version and fresh approvals"
)
#: Two contracts, kept apart: the Qwen evidence is never re-pinned or edited by the LFM3 contract.
SEPARATION: dict[str, str] = {
    "qwen": (
        "Frozen and unchanged: the screening plan, the final plan, the 460-case corpus and their digests (qwen_preserved), "
        "pinned to llama.cpp b11840 and the Qwen sampling. This contract only reads them."
    ),
    "lfm3": (
        "This document: LFM3 candidates and the runtime floor b11960 (or a later pinned build). Every arm it defines, the "
        "matched Qwen comparators included, runs on the LFM3 runtime so that runtime is not a confounder; that does not "
        "alter the Qwen contract."
    ),
}

#: The only comparator pins (read from the committed registry at call time, never edited here).
#: The archive members the harness may ever launch (names only; their hashes are recorded after S2).
_ACTIVE_SUFFIXES = frozenset(
    {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py", ".sh", ".so", ".dylib"}
)
LAUNCHABLE_NAMES: frozenset[str] = frozenset({"llama-completion.exe", "llama-cli.exe"})
COMPARATORS: dict[str, str] = {
    "lfm3-1.7b-q4_k_m-liquidai": "qwen3.5-4b-q4_k_m-unsloth",
    "lfm3-1.7b-q8_0-liquidai": "qwen3.5-4b-q8_0-unsloth",
}

#: Vendor sampling (model card + ``generation_config.json``: temperature 0.1, top_k 50, repetition_penalty 1.1). ``top_p`` and
#: ``min_p`` are pinned explicitly because llama.cpp's own defaults (0.95 and 0.05) would otherwise apply silently while the
#: vendor's transformers settings leave both neutral.
SAMPLING_PROFILES: dict[str, dict[str, Any]] = {
    "lfm3_vendor": {
        "temperature": 0.1,
        "top_k": 50,
        "top_p": 1.0,
        "min_p": 0.0,
        "repeat_penalty": 1.1,
        "presence_penalty": 0.0,
        "seed": 321,
        "basis": f"{PUBLISHER_REPO}@{PUBLISHER_REVISION} generation_config.json and model card",
    },
    "lfm3_no_repeat": {
        "temperature": 0.1,
        "top_k": 50,
        "top_p": 1.0,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
        "presence_penalty": 0.0,
        "seed": 321,
        "basis": "pre-registered Stage A sensitivity arm: a repetition penalty can discourage verbatim token copying",
    },
}
QWEN_SAMPLING_PROFILE = "qwen_frozen"

#: Flags the LFM3 argv may use: the production vocabulary plus the two sampling flags that vocabulary lacks. Both exist in
#: ``common/arg.cpp`` at b11938 and b11960 (static source evidence only; D12a must still show them in the binary's help).
EXTRA_FLAGS: frozenset[str] = frozenset({"--min-p", "--repeat-penalty"})
LFM3_ALLOWED_FLAGS: frozenset[str] = ALLOWED_FLAGS | EXTRA_FLAGS

_PROFILE_FIELDS = (
    "temperature",
    "top_k",
    "top_p",
    "min_p",
    "repeat_penalty",
    "presence_penalty",
    "seed",
)

STRUCTURED_OUTPUT: dict[str, Any] = {
    "mode": "json_schema_grammar",
    "schema_flag": "--json-schema-file",
    "frame": "ai_assist.frame/1 unchanged (identical prompt bytes for LFM3 and the matched Qwen arm)",
    "chat_template": "not applied: raw frame through -f with --no-conversation, as for the frozen Qwen arms",
    "reasoning_flag": "--reasoning off is passed but is inert for a raw frame; the grammar is what excludes thinking text",
    "stdout_rule": (
        "validate_output accepts exactly one JSON object; other text, a <think> block included, is MALFORMED (not_json) "
        "and never repaired, except that text opening like a refusal is classed REFUSED_BY_MODEL by the existing rule"
    ),
    "ungrammared_probe": "not part of this contract: the schema-valid rate without the grammar is not measured here",
    "unknown": [
        "whether a template-less raw frame suits a chat-tuned model: both LFM3 and the matched Qwen arm receive it, so the "
        "comparison shows relative robustness to it and cannot isolate the template effect",
        "whether the grammar constrains LFM3 as it does Qwen: measured as the schema-valid rate",
        "the vendor sampling values are chat recommendations applied to a raw frame; llama.cpp defaults outside the closed "
        "vocabulary (for example the repetition window --repeat-last-n) are not pinned",
    ],
}

#: Same bounds as the frozen plan so the matched comparison has one resource envelope.
LIMITS: dict[str, Any] = asdict(RunLimits())

STAGE_A_CASES = 30
STAGE_A_SEED = 11502

MONITORING: dict[str, Any] = {
    "read_roots": ["<evidence>/ai-root", "<SystemRoot>"],
    "write_roots": ["<evidence>/ai-root/work"],
    "extra_read_roots": "none expected; any addition must be named in the owner approval and is recorded in the manifest",
    "capture": {
        "analyzer_version": "3",
        "per_arm_capture": True,
        "max_mb": 1024,
        "canary_proof": "a different capture, same host, same tool hashes, under 24 h old, from a protected interpreter",
    },
    "egress": {
        "observed_connections_allowed": 0,
        "includes_loopback": True,
        "preventive_barrier": "operator-attested outbound firewall restriction (never created or verified by StableNew)",
        "child_environment": "scrubbed: no proxy variables, HF_HUB_OFFLINE=1, LLAMA_ARG_OFFLINE=1, NO_PROXY=*",
    },
    "teardown": {
        "after_every_request": "process record complete and active_after_teardown == 0 (real time, from the job object)",
        "session_end": "no llama-*.exe survivor, checked by the harness; trace sessions are stopped and proved gone by the operator",
        "between_arms": "previous capture STOPPED and VERIFIED and 'logman query -ets' lists no StableNewCap session before the next capture starts (operator-checked; the standard-user harness can neither stop nor prove an elevated session)",
        "any_failure": "abort the arm and the session",
    },
    "gpu": {
        "ngl": 0,
        "environment": "CUDA_VISIBLE_DEVICES=-1",
        "runtime_members": "no ggml-cuda, ggml-vulkan, ggml-hip, ggml-sycl or ggml-opencl member may be present",
        "rpc_backend": (
            "the b11960 archive holds ggml-rpc.dll and ggml-rpc-server.exe, which the backend scan may load from the "
            "runtime directory: --rpc stays forbidden, the child environment is scrubbed, ggml-rpc-server.exe is never "
            "launched, and zero connections (loopback included) must be shown by D12a and every capture"
        ),
        "vram": "no per-process GPU attribution exists in the repository; the only control is the existing nvidia-smi probe (global memory.used growth under 2048 MiB since its first reading, read before each arm; unreadable = stop)",
    },
    "memory": {
        "admission_gib": "model file GiB + 4 (RAM and commit)",
        "abort": "available RAM < 0.25 GiB or commit headroom < 1 GiB for two consecutive samples",
        "tree_private_cap_gib": "1.5 x model file GiB + 2",
        "recorded": [
            "peak_tree_private_gib",
            "peak_tree_working_set_gib",
            "host available/commit minima per arm",
        ],
    },
    "latency": {
        "median_seconds_max": 20.0,
        "recorded": [
            "cold first request",
            "warm median",
            "p95",
            "max",
            "output characters per second",
        ],
        "not_measurable": "prefill/decode tokens per second (no timing flag is in the closed vocabulary)",
    },
}

APPROVAL_STEPS: dict[str, dict[str, Any]] = {
    "S0_download": {
        "grants": "download exactly the three named files into operator staging; no import, extraction or execution",
        "artifacts": ["lfm3-1.7b-q4_k_m-liquidai", "lfm3-1.7b-q8_0-liquidai", "runtime:b11960"],
        "prerequisites": [],
    },
    "S1_license": {
        "grants": "the owner records acceptance of LFM Open License v1.0 and states the Threshold position",
        "artifacts": ["license"],
        "prerequisites": [],
    },
    "S2_d12a_b11960": {
        "grants": "extract the CPU archive to an evidence-only directory and run --version and --help of the named members",
        "artifacts": ["runtime:b11960"],
        "prerequisites": ["S0_download", "S1_license"],
    },
    "S3_stage_a": {
        "grants": "import the verified files into an evidence-local root and run Stage A for the named arms under capture",
        "artifacts": [
            "lfm3-1.7b-q4_k_m-liquidai",
            "lfm3-1.7b-q8_0-liquidai",
            "qwen:qwen3.5-4b-q4_k_m-unsloth",
            "qwen:qwen3.5-4b-q8_0-unsloth",
            "runtime:b11960",
        ],
        "prerequisites": ["S0_download", "S1_license", "S2_d12a_b11960"],
    },
    "S4_stage_b": {
        "grants": "run the full frozen corpus for the owner-chosen leading arms, then the blind preference session; the approval states how each arm is split across captures",
        "artifacts": [
            "lfm3-1.7b-q4_k_m-liquidai",
            "lfm3-1.7b-q8_0-liquidai",
            "qwen:qwen3.5-4b-q4_k_m-unsloth",
            "qwen:qwen3.5-4b-q8_0-unsloth",
            "runtime:b11960",
        ],
        "prerequisites": ["S0_download", "S1_license", "S2_d12a_b11960", "S3_stage_a"],
    },
}
PROMOTION = "registry and manifest promotion (qualified=true) and enabling Suggest are outside this contract"

KNOWN_BLOCKERS: tuple[str, ...] = (
    "harness_pinned_to_b11840_single_runtime_single_sampling",
    "b11960_archive_holds_ggml_rpc_dll_and_rpc_server_exe_so_zero_connections_must_be_shown_by_d12a_and_the_capture",
    "d12a_b11960_not_run",
    "protected_system_python_and_capture_control_copy_absent",
    "live_canary_proof_for_current_tool_hashes_absent",
    "firewall_attestation_absent",
    "owner_approvals_absent",
    "stage_a_report_and_d12a_defaults_pinned_to_the_qwen_screening_plan_and_b11840",
    "derive_runtime_build_without_a_named_member_does_not_pin_the_member_hash",
    "stage_b_arm_exceeds_one_1024mb_capture_and_the_split_and_record_merge_are_undefined",
    "infrastructure_abort_counts_four_of_the_ten_infrastructure_outcome_codes",
)


def _qwen_entry(registry: ModelRegistry, model_id: str) -> dict[str, Any]:
    entry = next((e for e in registry.entries if e.model_id == model_id), None)
    if entry is None:
        raise ValueError(f"comparator is not in the committed registry: {model_id}")
    return {
        "model_id": entry.model_id,
        "bytes": entry.bytes,
        "sha256": entry.sha256,
        "quantization": entry.quantization,
        "publisher_revision": entry.provenance.publisher_revision,
        "packager_revision": entry.provenance.packager_revision,
    }


def _arms(registry: ModelRegistry) -> list[dict[str, Any]]:
    arms: list[dict[str, Any]] = [
        {
            "arm_id": "B1_engine",
            "kind": "baseline",
            "note": "deterministic engine; free; the preference reference for every model arm",
        }
    ]
    for lfm, qwen in COMPARATORS.items():
        arms.append(
            {
                "arm_id": f"{lfm}@lfm3_vendor",
                "kind": "candidate",
                "model_id": lfm,
                "sampling": "lfm3_vendor",
                "runtime": SELECTED_RUNTIME,
                "stages": ["A", "B"],
                "matched_comparator": f"{qwen}@{QWEN_SAMPLING_PROFILE}",
            }
        )
        arms.append(
            {
                "arm_id": f"{qwen}@{QWEN_SAMPLING_PROFILE}",
                "kind": "comparator",
                "model": _qwen_entry(registry, qwen),
                "sampling": QWEN_SAMPLING_PROFILE,
                "runtime": SELECTED_RUNTIME,
                "stages": ["A", "B"],
                "note": "frozen Qwen sampling, re-run on the LFM3 runtime so the runtime is not a confounder",
            }
        )
    arms.append(
        {
            "arm_id": "lfm3-1.7b-q4_k_m-liquidai@lfm3_no_repeat",
            "kind": "sensitivity",
            "model_id": "lfm3-1.7b-q4_k_m-liquidai",
            "sampling": "lfm3_no_repeat",
            "runtime": SELECTED_RUNTIME,
            "stages": ["A"],
            "note": "Stage A only. Stage B uses the vendor profile unless the pre-registered rule below picks this one.",
        }
    )
    return arms


def stage_a_case_ids() -> list[str]:
    return [c.case_id for c in stage_a_subset(final_corpus(), STAGE_A_CASES, STAGE_A_SEED)]


def _stages() -> dict[str, Any]:
    thresholds = frozen_plan()["thresholds"]
    return {
        "A": {
            "purpose": "compatibility, integrity and monitoring smoke; never a qualification",
            "cases_per_arm": STAGE_A_CASES,
            "case_ids_sha256": digest(stage_a_case_ids()),
            "corpus": f"stablenew.ai111.final.v2 subset, seed {STAGE_A_SEED}",
            "admission": [
                "S0-S3 approvals, each quoting this contract's digest and its artifact hashes (Qwen comparators included), and the licence acknowledgement with the owner's Threshold position",
                "D12a for the b11960 members: PASS; launched members' hashes equal the recorded ones",
                "protected capture runtime proven; a live canary PASS from different capture within 24 h",
                "one 1024 MB capture per arm with a start and end canary; analysis v3 PASS (zero lost events)",
                "quiet host; memory preflight per arm; firewall attestation recorded in the evidence-local root",
                "previous capture STOPPED and VERIFIED and no StableNewCap trace session listed before each arm's capture starts",
            ],
            "stop_criteria": {
                "real_time": [
                    "owned child tree not proven gone after a request (the arm and the session stop)",
                    "a request that hits its timeout, output cap or memory cap (the runner kills the whole tree)",
                    "identity changed since the arm preconditions, or a loadable file beyond the pinned set",
                    "three consecutive TIMEOUT, UNAVAILABLE, RESOURCE_INSUFFICIENT or YIELDED_TO_GENERATION outcomes",
                    "host memory abort (checked between requests) or the capture deadline",
                    "global VRAM growth above the nvidia-smi probe limit, or the GPU unreadable (checked before each arm)",
                ],
                "retrospective_invalidation": [
                    "any connection attempt (loopback included), write outside the write root or read outside the read roots: found only in the stopped capture, it invalidates the arm and stops nothing",
                    "capture analysis INCONCLUSIVE or FAIL, or a trace session left running",
                ],
            },
            "recommendation_rule": (
                "stage_a_report.judge_arm applied unchanged: REJECT on a hard gate, security FAIL or a model that never "
                "ran; ADVANCE only when compatibility, integrity and security all PASS and no measured threshold is "
                "missed; otherwise INCONCLUSIVE. Stage A can never yield GO."
            ),
            "sensitivity_rule": (
                "For the Q4_K_M model only: the no-repeat profile replaces the vendor profile for Stage B only if the "
                "vendor arm records strictly more MALFORMED outcomes with reason protected_tokens_changed on the Stage A "
                "slice and the no-repeat arm records zero (the validator turns such a change into MALFORMED, so the "
                "accepted-change count is structurally zero and cannot decide). The Q8_0 arm uses the profile chosen "
                "for Q4_K_M. Otherwise the vendor profile stands. Decided before any run; not tuned afterwards."
            ),
        },
        "B": {
            "purpose": "selection evidence on the frozen 460-case corpus",
            "corpus_sha256": final_plan()["corpus_sha256"],
            "go_requires": [
                "evaluate_final_gates over all 460 cases per arm, including zero hard-gate violations",
                "teardown verified, zero egress, no ownership violation, analysis v3 PASS for every capture",
                "at least 100 decisive blind judgments versus B1_engine with lower 95% bound above 0.5",
                "every record carries this contract's digest, the arm's sampling profile and the runtime asset hash",
            ],
            "capture_split": "undefined: 460 requests at the allowed 20 s median exceed one 1024 MB capture; the S4 approval must state the case blocks per capture, which request is cold, and how records are merged. Until a harness supports it Stage B cannot run (see known_blockers)",
            "no_go": "any hard gate violated or any measured threshold missed on complete evidence",
            "inconclusive": "incomplete cases, missing capture analysis, fewer than 100 decisive judgments, or any abort",
            "head_to_head": (
                "LFM3 versus its matched Qwen comparator is reported with a paired blind preference; LFM3 is described as "
                "preferred only if the lower 95% bound exceeds 0.5 over at least 100 decisive judgments. It is never a "
                "gate for either model."
            ),
            "never": "pooled with Stage A records; a subset; a hermetic or cooperative-journal run",
        },
        "thresholds": dict(thresholds),
    }


def contract(registry_path: Path = plan_module.REGISTRY_PATH) -> dict[str, Any]:
    registry = load_model_registry(registry_path)
    if registry.problems:
        raise ValueError("model registry has problems: " + "; ".join(registry.problems))
    return {
        "schema": SCHEMA,
        "contract_id": CONTRACT_ID,
        "status": "FROZEN_PROPOSAL_UNAPPROVED",
        "execution": "none: this document authorizes no download, import, extraction, inference or promotion",
        "qwen_preserved": dict(QWEN_FROZEN),
        "license": dict(LICENSE),
        "candidates": [json.loads(json.dumps(c)) for c in CANDIDATES],
        "separation": SEPARATION,
        "runtime": {
            "minimum_tag": MINIMUM_RUNTIME_TAG,
            "later_build_rule": LATER_BUILD_RULE,
            "selected": SELECTED_RUNTIME,
            "candidates": json.loads(json.dumps(RUNTIME_CANDIDATES)),
        },
        "arms": _arms(registry),
        "sampling": {
            **json.loads(json.dumps(SAMPLING_PROFILES)),
            QWEN_SAMPLING_PROFILE: asdict(Sampling()),
        },
        "limits": dict(LIMITS),
        "argv": {
            "allowed_flags": sorted(LFM3_ALLOWED_FLAGS),
            "extra_flags_beyond_production": sorted(EXTRA_FLAGS),
            "forbidden_flags": sorted(FORBIDDEN_FLAGS),
            "help_must_list": sorted(LFM3_ALLOWED_FLAGS),
        },
        "structured_output": json.loads(json.dumps(STRUCTURED_OUTPUT)),
        "monitoring": json.loads(json.dumps(MONITORING)),
        "stages": _stages(),
        "approvals": json.loads(json.dumps(APPROVAL_STEPS)),
        "promotion": PROMOTION,
        "known_blockers": list(KNOWN_BLOCKERS),
        "authorization": dict.fromkeys(APPROVAL_STEPS, False),
    }


def contract_digest(document: Mapping[str, Any] | None = None) -> str:
    return digest(contract() if document is None else document)


# -- fail-closed validators --------------------------------------------------------------------------------------------


def candidate_problems(entry: Mapping[str, Any], production: ModelRegistry) -> list[str]:
    """Why a LFM3 candidate entry may not be used. Empty means only that its metadata is internally consistent."""

    problems: list[str] = []
    document = json.dumps({"schema_version": 1, "models": [dict(entry)]})
    parsed = load_model_registry(document)
    if parsed.problems or len(parsed.entries) != 1:
        return [f"registry parser: {p}" for p in parsed.problems] or [
            "registry parser: entry dropped"
        ]
    model = parsed.entries[0]
    if model.qualified:
        problems.append("a candidate may not claim qualified=true")
    if not model.model_id.startswith(MODEL_PREFIX):
        problems.append("candidate id is outside the lfm3- namespace")
    if model.architecture != "lfm3":
        problems.append("architecture is not lfm3")
    provenance = model.provenance
    if (provenance.publisher_repo, provenance.packager_repo) != (PUBLISHER_REPO, PACKAGER_REPO):
        problems.append("publisher/packager repository is not the pinned Liquid AI pair")
    for label, revision in (
        ("publisher_revision", provenance.publisher_revision),
        ("packager_revision", provenance.packager_revision),
    ):
        if not COMMIT.match(revision):
            problems.append(f"{label} is not an immutable 40-hex commit")
    expected_url = f"https://huggingface.co/{PACKAGER_REPO}/resolve/{provenance.packager_revision}/{model.filename}"
    if provenance.source_url != expected_url:
        problems.append("source_url is not the revision-pinned resolve URL of the filename")
    if model.license_spdx != LICENSE["spdx"]:
        problems.append("licence identifier does not name the recorded LFM Open License v1.0")
    pinned = next((f for f in _CANDIDATE_FILES.values() if f["filename"] == model.filename), None)
    if pinned is None:
        problems.append("filename is not one of the two pinned quantizations")
    elif (model.bytes, model.sha256) != (pinned["bytes"], pinned["sha256"]):
        problems.append("size or SHA-256 differs from the pinned LFS values")
    if any(e.sha256 == model.sha256 or e.model_id == model.model_id for e in production.entries):
        problems.append("candidate collides with a production registry entry")
    return problems


def license_problems(record: Mapping[str, Any], *, require_acknowledged: bool) -> list[str]:
    problems: list[str] = []
    for key in (
        "spdx",
        "name",
        "text_sha256",
        "text_bytes",
        "commercial_use_threshold_usd_annual_revenue",
    ):
        if not record.get(key):
            problems.append(f"licence record lacks {key}")
    if (
        record.get("text_sha256") != LICENSE["text_sha256"]
        or record.get("text_bytes") != LICENSE["text_bytes"]
    ):
        problems.append("licence text hash differs from the recorded LICENSE")
    if record.get("owner_acknowledgement_required") is not True:
        problems.append("licence record must require owner acknowledgement")
    for key in ("spdx", "name", "commercial_use_threshold_usd_annual_revenue"):
        if record.get(key) != LICENSE[key]:
            problems.append(f"licence {key} differs from the recorded LICENSE")
    if require_acknowledged:
        if record.get("owner_acknowledged") is not True:
            problems.append("licence not acknowledged by the owner")
        position = record.get("owner_threshold_position")
        if not isinstance(position, str) or not position.strip():
            problems.append("owner has not stated a Threshold position")
    return problems


def runtime_problems(entry: Mapping[str, Any], *, require_members: bool) -> list[str]:
    """Why a runtime entry may not be used: it must equal a pinned candidate, field for field."""

    tag = str(entry.get("tag", ""))
    known = RUNTIME_CANDIDATES.get(tag)
    if known is None:
        return [f"runtime tag is not a pinned candidate: {tag or '(none)'}"]
    problems: list[str] = []
    for key in (
        "repository",
        "commit",
        "asset",
        "bytes",
        "sha256",
        "license",
        "compute",
        "source_url",
    ):
        if entry.get(key) != known[key]:
            problems.append(f"runtime {key} differs from the pinned candidate")
    if entry.get("asset") != f"llama-{tag}-bin-win-cpu-x64.zip" or entry.get("compute") != "cpu":
        problems.append("runtime is not the CPU x64 Windows asset of its own tag")
    if not SHA256.match(str(entry.get("sha256", ""))) or not COMMIT.match(
        str(entry.get("commit", ""))
    ):
        problems.append("asset SHA-256 or tag commit is not a full lowercase digest")
    if not isinstance(entry.get("bytes"), int) or entry["bytes"] <= 0:
        problems.append("asset size is not a positive integer")
    members, files = entry.get("members"), entry.get("files")
    if not isinstance(members, dict) or any(
        name not in LAUNCHABLE_NAMES or not SHA256.match(str(value))
        for name, value in members.items()
    ):
        problems.append("launchable member map is malformed")
        return problems
    if not isinstance(files, dict) or any(
        PurePosixPath(str(name)).suffix.lower() not in _ACTIVE_SUFFIXES
        or not SHA256.match(str(value))
        for name, value in files.items()
    ):
        problems.append("loadable file map is malformed")
        return problems
    if any(files.get(name) != value for name, value in members.items()):
        problems.append("a launchable member is missing from, or differs in, the loadable file map")
    for key, recorded in (("members", members), ("files", files)):
        if known[key] and recorded != known[key]:
            problems.append(f"runtime {key} differ from the measured pinned values")
    if require_members and (not members or not files):
        problems.append("launchable member hashes are not recorded")
    return problems


def lfm3_argv(
    profile: str,
    model_path: Path,
    prompt_file: Path,
    schema_file: Path,
    limits: RunLimits | None = None,
) -> list[str]:
    """Closed argv for one LFM3 completion. The production prefix, then the profile's sampling; no other path exists."""

    if profile not in SAMPLING_PROFILES:
        raise ValueError(f"unknown LFM3 sampling profile: {profile}")
    values = SAMPLING_PROFILES[profile]
    limits = limits or RunLimits()
    argv = [
        "--offline",
        "-ngl",
        "0",
        "--log-disable",
        "--no-display-prompt",
        "--no-conversation",
        "--reasoning",
        "off",
        "--prio",
        "-1",
        "-m",
        str(model_path),
        "-f",
        str(prompt_file),
        "--json-schema-file",
        str(schema_file),
        "-c",
        str(limits.context_tokens),
        "-n",
        str(limits.max_new_tokens),
        "-t",
        str(limits.threads),
        "--temp",
        repr(float(values["temperature"])),
        "--top-k",
        str(int(values["top_k"])),
        "--top-p",
        repr(float(values["top_p"])),
        "--min-p",
        repr(float(values["min_p"])),
        "--repeat-penalty",
        repr(float(values["repeat_penalty"])),
        "--presence-penalty",
        repr(float(values["presence_penalty"])),
        "--seed",
        str(int(values["seed"])),
    ]
    assert_argv_allowed(argv, LFM3_ALLOWED_FLAGS)
    return argv


def help_flag_report(help_text: str, *, truncated: bool) -> dict[str, Any]:
    """Flag spellings the contract needs, against a runtime's ``--help`` text (syntax evidence only)."""

    missing = sorted(f for f in LFM3_ALLOWED_FLAGS if not flag_in_text(f, help_text))
    if not help_text.strip() or (missing and truncated):
        verdict = "INCONCLUSIVE"
    else:
        verdict = "FAIL" if missing else "PASS"
    return {"verdict": verdict, "missing": missing, "truncated": truncated}


def approval_problems(step: str, text: str, document: Mapping[str, Any] | None = None) -> list[str]:
    """Identity binding of an owner approval to this contract. It checks names, never the owner's intent."""

    document = contract() if document is None else document
    steps = document["approvals"]
    if step not in steps:
        return [f"unknown approval step: {step}"]
    lowered = text.lower()
    problems: list[str] = []
    if not text.strip():
        return ["empty approval"]
    if step.lower() not in lowered:
        problems.append("approval does not name its step")
    if digest(document) not in lowered:
        problems.append("approval does not quote this contract's digest")
    for artifact in steps[step]["artifacts"]:
        for token in _artifact_tokens(artifact, document):
            if token not in lowered:
                problems.append(f"approval does not name {artifact}: {token[:16]}...")
    return problems


def _artifact_tokens(artifact: str, document: Mapping[str, Any]) -> list[str]:
    if artifact == "license":
        return [document["license"]["text_sha256"]]
    if artifact.startswith("runtime:"):
        return [document["runtime"]["candidates"][artifact.split(":", 1)[1]]["sha256"]]
    if artifact.startswith("qwen:"):
        wanted = artifact.split(":", 1)[1]
        arm = next(a for a in document["arms"] if a.get("model", {}).get("model_id") == wanted)
        return [arm["model"]["sha256"]]
    entry = next(c for c in document["candidates"] if c["model_id"] == artifact)
    return [entry["sha256"]]


def validate_contract(
    document: Mapping[str, Any], registry_path: Path = plan_module.REGISTRY_PATH
) -> list[str]:
    """Structural invariants a contract must hold before any owner is asked to approve it."""

    problems: list[str] = []
    if digest(document) != FROZEN_CONTRACT_SHA256:
        problems.append("contract differs from the frozen digest")
    production = load_model_registry(registry_path)
    recomputed = {
        "screening_plan_sha256": digest(frozen_plan(registry_path)),
        "final_plan_sha256": digest(final_plan()),
        "final_corpus_sha256": corpus_digest(final_corpus()),
    }
    if document.get("qwen_preserved") != QWEN_FROZEN or recomputed != QWEN_FROZEN:
        problems.append("Qwen plan, corpus or digests changed")
    if document.get("schema") != SCHEMA or document.get("status") != "FROZEN_PROPOSAL_UNAPPROVED":
        problems.append("contract schema or status is wrong")
    if any(document.get("authorization", {}).values()) or not document.get("authorization"):
        problems.append("a contract may not carry a granted authorization")
    for entry in document.get("candidates", []):
        problems += [f"{entry.get('model_id')}: {p}" for p in candidate_problems(entry, production)]
    selected = document["runtime"]["selected"]
    for tag, entry in document["runtime"]["candidates"].items():
        problems += [f"runtime {tag}: {p}" for p in runtime_problems(entry, require_members=False)]
        if (tag == selected) != bool(entry.get("selected")):
            problems.append("exactly the selected runtime must be marked selected")
    problems += license_problems(document["license"], require_acknowledged=False)
    steps = document["approvals"]
    for step, spec in steps.items():
        if not set(spec["prerequisites"]) <= set(steps) - {step}:
            problems.append(f"{step}: prerequisites name an unknown step")
    if any(e.model_id.startswith(MODEL_PREFIX) for e in production.entries):
        problems.append("an LFM3 entry is present in the production registry")
    if not set(document["argv"]["allowed_flags"]) <= LFM3_ALLOWED_FLAGS:
        problems.append("argv vocabulary exceeds the closed LFM3 set")
    if set(document["argv"]["allowed_flags"]) & FORBIDDEN_FLAGS:
        problems.append("argv vocabulary contains a forbidden flag")
    arm_ids = [a["arm_id"] for a in document["arms"]]
    if len(set(arm_ids)) != len(arm_ids):
        problems.append("duplicate arm id")
    for arm in document["arms"]:
        if arm["kind"] == "baseline":
            continue
        if arm["runtime"] != selected:
            problems.append(
                f"{arm['arm_id']}: runtime differs from the selected one (confounded comparison)"
            )
        if arm["sampling"] not in document["sampling"]:
            problems.append(f"{arm['arm_id']}: unknown sampling profile")
    return problems


# -- record and readiness guards ---------------------------------------------------------------------------------------


def _arm_model_sha(document: Mapping[str, Any], arm: Mapping[str, Any]) -> str:
    if "model" in arm:
        return str(arm["model"]["sha256"])
    return str(
        next(c for c in document["candidates"] if c["model_id"] == arm["model_id"])["sha256"]
    )


def record_problems(
    rows: Sequence[Mapping[str, Any]],
    document: Mapping[str, Any],
    arm_id: str,
    case_ids: Sequence[str] | None = None,
) -> list[str]:
    """Every record must be attributable to this contract, this arm's model, sampling, runtime and a recorded member.

    With ``case_ids`` the record set must also be exactly that list, once each. Hermetic and cooperative runs carry a
    different ``monitor_kind`` and are refused."""

    arm = next((a for a in document["arms"] if a["arm_id"] == arm_id), None)
    if arm is None or arm["kind"] == "baseline":
        return [f"no executable arm named {arm_id}"]
    runtime = document["runtime"]["candidates"][document["runtime"]["selected"]]
    members = set(runtime.get("members", {}).values())
    expected = {
        "contract_sha256": digest(document),
        "arm": arm_id,
        "sampling_profile": arm["sampling"],
        "runtime_asset_sha256": runtime["sha256"],
        "model_sha256": _arm_model_sha(document, arm),
        "monitor_kind": "host",
    }
    problems = []
    if not rows:
        problems.append("no records")
    for index, row in enumerate(rows):
        for key, value in expected.items():
            if row.get(key) != value:
                problems.append(f"record {index}: {key} does not match the contract")
        if row.get("runtime_member_sha256") not in members:
            problems.append(f"record {index}: launched member is not a recorded member hash")
    ids = [row.get("case_id") for row in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate case records")
    if case_ids is not None and set(ids) != set(case_ids):
        problems.append("record set differs from the frozen case list")
    return problems


def stage_b_verdict(
    rows: Sequence[Mapping[str, Any]],
    document: Mapping[str, Any],
    arm_id: str,
    cases: Sequence[Any],
    *,
    teardown_verified: bool,
    preference: Mapping[str, Any] | None,
    capture_verdicts: Sequence[str],
) -> dict[str, Any]:
    """The one computable form of Stage B ``go_requires``. Any problem is INCONCLUSIVE; GO only from complete evidence."""

    unmet = record_problems(rows, document, arm_id, [c.case_id for c in cases])
    if corpus_digest(list(cases)) != document["stages"]["B"]["corpus_sha256"]:
        unmet.append("cases are not the frozen Stage B corpus")
    if not capture_verdicts:
        unmet.append("no capture analysis")
    unmet += [f"capture analysis is {v}, not PASS" for v in capture_verdicts if v != "PASS"]
    if unmet:
        return {"verdict": "INCONCLUSIVE", "unmet": unmet}
    verdict: dict[str, Any] = evaluate_final_gates(  # type: ignore[no-untyped-call]
        list(cases), rows, teardown_verified=teardown_verified, preference=preference
    )
    return verdict


_STAGE_STEPS: dict[str, tuple[str, ...]] = {
    "S0_download": ("S0_download",),
    "S2_d12a_b11960": ("S0_download", "S1_license", "S2_d12a_b11960"),
    "S3_stage_a": ("S0_download", "S1_license", "S2_d12a_b11960", "S3_stage_a"),
    "S4_stage_b": ("S0_download", "S1_license", "S2_d12a_b11960", "S3_stage_a", "S4_stage_b"),
}
_STAGE_FLAGS: dict[str, tuple[str, ...]] = {
    "S0_download": (),
    "S2_d12a_b11960": ("artifacts_verified", "harness_supports_contract"),
    "S3_stage_a": (
        "d12a_b11960_pass",
        "harness_supports_contract",
        "protected_runtime",
        "canary_proof_current",
        "firewall_attested",
        "quiet_host",
        "capture_state_clear",
    ),
    "S4_stage_b": (
        "d12a_b11960_pass",
        "harness_supports_contract",
        "protected_runtime",
        "canary_proof_current",
        "firewall_attested",
        "quiet_host",
        "capture_state_clear",
        "stage_a_advance",
        "stage_b_capture_split_defined",
        "blind_session_scheduled",
    ),
}


def readiness_blockers(
    stage: str, evidence: Mapping[str, Any], document: Mapping[str, Any] | None = None
) -> list[str]:
    """What still prevents a stage from starting. Approvals, the licence, the runtime entry and the ``--help`` report are
    judged here from their evidence objects; the remaining flags are operator attestations and count only as exactly True."""

    if stage not in _STAGE_STEPS:
        return [f"unknown stage: {stage}"]
    document = contract() if document is None else document
    blockers: list[str] = []
    approvals = evidence.get("approvals")
    texts = approvals if isinstance(approvals, Mapping) else {}
    for step in _STAGE_STEPS[stage]:
        text = texts.get(step)
        if not isinstance(text, str) or approval_problems(step, text, document):
            blockers.append(f"approval_{step}")
    if stage != "S0_download":
        licence = evidence.get("license")
        if not isinstance(licence, Mapping) or license_problems(licence, require_acknowledged=True):
            blockers.append("license_acknowledged")
    if stage in ("S3_stage_a", "S4_stage_b"):
        runtime = evidence.get("runtime")
        if not isinstance(runtime, Mapping) or runtime_problems(runtime, require_members=True):
            blockers.append("runtime_members_recorded")
        report = evidence.get("help_report")
        if not isinstance(report, Mapping) or report.get("verdict") != "PASS":
            blockers.append("help_lists_every_contract_flag")
    blockers += [key for key in _STAGE_FLAGS[stage] if evidence.get(key) is not True]
    return blockers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    document = contract()
    problems = validate_contract(document)
    if problems:
        raise SystemExit("contract is invalid: " + "; ".join(problems))
    args.out.mkdir(parents=True)
    (args.out / "contract.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"contract_sha256": digest(document)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
