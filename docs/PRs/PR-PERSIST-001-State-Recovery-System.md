# PR-PERSIST-001: Comprehensive State Recovery System

**Status:** Discovery Complete  
**Priority:** High  
**Complexity:** High - Multi-component system  
**Created:** 2025-12-22

## Overview

Implement comprehensive persistence and recovery system to allow StableNew to:
1. Survive crashes and restore full state
2. Gracefully restart without losing work
3. Maintain job history with archival
4. Auto-spawn new process before shutdown (hot reload)

## Current State Analysis

### ✅ Already Implemented

**Queue Persistence (`src/services/queue_store_v2.py`):**
- Queue state ALREADY persists across restarts
- Saves to `state/queue_state_v2.json`
- Schema version 2.6 compliant
- Stores: jobs, auto_run_enabled, paused flags
- Each job includes full NJR snapshot
- Auto-saved on queue changes via `_persist_queue_state()`

**Job History (`src/history/job_history_store.py`):**
- Already persists to `data/job_history.jsonl`
- Uses JSONL format (append-only)
- Schema version 2.6 compliant
- Stores complete HistoryRecord for each job

**Shutdown Flow (`src/utils/graceful_exit.py`):**
- Orderly shutdown sequence in place
- Cancels active jobs
- Stops background work
- Shuts down WebUI
- Closes loggers and clients

### ❌ Missing Features

1. **Queue state auto-restore on startup** - Currently loads but may not restore fully
2. **Job history archival** - No 100-entry limit or archive mechanism
3. **Preview panel state persistence** - No save/restore of preview selections
4. **Pack list persistence** - No save of loaded packs
5. **Hot reload/restart** - No spawn-new-before-closing mechanism
6. **UI state recovery** - No tab selection, scroll position, etc.

## Proposed Architecture

### Phase 1: Enhanced Queue Restore (Easy - 1-2 hours)

**Goal:** Ensure queue fully restores on startup

**Changes:**
- `src/controller/job_execution_controller.py`:
  - Verify `restore_queue_state()` is called on init
  - Restore `auto_run_enabled` and `paused` flags
  - Auto-start runner if `auto_run_enabled` was true

**Files:**
- `src/controller/job_execution_controller.py` (modify)
- Test: `tests/controller/test_queue_restore.py` (create)

---

### Phase 2: Job History Archival (Medium - 2-3 hours)

**Goal:** Keep last 100 entries, move older to archive

**Implementation:**
```python
# In src/history/job_history_store.py
MAX_ACTIVE_ENTRIES = 100
ARCHIVE_PATH = "data/job_history_archive.jsonl"

def archive_old_entries(self) -> None:
    """Move entries >100 to archive file."""
    entries = self.load()
    if len(entries) <= MAX_ACTIVE_ENTRIES:
        return
    
    active = entries[-MAX_ACTIVE_ENTRIES:]
    archived = entries[:-MAX_ACTIVE_ENTRIES]
    
    # Append to archive
    self._append_to_archive(archived)
    
    # Save only active entries
    self.save(active)
```

**Trigger Points:**
- After each job completion
- On app startup
- Manual "Archive Old History" button

**Files:**
- `src/history/job_history_store.py` (modify)
- `src/controller/job_history_service.py` (add archival calls)
- `src/gui/job_history_panel_v2.py` (add "View Archive" button)
- Test: `tests/history/test_history_archival.py` (create)

---

### Phase 3: Preview Panel State Persistence (Easy - 1 hour)

**Goal:** Save/restore preview panel state

**State to persist:**
```json
{
  "selected_job_index": 0,
  "scroll_position": 0.5,
  "expanded_sections": ["prompt", "params"],
  "show_preview_enabled": true
}
```

**Implementation:**
```python
# In src/gui/preview_panel_v2.py
PREVIEW_STATE_PATH = Path("state") / "preview_panel_state.json"

def save_state(self) -> None:
    """Save preview panel state."""
    state = {
        "selected_job_index": self._selected_index,
        "scroll_position": self._get_scroll_position(),
        "show_preview": self._show_preview_var.get()
    }
    PREVIEW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_STATE_PATH.write_text(json.dumps(state, indent=2))

def restore_state(self) -> None:
    """Restore preview panel state."""
    if not PREVIEW_STATE_PATH.exists():
        return
    try:
        state = json.loads(PREVIEW_STATE_PATH.read_text())
        self._restore_from_dict(state)
    except Exception as e:
        logger.warning(f"Failed to restore preview state: {e}")
```

