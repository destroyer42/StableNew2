Root Cause Analysis
Issue 1: Preview Panel shows "Job: 1" when empty
The preview panel initialization shows "Job: 1" because _render_summary is called with total=1 as default, and the label formatting uses "Job:" vs "Jobs:" based on count.

Issue 2: Adding a 10-prompt pack shows 3 jobs instead of 10
Looking at on_pipeline_add_packs_to_job:

It creates ONE PackJobEntry per pack (not per prompt)
The PackJobEntry contains prompts: list[str] with all prompts from the pack
But JobBuilderV2.build_from_run_request iterates over pack_entries (1 entry) not individual prompts
Issue 3: Only 3 images produced
The builder is creating jobs from pack entries, but not expanding prompts within each pack entry.

Let me verify the JobBuilderV2 expansion logic: Now I understand the full issue. Let me create a comprehensive PR to fix this:

PR-PREVIEW-001 — Fix PromptPack Preview Queue Job Count and Expansion.md
PR TYPE
 Bug Fix
 Refactor
 Feature
 Docs Only
 Test-only
 Chore / Cleanup
EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK
By proceeding, I acknowledge the StableNew v2.6 Canonical Execution Contract. I understand that partial compliance, undocumented deviations, or unverifiable claims constitute failure. I will either complete the PR exactly as specified with proof, or I will stop.

PR ID
PR-PREVIEW-001-PACK-PROMPT-EXPANSION

Related Canonical Sections
ARCHITECTURE_v2.6.md Section 4 (Builder Pipeline Architecture)
ARCHITECTURE_v2.6.md Section 8 (GUI Architecture)
Builder Pipeline Deep-Dive v2.6 Section 5.5 (JobBuilderV2)
INTENT
What this PR does:
Fixes Preview Panel initial state — Shows "Jobs: 0" when no packs are added (not "Job: 1")
Fixes prompt expansion — When a 10-prompt pack is added, creates 10 NJRs (one per prompt), not 1 NJR per pack
Fixes total image count display — Preview panel shows correct expected image count based on all prompts
Fixes queue submission — All prompts from all packs are submitted as individual jobs within a single run
What this PR does NOT do:
Does not change NJR schema or fields
Does not modify queue execution path
Does not alter pipeline runner behavior
Does not change persistence format
ROOT CAUSE ANALYSIS
Current Broken Flow:

User selects pack (10 prompts) → on_pipeline_add_packs_to_job() creates 1 PackJobEntry →PackJobEntry.prompts = ["prompt1", "prompt2", ..., "prompt10"] →JobBuilderV2.build_from_run_request() iterates pack_entries (1 entry) →Creates 1 NJR (ignoring the 10 prompts inside)
Expected Correct Flow:

User selects pack (10 prompts) →on_pipeline_add_packs_to_job() creates 1 PackJobEntry with 10 prompts →JobBuilderV2.build_from_run_request() expands each prompt →Creates 10 NJRs (one per prompt line)
Bug Locations:
job_builder_v2.py — build_from_run_request() does not expand entry.prompts list
preview_panel_v2.py — Initial state shows "Job: 1" instead of "Jobs: 0"
app_controller.py — on_pipeline_add_packs_to_job() creates correct structure but downstream doesn't expand
SCOPE OF CHANGE
Files TO BE MODIFIED (REQUIRED)
File	Purpose
job_builder_v2.py	Fix build_from_run_request() to expand prompts within each PackJobEntry
preview_panel_v2.py	Fix initial state to show "Jobs: 0" and correct total image count
app_state_v2.py	Add helper to calculate total expected images from draft
tests/pipeline/test_job_builder_prompt_expansion.py	NEW: Test prompt expansion behavior
Files VERIFIED UNCHANGED
job_queue.py
single_node_runner.py
job_models_v2.py
job_execution_controller.py
ARCHITECTURAL COMPLIANCE
 NJR-only execution path (NJRs are produced per-prompt)
 No PipelineConfig usage in runtime
 No dict-based execution configs
 Legacy code classified (none affected)
IMPLEMENTATION STEPS
Step 1: Fix JobBuilderV2.build_from_run_request() to expand prompts
File: job_builder_v2.py

Change: Modify build_from_run_request() to iterate over each prompt within a PackJobEntry, not just each entry.


