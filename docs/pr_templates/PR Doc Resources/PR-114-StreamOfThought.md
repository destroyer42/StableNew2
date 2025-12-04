Confirming paths in internal repo snapshot
User needs a PR spec. I don’t need a web search since it’s related to internal details. I’ll inspect files in the snapshot to check filenames and confirm paths for controllers, job services, etc. I’ll look at the current inventory file for verification and proceed with the relevant structure for the PR.

Inspecting repo snapshot and inventory for paths
import json, textwrap, os, zipfile, itertools, math
Re-importing necessary components
I need to re-import the required components. Looks like something might not have been properly loaded. Let me make sure I get the correct module or file in place before continuing with the task. I'll go ahead and import what’s needed so I can move forward smoothly!

Re-importing required Python libraries
import json, os, zipfile, textwrap, math, itertools
Opening inventory for review
I’ll go ahead and open the inventory now. This should help me confirm the paths for the necessary files and components. I'll take a detailed look to ensure everything is in place and set up correctly, so I can proceed smoothly with the task. Should have this done shortly.

Checking inventory file existence
inv_path = "/mnt/data/repo_inventory.json"
print(os.path.exists(inv_path))

True
Opening inventory data
with open(inv_path) as f:
    inv = json.load(f)
list(inv.keys())
['repo_root',
 'created_at',
 'snapshot_zip',
 'file_count',
 'total_size_bytes',
 'excludes',
 'excluded_exts',
 'files']
Opening inventory and displaying snapshot zip
len(inv["files"]), inv["snapshot_zip"]
(1301,
 'C:\\Users\\rob\\projects\\StableNew\\snapshots\\StableNew-snapshot-20251203-231300.zip')
Identifying relevant controller/pipeline files
I’ll list the relevant controller and pipeline files now. These will help ensure that we’re looking at the right components for the task ahead. I'll identify the key files needed and verify that everything is organized correctly to carry out the required steps smoothly.

Listing relevant controller and pipeline files
[file for file in inv["files"] if "pipeline_controller" in file.lower() or "job_service" in file.lower() or "single_node" in file.lower()][:50]

---------------------------------------------------------------------------
AttributeError                            Traceback (most recent call last)
Cell In[5], line 1
----> 1 [file for file in inv["files"] if "pipeline_controller" in file.lower() or "job_service" in file.lower() or "single_node" in file.lower()][:50]

Cell In[5], line 1, in <listcomp>(.0)
----> 1 [file for file in inv["files"] if "pipeline_controller" in file.lower() or "job_service" in file.lower() or "single_node" in file.lower()][:50]

AttributeError: 'dict' object has no attribute 'lower'
Adjusting file path structure
It looks like I need to adjust my approach. The inv["files"] is a list of dictionaries with a path key. I’ll have to tweak my understanding and code to handle this structure effectively. Let me adjust accordingly before moving forward with the task.

Filtering file paths based on specific criteria
files = inv["files"]
paths = [f["path"] for f in files]
[p for p in paths if "pipeline_controller" in os.path.basename(p).lower() or 
                  "job_service" in os.path.basename(p).lower() or 
                  "single_node" in os.path.basename(p).lower()][:50]

['docs/pr_templates/PriorWork_complete/PR-QUEUE-V2-JOBMODEL-001_queue_model_and_single_node_runner_skeleton.md',
 'src/controller/job_service.py',
 'src/controller/pipeline_controller.py',
 'src/queue/single_node_runner.py',
 'tests/controller/test_job_service_unit.py',
 'tests/controller/test_pipeline_controller_config_path.py',
 'tests/controller/test_pipeline_controller_queue_mode.py',
 'tests/controller/test_pipeline_controller_webui_gating.py',
 'tests/queue/test_single_node_runner.py',
 'tests/queue/test_single_node_runner_loopback.py']
Including app_controller paths
Alright, I need to get the paths for the app_controller as well. These are just as important for the task, so I'll ensure I include them in the process. Let me grab those and make sure everything is set and ready for the task ahead.

Filtering app_controller paths
[p for p in paths if os.path.basename(p)=="app_controller.py"]
['src/controller/app_controller.py']
Generating a robust PR spec
I need to generate PR-0114 specs with intent, context (linking to D-11), allowed/forbidden files, risk tier, implementation steps, test plan, and validation checklist. Following the StableNew PR template's guardrails, I’ll include the robust details the user asked for. We shouldn't modify critical files like pipeline_runner core. I'll only treat them as dependencies and avoid editing them. Files like app_controller.py, pipeline_controller.py, job_service.py, and single_node_runner.py are allowed.

Clarifying test scope and run mode behavior
I’ll focus on tests in tests/controller and tests/queue, adding new tests for "run modes" if needed, but keeping the scope limited. I need to describe the run modes: "direct" vs. "queue." For the "queue" mode, I'll define behavior in pipeline_controller.start_pipeline(), ensuring current tests (like test_pipeline_controller_queue_mode.py) are not broken. I'll inspect these tests to confirm behavior while centralizing pipeline assembly.

Generating PR specification and assessing file permissions
def show(path, n=200):
    with open("/mnt/data/StableNew-snapshot-20251203-231300.zip", "rb") as f:
        with zipfile.ZipFile(f) as z:
            with z.open(path) as fh:
                data = fh.read().decode("utf-8", errors="ignore")
    print("\n".join(data.splitlines()[:n]))

show("src/controller/pipeline_controller.py", 260)

"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller."""

from __future__ import annotations

import uuid

from typing import Callable, Any

from src.controller.job_service import JobService
from src.gui.controller import PipelineController as _GUIPipelineController
from src.gui.state import StateManager
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.controller.job_execution_controller import JobExecutionController
from src.controller.queue_execution_controller import QueueExecutionController
from src.queue.job_model import JobStatus, Job, JobPriority
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.pipeline.pipeline_runner import PipelineRunResult, PipelineConfig, PipelineRunner
from src.gui.state import GUIState
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState
from src.config import app_config
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.state import PipelineState
from src.api.client import SDWebUIClient
from src.utils import StructuredLogger