**Trigger:**
- Save on window close
- Restore on panel init

**Files:**
- `src/gui/preview_panel_v2.py` (modify)
- Test: `tests/gui_v2/test_preview_panel_persistence.py` (create)

---

### Phase 4: Pack List Persistence (Easy - 1 hour)

**Goal:** Remember which packs were loaded

**State to persist:**
```json
{
  "selected_list": "My Custom List",
  "selected_packs": ["pack1", "pack2", "pack3"],
  "prompt_text": "a beautiful landscape"
}
```

**Implementation:**
```python
# In src/gui/sidebar_panel_v2.py
SIDEBAR_STATE_PATH = Path("state") / "sidebar_state.json"

def save_state(self) -> None:
    """Save sidebar state."""
    state = {
        "selected_list": self.pack_list_var.get(),
        "selected_packs": self._get_selected_pack_names(),
        "prompt_text": self.prompt_text.get()
    }
    SIDEBAR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIDEBAR_STATE_PATH.write_text(json.dumps(state, indent=2))
```

**Trigger:**
- Save on selection change (debounced)
- Restore on sidebar init

**Files:**
- `src/gui/sidebar_panel_v2.py` (modify)
- Test: `tests/gui_v2/test_sidebar_persistence.py` (create)

---

### Phase 5: Hot Reload / Graceful Restart (Complex - 4-6 hours)

**Goal:** Spawn new process before closing old one

**Challenges:**
- Single instance lock must transfer
- WebUI process handoff
- Port conflicts
- Queue state coordination

**Approach:**

```python
# New file: src/utils/hot_reload.py

def initiate_hot_reload() -> bool:
    """Spawn new StableNew process, then gracefully exit current."""
    
    # 1. Save all state
    save_all_state()
    
    # 2. Mark as reloading (flag file)
    RELOAD_FLAG = Path("state") / "reloading.flag"
    RELOAD_FLAG.write_text(str(os.getpid()))
    
    # 3. Spawn new process
    import subprocess
    import sys
    subprocess.Popen([sys.executable, "-m", "src.main"])
    
    # 4. Wait for new process to acquire lock (max 10s)
    deadline = time.time() + 10
    while time.time() < deadline:
        if new_process_has_lock():
            break
        time.sleep(0.5)
    
    # 5. Graceful exit (transfers WebUI, releases lock)
    graceful_exit(controller, root, lock, logger, reason="hot-reload")
```

**Single Instance Lock Enhancement:**
```python
# In src/utils/single_instance.py

def is_reload_handoff(self) -> bool:
    """Check if previous instance is doing hot reload."""
    reload_flag = Path("state") / "reloading.flag"
    if not reload_flag.exists():
        return False
    
    try:
        old_pid = int(reload_flag.read_text())
        # Check if old process still alive
        return psutil.pid_exists(old_pid)
    except:
        return False

def wait_for_handoff(self, timeout: float = 10) -> bool:
    """Wait for previous instance to release lock during hot reload."""
    if not self.is_reload_handoff():
        return False
    
    deadline = time.time() + timeout
    while time.time() < deadline:
        if self.try_acquire():
            return True
        time.sleep(0.5)
    return False
```