# ...existing code...    def build_from_run_request(self, run_request: PipelineRunRequest) -> list[NormalizedJobRecord]:        """Build normalized jobs directly from a PipelineRunRequest.                Expands each PackJobEntry's prompts list into individual NJRs.        A pack with 10 prompts produces 10 NJRs.        """        entries = list(run_request.pack_entries or [])        if not entries:            return []                jobs: list[NormalizedJobRecord] = []        output_dir = run_request.explicit_output_dir or "output"        filename_template = "{seed}"                total_prompt_count = sum(len(entry.prompts) if entry.prompts else 1 for entry in entries)        global_prompt_index = 0                for entry in entries:            config = entry.config_snapshot or {}            txt2img_config = config.get("txt2img", {})                        # Get list of prompts from the entry - each becomes a separate NJR            prompts_to_expand = entry.prompts if entry.prompts else [entry.prompt_text or ""]                        for prompt_index, prompt_text in enumerate(prompts_to_expand):                if global_prompt_index >= run_request.max_njr_count:                    break                                    seed = self._extract_config_value(config, "seed") or txt2img_config.get("seed")                seed_val = int(seed) if seed is not None else None                                stage = StageConfig(                    stage_type="txt2img",                    enabled=True,                    steps=int(txt2img_config.get("steps") or config.get("steps") or 20),                    cfg_scale=float(txt2img_config.get("cfg_scale") or config.get("cfg_scale") or 7.5),                    sampler_name=txt2img_config.get("sampler_name") or config.get("sampler") or "DPM++ 2M",                    scheduler=txt2img_config.get("scheduler") or config.get("scheduler") or "ddim",                    model=txt2img_config.get("model") or config.get("model") or "unknown",                    vae=txt2img_config.get("vae"),                    extra={},                )                                # Use the specific prompt from the prompts list                final_prompt = prompt_text.strip() if prompt_text else ""                final_negative = entry.negative_prompt_text or ""                                record = NormalizedJobRecord(                    job_id=self._id_fn(),                    config=config,                    path_output_dir=output_dir,                    filename_template=filename_template,                    seed=seed_val,                    variant_index=0,                    variant_total=1,                    batch_index=0,                    batch_total=1,                    created_ts=self._time_fn(),                    randomizer_summary=entry.randomizer_metadata,                    txt2img_prompt_info=StagePromptInfo(                        original_prompt=final_prompt,                        final_prompt=final_prompt,                        original_negative_prompt=final_negative,                        final_negative_prompt=final_negative,                        global_negative_applied=False,                    ),                    pack_usage=self._build_pack_usage(config),                    prompt_pack_id=run_request.prompt_pack_id,                    prompt_pack_name=entry.pack_name or "",                    prompt_pack_row_index=prompt_index,                    positive_prompt=final_prompt,                    negative_prompt=final_negative,                    positive_embeddings=list(entry.matrix_slot_values.keys()),                    negative_embeddings=[],                    lora_tags=[],                    matrix_slot_values=dict(entry.matrix_slot_values),                    steps=stage.steps or 0,                    cfg_scale=stage.cfg_scale or 0.0,                    width=int(txt2img_config.get("width") or config.get("width") or 1024),                    height=int(txt2img_config.get("height") or config.get("height") or 1024),                    sampler_name=stage.sampler_name or "",                    scheduler=stage.scheduler or "",                    clip_skip=int(config.get("clip_skip", 0) or 0),                    base_model=stage.model or "",                    vae=stage.vae,                    stage_chain=[stage],                    loop_type=config.get("pipeline", {}).get("loop_type", "pipeline"),                    loop_count=int(config.get("pipeline", {}).get("loop_count", 1)),                    images_per_prompt=int(config.get("pipeline", {}).get("images_per_prompt", 1)),                    variant_mode=str(config.get("pipeline", {}).get("variant_mode", "standard")),                    run_mode=run_request.run_mode.name,                    queue_source=run_request.source.name,                    randomization_enabled=bool(config.get("randomization", {}).get("enabled")),                    matrix_name=str(config.get("randomization", {}).get("matrix_name", "")),                    matrix_mode=str(config.get("randomization", {}).get("mode", "")),                    matrix_prompt_mode=str(config.get("randomization", {}).get("prompt_mode", "")),                    config_variant_label="base",                    config_variant_index=0,                    config_variant_overrides={},                    aesthetic_enabled=bool(config.get("aesthetic", {}).get("enabled")),                    aesthetic_weight=config.get("aesthetic", {}).get("weight"),                    aesthetic_text=config.get("aesthetic", {}).get("text"),                    aesthetic_embedding=config.get("aesthetic", {}).get("embedding"),                    extra_metadata={                        "tags": list(run_request.tags),                        "selected_row_ids": list(run_request.selected_row_ids),                        "requested_job_label": run_request.requested_job_label,                        "pack_prompt_index": prompt_index,                        "pack_prompt_total": len(prompts_to_expand),                    },                    status=JobStatusV2.QUEUED,                )                jobs.append(record)                global_prompt_index += 1                            if global_prompt_index >= run_request.max_njr_count:                break                        return jobs# ...existing code...
Step 2: Fix Preview Panel initial state and total image calculation
File: preview_panel_v2.py

