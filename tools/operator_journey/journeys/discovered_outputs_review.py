"""Operator journey: Learning -> Discovered Outputs over a disposable output tree.

synthetic historical outputs -> Rescan -> inferred group -> Review -> observational
rating -> Done/Restore -> Dismiss/rescan/Restore -> missing artifact -> Clean
Missing References -> Rebuild Scanned Inbox.

Every action is a real Tk control.  Stores and files are only observed, and the
AccessSpy fails the run if anything reads or lists the operator's real output tree.
No generation backend is used (the loopback double only keeps StableNew from
contacting a real WebUI).
"""

from __future__ import annotations

import json
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.capture import FaultCapture, leaked_non_daemon_threads, thread_snapshot
from tools.operator_journey.dialogs import DialogSeam, scripted_dialogs
from tools.operator_journey.evidence import JourneyEvidence
from tools.operator_journey.fake_a1111 import FakeA1111
from tools.operator_journey.fixtures import (
    CFG_VALUES,
    FixtureArtifact,
    write_discovered_fixture,
    write_png,
)
from tools.operator_journey.journeys.learning_lora_strength import (
    JourneyAbort,
    JourneyConfig,
    _create_root,
)
from tools.operator_journey.owned import OwnedResources
from tools.operator_journey.tk_driver import (
    ActionTrace,
    JourneyTimeout,
    TkDriver,
    WidgetNotFound,
)
from tools.operator_journey.workspace import (
    AccessSpy,
    OperatorWorkspace,
    UserDataGuard,
    repo_sha,
)

JOURNEY_ID = "discovered-outputs-review"
_STAR = "★"


def _is_descendant(widget: tk.Misc, ancestor: tk.Misc) -> bool:
    node: tk.Misc | None = widget
    while node is not None:
        if node is ancestor:
            return True
        node = getattr(node, "master", None)
    return False