**WebUI Handoff:**
- Option 1: Keep WebUI alive (don't shutdown, new process connects)
- Option 2: Graceful handoff via port negotiation
- Option 3: Restart WebUI in new process

**GUI Integration:**
```python
# In src/gui/main_window_v2.py

def on_restart_requested(self) -> None:
    """Handle File > Restart menu action."""
    if messagebox.askyesno("Restart", "Restart StableNew?"):
        from src.utils.hot_reload import initiate_hot_reload
        initiate_hot_reload()
```

**Files:**
- `src/utils/hot_reload.py` (create)
- `src/utils/single_instance.py` (modify for handoff)
- `src/main.py` (check for reload flag on startup)
- `src/gui/main_window_v2.py` (add File > Restart menu)
- Test: `tests/utils/test_hot_reload.py` (create)

---

### Phase 6: Complete UI State Persistence (Medium - 2-3 hours)

**Goal:** Save/restore all UI state

**State to persist:**
```json
{
  "window": {
    "geometry": "1200x800+100+50",
    "tab_index": 0
  },
  "pipeline_tab": {
    "selected_packs": ["pack1", "pack2"],
    "prompt_text": "...",
    "stage_configs": {...}
  },
  "history_tab": {
    "filter": "completed",
    "sort_by": "timestamp"
  }
}
```

**Implementation:**
- Create `src/services/ui_state_store.py`
- Each tab/panel implements `save_state()` / `restore_state()`
- Coordinator saves all on shutdown
- Coordinator restores all on startup

**Files:**
- `src/services/ui_state_store.py` (create)
- All major GUI components (modify for state methods)
- Test: `tests/services/test_ui_state_store.py` (create)

---

## Implementation Order

**Recommended sequence:**

1. **Phase 1** - Queue restore enhancement (quick win)
2. **Phase 2** - Job history archival (visible improvement)
3. **Phase 3** - Preview panel persistence (user convenience)
4. **Phase 4** - Pack list persistence (user convenience)
5. **Phase 6** - UI state persistence (polish)
6. **Phase 5** - Hot reload (complex, do last)

**Alternative: Skip Phase 5**
- Hot reload is complex and risky
- Phases 1-4 + 6 provide 90% of value
- User can manually restart with full state restore

---

## Testing Strategy

**Unit Tests:**
- Each store module (queue, history, UI state)
- Serialization/deserialization
- Archive logic

**Integration Tests:**
- Full shutdown → startup cycle
- Crash simulation → recovery
- Queue state preservation
- History archival trigger

**Manual Tests:**
- Create jobs, shutdown, verify restore
- Fill history >100 entries, verify archive
- Change UI state, restart, verify restore
- Trigger hot reload (if implemented)

---

## Risks & Mitigations

**Risk 1: Corrupt state files**
- Mitigation: Schema validation, fallback to defaults, backup previous state

**Risk 2: Lock contention during hot reload**
- Mitigation: Timeout handling, clear error messages, manual restart fallback

**Risk 3: WebUI port conflicts**
- Mitigation: Graceful WebUI shutdown in old process, connection retry in new

**Risk 4: Large history file performance**
- Mitigation: Regular archival, JSONL streaming, pagination in UI

---

## Success Criteria

**Phase 1-4:**
- ✅ Queue fully restores after crash (jobs, flags, positions)
- ✅ History archives automatically at 100 entries
- ✅ Preview panel state persists across sessions
- ✅ Pack selections and prompt text persist

**Phase 5 (Optional):**
- ✅ Hot reload completes without errors
- ✅ Queue continues processing across reload
- ✅ WebUI stays alive or reconnects cleanly
- ✅ No duplicate processes or locks

**Phase 6:**
- ✅ All UI state (tabs, scroll, selections) persists
- ✅ Window geometry persists
- ✅ Feels like "session restore"

---

## Estimated Effort

| Phase | Complexity | Hours | Priority |
|-------|-----------|-------|----------|
| 1. Queue Restore | Low | 1-2 | High |
| 2. History Archival | Medium | 2-3 | High |
| 3. Preview Panel | Low | 1 | Medium |
| 4. Pack List | Low | 1 | Medium |
| 5. Hot Reload | High | 4-6 | Low |
| 6. UI State | Medium | 2-3 | Medium |
| **Total (w/o #5)** | - | **7-9h** | - |
| **Total (with #5)** | - | **11-15h** | - |

---

## Next Steps

**Option A: Implement Phases 1-4 (Recommended)**
- Provides core functionality
- Low risk
- ~7-9 hours effort
- User can manually restart with full recovery

**Option B: Implement All Phases (Ambitious)**
- Full hot reload capability
- Higher risk
- ~11-15 hours effort
- More complex testing

**Option C: Phased Rollout**
- Implement Phase 1 immediately (queue restore)
- Implement Phase 2 next (history archival)
- Evaluate remaining phases after user feedback

---

## Questions for User

1. **Hot reload priority:** Is spawning new process before shutdown critical, or is manual restart with full state restore acceptable?

2. **History limit:** Is 100 entries the right limit, or would you prefer configurable (50, 100, 200)?

3. **Archive access:** Should archived history be:
   - Read-only in GUI (view but not re-run)?
   - Importable back to active history?
   - Separate "Archive Viewer" dialog?

4. **Crash recovery prompt:** On startup after crash, should we:
   - Auto-restore silently?
   - Show "Restore previous session?" dialog?
   - Offer choice to start fresh?

5. **Implementation order:** Prefer Option A (Phases 1-4, skip hot reload), Option B (all phases), or Option C (incremental)?