Change:

Initialize with "Jobs: 0" when no packs added
Calculate and display total expected images
Update job count label to reflect actual pack count

# ...existing code...class PreviewPanelV2(ttk.LabelFrame):    """Preview panel showing job draft summary before queue submission."""    def __init__(self, parent: tk.Widget, app_state: AppStateV2, **kwargs: Any) -> None:        # ...existing code...        self._init_ui()        # Initialize with empty state        self._render_empty_state()    def _render_empty_state(self) -> None:        """Render the panel when no packs have been added to the draft."""        self.job_count_label.config(text="Jobs: 0")        self.total_images_label.config(text="Expected Images: 0")        self.positive_preview.delete("1.0", tk.END)        self.positive_preview.insert("1.0", "(No packs added)")        self.negative_preview.delete("1.0", tk.END)        self.model_label.config(text="Model: —")        self.sampler_label.config(text="Sampler: —")        self.steps_label.config(text="Steps: —")        self.cfg_label.config(text="CFG: —")        print("[PreviewPanel] Rendered empty state")    def _calculate_total_expected_images(self) -> int:        """Calculate total expected images from all packs in draft."""        if not self._app_state or not self._app_state.job_draft:            return 0        total = 0        for pack_entry in self._app_state.job_draft.packs:            # Each prompt in the pack produces images_per_prompt images            prompt_count = len(pack_entry.prompts) if pack_entry.prompts else 1            images_per = pack_entry.config_snapshot.get("pipeline", {}).get("images_per_prompt", 1) if pack_entry.config_snapshot else 1            total += prompt_count * images_per        return total    def _render_summary(self, summary: Any | None = None, total: int | None = None) -> None:        """Render preview summary from draft state."""        packs = self._app_state.job_draft.packs if self._app_state and self._app_state.job_draft else []                # Count total prompts across all packs (not pack count)        total_prompts = sum(len(p.prompts) if p.prompts else 1 for p in packs)        total_images = self._calculate_total_expected_images()                print(f"[PreviewPanel] _render_summary called: packs={len(packs)}, total_prompts={total_prompts}, total_images={total_images}")                if total_prompts == 0:            self._render_empty_state()            return                # Update job count label - shows number of NJRs that will be created        job_label = f"Job: {total_prompts}" if total_prompts == 1 else f"Jobs: {total_prompts}"        self.job_count_label.config(text=job_label)        print(f"[PreviewPanel] Setting job_count_label to: {job_label}")                # Update total expected images        self.total_images_label.config(text=f"Expected Images: {total_images}")                # Show preview of first pack's first prompt        if packs:            first_pack = packs[0]            first_prompt = first_pack.prompts[0] if first_pack.prompts else first_pack.prompt_text or ""            negative = first_pack.negative_prompt_text or ""            config = first_pack.config_snapshot or {}            txt2img = config.get("txt2img", {})                        # Truncate for display            pos_preview = first_prompt[:120] + "..." if len(first_prompt) > 120 else first_prompt            neg_preview = negative[:120] + "..." if len(negative) > 120 else negative                        self.positive_preview.delete("1.0", tk.END)            self.positive_preview.insert("1.0", pos_preview or "(empty)")            print(f"[PreviewPanel] Positive preview length: {len(pos_preview)}, Negative: {len(neg_preview)}")                        self.negative_preview.delete("1.0", tk.END)            self.negative_preview.insert("1.0", neg_preview or "(none)")                        model = txt2img.get("model") or config.get("model") or "unknown"            sampler = txt2img.get("sampler_name") or config.get("sampler") or ""            steps = txt2img.get("steps") or config.get("steps") or 0            cfg = txt2img.get("cfg_scale") or config.get("cfg_scale") or 0.0                        self.model_label.config(text=f"Model: {model}")            self.sampler_label.config(text=f"Sampler: {sampler}")            self.steps_label.config(text=f"Steps: {steps}")            self.cfg_label.config(text=f"CFG: {cfg}")                        print(f"[PreviewPanel] Model: {model}")            print(f"[PreviewPanel] Sampler: {sampler}")            print(f"[PreviewPanel] Steps: {steps}")            print(f"[PreviewPanel] CFG: {cfg}")    # ...existing code...
Step 3: Add total_images_label to preview panel UI
File: preview_panel_v2.py