class _DiscoveredJourney:
    def __init__(
        self,
        config: JourneyConfig,
        evidence: JourneyEvidence,
        workspace: OperatorWorkspace,
        fake: FakeA1111,
    ) -> None:
        self.config = config
        self.ev = evidence
        self.ws = workspace
        self.fake = fake
        self.trace = ActionTrace()
        self.dialogs = DialogSeam()
        self.fixture: list[FixtureArtifact] = []
        self.checkpoints: list[dict[str, Any]] = []
        self.group_id = ""

    # -- plumbing -------------------------------------------------------
    def check(self, phase: str, name: str, passed: bool, detail: str = "") -> bool:
        return self.ev.check(phase, name, passed, "" if passed else detail)

    def require(self, phase: str, name: str, passed: bool, detail: str = "") -> None:
        if not self.check(phase, name, passed, detail):
            raise JourneyAbort(f"{phase}/{name}: {detail}")

    def store(self) -> Any:
        """A fresh store over the journey's own Learning data: what is durable on disk."""

        from src.learning.discovered_review_store import DiscoveredReviewStore

        return DiscoveredReviewStore(self.ws.root / "data" / "learning")

    def handles(self) -> list[Any]:
        return self.store().list_handles()

    def rows(self, tree: ttk.Treeview) -> list[tuple[str, tuple[str, ...]]]:
        return [
            (iid, tuple(str(v) for v in tree.item(iid, "values"))) for iid in tree.get_children()
        ]

    def note(self, label: str) -> None:
        self.checkpoints.append(
            {
                "checkpoint": label,
                "groups": [
                    {
                        "group_id": h.group_id,
                        "status": h.status,
                        "total": h.item_count,
                        "available": h.available_item_count,
                        "missing": h.missing_item_count,
                    }
                    for h in self.handles()
                ],
            }
        )

    # -- run ------------------------------------------------------------
    def run(self) -> None:
        from src.app_factory import build_v2_app

        baseline_threads = {t.name for t in __import__("threading").enumerate()}
        self.fixture = write_discovered_fixture(self.ws.output_dir)
        self.ev.summary["fixture_artifacts"] = [str(a.image) for a in self.fixture]
        root = _create_root()
        if self.config.show_window:
            root.geometry("1500x950+40+40")
        else:  # mapped but off-screen so widget geometry is real without flashing a window
            root.geometry("1500x950+-4000+-4000")
        self.driver = TkDriver(root, self.trace, use_mainloop=True)
        with FaultCapture(root) as faults, scripted_dialogs(self.dialogs):
            try:
                _, _, controller, window = build_v2_app(
                    root=root,
                    webui_manager=None,
                    threaded=True,
                    config_manager=self.ws.config_manager(),
                )
                self.controller, self.window = controller, window
                self.driver.pump(1.0)
                self._open_and_scan()
                self._review_and_rate()
                self._done_restore()
                self._dismiss_restore()
                self._missing_artifact()
                self._clean_missing()
                self._rebuild()
            except (JourneyAbort, JourneyTimeout, WidgetNotFound) as exc:
                self.ev.abort_reason = f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                self.ev.abort_reason = f"unexpected {type(exc).__name__}: {exc}"
            finally:
                self._shutdown(faults, baseline_threads)
        self.ev.shutdown_noise = list(faults.shutdown_noise)
        self.ev.gui_errors.extend(faults.tk_errors)
        self.ev.thread_errors.extend([*faults.thread_errors, *faults.main_errors])
        self.ev.log_errors.extend(faults.error_logs())
        self.ev.action_trace = list(self.trace.entries)
        self.ev.summary["checkpoints"] = self.checkpoints
        self.ev.summary["dialogs"] = [
            {"kind": c.kind, "title": c.title, "message": c.message, "answer": c.answer}
            for c in self.dialogs.calls
        ]

    # -- phase 1: scan --------------------------------------------------
    def _open_and_scan(self) -> None:
        ph = "scan"
        d = self.driver
        d.select_tab(self.window.center_notebook, "Learning - Adv")
        tab = self.tab = self.window.learning_tab
        d.select_tab(tab._mode_notebook, "Discovered Outputs")
        self.inbox = tab.discovered_inbox_panel
        self.table = tab.discovered_review_table
        d.invoke(self.inbox._reset_scan_root_btn, label="Auto Root")
        effective = Path(tab._get_effective_discovered_scan_root()).resolve()
        self.ev.summary["scan_root"] = str(effective)
        self.require(
            ph,
            "scan_root_inside_workspace",
            effective == self.ws.output_dir.resolve(),
            f"effective scan root {effective} is not the workspace output {self.ws.output_dir}",
        )
        shown = self.inbox._scan_root_var.get()
        self.check(
            ph,
            "displayed_root_is_workspace",
            shown.startswith("Scan Root:") and shown.rstrip().endswith(str(effective)[-30:]),
            f"label={shown!r}",
        )
        self.scan()
        rows = self.rows(self.inbox._tree)
        handles = self.handles()
        self.require(ph, "one_group", len(rows) == 1 and len(handles) == 1, f"rows={rows}")
        handle = handles[0]
        self.group_id = handle.group_id
        self.ev.summary["group_id"] = self.group_id
        self.check(
            ph,
            "starting_counts_3_3_0",
            (handle.item_count, handle.available_item_count, handle.missing_item_count) == (3, 3, 0)
            and rows[0][1][1:4] == ("3", "3", "0"),
            f"handle={handle} row={rows[0]}",
        )
        self.check(
            ph,
            "varying_field_is_cfg",
            tuple(handle.varying_fields) == ("cfg_scale",),
            f"varying={handle.varying_fields}",
        )
        index = self.store().load_scan_index()
        group = self.store().load_group(self.group_id)
        workspace_root = str(self.ws.root.resolve())
        referenced = [item.artifact_path for item in group.items] + list(index)
        self.check(
            ph,
            "scan_references_only_isolated_paths",
            len(group.items) == 3
            and all(str(Path(p).resolve()).startswith(workspace_root) for p in referenced),
            f"references={sorted(referenced)}",
        )
        self.note("scanned")

    def scan(self) -> None:
        """Click Rescan and wait for the scan result the panel itself reports."""

        d = self.driver
        d.invoke(self.inbox._scan_btn, label="Rescan")
        label = self.inbox._scan_status_label
        d.wait_until(
            lambda: str(label.cget("text")).startswith(("Scan succeeded", "Scan failed")),
            timeout=60,
            description="Rescan reports a result",
            evidence=lambda: str(label.cget("text")),
        )
        self.last_scan = str(label.cget("text"))
        self.require(
            "scan", "scan_succeeded", self.last_scan.startswith("Scan succeeded"), self.last_scan
        )

    # -- phase 2: review + observational ratings ---------------------------
    def _select_group(self, filter_label: str | None = None) -> None:
        d = self.driver
        if filter_label:
            d.invoke(
                d.find(self.inbox, ttk.Radiobutton, text=filter_label),
                label=f"filter {filter_label}",
            )
        d.select_tree_row(self.inbox._tree, self.group_id, label="discovered group")

    def _review_and_rate(self) -> None:
        ph = "review"
        d = self.driver
        self._select_group()
        d.invoke(self.inbox._open_btn, label="Review")
        items = self.rows(self.table._tree)
        self.require(ph, "all_items_listed", len(items) == 3, f"items={items}")
        thumb = self.table._preview_thumbnail
        d.wait_until(
            lambda: thumb._photo_image is not None, timeout=10, description="preview loads"
        )
        self.check(
            ph,
            "preview_is_workspace_artifact",
            str(Path(thumb._current_path).resolve()).startswith(str(self.ws.root.resolve())),
            f"preview path={thumb._current_path}",
        )
        meta = self.table._preview_meta_var.get()
        self.check(
            ph,
            "metadata_coherent_and_available",
            "Artifact unavailable" not in meta and "txt2img" in meta and "64 x 64" in meta,
            f"meta={meta!r}",
        )
        self._layout_checks()
        # Observational ratings through the real star buttons: item 1 -> 4, item 2 -> 5.
        first, second = (iid for iid, _ in items[:2])
        d.select_tree_row(self.table._tree, first, label="review item 1")
        d.invoke(d.find_button(self.table, f"4{_STAR}"), label="rate 4")
        d.select_tree_row(self.table._tree, second, label="review item 2")
        d.invoke(d.find_button(self.table, f"5{_STAR}"), label="rate 5")
        group = self.store().load_group(self.group_id)
        ratings = {item.item_id: item.rating for item in group.items}
        self.check(
            ph,
            "ratings_persisted",
            (ratings.get(first), ratings.get(second)) == (4, 5),
            f"ratings={ratings}",
        )
        self.check(
            ph,
            "ratings_are_observational",
            group.origin == "filesystem_scan"
            and not any(
                (i.extra_fields.get("learning_context") or {}).get("experiment_id")
                for i in group.items
            )
            and not self.ws.records_path.exists(),
            "discovered ratings must not create controlled Learning records",
        )
        self.ev.summary["ratings"] = ratings
        self.note("rated")

    def _layout_checks(self) -> None:
        ph = "layout"
        d = self.driver
        tab, table, inbox = self.tab, self.table, self.inbox
        d.pump(0.5)
        thumb = table._preview_thumbnail
        self.check(
            ph,
            "navigation_owns_groups_and_items",
            _is_descendant(inbox._tree, tab._discovered_navigation_split)
            and _is_descendant(table._tree, tab._discovered_item_navigation),
            "group/item lists are not inside the left navigation",
        )
        self.check(
            ph,
            "review_surface_owns_preview_and_rating",
            _is_descendant(thumb, table)
            and not _is_descendant(thumb, tab._discovered_navigation_split)
            and any(
                isinstance(w, ttk.Button) and str(w.cget("text")) == f"3{_STAR}"
                for w in _walk(table)
            ),
            "preview/rating controls are not on the review surface",
        )
        self.check(
            ph,
            "preview_allocated_positive",
            thumb.winfo_width() > 1 and thumb.winfo_height() > 1,
            f"preview allocated {thumb.winfo_width()}x{thumb.winfo_height()}",
        )
        total = max(1, tab._discovered_split.winfo_width())
        self.check(
            ph,
            "artifact_list_not_dominating",
            0 < table._tree.winfo_width() < 0.6 * total,
            f"items tree {table._tree.winfo_width()} of workspace {total}",
        )

    # -- phase 3: Done / Restore ------------------------------------------
    def _status_of_group(self) -> str:
        return next(h.status for h in self.handles() if h.group_id == self.group_id)

    def _done_restore(self) -> None:
        ph = "done"
        d = self.driver
        self._select_group("Active")
        d.invoke(self.inbox._close_btn, label="Done")
        self.check(ph, "leaves_active", self.rows(self.inbox._tree) == [], "group still in Active")
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Done"), label="filter Done")
        rows = self.rows(self.inbox._tree)
        self.check(
            ph,
            "listed_as_closed",
            [r[0] for r in rows] == [self.group_id] and rows[0][1][0] == "Closed",
            f"rows={rows}",
        )
        self.check(
            ph, "done_is_durable", self._status_of_group() == "closed", "store status differs"
        )
        d.select_tree_row(self.inbox._tree, self.group_id, label="closed group")
        d.invoke(self.inbox._reopen_btn, label="Restore")
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Active"), label="filter Active")
        self.check(
            ph,
            "restore_returns_to_active",
            [r[0] for r in self.rows(self.inbox._tree)] == [self.group_id]
            and self._status_of_group() == "waiting_review",
            f"rows={self.rows(self.inbox._tree)} status={self._status_of_group()}",
        )
        self.note("done_restored")

    # -- phase 4: Dismiss / rescan / Restore --------------------------------
    def _dismiss_restore(self) -> None:
        ph = "dismiss"
        d = self.driver
        self._select_group("Active")
        d.invoke(self.inbox._ignore_btn, label="Dismiss")
        self.check(ph, "leaves_active", self.rows(self.inbox._tree) == [], "group still in Active")
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Dismissed"), label="filter Dismissed")
        rows = self.rows(self.inbox._tree)
        self.check(
            ph,
            "listed_as_ignored",
            [r[0] for r in rows] == [self.group_id] and rows[0][1][0] == "Ignored",
            f"rows={rows}",
        )
        self.scan()  # ordinary rescan must not resurrect it
        handles = self.handles()
        self.check(
            ph,
            "rescan_creates_no_duplicate",
            len(handles) == 1
            and handles[0].status == "ignored"
            and "no new groups" in self.last_scan,
            f"handles={[(h.group_id, h.status) for h in handles]} scan={self.last_scan!r}",
        )
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Active"), label="filter Active")
        self.check(
            ph, "still_not_active_after_rescan", self.rows(self.inbox._tree) == [], "resurrected"
        )
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Dismissed"), label="filter Dismissed")
        d.select_tree_row(self.inbox._tree, self.group_id, label="dismissed group")
        d.invoke(self.inbox._reopen_btn, label="Restore")
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Active"), label="filter Active")
        self.check(
            ph,
            "restore_returns_to_active",
            [r[0] for r in self.rows(self.inbox._tree)] == [self.group_id],
            f"rows={self.rows(self.inbox._tree)}",
        )
        self.note("dismiss_restored")

    # -- phase 5: missing artifact ----------------------------------------------
    def _missing_artifact(self) -> None:
        ph = "missing"
        d = self.driver
        gone = self.fixture[2]  # the unrated CFG 9 artifact; its manifest stays in place
        self.gone_png = gone.image.read_bytes()
        gone.image.unlink()
        self.scan()  # normal refresh pathway
        handle = next(h for h in self.handles() if h.group_id == self.group_id)
        row = self.rows(self.inbox._tree)[0][1]
        self.check(
            ph,
            "counts_3_2_1",
            (handle.item_count, handle.available_item_count, handle.missing_item_count) == (3, 2, 1)
            and row[1:4] == ("3", "2", "1"),
            f"handle={handle} row={row}",
        )
        self._select_group()
        d.invoke(self.inbox._open_btn, label="Review")
        items = self.rows(self.table._tree)
        missing = [iid for iid, values in items if values[-1].startswith("[missing]")]
        self.require(ph, "one_missing_row", len(items) == 3 and len(missing) == 1, f"items={items}")
        d.select_tree_row(self.table._tree, missing[0], label="missing item")
        thumb = self.table._preview_thumbnail
        self.check(
            ph,
            "missing_state_is_explicit_and_not_stale",
            "Artifact unavailable" in self.table._preview_meta_var.get()
            and thumb._current_path is None
            and thumb._photo_image is None
            and not any(thumb.type(i) == "image" for i in thumb.find_all()),
            f"meta={self.table._preview_meta_var.get()!r} path={thumb._current_path}",
        )
        d.invoke(d.find_button(self.table, f"3{_STAR}"), label="rate missing item")
        before = {i.item_id: i.rating for i in self.store().load_group(self.group_id).items}
        self.check(
            ph,
            "missing_item_cannot_be_rated",
            "rating is disabled" in self.table._preview_meta_var.get() and before[missing[0]] == 0,
            f"meta={self.table._preview_meta_var.get()!r} rating={before[missing[0]]}",
        )
        available = next(iid for iid, _ in items if iid != missing[0])
        d.select_tree_row(self.table._tree, available, label="available item")
        d.invoke(d.find_button(self.table, f"2{_STAR}"), label="rate available")
        after = {i.item_id: i.rating for i in self.store().load_group(self.group_id).items}
        self.check(ph, "available_items_still_rateable", after[available] == 2, f"ratings={after}")
        self.note("missing")

    # -- phase 6: Clean Missing References ----------------------------------------
    def _clean_missing(self) -> None:
        ph = "clean"
        d = self.driver
        self.dialogs.calls.clear()
        self.dialogs.script(True)
        d.invoke(self.inbox._prune_btn, label="Clean Missing References...")
        prompt = next(
            (c for c in self.dialogs.calls if c.title == "Clean Missing References"), None
        )
        self.require(ph, "confirmation_shown", prompt is not None, f"dialogs={self.dialogs.calls}")
        self.check(
            ph,
            "prompt_reports_truthful_counts",
            "Scanner missing: 1" in prompt.message
            and "Legacy missing: 0" in prompt.message
            and "Zero-available groups: 0" in prompt.message
            and "Affected scan-index entries:" in prompt.message,
            f"prompt={prompt.message!r}",
        )
        status = str(self.inbox._scan_status_label.cget("text"))
        self.check(ph, "cleanup_reported", status.startswith("Pruned 1 missing item(s)"), status)
        handle = next(h for h in self.handles() if h.group_id == self.group_id)
        self.check(
            ph,
            "counts_2_2_0",
            (handle.item_count, handle.available_item_count, handle.missing_item_count)
            == (2, 2, 0),
            f"handle={handle}",
        )
        self.check(
            ph,
            "physical_artifacts_untouched",
            all(a.manifest.exists() for a in self.fixture)
            and all(a.image.exists() for a in self.fixture[:2]),
            "cleanup deleted a manifest or a remaining image",
        )
        index = self.store().load_scan_index()
        self.check(
            ph,
            "no_stale_index_entry_survives",
            str(self.fixture[2].image) not in index,
            f"index={sorted(index)}",
        )
        self.note("cleaned")

    # -- phase 7: Rebuild Scanned Inbox --------------------------------------------
    def _rebuild(self) -> None:
        ph = "rebuild"
        d = self.driver
        write_png(self.fixture[2].image, (40, 40, 200))  # the operator restores the file
        # A dismissed group is preserved by a rebuild and is not duplicated by the rescan.
        self._select_group("Active")
        d.invoke(self.inbox._ignore_btn, label="Dismiss")
        self.dialogs.calls.clear()
        self.dialogs.script(True)
        d.invoke(self.inbox._rebuild_btn, label="Rebuild Scanned Inbox...")
        self._wait_scan_result()
        handles = self.handles()
        self.check(
            ph,
            "dismissed_group_preserved_no_duplicate",
            [(h.group_id, h.status) for h in handles] == [(self.group_id, "ignored")],
            f"handles={[(h.group_id, h.status) for h in handles]}",
        )
        prompt = next((c for c in self.dialogs.calls if c.title == "Rebuild Scanned Inbox"), None)
        self.check(
            ph,
            "rebuild_confirmation_says_files_preserved",
            prompt is not None and "Images, manifests" in prompt.message,
            f"dialogs={self.dialogs.calls}",
        )
        # Restore it, then rebuild again: the active scanner group is reset and rebuilt.
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Dismissed"), label="filter Dismissed")
        d.select_tree_row(self.inbox._tree, self.group_id, label="dismissed group")
        d.invoke(self.inbox._reopen_btn, label="Restore")
        d.invoke(d.find(self.inbox, ttk.Radiobutton, text="Active"), label="filter Active")
        self.dialogs.script(True)
        d.invoke(self.inbox._rebuild_btn, label="Rebuild Scanned Inbox...")
        self._wait_scan_result()
        handles = self.handles()
        self.require(ph, "one_group_rebuilt", len(handles) == 1, f"handles={handles}")
        handle = handles[0]
        group = self.store().load_group(handle.group_id)
        self.check(
            ph,
            "rebuilt_group_3_3_0_unrated",
            (handle.item_count, handle.available_item_count, handle.missing_item_count) == (3, 3, 0)
            and handle.status == "waiting_review"
            and all(item.rating == 0 for item in group.items),
            f"handle={handle}",
        )
        self.check(
            ph,
            "fixture_files_intact",
            all(a.image.exists() and a.manifest.exists() for a in self.fixture),
            "rebuild deleted a fixture artifact",
        )
        self.check(
            ph,
            "rebuilt_group_visible_in_active",
            [r[0] for r in self.rows(self.inbox._tree)] == [handle.group_id],
            f"rows={self.rows(self.inbox._tree)}",
        )
        self.note("rebuilt")

    def _wait_scan_result(self) -> None:
        label = self.inbox._scan_status_label
        self.driver.wait_until(
            lambda: str(label.cget("text")).startswith(("Scan succeeded", "Scan failed")),
            timeout=60,
            description="rebuild rescan reports a result",
            evidence=lambda: str(label.cget("text")),
        )
        self.last_scan = str(label.cget("text"))

    # -- shutdown -------------------------------------------------------------
    def _shutdown(self, faults: FaultCapture, baseline_threads: set[str]) -> None:
        ph = "shutdown"
        d = self.driver
        root = d.root
        try:
            self.ev.thread_checkpoints.append(thread_snapshot("before_shutdown"))
            faults.begin_shutdown()
            d.close_via_window_manager()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    root.update()
                    root.winfo_exists()
                except tk.TclError:
                    break
                time.sleep(0.02)
            else:
                self.check(ph, "graceful_close", False, "Tk root still alive 15s after close")
        except tk.TclError:
            pass
        deadline = time.monotonic() + 10
        leaked = leaked_non_daemon_threads(baseline_threads)
        while leaked and time.monotonic() < deadline:
            time.sleep(0.1)
            leaked = leaked_non_daemon_threads(baseline_threads)
        self.check(ph, "no_leaked_threads", not leaked, f"non-daemon threads alive: {leaked}")
        self.ev.thread_checkpoints.append(thread_snapshot("after_shutdown"))


