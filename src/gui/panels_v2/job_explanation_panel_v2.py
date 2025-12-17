"""Job Explanation panel for the Debug Hub."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read JSON from %s", path)
        return None


class JobExplanationPanelV2(tk.Toplevel):
    """Explain a job by summarizing its metadata, prompts, and manifests."""

    def __init__(
        self,
        job_id: str,
        *,
        master: tk.Misc | None = None,
        base_runs_dir: Path | None = None,
    ) -> None:
        self.job_id = job_id
        self._base_dir = base_runs_dir or Path("runs")
        self._run_dir = self._base_dir / job_id
        super().__init__(master or self._resolve_master())
        self.title(f"Explain job {job_id}")
        self.geometry("860x620")
        self.minsize(640, 480)
        self._protocol = self.protocol("WM_DELETE_WINDOW", self.destroy)

        container = ttk.Frame(self, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=tk.X)
        ttk.Label(header, text=f"Job {job_id}", font=("TkDefaultFont", 12, "bold")).pack(
            side=tk.LEFT
        )
        ttk.Button(header, text="Open Run Folder", command=self._open_run_folder).pack(
            side=tk.RIGHT
        )

        self._origin_frame = ttk.LabelFrame(container, text="Job Origin")
        self._origin_frame.pack(fill=tk.X, pady=(8, 8))
        self._origin_text = ttk.Label(self._origin_frame, text="Loading...")
        self._origin_text.pack(fill=tk.X, padx=8, pady=4)

        stage_frame = ttk.LabelFrame(container, text="Stage Prompts")
        stage_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        columns = ("stage", "prompt", "negative", "global_terms", "status")
        self.stage_tree = ttk.Treeview(stage_frame, columns=columns, show="headings", height=6)
        for col, label in [
            ("stage", "Stage"),
            ("prompt", "Prompt"),
            ("negative", "Negative"),
            ("global_terms", "Global Negative Terms"),
            ("status", "Status"),
        ]:
            self.stage_tree.heading(col, text=label)
            self.stage_tree.column(
                col, width=120 if col in {"stage", "status"} else 220, anchor=tk.W
            )
        self.stage_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        flow_frame = ttk.LabelFrame(container, text="Stage Flow")
        flow_frame.pack(fill=tk.X, pady=(0, 8))
        self._stage_flow_label = ttk.Label(flow_frame, text="")
        self._stage_flow_label.pack(anchor=tk.W, padx=8, pady=4)

        metadata_frame = ttk.LabelFrame(container, text="Config Snapshot")
        metadata_frame.pack(fill=tk.BOTH, expand=True)
        self._metadata_text = tk.Text(metadata_frame, height=6, wrap=tk.NONE)
        self._metadata_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._metadata_text.configure(state=tk.DISABLED)

        self._load_data()

    def _resolve_master(self) -> tk.Misc:
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
        return root

    def _load_data(self) -> None:
        run_metadata = _read_json(self._run_dir / "run_metadata.json")
        if not run_metadata:
            self._origin_text.config(text="Run metadata not found.")
            self.stage_tree.insert("", "end", values=("?", "Missing metadata", "", "", "missing"))
            self._stage_flow_label.config(text="Stages unknown")
            return

        packs = run_metadata.get("packs") or []
        if packs:
            origin = "; ".join(
                f"{item.get('pack_name', 'unknown')} (stage={item.get('used_for_stage', 'txt2img')})"
                for item in packs
            )
        else:
            origin = "Manual prompt / direct entry"
        self._origin_text.config(text=f"Source: {origin}")

        config = run_metadata.get("config") or {}
        prompt_source = run_metadata.get("one_click_action") or "Manual"
        if prompt_source:
            origin += f" | Prompt source: {prompt_source}"
        self._fill_stage_flow(run_metadata)
        self._populate_metadata(config)
        self._populate_stage_prompts(run_metadata, config)

    def _populate_stage_prompts(self, run_metadata: dict[str, Any], config: dict[str, Any]) -> None:
        manifest_templates = [
            ("txt2img", "txt2img_01.json"),
            ("img2img", "img2img_01.json"),
            ("upscale", "upscale_01.json"),
        ]
        self.stage_tree.delete(*self.stage_tree.get_children())
        stages_present: list[str] = []
        for stage_name, filename in manifest_templates:
            manifest = _read_json(self._run_dir / filename)
            prompt = (
                manifest.get("final_prompt")
                if manifest
                else run_metadata.get("config", {}).get("prompt", "")
            )
            negative = (
                manifest.get("final_negative_prompt")
                if manifest
                else config.get("negative_prompt", "")
            )
            global_terms = manifest.get("global_negative_terms", "") if manifest else ""
            status = "available" if manifest else "missing"
            stages_present.append(stage_name)
            self.stage_tree.insert(
                "",
                "end",
                values=(
                    stage_name,
                    prompt or "-",
                    negative or "-",
                    global_terms or "-",
                    status,
                ),
            )
        flow_text = " → ".join(stages_present) or "No stages recorded"
        self._stage_flow_label.config(text=flow_text)

    def _fill_stage_flow(self, run_metadata: dict[str, Any]) -> None:
        outputs = run_metadata.get("stage_outputs") or []
        names = [entry.get("stage") for entry in outputs if entry.get("stage")]
        if names:
            self._stage_flow_label.config(text=" → ".join(names))
        else:
            self._stage_flow_label.config(text="txt2img → img2img → upscale")

    def _populate_metadata(self, config: dict[str, Any]) -> None:
        self._metadata_text.config(state=tk.NORMAL)
        self._metadata_text.delete("1.0", tk.END)
        payload = json.dumps(config, indent=2, ensure_ascii=False)
        self._metadata_text.insert(tk.END, payload)
        self._metadata_text.config(state=tk.DISABLED)

    def _open_run_folder(self) -> None:
        if not self._run_dir.exists():
            return
        try:
            if self.tk.call("tk", "windowingsystem") == "aqua":
                subprocess.run(["open", str(self._run_dir)], check=False)
            elif sys.platform == "win32":
                os.startfile(str(self._run_dir))
            else:
                subprocess.run(["xdg-open", str(self._run_dir)], check=False)
        except Exception:
            pass