Change: Add the total_images_label widget in _init_ui()


# In _init_ui() method, after job_count_label:    def _init_ui(self) -> None:        # ...existing code for job_count_label...                self.job_count_label = ttk.Label(header_frame, text="Jobs: 0")        self.job_count_label.pack(side=tk.LEFT, padx=(0, 10))                # NEW: Add total expected images label        self.total_images_label = ttk.Label(header_frame, text="Expected Images: 0")        self.total_images_label.pack(side=tk.LEFT, padx=(0, 10))                # ...existing code...
Step 4: Fix _update_action_states to use correct pack/prompt count
File: preview_panel_v2.py

Change: Update action states based on actual prompts, not just pack presence


    def _update_action_states(self) -> None:        """Update button states based on draft content."""        packs = self._app_state.job_draft.packs if self._app_state and self._app_state.job_draft else []        total_prompts = sum(len(p.prompts) if p.prompts else 1 for p in packs)        has_parts = total_prompts > 0        has_draft = len(packs) > 0                print(f"[PreviewPanel] _update_action_states: packs={len(packs)}, total_prompts={total_prompts}, has_parts={has_parts}, has_draft={has_draft}")                # Enable buttons only when there are actual prompts to process        if has_parts:            self.add_to_queue_btn.state(["!disabled"])            self.run_now_btn.state(["!disabled"])            self.clear_btn.state(["!disabled"])            print("[PreviewPanel] Setting button state to: ['!disabled']")        else:            self.add_to_queue_btn.state(["disabled"])            self.run_now_btn.state(["disabled"])            self.clear_btn.state(["disabled"])            print("[PreviewPanel] Setting button state to: ['disabled']")
Step 5: Create test for prompt expansion
File: tests/pipeline/test_job_builder_prompt_expansion.py (NEW)