def _walk(widget: tk.Misc) -> Any:
    from tools.operator_journey.tk_driver import iter_widgets

    return iter_widgets(widget)


def run_discovered_journey(config: JourneyConfig) -> JourneyEvidence:
    """Execute the journey; the evidence bundle is also written to disk."""

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = Path(config.evidence_root) / f"{stamp}_{JOURNEY_ID}"
    evidence = JourneyEvidence(journey_id=JOURNEY_ID, backend_mode="none")
    evidence.repository_sha = repo_sha()
    evidence.started_at = evidence.now()
    evidence.summary["evidence_dir"] = str(run_dir)
    guard = UserDataGuard()
    guard.capture()
    owned = OwnedResources()
    fake = FakeA1111()  # keeps StableNew off any real WebUI; never receives a generation
    fake.start()
    owned.register("fake-a1111", fake.stop)
    try:
        workspace = OperatorWorkspace(
            root=Path(tempfile.mkdtemp(prefix="opj_")),
            webui_base_url=fake.base_url,
            startup_grace_sec=0.0,
        )
        evidence.summary["workspace"] = str(workspace.root)
        evidence.summary["workspace_output_root"] = str(workspace.output_dir)
        spy = AccessSpy(allowed=(workspace.root,))
        with workspace.activate(), spy:
            _DiscoveredJourney(config, evidence, workspace, fake).run()
        evidence.check(
            "isolation",
            "no_generation_requested",
            not fake.txt2img_payloads,
            f"{len(fake.txt2img_payloads)} generation requests reached the backend",
        )
        evidence.isolation_violations.extend(spy.violations())
        evidence.summary["production_output_reads"] = len(set(spy.read_outputs))
        evidence.summary["production_output_listings"] = len(set(spy.enumerated))
        archive_discovered(workspace, evidence, run_dir, discard=config.discard_workspace)
    except Exception as exc:
        evidence.abort_reason = (
            evidence.abort_reason or f"harness error {type(exc).__name__}: {exc}"
        )
    finally:
        owned.cleanup()
        evidence.isolation_violations.extend(guard.violations())
        evidence.completed_at = evidence.now()
        evidence.write(run_dir)
    return evidence


def archive_discovered(
    workspace: OperatorWorkspace, evidence: JourneyEvidence, run_dir: Path, *, discard: bool
) -> None:
    """Copy fixtures and discovered-store metadata (short names) into the evidence dir."""

    import shutil

    target = run_dir / "artifacts"
    target.mkdir(parents=True, exist_ok=True)
    for index, cfg in enumerate(CFG_VALUES):
        stem = f"txt2img_fixture_cfg{int(cfg)}"
        run = workspace.output_dir / "Pipeline" / "20260101_000000_operator_fixture"
        for source, name in (
            (run / f"{stem}.png", f"fixture{index}.png"),
            (run / "manifests" / f"{stem}.json", f"fixture{index}_manifest.json"),
        ):
            if source.is_file():
                shutil.copy2(source, target / name)
    store_root = workspace.root / "data" / "learning" / "discovered_experiments"
    if store_root.is_dir():
        shutil.copytree(store_root, target / "discovered_experiments", dirs_exist_ok=True)
    (target / "checkpoints.json").write_text(
        json.dumps(evidence.summary.get("checkpoints", []), indent=2), encoding="utf-8"
    )
    if discard:
        shutil.rmtree(workspace.root, ignore_errors=True)