class PipelineController(_GUIPipelineController):
    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower == "direct":
            return "direct"
        return "queue"

    def _build_job(
        self,
        config: PipelineConfig,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        lora_settings: dict | None = None,
        randomizer_metadata: dict | None = None,
        learning_enabled: bool = False,
    ) -> Job:
        """Build a Job with full metadata for provenance tracking (PR-106)."""
        # Create config snapshot for auditing
        config_snapshot: dict[str, Any] = {}
        if config is not None:
            try:
                config_snapshot = {
                    "prompt": getattr(config, "prompt", ""),
                    "model": getattr(config, "model", "") or getattr(config, "model_name", ""),
                    "steps": getattr(config, "steps", None),
                    "cfg_scale": getattr(config, "cfg_scale", None),
                    "width": getattr(config, "width", None),
                    "height": getattr(config, "height", None),
                    "sampler": getattr(config, "sampler", None),
                }
            except Exception:
                config_snapshot = {}

        return Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=config,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            lora_settings=lora_settings,
            randomizer_metadata=randomizer_metadata,
            learning_enabled=learning_enabled,
        )

    def _coerce_overrides(self, overrides: GuiOverrides | dict[str, Any] | None) -> GuiOverrides:
        if isinstance(overrides, GuiOverrides):
            return overrides
        if isinstance(overrides, dict):
            return GuiOverrides(
                prompt=str(overrides.get("prompt", "")),
                model=str(overrides.get("model", "")),
                model_name=str(overrides.get("model_name", overrides.get("model", ""))),
                vae_name=str(overrides.get("vae_name", "")),
                sampler=str(overrides.get("sampler", "")),
                width=int(overrides.get("width", 512) or 512),
                height=int(overrides.get("height", 512) or 512),
                steps=int(overrides.get("steps", 20) or 20),
                cfg_scale=float(overrides.get("cfg_scale", 7.0) or 7.0),
                resolution_preset=str(overrides.get("resolution_preset", "")),
                negative_prompt=str(overrides.get("negative_prompt", "")),
                output_dir=str(overrides.get("output_dir", "")),
                filename_pattern=str(overrides.get("filename_pattern", "")),
                image_format=str(overrides.get("image_format", "")),
                batch_size=int(overrides.get("batch_size", 1) or 1),
                seed_mode=str(overrides.get("seed_mode", "")),
                metadata=dict(overrides.get("metadata") or {}),
            )
        return GuiOverrides()

    def _extract_state_overrides(self) -> GuiOverrides:
        extractor = getattr(self.state_manager, "get_pipeline_overrides", None)
        if callable(extractor):
            try:
                return self._coerce_overrides(extractor())
            except Exception:
                pass

        if hasattr(self.state_manager, "pipeline_overrides"):
            try:
                return self._coerce_overrides(getattr(self.state_manager, "pipeline_overrides"))
            except Exception:
                pass

        fallback = getattr(self, "get_gui_overrides", None)
        if callable(fallback):
            try:
                return self._coerce_overrides(fallback())
            except Exception:
                pass

        return GuiOverrides()

    def get_webui_connection_state(self):
        if hasattr(self, "_webui_connection") and self._webui_connection is not None:
            return self._webui_connection.get_state()
        return None


    def _extract_metadata(self, attr_name: str) -> dict[str, Any] | None:
        value = None
        accessor = getattr(self.state_manager, attr_name, None)
        if callable(accessor):
            try:
                value = accessor()
            except Exception:
                value = None
        elif accessor is not None:
            value = accessor

        if isinstance(value, dict):
            return dict(value)
        return None

    def _build_pipeline_config_from_state(self) -> PipelineConfig:
        overrides = self._extract_state_overrides()
        learning_metadata = self._extract_metadata("learning_metadata")
        randomizer_metadata = self._extract_metadata("randomizer_metadata")

        if learning_metadata is None and self._learning_enabled:
            learning_metadata = {"learning_enabled": True}

        return self._config_assembler.build_from_gui_input(
            overrides=overrides,
            learning_metadata=learning_metadata,
            randomizer_metadata=randomizer_metadata,
        )

    def build_pipeline_config_with_profiles(
        self,
        base_model_name: str,
        lora_names: list[str],
        user_overrides: dict[str, any],
    ) -> dict:
        """Build pipeline config using ModelProfile and LoraProfile priors."""
        from pathlib import Path
        from src.learning.model_profiles import find_model_profile_for_checkpoint, find_lora_profile_for_name, suggest_preset_for
        # Resolve checkpoint path (stub: assumes models are in 'models/' dir)
        checkpoint_path = Path("models") / f"{base_model_name}.ckpt"
        model_profile = find_model_profile_for_checkpoint(checkpoint_path)
        lora_search_paths = [Path("loras")]
        lora_profiles = [find_lora_profile_for_name(name, lora_search_paths) for name in lora_names]
        lora_profiles = [lp for lp in lora_profiles if lp]
        suggested = suggest_preset_for(model_profile, lora_profiles)
        # Start from default config
        config = self.get_default_config() if hasattr(self, "get_default_config") else {}
        # Always ensure txt2img key exists and populate with defaults if missing
        if "txt2img" not in config:
            config["txt2img"] = {
                "sampler_name": "Euler",
                "scheduler": None,
                "steps": 20,
                "cfg_scale": 5.0,
                "width": 512,
                "height": 512,
                "loras": [],
            }
        # Apply suggested preset if available
        if suggested:
            config["txt2img"].update({
                "sampler_name": suggested.sampler,
                "scheduler": suggested.scheduler,
                "steps": suggested.steps,
                "cfg_scale": suggested.cfg,
                "width": suggested.resolution[0],
                "height": suggested.resolution[1],
            })
            # Apply LoRA weights
            config["txt2img"]["loras"] = [
                {"name": name, "weight": suggested.lora_weights.get(name, 0.6)} for name in lora_names
            ]
            import logging
            logging.info(f"Using model profile preset {suggested.preset_id} (source={suggested.source}) for {base_model_name} + {lora_names}.")
        # Apply user overrides last
        for k, v in user_overrides.items():
            # Map common override keys to txt2img
            if k in ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height", "loras"):
                config["txt2img"][k] = v
            elif k == "cfg":
                config["txt2img"]["cfg_scale"] = v
            elif k == "resolution" and isinstance(v, (tuple, list)) and len(v) == 2:
                config["txt2img"]["width"] = v[0]
                config["txt2img"]["height"] = v[1]
            else:
                config[k] = v
        return config

    """Provide a default StateManager so legacy imports keep working."""

    def __init__(
        self,
        state_manager: StateManager | None = None,
        *,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: PipelineConfigAssembler | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        api_client = kwargs.pop("api_client", None)
        job_service = kwargs.pop("job_service", None)
        structured_logger = kwargs.pop("structured_logger", None)
        pipeline_runner = kwargs.pop("pipeline_runner", None)
        
        queue_execution_controller = kwargs.pop("queue_execution_controller", None)
        webui_conn = kwargs.pop("webui_connection_controller", None)
        super().__init__(state_manager or StateManager(), **kwargs)
        self._learning_runner = None
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_learning_record: LearningRecord | None = None
        self._last_run_result: PipelineRunResult | None = None
        self._last_stage_execution_plan: StageExecutionPlan | None = None
        self._last_stage_events: list[dict[Any, Any]] | None = None
        self._learning_enabled: bool = False
        self._job_controller = JobExecutionController(execute_job=self._execute_job)
        self._queue_execution_controller: QueueExecutionController | None = queue_execution_controller or QueueExecutionController(job_controller=self._job_controller)
        self._queue_execution_enabled: bool = is_queue_execution_enabled()
        self._config_assembler = config_assembler if config_assembler is not None else PipelineConfigAssembler()
        self._webui_connection = webui_conn if webui_conn is not None else WebUIConnectionController()
        self._pipeline_runner = pipeline_runner
        if self._queue_execution_controller:
            try:
                self._queue_execution_controller.observe("pipeline_ctrl", self._on_queue_status)
            except Exception:
Reprinting file carefully for reasoning
I noticed the output was cut off due to truncation. I should reprint the entire file so I can follow along properly, but I'll need to be cautious about the length to avoid issues. It's okay though because for the reasoning process, I just need everything laid out clearly.

Displaying full file contents with truncation handling
show("src/controller/pipeline_controller.py", 400)

"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller."""

from __future__ import annotations

import uuid

from typing import Callable, Any

from src.controller.job_service import JobService
from src.gui.controller import PipelineController as _GUIPipelineController
from src.gui.state import StateManager
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.controller.job_execution_controller import JobExecutionController
from src.controller.queue_execution_controller import QueueExecutionController
from src.queue.job_model import JobStatus, Job, JobPriority
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.pipeline.pipeline_runner import PipelineRunResult, PipelineConfig, PipelineRunner
from src.gui.state import GUIState
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState
from src.config import app_config
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.state import PipelineState
from src.api.client import SDWebUIClient
from src.utils import StructuredLogger


class PipelineController(_GUIPipelineController):
    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower == "direct":
            return "direct"
        return "queue"

    def _build_job(
        self,
        config: PipelineConfig,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        lora_settings: dict | None = None,
        randomizer_metadata: dict | None = None,
        learning_enabled: bool = False,
    ) -> Job:
        """Build a Job with full metadata for provenance tracking (PR-106)."""
        # Create config snapshot for auditing
        config_snapshot: dict[str, Any] = {}
        if config is not None:
            try:
                config_snapshot = {
                    "prompt": getattr(config, "prompt", ""),
                    "model": getattr(config, "model", "") or getattr(config, "model_name", ""),
                    "steps": getattr(config, "steps", None),
                    "cfg_scale": getattr(config, "cfg_scale", None),
                    "width": getattr(config, "width", None),
                    "height": getattr(config, "height", None),
                    "sampler": getattr(config, "sampler", None),
                }
            except Exception:
                config_snapshot = {}

        return Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=config,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            lora_settings=lora_settings,
            randomizer_metadata=randomizer_metadata,
            learning_enabled=learning_enabled,
        )

    def _coerce_overrides(self, overrides: GuiOverrides | dict[str, Any] | None) -> GuiOverrides:
        if isinstance(overrides, GuiOverrides):
            return overrides
        if isinstance(overrides, dict):
            return GuiOverrides(
                prompt=str(overrides.get("prompt", "")),
                model=str(overrides.get("model", "")),
                model_name=str(overrides.get("model_name", overrides.get("model", ""))),
                vae_name=str(overrides.get("vae_name", "")),
                sampler=str(overrides.get("sampler", "")),
                width=int(overrides.get("width", 512) or 512),
                height=int(overrides.get("height", 512) or 512),
                steps=int(overrides.get("steps", 20) or 20),
                cfg_scale=float(overrides.get("cfg_scale", 7.0) or 7.0),
                resolution_preset=str(overrides.get("resolution_preset", "")),
                negative_prompt=str(overrides.get("negative_prompt", "")),
                output_dir=str(overrides.get("output_dir", "")),
                filename_pattern=str(overrides.get("filename_pattern", "")),
                image_format=str(overrides.get("image_format", "")),
                batch_size=int(overrides.get("batch_size", 1) or 1),
                seed_mode=str(overrides.get("seed_mode", "")),
                metadata=dict(overrides.get("metadata") or {}),
            )
        return GuiOverrides()

    def _extract_state_overrides(self) -> GuiOverrides:
        extractor = getattr(self.state_manager, "get_pipeline_overrides", None)
        if callable(extractor):
            try:
                return self._coerce_overrides(extractor())
            except Exception:
                pass

        if hasattr(self.state_manager, "pipeline_overrides"):
            try:
                return self._coerce_overrides(getattr(self.state_manager, "pipeline_overrides"))
            except Exception:
                pass

        fallback = getattr(self, "get_gui_overrides", None)
        if callable(fallback):
            try:
                return self._coerce_overrides(fallback())
            except Exception:
                pass

        return GuiOverrides()

    def get_webui_connection_state(self):
        if hasattr(self, "_webui_connection") and self._webui_connection is not None:
            return self._webui_connection.get_state()
        return None


    def _extract_metadata(self, attr_name: str) -> dict[str, Any] | None:
        value = None
        accessor = getattr(self.state_manager, attr_name, None)
        if callable(accessor):
            try:
                value = accessor()
            except Exception:
                value = None
        elif accessor is not None:
            value = accessor

        if isinstance(value, dict):
            return dict(value)
        return None

    def _build_pipeline_config_from_state(self) -> PipelineConfig:
        overrides = self._extract_state_overrides()
        learning_metadata = self._extract_metadata("learning_metadata")
        randomizer_metadata = self._extract_metadata("randomizer_metadata")

        if learning_metadata is None and self._learning_enabled:
            learning_metadata = {"learning_enabled": True}

        return self._config_assembler.build_from_gui_input(
            overrides=overrides,
            learning_metadata=learning_metadata,
            randomizer_metadata=randomizer_metadata,
        )

    def build_pipeline_config_with_profiles(
        self,
        base_model_name: str,
        lora_names: list[str],
        user_overrides: dict[str, any],
    ) -> dict:
        """Build pipeline config using ModelProfile and LoraProfile priors."""
        from pathlib import Path
        from src.learning.model_profiles import find_model_profile_for_checkpoint, find_lora_profile_for_name, suggest_preset_for
        # Resolve checkpoint path (stub: assumes models are in 'models/' dir)
        checkpoint_path = Path("models") / f"{base_model_name}.ckpt"
        model_profile = find_model_profile_for_checkpoint(checkpoint_path)
        lora_search_paths = [Path("loras")]
        lora_profiles = [find_lora_profile_for_name(name, lora_search_paths) for name in lora_names]
        lora_profiles = [lp for lp in lora_profiles if lp]
        suggested = suggest_preset_for(model_profile, lora_profiles)
        # Start from default config
        config = self.get_default_config() if hasattr(self, "get_default_config") else {}
        # Always ensure txt2img key exists and populate with defaults if missing
        if "txt2img" not in config:
            config["txt2img"] = {
                "sampler_name": "Euler",
                "scheduler": None,
                "steps": 20,
                "cfg_scale": 5.0,
                "width": 512,
                "height": 512,
                "loras": [],
            }
        # Apply suggested preset if available
        if suggested:
            config["txt2img"].update({
                "sampler_name": suggested.sampler,
                "scheduler": suggested.scheduler,
                "steps": suggested.steps,
                "cfg_scale": suggested.cfg,
                "width": suggested.resolution[0],
                "height": suggested.resolution[1],
            })
            # Apply LoRA weights
            config["txt2img"]["loras"] = [
                {"name": name, "weight": suggested.lora_weights.get(name, 0.6)} for name in lora_names
            ]
            import logging
            logging.info(f"Using model profile preset {suggested.preset_id} (source={suggested.source}) for {base_model_name} + {lora_names}.")
        # Apply user overrides last
        for k, v in user_overrides.items():
            # Map common override keys to txt2img
            if k in ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height", "loras"):
                config["txt2img"][k] = v
            elif k == "cfg":
                config["txt2img"]["cfg_scale"] = v
            elif k == "resolution" and isinstance(v, (tuple, list)) and len(v) == 2:
                config["txt2img"]["width"] = v[0]
                config["txt2img"]["height"] = v[1]
            else:
                config[k] = v
        return config

    """Provide a default StateManager so legacy imports keep working."""

    def __init__(
        self,
        state_manager: StateManager | None = None,
        *,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: PipelineConfigAssembler | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        api_client = kwargs.pop("api_client", None)
        job_service = kwargs.pop("job_service", None)
        structured_logger = kwargs.pop("structured_logger", None)
        pipeline_runner = kwargs.pop("pipeline_runner", None)
        
        queue_execution_controller = kwargs.pop("queue_execution_controller", None)
        webui_conn = kwargs.pop("webui_connection_controller", None)
        super().__init__(state_manager or StateManager(), **kwargs)
        self._learning_runner = None
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_learning_record: LearningRecord | None = None
        self._last_run_result: PipelineRunResult | None = None
        self._last_stage_execution_plan: StageExecutionPlan | None = None
        self._last_stage_events: list[dict[Any, Any]] | None = None
        self._learning_enabled: bool = False
        self._job_controller = JobExecutionController(execute_job=self._execute_job)
        self._queue_execution_controller: QueueExecutionController | None = queue_execution_controller or QueueExecutionController(job_controller=self._job_controller)
        self._queue_execution_enabled: bool = is_queue_execution_enabled()
        self._config_assembler = config_assembler if config_assembler is not None else PipelineConfigAssembler()
        self._webui_connection = webui_conn if webui_conn is not None else WebUIConnectionController()
        self._pipeline_runner = pipeline_runner
        if self._queue_execution_controller:
            try:
                self._queue_execution_controller.observe("pipeline_ctrl", self._on_queue_status)
            except Exception:
                pass
        self._job_history_service: JobHistoryService | None = None
        self._active_job_id: str | None = None
        self._last_run_config: dict[str, Any] | None = None
        self._last_run_config: dict[str, Any] | None = None
        queue = self._job_controller.get_queue()
        runner = self._job_controller.get_runner()
        history_store = self._job_controller.get_history_store()
        self._job_service = job_service if job_service is not None else JobService(queue, runner, history_store)
        self._job_controller.set_status_callback("pipeline", self._on_job_status)

    def _get_learning_runner(self):
        if self._learning_runner is None:
            from src.learning.learning_runner import LearningRunner

            self._learning_runner = LearningRunner()
        return self._learning_runner

    def get_learning_runner_for_tests(self):
        """Return the learning runner instance for test inspection."""

        return self._get_learning_runner()

    def handle_learning_record(self, record: LearningRecord) -> None:
        """Handle learning records forwarded from pipeline runner."""

        self._last_learning_record = record
        if self._learning_record_writer and self._learning_enabled:
            try:
                append = getattr(self._learning_record_writer, "append_record", None)
                if callable(append):
                    append(record)
                else:
                    self._learning_record_writer.write(record)
            except Exception:
                pass
        if self._learning_record_callback:
            try:
                self._learning_record_callback(record)
            except Exception:
                pass

    def get_learning_record_handler(self):
        """Return a callback suitable for passing to PipelineRunner."""

        return self.handle_learning_record

    def get_last_learning_record(self) -> LearningRecord | None:
        """Return the most recent LearningRecord handled by the controller."""

        return self._last_learning_record

    def set_learning_enabled(self, enabled: bool) -> None:
        """Enable or disable passive learning record emission."""

        self._learning_enabled = bool(enabled)

    def is_learning_enabled(self) -> bool:
        """Return whether learning record emission is enabled."""

        return self._learning_enabled

    def record_run_result(self, result: PipelineRunResult) -> None:
        """Record the last PipelineRunResult for inspection by higher layers/tests."""

        self._last_run_result = result
        self._last_stage_events = getattr(result, "stage_events", None)

    def get_last_run_result(self) -> PipelineRunResult | None:
        """Return the most recent PipelineRunResult recorded on this controller."""

        return self._last_run_result

    def validate_stage_plan(self, config: dict) -> StageExecutionPlan:
        """Build and store a stage execution plan for testing/inspection."""

        plan = build_stage_execution_plan(config)
        self._last_stage_execution_plan = plan
        return plan

    def get_last_stage_execution_plan_for_tests(self) -> StageExecutionPlan | None:
        """Return the most recent StageExecutionPlan built by this controller."""

        return self._last_stage_execution_plan

    def get_last_run_config_for_tests(self) -> dict[str, Any] | None:
        return self._last_run_config

    def get_last_stage_events_for_tests(self) -> list[dict] | None:
        """Return last emitted stage events."""

        return self._last_stage_events

    # Queue-backed execution -------------------------------------------------
    def start_pipeline(
        self,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
        *,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        run_config: dict[str, Any] | None = None,
    ) -> bool:
        """Submit a pipeline job using assembler-enforced config."""
        if not self.state_manager.can_run():
            return False

        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self.state_manager.transition_to(GUIState.ERROR)
                except Exception:
                    pass
                return False

        if run_config is not None:
            self._last_run_config = run_config
            requested_mode = (run_config.get("run_mode") or "").strip().lower()
            try:
                if requested_mode in {"direct", "queue"}:
                    self.state_manager.pipeline_state.run_mode = requested_mode
            except Exception:
                pass

        try:
            config = self._build_pipeline_config_from_state()
        except Exception as exc:  # noqa: BLE001
            if on_error:
                on_error(exc)
            raise

        def _payload() -> dict[Any, Any]:
            try:
                result: dict[str, Any] = {"config": config}
                run_result = self._run_pipeline_job(config, pipeline_func=pipeline_func)
                if isinstance(run_result, dict):
                    result.update(run_result)
                if on_complete:
                    on_complete(result)
                return result
Reading file fully for complete details
The output is still being truncated, and I’m not getting the full file yet. It could be longer, but I really need the entire listing to make sure I don’t miss anything important. I’ll read through the whole file and might search for the start_pipeline function specifically.

Reading and searching file contents for start_pipeline function
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    data = z.read("src/controller/pipeline_controller.py").decode("utf-8", errors="ignore")
print("start_pipeline" in data)
print(data[:1200])

True
"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller."""

from __future__ import annotations

import uuid

from typing import Callable, Any

from src.controller.job_service import JobService
from src.gui.controller import PipelineController as _GUIPipelineController
from src.gui.state import StateManager
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.controller.job_execution_controller import JobExecutionController
from src.controller.queue_execution_controller import QueueExecutionController
from src.queue.job_model import JobStatus, Job, JobPriority
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.pipeline.pipeline_runner import PipelineRunResult, PipelineConfig, PipelineRunner
from src.gui.state import GUIState
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState
from src.config import app_config
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_config_assembler import PipelineConfigAssem
Fixing truncation by focusing search efforts
The output is still truncated due to the environment’s 1200-character print limit. So, instead of relying solely on the full file, I’ll search around the start_pipeline function's region and use substring indexes to narrow things down. This way, I don't miss important details.

Searching for start_pipeline function in code
idx = data.index("def start_pipeline")
print(idx)
print(data[idx:idx+1200])

15893
def start_pipeline(
        self,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
        *,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        run_config: dict[str, Any] | None = None,
    ) -> bool:
        """Submit a pipeline job using assembler-enforced config."""
        if not self.state_manager.can_run():
            return False

        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self.state_manager.transition_to(GUIState.ERROR)
                except Exception:
                    pass
                return False

        if run_config is not None:
            self._last_run_config = run_config
            requested_mode = (run_config.get("run_mode") or "").strip().lower()
            try:
                if requested_mode in {"direct", "queue"}:
                    self.state_manager.pipeline_state.run_mode = requested_mode
            except Exception:
Extracting data based on substring indices
print(data[idx+1200:idx+2400])


                pass

        try:
            config = self._build_pipeline_config_from_state()
        except Exception as exc:  # noqa: BLE001
            if on_error:
                on_error(exc)
            raise

        def _payload() -> dict[Any, Any]:
            try:
                result: dict[str, Any] = {"config": config}
                run_result = self._run_pipeline_job(config, pipeline_func=pipeline_func)
                if isinstance(run_result, dict):
                    result.update(run_result)
                if on_complete:
                    on_complete(result)
                return result
            except Exception as exc:  # noqa: BLE001
                if on_error:
                    on_error(exc)
                raise

        if self._queue_execution_enabled and self._queue_execution_controller:
            self._active_job_id = self._queue_execution_controller.submit_pipeline_job(_payload)
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass
            return True

        self._active_job_id = self._job_controller.submit_pipeline_
Printing data slice for substring indexing
print(data[idx+2400:idx+3600])

run(_payload)
        try:
            self.state_manager.transition_to(GUIState.RUNNING)
        except Exception:
            pass
        return True

    def _run_pipeline_job(
        self,
        config: PipelineConfig,
        *,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a pipeline job using the assembled config or a compatibility callable."""

        runner = getattr(self, "run_full_pipeline", None)
        if callable(runner):
            maybe_result = runner(config)
            if isinstance(maybe_result, dict):
                return maybe_result

        if pipeline_func:
            maybe_result = pipeline_func()
            if isinstance(maybe_result, dict):
                return maybe_result

        return {}

    def stop_pipeline(self) -> bool:
        """Cancel the active job."""

        if self._active_job_id:
            if self._queue_execution_enabled and self._queue_execution_controller:
                try:
                    self._queue_execution_controller.cancel_job(self._active_job_id)
                except Exception:
                    pass
   
Inspecting key components for pipeline execution
It sounds like start_pipeline already uses important components like queue_execution_controller, job_controller, and so on. _run_pipeline_job relies on the run_full_pipeline method or a fallback. Now, I need to look closer at JobExecutionController, QueueExecutionController, JobService, and SingleNodeJobRunner to understand how they work together.

Inspecting job and queue execution controllers
for path in ["src/controller/job_execution_controller.py",
             "src/controller/queue_execution_controller.py",
             "src/controller/job_service.py",
             "src/queue/single_node_runner.py"]:
    print("====", path, "====")
    with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
        data = z.read(path).decode("utf-8", errors="ignore")
    print("\n".join(data.splitlines()[:260]))

==== src/controller/job_execution_controller.py ====
"""Job execution bridge for queue-backed pipeline runs."""

from __future__ import annotations

import threading
import uuid
from typing import Callable, Optional

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore, JSONLJobHistoryStore
from pathlib import Path
from src.config.app_config import get_job_history_path
from src.cluster.worker_registry import WorkerRegistry
from src.cluster.worker_model import WorkerDescriptor


class JobExecutionController:
    """Owns JobQueue and SingleNodeJobRunner for single-node execution."""

    def __init__(
        self,
        execute_job: Callable[[Job], dict] | None = None,
        poll_interval: float = 0.05,
        history_store: JobHistoryStore | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._history_store = history_store or self._default_history_store()
        self._worker_registry = worker_registry or WorkerRegistry()
        self._queue = JobQueue(history_store=self._history_store)
        self._execute_job = execute_job
        self._runner = SingleNodeJobRunner(
            self._queue, self._execute_job, poll_interval=poll_interval, on_status_change=self._on_status
        )
        self._started = False
        self._lock = threading.Lock()
        self._callbacks: dict[str, Callable[[Job, JobStatus], None]] = {}

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._runner.start()
                self._started = True

    def stop(self) -> None:
        with self._lock:
            if self._started:
                self._runner.stop()
                self._started = False

    def submit_pipeline_run(self, pipeline_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        job_id = str(uuid.uuid4())
        worker_id = None
        try:
            worker_id = self._worker_registry.get_local_worker().id
        except Exception:
            worker_id = None
        job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
        self._queue.submit(job)
        self.start()
        return job_id

    def cancel_job(self, job_id: str) -> None:
        # Mark as cancelled so runner will skip it if not already running.
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        if job and job.status == JobStatus.QUEUED:
            job.mark_status(JobStatus.CANCELLED)

    def get_job_status(self, job_id: str) -> JobStatus | None:
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        return job.status if job else None

    def set_status_callback(self, key: str, callback: Callable[[Job, JobStatus], None]) -> None:
        self._callbacks[key] = callback

    def clear_status_callback(self, key: str) -> None:
        self._callbacks.pop(key, None)

    def _on_status(self, job: Job, status: JobStatus) -> None:
        for cb in list(self._callbacks.values()):
            try:
                cb(job, status)
            except Exception:
                pass

    def get_history_store(self) -> JobHistoryStore:
        return self._history_store

    def get_queue(self) -> JobQueue:
        return self._queue

    def get_worker_registry(self) -> WorkerRegistry:
        return self._worker_registry

    def get_runner(self) -> SingleNodeJobRunner:
        return self._runner

    def _default_history_store(self) -> JobHistoryStore:
        path = Path(get_job_history_path())
        return JSONLJobHistoryStore(path)
==== src/controller/queue_execution_controller.py ====
from __future__ import annotations

from typing import Callable

from src.controller.job_execution_controller import JobExecutionController
from src.queue.job_model import JobPriority


class QueueExecutionController:
    """Facade around JobExecutionController for controller/GUI usage."""

    def __init__(self, *, job_controller: JobExecutionController | None = None) -> None:
        self._job_controller = job_controller or JobExecutionController()

    def submit(self, payload_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        return self._job_controller.submit_pipeline_run(payload_callable, priority=priority)

    def submit_pipeline_job(self, payload_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        """Submit a job payload (typically a PipelineConfig) to the queue."""

        return self.submit(payload_callable, priority=priority)

    def cancel(self, job_id: str) -> None:
        self._job_controller.cancel_job(job_id)

    def cancel_job(self, job_id: str) -> None:
        """Cancel a queued/running job."""

        self.cancel(job_id)

    def observe(self, key: str, callback: Callable) -> None:
        self._job_controller.set_status_callback(key, callback)

    def clear_observer(self, key: str) -> None:
        self._job_controller.clear_status_callback(key)

    def register_status_callback(self, key: str, callback: Callable) -> None:
        self.observe(key, callback)

    def get_queue(self):
        return self._job_controller.get_queue()

    def get_history_store(self):
        return self._job_controller.get_history_store()
==== src/controller/job_service.py ====
"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

import logging

from typing import Any, Callable, Literal

from src.queue.job_model import Job, JobStatus
from src.gui.pipeline_panel_v2 import format_queue_job_summary
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore

QueueStatus = Literal["idle", "running", "paused"]


class JobService:
    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"
    EVENT_QUEUE_STATUS = "queue_status"

    def __init__(
        self,
        job_queue: JobQueue,
        runner: SingleNodeJobRunner,
        history_store: JobHistoryStore | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.runner = runner
        self.history_store = history_store
        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._queue_status: QueueStatus = "idle"
        self.runner._on_status_change = self._handle_runner_status

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job: Job) -> None:
        self.job_queue.submit(job)
        self._emit_queue_updated()

    def run_now(self, job: Job) -> None:
        self.enqueue(job)
        try:
            self.run_next_now()
        except Exception:
            pass
        if not self.runner.is_running():
            self.runner.start()

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

    def cancel_current(self) -> None:
        current = getattr(self.runner, "current_job", None)
        if current:
            self.job_queue.mark_cancelled(current.job_id)
        self.runner.cancel_current()
        self._set_queue_status("idle")

    def list_queue(self) -> list[Job]:
        return self.job_queue.list_jobs()

    def run_next_now(self) -> None:
        """Synchronously run the next queued job via the runner."""
        job = self.job_queue.get_next_job()
        if job is None:
            return
        self._set_queue_status("running")
        try:
            self.runner.run_once(job)
        finally:
            if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
                self._set_queue_status("idle")

    def _handle_runner_status(self, job: Job, status: JobStatus) -> None:
        if status == JobStatus.RUNNING:
            self._emit(self.EVENT_JOB_STARTED, job)
        elif status == JobStatus.COMPLETED:
            self._emit(self.EVENT_JOB_FINISHED, job)
        elif status == JobStatus.CANCELLED:
            self._emit(self.EVENT_JOB_FAILED, job)
        elif status == JobStatus.FAILED:
            self._emit(self.EVENT_JOB_FAILED, job)
        self._emit_queue_updated()
        if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
            self._emit(self.EVENT_QUEUE_EMPTY)

    def _emit_queue_updated(self) -> None:
        jobs = self.job_queue.list_jobs()
        summaries = [format_queue_job_summary(job) for job in jobs]
        self._emit(self.EVENT_QUEUE_UPDATED, summaries)

    def _set_queue_status(self, status: QueueStatus) -> None:
        if self._queue_status != status:
            self._queue_status = status
            self._emit(self.EVENT_QUEUE_STATUS, status)

    def _emit(self, event: str, *args: Any) -> None:
        for callback in self._listeners.get(event, []):
            try:
                callback(*args)
            except Exception:
                continue
==== src/queue/single_node_runner.py ====
# Subsystem: Queue
# Role: Executes queued jobs on a single node in FIFO/priority order.

"""Single-node job runner that executes jobs from an in-memory queue."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from src.queue.job_model import JobStatus, Job
from src.queue.job_queue import JobQueue


class SingleNodeJobRunner:
    """Background worker that executes jobs from a JobQueue."""

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
        poll_interval: float = 0.1,
        on_status_change: Callable[[Job, JobStatus], None] | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.run_callable = run_callable
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self.job_queue.get_next_job()
            if job is None:
                time.sleep(self.poll_interval)
                continue
            self.job_queue.mark_running(job.job_id)
            self._notify(job, JobStatus.RUNNING)
            self._current_job = job
            self._cancel_current.clear()
            try:
                if self._cancel_current.is_set():
                    self.job_queue.mark_cancelled(job.job_id)
                    self._notify(job, JobStatus.CANCELLED)
                    continue
                if self.run_callable:
                    result = self.run_callable(job)
                else:
                    result = {}
                self.job_queue.mark_completed(job.job_id, result=result)
                self._notify(job, JobStatus.COMPLETED)
            except Exception as exc:  # noqa: BLE001
                self.job_queue.mark_failed(job.job_id, error_message=str(exc))
                self._notify(job, JobStatus.FAILED)
            finally:
                self._current_job = None
        return

    def run_once(self, job: Job) -> dict | None:
        """Synchronously execute a single job (used by Run Now)."""
        if job is None:
            return None
        self.job_queue.mark_running(job.job_id)
        self._notify(job, JobStatus.RUNNING)
        self._current_job = job
        self._cancel_current.clear()
        try:
            if self.run_callable:
                result = self.run_callable(job)
            else:
                result = {}
            self.job_queue.mark_completed(job.job_id, result=result)
            self._notify(job, JobStatus.COMPLETED)
            return result
        except Exception as exc:  # noqa: BLE001
            self.job_queue.mark_failed(job.job_id, error_message=str(exc))
            self._notify(job, JobStatus.FAILED)
            raise
        finally:
            self._current_job = None

    def _notify(self, job: Job, status: JobStatus) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(job, status)
            except Exception:
                pass

    def cancel_current(self) -> None:
        self._cancel_current.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()
Accessing full details for job execution
It seems like I’m missing some crucial details from job_execution_controller, particularly around submit_pipeline_job. I need to gather the full implementation of this to better understand how it works, so I can align things properly and ensure the process integrates smoothly.

Extracting job_execution_controller code snippet
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    jec = z.read("src/controller/job_execution_controller.py").decode("utf-8", errors="ignore")
print(jec[:1600])

"""Job execution bridge for queue-backed pipeline runs."""

from __future__ import annotations

import threading
import uuid
from typing import Callable, Optional

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore, JSONLJobHistoryStore
from pathlib import Path
from src.config.app_config import get_job_history_path
from src.cluster.worker_registry import WorkerRegistry
from src.cluster.worker_model import WorkerDescriptor


class JobExecutionController:
    """Owns JobQueue and SingleNodeJobRunner for single-node execution."""

    def __init__(
        self,
        execute_job: Callable[[Job], dict] | None = None,
        poll_interval: float = 0.05,
        history_store: JobHistoryStore | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._history_store = history_store or self._default_history_store()
        self._worker_registry = worker_registry or WorkerRegistry()
        self._queue = JobQueue(history_store=self._history_store)
        self._execute_job = execute_job
        self._runner = SingleNodeJobRunner(
            self._queue, self._execute_job, poll_interval=poll_interval, on_status_change=self._on_status
        )
        self._started = False
        self._lock = threading.Lock()
        self._callbacks: dict[str, Callable[[Job, JobStatus], None]] = {}

    def start(self) -> None:
        with self._lock:
Extracting submit_pipeline_job function code
idx = jec.index("def submit_pipeline_job")
print(jec[idx:idx+1000])

---------------------------------------------------------------------------
ValueError                                Traceback (most recent call last)
Cell In[16], line 1
----> 1 idx = jec.index("def submit_pipeline_job")
      2 print(jec[idx:idx+1000])

ValueError: substring not found
Investigating the method naming issue
It seems the last error is just related to a missing substring, nothing major. The environment is warning, but I can safely ignore that. I’ll search for any method with the "submit_" pattern to check if the method name differs or if there’s a different way to approach this.

Searching for submit_ method pattern
for token in ["submit_pipeline", "submit_job", "submit", "submit_pipeline_job"]:
    print("Searching", token, token in jec)

Searching submit_pipeline True
Searching submit_job False
Searching submit True
Searching submit_pipeline_job False
Searching for "submit_" pattern in text
start = jec.index("submit_pipeline")
print(jec[start-120:start+600])

:
            if self._started:
                self._runner.stop()
                self._started = False

    def submit_pipeline_run(self, pipeline_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        job_id = str(uuid.uuid4())
        worker_id = None
        try:
            worker_id = self._worker_registry.get_local_worker().id
        except Exception:
            worker_id = None
        job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
        self._queue.submit(job)
        self.start()
        return job_id

    def cancel_job(self, job_id: str) -> None:
        # Mark as cancelled so runner will ski
Exploring the job_service.py file
I see that JobExecutionController houses the queue, SingleNodeJobRunner, and submit_pipeline_run. Now, I’m curious about what src/controller/job_service.py contains. I’ll need to read through that file to understand its role in the process and how it connects to the rest of the system.

Reading job_service.py file from zip archive
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    js = z.read("src/controller/job_service.py").decode("utf-8", errors="ignore")
print(js[:1600])

"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

import logging

from typing import Any, Callable, Literal

from src.queue.job_model import Job, JobStatus
from src.gui.pipeline_panel_v2 import format_queue_job_summary
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore

QueueStatus = Literal["idle", "running", "paused"]


class JobService:
    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"
    EVENT_QUEUE_STATUS = "queue_status"

    def __init__(
        self,
        job_queue: JobQueue,
        runner: SingleNodeJobRunner,
        history_store: JobHistoryStore | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.runner = runner
        self.history_store = history_store
        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._queue_status: QueueStatus = "idle"
        self.runner._on_status_change = self._handle_runner_status

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job: Job) -> None:
        self.job_queue.submit(job)
        self._emit_queue_updated()

    def run_now(self, job: Job) -> None:
        self.enqueue(job)
        tr
Looking for the full content around run_now
It looks like the content is getting truncated again; I need to get the rest of the code near run_now to see what else is going on. I'll check around that area so I can fully understand the context and how it fits into the overall system.

Extracting code snippet near 'run_now' function
idx = js.index("def run_now")
print(js[idx:idx+800])

def run_now(self, job: Job) -> None:
        self.enqueue(job)
        try:
            self.run_next_now()
        except Exception:
            pass
        if not self.runner.is_running():
            self.runner.start()

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct executi
Printing truncated data slice
print(js[idx+800:idx+1600])

on path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
Investigating pipeline_controller's design
It looks like there's a mix-up in design. JobService directly uses the JobQueue and SingleNodeJobRunner, but PipelineController is using JobExecutionController and QueueExecutionController. But wait, PipelineController imports JobService at the top, yet its __init__ method uses the other controllers. I should inspect the pipeline_controller earlier in the file to clarify this.

Investigating pipeline_controller class design and dependencies
print(data[:2000])

# Subsystem: Queue
# Role: Executes queued jobs on a single node in FIFO/priority order.

"""Single-node job runner that executes jobs from an in-memory queue."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from src.queue.job_model import JobStatus, Job
from src.queue.job_queue import JobQueue


class SingleNodeJobRunner:
    """Background worker that executes jobs from a JobQueue."""

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
        poll_interval: float = 0.1,
        on_status_change: Callable[[Job, JobStatus], None] | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.run_callable = run_callable
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self.job_queue.get_next_job()
            if job is None:
                time.sleep(self.poll_interval)
                continue
            self.job_queue.mark_running(job.job_id)
            self._notify(job, JobStatus.RUNNING)
            self._current_job = job
            self._cancel_current.clear()
            try:
                if self._cancel_current.is_set():
                    self.job_queue.mark_canc
Fixing variable confusion in pipeline controller
Oops! I mistakenly used the wrong 'data' variable, which was overwritten with single_node_runner. I'll reload pipeline_controller into a fresh variable to avoid the mix-up and ensure I’m working with the correct data. That’ll help me continue without any further confusion!

Reloading pipeline controller into variable
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    pc = z.read("src/controller/pipeline_controller.py").decode("utf-8", errors="ignore")
print(pc[:2200])

"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller."""

from __future__ import annotations

import uuid

from typing import Callable, Any

from src.controller.job_service import JobService
from src.gui.controller import PipelineController as _GUIPipelineController
from src.gui.state import StateManager
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.controller.job_execution_controller import JobExecutionController
from src.controller.queue_execution_controller import QueueExecutionController
from src.queue.job_model import JobStatus, Job, JobPriority
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.pipeline.pipeline_runner import PipelineRunResult, PipelineConfig, PipelineRunner
from src.gui.state import GUIState
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState
from src.config import app_config
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.state import PipelineState
from src.api.client import SDWebUIClient
from src.utils import StructuredLogger


class PipelineController(_GUIPipelineController):
    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower == "direct":
            return "direct"
        return "queue"

    def _build_job(
        self,
        config: PipelineConfig,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        lora_settings: dict | None = None,
        randomizer_metadata: dict | None = None,
        learning_enabled: bool = False,
    ) -> Job:
        """Build a Job with full metadata for provenance tracking
Investigating queue_execution_controller initialization
I’m scrolling a bit further to check out the initialization for queue_execution_controller and related components. It seems this part of the code might offer some important details on how everything ties together. I’ll keep looking to get the full picture and understand better!

Extracting class definition from pipeline controller code
idx = pc.index("class PipelineController")
print(pc[idx:idx+2200])

class PipelineController(_GUIPipelineController):
    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower == "direct":
            return "direct"
        return "queue"

    def _build_job(
        self,
        config: PipelineConfig,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        lora_settings: dict | None = None,
        randomizer_metadata: dict | None = None,
        learning_enabled: bool = False,
    ) -> Job:
        """Build a Job with full metadata for provenance tracking (PR-106)."""
        # Create config snapshot for auditing
        config_snapshot: dict[str, Any] = {}
        if config is not None:
            try:
                config_snapshot = {
                    "prompt": getattr(config, "prompt", ""),
                    "model": getattr(config, "model", "") or getattr(config, "model_name", ""),
                    "steps": getattr(config, "steps", None),
                    "cfg_scale": getattr(config, "cfg_scale", None),
                    "width": getattr(config, "width", None),
                    "height": getattr(config, "height", None),
                    "sampler": getattr(config, "sampler", None),
                }
            except Exception:
                config_snapshot = {}

        return Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=config,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            lora_settings=lora_settings,
            randomizer_metadata=randomizer_metadata,
            learning_enabled=learning_enabled,
        )

    def _coerce_overrides(self, overrides: GuiOverrides | dict[str, Any] | None) -> GuiOverrides:
        if isinstance(overrides, GuiOverrides):
            return overrides
Looking for __init__ function
Hmm, it looks like I’ve reached a point where I need to find the __init__ function. Let me check some of the earlier lines to see where it's defined. Getting that context will be helpful to better understand initialization and everything that follows. I'm sure I’ll find it soon!

Displaying section of code from index 2200 to 4400
print(pc[2200:4400])

 (PR-106)."""
        # Create config snapshot for auditing
        config_snapshot: dict[str, Any] = {}
        if config is not None:
            try:
                config_snapshot = {
                    "prompt": getattr(config, "prompt", ""),
                    "model": getattr(config, "model", "") or getattr(config, "model_name", ""),
                    "steps": getattr(config, "steps", None),
                    "cfg_scale": getattr(config, "cfg_scale", None),
                    "width": getattr(config, "width", None),
                    "height": getattr(config, "height", None),
                    "sampler": getattr(config, "sampler", None),
                }
            except Exception:
                config_snapshot = {}

        return Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=config,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            lora_settings=lora_settings,
            randomizer_metadata=randomizer_metadata,
            learning_enabled=learning_enabled,
        )

    def _coerce_overrides(self, overrides: GuiOverrides | dict[str, Any] | None) -> GuiOverrides:
        if isinstance(overrides, GuiOverrides):
            return overrides
        if isinstance(overrides, dict):
            return GuiOverrides(
                prompt=str(overrides.get("prompt", "")),
                model=str(overrides.get("model", "")),
                model_name=str(overrides.get("model_name", overrides.get("model", ""))),
                vae_name=str(overrides.get("vae_name", "")),
                sampler=str(overrides.get("sampler", "")),
                width=int(overrides.get("width", 512) or 512),
                height=int(overrides.get("height", 512) or 512),
                steps=int(overrides.get("steps", 20) or 20),
                cfg_scale=float(overrides.get("cfg_scale", 7.0) or 7.0),
                resolution_preset=str(overrides.get("resolution_preset", "")),
                neg
Searching for __init__ in earlier lines
I’m going to scroll up a bit to check earlier lines before the class definition. Maybe it contains the __init__ method, especially since it might be part of a compatibility wrapper or something similar. I’ll search directly for __init__( to make sure I find it quickly.

Searching for __init__ method definitions
for match in [m for m in range(len(pc)) if pc.startswith("    def __init__", m)]:
    print("init at", match)

init at 9956
Searching for __init__ method definition
print(pc[9900:10400])

ault StateManager so legacy imports keep working."""

    def __init__(
        self,
        state_manager: StateManager | None = None,
        *,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: PipelineConfigAssembler | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        api_client = kwargs.pop("api_client", N
Requesting More Context
It looks like we hit truncation and missed some essential details. I need more context to fully understand the situation. I'll go back and try to grab the missing information so I can get the full picture and provide the most accurate response.

Extracting data within specific range
print(pc[9900:11100])

ault StateManager so legacy imports keep working."""

    def __init__(
        self,
        state_manager: StateManager | None = None,
        *,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: PipelineConfigAssembler | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        api_client = kwargs.pop("api_client", None)
        job_service = kwargs.pop("job_service", None)
        structured_logger = kwargs.pop("structured_logger", None)
        pipeline_runner = kwargs.pop("pipeline_runner", None)
        
        queue_execution_controller = kwargs.pop("queue_execution_controller", None)
        webui_conn = kwargs.pop("webui_connection_controller", None)
        super().__init__(state_manager or StateManager(), **kwargs)
        self._learning_runner = None
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_learning_record: LearningRecord | None = None
        self._last_run_result: PipelineRunResul
Displaying data subset
print(pc[11100:12600])

t | None = None
        self._last_stage_execution_plan: StageExecutionPlan | None = None
        self._last_stage_events: list[dict[Any, Any]] | None = None
        self._learning_enabled: bool = False
        self._job_controller = JobExecutionController(execute_job=self._execute_job)
        self._queue_execution_controller: QueueExecutionController | None = queue_execution_controller or QueueExecutionController(job_controller=self._job_controller)
        self._queue_execution_enabled: bool = is_queue_execution_enabled()
        self._config_assembler = config_assembler if config_assembler is not None else PipelineConfigAssembler()
        self._webui_connection = webui_conn if webui_conn is not None else WebUIConnectionController()
        self._pipeline_runner = pipeline_runner
        if self._queue_execution_controller:
            try:
                self._queue_execution_controller.observe("pipeline_ctrl", self._on_queue_status)
            except Exception:
                pass
        self._job_history_service: JobHistoryService | None = None
        self._active_job_id: str | None = None
        self._last_run_config: dict[str, Any] | None = None
        self._last_run_config: dict[str, Any] | None = None
        queue = self._job_controller.get_queue()
        runner = self._job_controller.get_runner()
        history_store = self._job_controller.get_history_store()
        self._job_service = job_service if job_service is not None else Jo
Displaying data slice from array
print(pc[12600:14200])

bService(queue, runner, history_store)
        self._job_controller.set_status_callback("pipeline", self._on_job_status)

    def _get_learning_runner(self):
        if self._learning_runner is None:
            from src.learning.learning_runner import LearningRunner

            self._learning_runner = LearningRunner()
        return self._learning_runner

    def get_learning_runner_for_tests(self):
        """Return the learning runner instance for test inspection."""

        return self._get_learning_runner()

    def handle_learning_record(self, record: LearningRecord) -> None:
        """Handle learning records forwarded from pipeline runner."""

        self._last_learning_record = record
        if self._learning_record_writer and self._learning_enabled:
            try:
                append = getattr(self._learning_record_writer, "append_record", None)
                if callable(append):
                    append(record)
                else:
                    self._learning_record_writer.write(record)
            except Exception:
                pass
        if self._learning_record_callback:
            try:
                self._learning_record_callback(record)
            except Exception:
                pass

    def get_learning_record_handler(self):
        """Return a callback suitable for passing to PipelineRunner."""

        return self.handle_learning_record

    def get_last_learning_record(self) -> LearningRecord | None:
        """Return the most recent LearningRecord handled by the controller."""

 
Investigating pipeline not firing
The pipeline_controller already constructs a JobService, including the relevant components from the job_execution_controller and has the _job_service attribute. I noticed that AppController also has its own job_service, which needs verification. Also, the pipeline isn't firing for the user, so I’ll investigate both the queue_execution_controller and single_node_runner to understand why it’s not functioning as expected.

Verifying pipeline job submission process
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    qec = z.read("src/controller/queue_execution_controller.py").decode("utf-8", errors="ignore")
print(qec[:1600])

from __future__ import annotations

from typing import Callable

from src.controller.job_execution_controller import JobExecutionController
from src.queue.job_model import JobPriority


class QueueExecutionController:
    """Facade around JobExecutionController for controller/GUI usage."""

    def __init__(self, *, job_controller: JobExecutionController | None = None) -> None:
        self._job_controller = job_controller or JobExecutionController()

    def submit(self, payload_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        return self._job_controller.submit_pipeline_run(payload_callable, priority=priority)

    def submit_pipeline_job(self, payload_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        """Submit a job payload (typically a PipelineConfig) to the queue."""

        return self.submit(payload_callable, priority=priority)

    def cancel(self, job_id: str) -> None:
        self._job_controller.cancel_job(job_id)

    def cancel_job(self, job_id: str) -> None:
        """Cancel a queued/running job."""

        self.cancel(job_id)

    def observe(self, key: str, callback: Callable) -> None:
        self._job_controller.set_status_callback(key, callback)

    def clear_observer(self, key: str) -> None:
        self._job_controller.clear_status_callback(key)

    def register_status_callback(self, key: str, callback: Callable) -> None:
        self.observe(key, callback)

    def get_queue(self):
        return self._job_controller.get_queue()

    def get_history_store(self)
Exploring queue submission
I’m looking into the queue submission process to understand why pipeline isn't triggering. I’ll examine the relevant lines to track how jobs are submitted and identify any discrepancies in execution. This will help me narrow down the cause of the issue and figure out what’s missing.

Extracting queue submission code segment
idx = qec.index("def submit_pipeline_job")
print(qec[idx:idx+600])

def submit_pipeline_job(self, payload_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        """Submit a job payload (typically a PipelineConfig) to the queue."""

        return self.submit(payload_callable, priority=priority)

    def cancel(self, job_id: str) -> None:
        self._job_controller.cancel_job(job_id)

    def cancel_job(self, job_id: str) -> None:
        """Cancel a queued/running job."""

        self.cancel(job_id)

    def observe(self, key: str, callback: Callable) -> None:
        self._job_controller.set_status_callback(key, callback)

Inspecting submit_pipeline_run implementation
I’ve seen part of the implementation for submit_pipeline_run in JobExecutionController, but it’s worth taking a closer look. I want to fully understand how this method works to ensure the pipeline runs properly and to investigate where things might be going wrong in the current setup.

Inspecting JobExecutionController implementation details
print(jec[800:1800])

 None = None,
        poll_interval: float = 0.05,
        history_store: JobHistoryStore | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._history_store = history_store or self._default_history_store()
        self._worker_registry = worker_registry or WorkerRegistry()
        self._queue = JobQueue(history_store=self._history_store)
        self._execute_job = execute_job
        self._runner = SingleNodeJobRunner(
            self._queue, self._execute_job, poll_interval=poll_interval, on_status_change=self._on_status
        )
        self._started = False
        self._lock = threading.Lock()
        self._callbacks: dict[str, Callable[[Job, JobStatus], None]] = {}

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._runner.start()
                self._started = True

    def stop(self) -> None:
        with self._lock:
            if self._started:

Inspecting submit_pipeline_run implementation
start = jec.index("def submit_pipeline_run")
print(jec[start:start+800])

def submit_pipeline_run(self, pipeline_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        job_id = str(uuid.uuid4())
        worker_id = None
        try:
            worker_id = self._worker_registry.get_local_worker().id
        except Exception:
            worker_id = None
        job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
        self._queue.submit(job)
        self.start()
        return job_id

    def cancel_job(self, job_id: str) -> None:
        # Mark as cancelled so runner will skip it if not already running.
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        if job and job.status == JobStatus.QUEUED:
            job.mark_status(
Investigating pipeline controller connection issue
Okay, so pipeline_controller.start_pipeline is already set up to bridge to queue_execution_controller and job_controller. D-11's earlier assumption about missing bridging was outdated. Now, I'm wondering: If the user says the pipeline buttons still aren't working, could the issue be with AppController still using the old _run_pipeline_via_runner_only method? Or maybe run_full_pipeline isn’t properly set up in pipeline_controller? I’ll need to look at PipelineController in src/gui/controller.py to figure this out.

Inspecting pipeline controller for full pipeline execution
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    gui_ctrl = z.read("src/gui/controller.py").decode("utf-8", errors="ignore")
idx = gui_ctrl.index("class PipelineController")
print(gui_ctrl[idx:idx+1400])

class PipelineController:
    """Controls pipeline execution with cancellation support."""

    @property
    def is_terminal(self):
        return self.state_manager.current in (GUIState.IDLE, GUIState.ERROR)

    _JOIN_TIMEOUT = 5.0

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.cancel_token = CancelToken()
        self.log_queue: queue.Queue[LogMessage] = queue.Queue()

        # Worker + subprocess
        self._worker: threading.Thread | None = None
        self._pipeline = None
        self._current_subprocess: subprocess.Popen | None = None
        self._subprocess_lock = threading.Lock()

        # Cleanup & joining
        self._join_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_started = False  # per-run guard (reset at start of each pipeline run)
        self._cleanup_done = threading.Event()  # signals cleanup completed (per run)
        self._cleanup_done.set()  # no prior run on init; don't block first start

        self._stop_in_progress = False

        # Lifecycle signals
        self.lifecycle_event = threading.Event()  # terminal (IDLE/ERROR)
        self.state_change_event = threading.Event()  # pulse on change

        # Test hook
        self._sync_cleanup = False

        # Epoch
        self._epoch_lock = thre
Looking for run_full_pipeline definition
I need to search for where run_full_pipeline is defined. This will help me understand exactly what it’s doing and whether it’s properly set up or linked in the code. Once I find it, I can verify if it’s implemented in the right place or if something is missing.

Searching for run_full_pipeline definition
print("run_full_pipeline" in gui_ctrl)
start = gui_ctrl.index("def run_full_pipeline")
print(gui_ctrl[start:start+800])

False
---------------------------------------------------------------------------
ValueError                                Traceback (most recent call last)
Cell In[36], line 2
      1 print("run_full_pipeline" in gui_ctrl)
----> 2 start = gui_ctrl.index("def run_full_pipeline")
      3 print(gui_ctrl[start:start+800])

ValueError: substring not found
Checking pipeline_controller._run_pipeline_job behavior
The first line printed False, and the second line's index call failed as expected. There's no run_full_pipeline method, so the runner = getattr(self, "run_full_pipeline", None) will be None. Next, I need to check how the fallback works and confirm if it uses PipelineRunner.

Inspecting pipeline job function for fallback usage
idx = pc.index("def _run_pipeline_job")
print(pc[idx:idx+1000])

def _run_pipeline_job(
        self,
        config: PipelineConfig,
        *,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a pipeline job using the assembled config or a compatibility callable."""

        runner = getattr(self, "run_full_pipeline", None)
        if callable(runner):
            maybe_result = runner(config)
            if isinstance(maybe_result, dict):
                return maybe_result

        if pipeline_func:
            maybe_result = pipeline_func()
            if isinstance(maybe_result, dict):
                return maybe_result

        return {}

    def stop_pipeline(self) -> bool:
        """Cancel the active job."""

        if self._active_job_id:
            if self._queue_execution_enabled and self._queue_execution_controller:
                try:
                    self._queue_execution_controller.cancel_job(self._active_job_id)
                except Except
Investigating missing run_full_pipeline and bug cause
If there's no run_full_pipeline and no pipeline function given, _run_pipeline_job returns an empty dictionary, but still works from the queue’s perspective. However, it doesn’t trigger PipelineRunner, causing the pipeline to be a no-op, which matches the bug. I'll look for the definition of run_full_pipeline in the repo.

Searching for run_full_pipeline definition
[p for p in paths if "run_full_pipeline" in p]

[]
Clarifying the missing bridge between payload and PipelineRunner
It seems that run_full_pipeline was likely present in a legacy controller, but it's missing in the current snapshot. As a result, the pipeline_controller expects it to exist, but it's not found. The real issue appears to be a missing bridge between the payload callable and PipelineRunner. I’ll search for where pipeline_runner.run is called.

Searching for PipelineRunner usage in code
hits = []
for f in files:
    path = f["path"]
    if not path.endswith(".py"): 
        continue
    with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
        try:
            content = z.read(path).decode("utf-8", errors="ignore")
        except KeyError:
            continue
    if "PipelineRunner(" in content or ".run(" in content and "PipelineRunner" in content:
        if "PipelineRunner" in content:
            hits.append(path)
hits
['docs/pr_templates/PriorWork_complete/PR-0_Pipeline_Execution_Hotfix_Bundle/tests_controller_test_app_controller_pipeline_flow_pr0.py',
 'src/controller/app_controller.py',
 'src/controller/pipeline_controller.py',
 'src/pipeline/stage_models.py',
 'tests/controller/test_adetailer_stage_integration_v2.py',
 'tests/controller/test_app_controller_config.py',
 'tests/controller/test_app_controller_lora_runtime.py',
 'tests/controller/test_app_controller_pipeline_flow_pr0.py',
 'tests/controller/test_app_controller_pipeline_integration.py',
 'tests/controller/test_pipeline_randomizer_config_v2.py',
 'tests/controller/test_resource_refresh_adetailer_v2.py',
 'tests/controller/test_webui_lifecycle_ux_v2.py',
 'tests/helpers/gui_harness_v2.py',
 'tests/integration/test_end_to_end_pipeline_v2.py',
 'tests/journey/test_phase1_pipeline_journey_v2.py',
 'tests/journeys/test_v2_full_pipeline_journey.py',
 'tests/learning/test_learning_hooks_pipeline_runner.py',
 'tests/pipeline/test_pipeline_adetailer_config.py',
 'tests/pipeline/test_pipeline_io_contracts.py',
 'tests/pipeline/test_pipeline_learning_hooks.py',
 'tests/pipeline/test_pipeline_runner_cancel_token.py',
 'tests/pipeline/test_pipeline_runner_sdxl_refiner_hires.py',
 'tests/pipeline/test_pipeline_runner_variants.py',
 'tests/pipeline/test_stage_sequencer_runner_integration.py',
 'tests/pipeline/test_stage_sequencing.py']
Inspecting pipeline-related code in app_controller
I’ll open src/controller/app_controller.py to explore the pipeline-related code. This might give me the details I need to understand how it's handling the pipeline functions and where things may not be connecting properly. Let's check for relevant parts of the code in that file.

Extracting pipeline-related code from app_controller.py
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    ac = z.read("src/controller/app_controller.py").decode("utf-8", errors="ignore")
idx = ac.index("_start_run_v2")
print(ac[idx-400:idx+1000])

pend_log(f"[controller] PipelineController bridge error: {exc!r}")
            return False

    def start_run_v2(self) -> Any:
        """
        Preferred, backward-compatible entrypoint for the V2 pipeline path.

        Tries the PipelineController bridge first; on failure, falls back to legacy start_run().
        """
        self._ensure_run_mode_default("run")
        return self._start_run_v2(RunMode.DIRECT, RunSource.RUN_BUTTON)

    def _ensure_run_mode_default(self, button_source: str) -> None:
        pipeline_state = getattr(self.app_state, "pipeline_state", None)
        if pipeline_state is None:
            return
        current = (getattr(pipeline_state, "run_mode", None) or "").strip().lower()
        if current in {"direct", "queue"}:
            return
        if button_source == "run":
            pipeline_state.run_mode = "direct"
            self._append_log("[controller] Defaulting run_mode to 'direct' for Run button.")
        elif button_source == "run_now":
            pipeline_state.run_mode = "queue"
            self._append_log("[controller] Defaulting run_mode to 'queue' for Run Now button.")
        elif button_source == "add_to_queue":
            pipeline_state.run_mode = "queue"
            self._append_log("[controller] Defaulting run_mode to 'queue' for Add to Queue button.")

    def _build_run_config(self, mode: RunMode, sou
Extracting pipeline-related code from app_controller.py
print(ac[idx+1000:idx+2200])

rce: RunSource) -> RunConfigDict:
        cfg: RunConfigDict = {"run_mode": mode.value, "source": source.value}
        prompt_source = "manual"
        prompt_pack_id = ""
        job_draft = getattr(self.app_state, "job_draft", None)
        if job_draft is not None:
            pack_id = getattr(job_draft, "pack_id", "") or ""
            if pack_id:
                prompt_source = "pack"
                prompt_pack_id = pack_id
        cfg["prompt_source"] = prompt_source
        if prompt_pack_id:
            cfg["prompt_pack_id"] = prompt_pack_id
        pipeline_state = getattr(self.app_state, "pipeline_state", None)
        if pipeline_state is not None:
            snapshot = {
                "run_mode": getattr(pipeline_state, "run_mode", None),
                "stage_txt2img_enabled": getattr(pipeline_state, "stage_txt2img_enabled", None),
                "stage_img2img_enabled": getattr(pipeline_state, "stage_img2img_enabled", None),
                "stage_upscale_enabled": getattr(pipeline_state, "stage_upscale_enabled", None),
                "stage_adetailer_enabled": getattr(pipeline_state, "stage_adetailer_enabled", None),
            }
            cfg["pipeline_s
Examining pipeline-related code in app_controller.py
idx2 = ac.index("def _start_run_v2")
print(ac[idx2:idx2+800])

def _start_run_v2(self, mode: RunMode, source: RunSource) -> Any:
        pipeline_state = getattr(self.app_state, "pipeline_state", None)
        if pipeline_state is not None:
            try:
                pipeline_state.run_mode = mode.value
            except Exception:
                pass
        run_config = self._build_run_config(mode, source)
        controller = getattr(self, "pipeline_controller", None)
        if controller is not None:
            start_fn = getattr(controller, "start_pipeline", None)
            if callable(start_fn):
                try:
                    self._append_log(
                        f"[controller] _start_run_v2 via PipelineController.start_pipeline "
                        f"(mode={mode.value}, source={source.value})"
                    
Displaying pipeline-related code snippet
print(ac[idx2+800:idx2+1600])

)
                    return start_fn(run_config=run_config)
                except TypeError:
                    self._append_log(
                        "[controller] PipelineController.start_pipeline does not accept run_config; calling without it."
                    )
                    return start_fn()
                except Exception as exc:  # noqa: BLE001
                    self._append_log(f"[controller] _start_run_v2 bridge error: {exc!r}")
        self._append_log("[controller] _start_run_v2 falling back to legacy start_run().")
        legacy = getattr(self, "start_run", None)
        if callable(legacy):
            return legacy()
        return None

    def on_run_job_now_v2(self) -> Any:
        """
        V2 entrypoint for "Run Now": prefer the queue-backed hand
Investigating pipeline_controller connection to PipelineRunner
AppController passes run_config but not pipeline_func to pipeline_controller.start_pipeline. We see that start_pipeline initializes the config and calls _run_pipeline_job, which should use PipelineRunner but doesn’t, because run_full_pipeline is missing. We need to search for where PipelineRunner is created in app_controller.

Identifying missing PipelineRunner integration
"PipelineRunner(" in ac
True
Identifying missing PipelineRunner integration step
start = ac.index("PipelineRunner(")
print(ac[start-200:start+400])

ogger()
        else:
            self._api_client = api_client or SDWebUIClient()
            self._structured_logger = structured_logger or StructuredLogger()
            self.pipeline_runner = PipelineRunner(self._api_client, self._structured_logger)

        self._webui_api: WebUIAPI | None = None

        client = getattr(self, "_api_client", None)
        self.resource_service = resource_service or WebUIResourceService(client=client)
        self.state.resources = self._empty_resource_map()
        self.webui_process_manager = webui_process_manager
        self._cancel_token:
Analyzing PipelineRunner initialization in AppController
AppController owns the PipelineRunner instance as self.pipeline_runner. In PipelineController, the __init__ method gets pipeline_runner passed in, storing it as self._pipeline_runner. I need to check if AppController is passing pipeline_runner when constructing PipelineController. I'll inspect that part.

Inspecting PipelineController instantiation in AppController
idx = ac.index("PipelineController(")
print(ac[idx-200:idx+400])

]
        self._selected_pack_index: Optional[int] = None

        # Initialize PipelineController for modern pipeline execution (bridge)
        self.pipeline_controller = pipeline_controller or PipelineController(
            api_client=self._api_client,
            structured_logger=self._structured_logger,
            job_service=self.job_service,
            pipeline_runner=self.pipeline_runner,
        )

        # GUI log handler for LogTracePanelV2
        self.gui_log_handler = InMemoryLogHandler(max_entries=500, level=logging.INFO)
        root_logger = logging.getLogger
Implementing _run_pipeline_job with _pipeline_runner
The pipeline_controller receives the pipeline_runner instance, but currently, it doesn’t use _pipeline_runner. The pull request should implement _run_pipeline_job to call self._pipeline_runner.run(config, cancel_token, log_cb), or something similar. I need to check the pipeline_runner API to make sure it’s aligned.

Analyzing pipeline_runner API usage
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    pr = z.read("src/pipeline/pipeline_runner.py").decode("utf-8", errors="ignore")
print(pr[:1600])

"""Production pipeline runner integration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from uuid import uuid4
import logging

from src.api.client import SDWebUIClient
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.learning_record_builder import build_learning_record
from src.learning.run_metadata import write_run_metadata
from src.gui.state import CancellationError
from src.pipeline.executor import Pipeline, PipelineStageError
from src.pipeline.payload_builder import build_sdxl_payload
from src.pipeline.stage_sequencer import (
    StageExecution,
    StageExecutionPlan,
    StageMetadata,
    StageSequencer,
    StageTypeEnum,
    build_stage_execution_plan,
)
from src.pipeline.stage_models import InvalidStagePlanError
from src.utils import StructuredLogger, get_logger, LogContext, log_with_ctx
from src.utils.config import ConfigManager

if TYPE_CHECKING:  # pragma: no cover
    from src.controller.app_controller import CancelToken


@dataclass
class PipelineConfig:
    """Controller-facing configuration passed into the pipeline runner."""

    prompt: str
    model: str
    sampler: str
    width: int
    height: int
    steps: int
    cfg_scale: float
    negative_prompt: str = ""
    pack_name: Optional[str] = None
    preset_name: Optional[str] = None
    variant_configs: Optional[List[dict[str, Any]]] = None
    randomizer_mode: Optional[str] = None
    randomizer_
Checking pipeline_runner API for usage
idx = pr.index("class PipelineRunner")
print(pr[idx:idx+800])

class PipelineRunner:
    """
    Adapter that drives the real multi-stage Pipeline executor.
    """

    def run_txt2img_once(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Minimal V2.5 happy path: run txt2img once and return result dict.
        """
        ctx = LogContext(subsystem="pipeline")
        log_with_ctx(get_logger(__name__), logging.INFO, "Starting txt2img once", ctx=ctx)
        # Build minimal payload for txt2img
        payload = {
            "prompt": config.get("prompt", "A beautiful landscape, trending on artstation"),
            "negative_prompt": config.get("negative_prompt", ""),
            "steps": config.get("steps", 20),
            "cfg_scale": config.get("cfg_scale", 7.0),
            "width": config.get("width", 512),
            "hei
Looking for the generic run entrypoint
I need to find the generic entry point for the run function. This will help ensure that I properly integrate and implement the call within the appropriate context. Once I have that, I’ll be able to link it in the right way with the rest of the system.

Defining generic run entrypoint
"def run(" in pr
True
Identifying run method signatures
# print function signatures for methods named run
for line in pr.splitlines():
    if line.strip().startswith("def run("):
        print(line)

    def run(
Finding run function entrypoint
idx = pr.index("def run(")
print(pr[idx:idx+600])

def run(
        self,
        config: PipelineConfig,
        cancel_token: "CancelToken",
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> "PipelineRunResult":
        """Execute the full pipeline using the provided configuration."""

        if log_fn:
            log_fn("[pipeline] PipelineRunner starting execution.")

        executor_config = self._build_executor_config(config)
        prompt = config.prompt.strip() or config.pack_name or config.preset_name or "StableNew GUI Run"
        run_name = config.pack_name or config.preset_name or "stable_new_session"
        suc
Connecting PipelineRunner and learning hooks
The PipelineRunner.run expects a PipelineConfig dataclass, which is presumably returned by pipeline_controller._build_pipeline_config_from_state—great, that part works. But _run_pipeline_job isn’t using run yet. I need to bridge that gap and integrate the learning hooks (_learning_enabled, _get_learning_runner). I'll also check tests for any existing connections.

Searching for _pipeline_runner usage in pipeline_controller
"_pipeline_runner" in pc
True
Searching for _pipeline_runner usage in pipeline_controller
for line in pc.splitlines():
    if "_pipeline_runner" in line:
        print(line)

        self._pipeline_runner = pipeline_runner
        if self._pipeline_runner is not None:
            result = self._pipeline_runner.run(config, self.cancel_token)
Inspecting surrounding code
I think that second line is likely nested inside another function, so I should check the surrounding code to understand its context better. By doing that, I can clarify its purpose and how it fits into the overall structure. Let's take a closer look at the code around it.

Inspecting code around specific function call
idx = pc.index("self._pipeline_runner.run")
print(pc[idx-200:idx+400])

 def run_pipeline(self, config: PipelineConfig) -> PipelineRunResult:
        """Run pipeline synchronously and return result."""
        if self._pipeline_runner is not None:
            result = self._pipeline_runner.run(config, self.cancel_token)
        else:
            api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
            result = runner.run(config, self.cancel_token)
        self.record_run_result(result)
        return result

    def get_
Adjusting for pipeline run and results
Okay, so pipeline_controller has a run_pipeline method that uses _pipeline_runner or builds a new one. Currently, _run_pipeline_job uses run_full_pipeline and pipeline_func, but I can adjust that to call run_pipeline instead or redefine run_full_pipeline to call run_pipeline. I'll need to check how to handle the return type and ensure it fits the expected UI format. Also, I should inspect the record_run_result method to understand how to convert the PipelineRunResult to a dict.

Inspecting run_pipeline and PipelineRunResult structure
idx = pc.index("def run_pipeline")
print(pc[idx:idx+800])

def run_pipeline(self, config: PipelineConfig) -> PipelineRunResult:
        """Run pipeline synchronously and return result."""
        if self._pipeline_runner is not None:
            result = self._pipeline_runner.run(config, self.cancel_token)
        else:
            api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
            result = runner.run(config, self.cancel_token)
        self.record_run_result(result)
        return result

    def get_job_history_service(self) -> JobHistoryService | None:
        """Return a JobHistoryService bound to this controller's queue/history."""

        if self._job_history_service is None:
            
Reviewing record_run_result functionality
I need to check the record_run_result method, and possibly the as_dict method, to ensure I'm handling the data properly. This will help me understand how to convert the PipelineRunResult into a format suitable for the expected output, especially for the UI.

Locating record_run_result function definition
idx = pc.index("def record_run_result")
print(pc[idx:idx+1000])

def record_run_result(self, result: PipelineRunResult) -> None:
        """Record the last PipelineRunResult for inspection by higher layers/tests."""

        self._last_run_result = result
        self._last_stage_events = getattr(result, "stage_events", None)

    def get_last_run_result(self) -> PipelineRunResult | None:
        """Return the most recent PipelineRunResult recorded on this controller."""

        return self._last_run_result

    def validate_stage_plan(self, config: dict) -> StageExecutionPlan:
        """Build and store a stage execution plan for testing/inspection."""

        plan = build_stage_execution_plan(config)
        self._last_stage_execution_plan = plan
        return plan

    def get_last_stage_execution_plan_for_tests(self) -> StageExecutionPlan | None:
        """Return the most recent StageExecutionPlan built by this controller."""

        return self._last_stage_execution_plan

    def get_last_run_config_for_tests(self) -
Evaluating the need for dict conversion in pipeline results
It seems that we may not need to convert PipelineRunResult to a dictionary, as start_pipeline currently treats it as a dict. However, I could adjust _run_pipeline_job to convert it if needed for UI and tests, though tests may expect it as a dict. I should check tests/controller/test_app_controller_pipeline_flow_pr0.py for more details on expectations.

Inspecting test expectations for pipeline result format
with zipfile.ZipFile("/mnt/data/StableNew-snapshot-20251203-231300.zip","r") as z:
    tflow = z.read("tests/controller/test_app_controller_pipeline_flow_pr0.py").decode("utf-8", errors="ignore")
print(tflow[:1600])

"""Tests for PR-0: AppController ⇄ PipelineRunner flow.

These tests are intentionally focused and should be created FIRST (TDD).
They assume the presence of:

- src.gui.main_window_v2.MainWindow
- src.controller.app_controller.AppController, LifecycleState
- src.controller.pipeline_runner.PipelineRunner (Protocol-like)
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

import pytest

from src.controller.app_controller import AppController, LifecycleState
from src.gui.main_window_v2 import MainWindow
from tests.helpers.factories import make_run_config


class FakePipelineRunner:
    """A simple fake implementing the PipelineRunner.run API for tests."""

    def __init__(self, should_raise: bool = False, simulate_long_run: bool = False) -> None:
        self.should_raise = should_raise
        self.simulate_long_run = simulate_long_run
        self.run_calls: list[dict[str, Any]] = []

    def run(self, config, cancel_token, log_fn: Callable[[str], None] | None = None) -> None:  # noqa: D401
        """Record the call and optionally raise or simulate work."""
        self.run_calls.append(
            {
                "config": config,
                "cancel_token": cancel_token,
            }
        )
        log_fn("[fake] pipeline started")
        if self.simulate_long_run:
            cancel_token.require_stop_to_finish()
        if self.should_raise:
            raise RuntimeError("Fake pipeline error")
        if self.simulate_long_run:
            # Instead of actually sleeping, 
Looking for 'start_run_v2' usage in app_controller
I need to find where start_run_v2 is used in the app_controller. Let me scroll through the code to locate this so I can understand its context and how it's being utilized. This will help guide the next steps needed for adjustments or improvements.

Locating usage of start_run_v2 method
idx = tflow.index("def test_start_run_v2")
print(tflow[idx:idx+1200])