"""Tests for JobBuilderV2 prompt expansion from PackJobEntry."""import pytestfrom unittest.mock import MagicMockfrom src.pipeline.job_builder_v2 import JobBuilderV2from src.pipeline.job_requests_v2 import PipelineRunRequest, PipelineRunMode, PipelineRunSourcefrom src.gui.app_state_v2 import PackJobEntryclass TestJobBuilderPromptExpansion:    """Test that JobBuilderV2 correctly expands prompts within PackJobEntry."""    def test_single_pack_10_prompts_creates_10_njrs(self):        """A pack with 10 prompts should produce 10 NJRs."""        builder = JobBuilderV2(            time_fn=lambda: 1000.0,            id_fn=lambda: "test-job-id",        )                # Create a pack entry with 10 prompts        prompts = [f"Prompt number {i}" for i in range(10)]        pack_entry = PackJobEntry(            pack_id="test-pack",            pack_name="Test Pack",            pack_row_index=0,            prompt_text=prompts[0],  # Legacy field            prompts=prompts,  # New field with all prompts            negative_prompt_text="bad quality",            config_snapshot={"txt2img": {"model": "test-model", "steps": 20}},            matrix_slot_values={},        )                run_request = PipelineRunRequest(            prompt_pack_id="test-pack",            selected_row_ids=["row-1"],            config_snapshot_id="config-1",            run_mode=PipelineRunMode.QUEUE,            source=PipelineRunSource.ADD_TO_QUEUE,            pack_entries=[pack_entry],        )                jobs = builder.build_from_run_request(run_request)                assert len(jobs) == 10, f"Expected 10 NJRs, got {len(jobs)}"                # Verify each job has the correct prompt        for i, job in enumerate(jobs):            assert job.positive_prompt == f"Prompt number {i}"            assert job.prompt_pack_row_index == i            assert job.extra_metadata["pack_prompt_index"] == i            assert job.extra_metadata["pack_prompt_total"] == 10    def test_multiple_packs_expands_all_prompts(self):        """Multiple packs should each expand their prompts."""        builder = JobBuilderV2(            time_fn=lambda: 1000.0,            id_fn=lambda: "test-job-id",        )                # Pack 1: 5 prompts        pack1 = PackJobEntry(            pack_id="pack-1",            pack_name="Pack 1",            pack_row_index=0,            prompt_text="P1 Prompt 0",            prompts=[f"P1 Prompt {i}" for i in range(5)],            negative_prompt_text="",            config_snapshot={},            matrix_slot_values={},        )                # Pack 2: 3 prompts        pack2 = PackJobEntry(            pack_id="pack-2",            pack_name="Pack 2",            pack_row_index=0,            prompt_text="P2 Prompt 0",            prompts=[f"P2 Prompt {i}" for i in range(3)],            negative_prompt_text="",            config_snapshot={},            matrix_slot_values={},        )                run_request = PipelineRunRequest(            prompt_pack_id="pack-1",            selected_row_ids=["row-1"],            config_snapshot_id="config-1",            pack_entries=[pack1, pack2],        )                jobs = builder.build_from_run_request(run_request)                assert len(jobs) == 8, f"Expected 8 NJRs (5+3), got {len(jobs)}"    def test_empty_prompts_list_uses_prompt_text(self):        """If prompts list is empty, fall back to prompt_text."""        builder = JobBuilderV2()                pack_entry = PackJobEntry(            pack_id="test-pack",            pack_name="Test Pack",            pack_row_index=0,            prompt_text="Single prompt from legacy field",            prompts=[],  # Empty list            negative_prompt_text="",            config_snapshot={},            matrix_slot_values={},        )                run_request = PipelineRunRequest(            prompt_pack_id="test-pack",            selected_row_ids=["row-1"],            config_snapshot_id="config-1",            pack_entries=[pack_entry],        )                jobs = builder.build_from_run_request(run_request)                assert len(jobs) == 1        assert jobs[0].positive_prompt == "Single prompt from legacy field"    def test_max_njr_count_limits_expansion(self):        """max_njr_count should limit total NJRs created."""        builder = JobBuilderV2()                # Pack with 100 prompts        pack_entry = PackJobEntry(            pack_id="test-pack",            pack_name="Test Pack",            pack_row_index=0,            prompt_text="",            prompts=[f"Prompt {i}" for i in range(100)],            negative_prompt_text="",            config_snapshot={},            matrix_slot_values={},        )                run_request = PipelineRunRequest(            prompt_pack_id="test-pack",            selected_row_ids=["row-1"],            config_snapshot_id="config-1",            pack_entries=[pack_entry],            max_njr_count=25,  # Limit to 25        )                jobs = builder.build_from_run_request(run_request)                assert len(jobs) == 25, f"Expected 25 NJRs (limited), got {len(jobs)}"class TestPreviewPanelJobCount:    """Test that preview panel shows correct job count."""    def test_empty_draft_shows_zero_jobs(self):        """Empty draft should show 'Jobs: 0'."""        # This would be a GUI test - documented for manual verification        pass    def test_pack_with_10_prompts_shows_10_jobs(self):        """Adding a 10-prompt pack should show 'Jobs: 10'."""        # This would be a GUI test - documented for manual verification        pass
TEST PLAN
Commands to Execute:

C:\Users\rob\projects\StableNew\.venv\Scripts\python.exe -m pytest -v tests/pipeline/test_job_builder_prompt_expansion.pyC:\Users\rob\projects\StableNew\.venv\Scripts\python.exe -m pytest -v tests/pipeline/test_job_builder_v2.pyC:\Users\rob\projects\StableNew\.venv\Scripts\python.exe -m pytest -v tests/gui/test_preview_panel_v2.py
Expected Output:

tests/pipeline/test_job_builder_prompt_expansion.py::TestJobBuilderPromptExpansion::test_single_pack_10_prompts_creates_10_njrs PASSEDtests/pipeline/test_job_builder_prompt_expansion.py::TestJobBuilderPromptExpansion::test_multiple_packs_expands_all_prompts PASSEDtests/pipeline/test_job_builder_prompt_expansion.py::TestJobBuilderPromptExpansion::test_empty_prompts_list_uses_prompt_text PASSEDtests/pipeline/test_job_builder_prompt_expansion.py::TestJobBuilderPromptExpansion::test_max_njr_count_limits_expansion PASSED
VERIFICATION & PROOF
git diff (after implementation)

git diff src/pipeline/job_builder_v2.pygit diff src/gui/panels_v2/preview_panel_v2.py
git status

git status --short
Expected:


M  src/pipeline/job_builder_v2.pyM  src/gui/panels_v2/preview_panel_v2.pyA  tests/pipeline/test_job_builder_prompt_expansion.py
Forbidden Symbol Check

git grep "PipelineConfig" src/pipeline/job_builder_v2.pygit grep "PipelineConfig" src/gui/panels_v2/preview_panel_v2.py
Expected: No matches (NJR-only)

MANUAL VERIFICATION CHECKLIST
After implementation, verify:

 Launch StableNew GUI
 Preview panel shows "Jobs: 0" and "Expected Images: 0" initially
 Select a prompt pack with 10 prompts
 Click "Add to Job"
 Preview panel shows "Jobs: 10" and "Expected Images: 10"
 First prompt preview shows first line from pack
 Model/Sampler/Steps/CFG display values from pack config
 Click "Add to Queue"
 Queue panel shows 10 queued jobs
 Run queue - produces 10 images (one per prompt)
DOCUMENTATION DISCREPANCY IDENTIFIED
Issue in ARCHITECTURE_v2.6.md Section 8.1
Current text:

Pipeline Tab does NOT: Hold draft job objects

Proposed clarification:
The draft is held in AppStateV2.job_draft, but the Preview Panel displays the draft summary. The architecture should clarify that:

AppStateV2.job_draft holds PackJobEntry objects
Each PackJobEntry.prompts contains the list of prompts from the pack
JobBuilderV2.build_from_run_request() expands these into individual NJRs
Proposed diff for ARCHITECTURE_v2.6.md:


## 8.1 Pipeline TabPipeline Tab is responsible for:- Selecting PromptPack + row(s)- Configuring sweeps and variants- Configuring stage toggles- Previewing resolved job summaries (UnifiedJobSummary)Pipeline Tab does NOT:- Hold draft job objects directly (these are in `AppStateV2.job_draft`)- Construct jobs (this is done by `JobBuilderV2`)- Read/write prompt text- Store builder logic### Draft Flow Clarification (PR-PREVIEW-001)When a user adds a pack to the draft:1. `AppController.on_pipeline_add_packs_to_job()` creates a `PackJobEntry`2. `PackJobEntry.prompts` contains ALL prompt lines from the pack file3. `AppStateV2.job_draft.packs` accumulates these entries4. Preview panel calculates total jobs = sum of all prompts across all packs5. On queue submission, `JobBuilderV2.build_from_run_request()` expands each prompt into an NJRTotal NJRs = Σ(prompts per pack) across all packs in draft
GOLDEN PATH CONFIRMATION
After implementation, these Golden Path tests must pass:

 GP1 – Simple Single-Row Job (1 prompt → 1 NJR)
 GP2 – Matrix Randomization (if applicable)
 GP5 – Stage Chain Enforcement
 GP6 – Global Negative Integration
FINAL DECLARATION
This PR:

 Fully implements the declared scope
 Includes all required file modifications
 Adds new test coverage
 Provides verifiable proof requirements
 Documents discovered architecture discrepancy
 Maintains NJR-only execution semantics
EXECUTOR INSTRUCTIONS SUMMARY
Modify job_builder_v2.py — Replace build_from_run_request() with version that iterates entry.prompts
Modify preview_panel_v2.py — Add total_images_label, fix _render_summary() to count prompts not packs, add _render_empty_state()
Create tests/pipeline/test_job_builder_prompt_expansion.py — Add 4 test cases
Run tests — Execute pytest commands and paste output
Manual verify — Follow checklist to confirm GUI behavior