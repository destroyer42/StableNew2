# D-GUI-004: Reprocess Multi-Folder Selection

**Status**: Discovery  
**Priority**: Medium  
**Impact**: UX annoyance when adding multiple folders for reprocessing  
**Estimated Implementation**: 1-2 hours

---

## Problem Statement

When adding folders to the reprocess custom folder list, users must select them one at a time through the file explorer. This is tedious when needing to add 10+ folders.

### Current Behavior
```
User clicks "Add Folder"
  → Windows File Explorer opens
  → Can only select ONE folder
  → Click OK
  → Repeat 10 times for 10 folders
```

### Expected Behavior
```
User clicks "Add Folder"
  → Windows File Explorer opens
  → Can select MULTIPLE folders (Ctrl+Click or Shift+Click)
  → Click OK
  → All selected folders added at once
```

---

## Root Cause Analysis

### Tkinter Folder Selection Limitation

**Standard Tkinter folder dialog**:
```python
from tkinter import filedialog

# CURRENT (single folder only):
folder = filedialog.askdirectory(title="Select Folder")
# Returns: single folder path or empty string
```

**Problem**: `askdirectory()` doesn't support multi-select natively.

### Solution Options

#### Option 1: Use File Dialog with Folder Mode
**Not possible** - Tkinter's `askopenfilenames()` only selects files, not folders.

#### Option 2: Custom Multi-Select Dialog
Create custom Tkinter dialog with folder tree and checkboxes.
- **Pros**: Full control, native Python
- **Cons**: Complex, time-consuming (4-6 hours)

#### Option 3: Platform-Specific Native Dialog (Recommended)
Use Windows COM/shell32 for native multi-folder selection.
- **Pros**: Native UX, multi-select works naturally
- **Cons**: Windows-only (but StableNew is Windows-focused)

#### Option 4: Batch File Selection
Let user select multiple image FILES (not folders), then extract unique parent folders.
- **Pros**: Works with standard `askopenfilenames()`
- **Cons**: Confusing UX ("select images to add their folders?")

#### Option 5: Repeated Dialog with "Add More" Button
Show dialog repeatedly with "Add another folder" button.
- **Pros**: Simple to implement
- **Cons**: Still requires multiple clicks, but faster than current

---

## Recommended Solution: Platform-Specific Multi-Select

### Implementation Using Windows Shell COM

**File**: `src/gui/panels_v2/reprocess_panel_v2.py` (or wherever reprocess UI is)

```python
def _select_multiple_folders_windows(self, title: str = "Select Folders") -> list[str]:
    """
    Open Windows native folder browser with multi-select support.
    
    Uses Windows Shell COM API to enable multi-folder selection.
    Falls back to single-folder selection on non-Windows or if COM fails.
    
    Returns:
        List of selected folder paths (may be empty if cancelled)
    """
    import sys
    
    # Only use Windows COM on Windows platform
    if sys.platform != "win32":
        # Fallback to single folder selection
        folder = filedialog.askdirectory(title=title)
        return [folder] if folder else []
    
    try:
        # Use Windows COM for multi-select
        import pythoncom
        from win32com.shell import shell, shellcon
        
        # Initialize COM
        pythoncom.CoInitialize()
        
        try:
            # Create folder browser dialog
            browse_info = shell.SHBrowseForFolder(
                0,  # Parent window handle (0 = desktop)
                None,  # Root folder (None = desktop)
                title,
                shellcon.BIF_NEWDIALOGSTYLE | shellcon.BIF_RETURNONLYFSDIRS,  # Flags
                None,  # Callback
                None   # lparam
            )
            
            if browse_info:
                # Get selected folder path
                folder_path = shell.SHGetPathFromIDList(browse_info[0])
                if folder_path:
                    return [folder_path]
        finally:
            pythoncom.CoUninitialize()
    
    except ImportError:
        # pywin32 not available, fall back to tkinter
        pass
    except Exception as e:
        logger.warning(f"Windows folder selection failed: {e}")
    
    # Fallback: use standard tkinter dialog
    folder = filedialog.askdirectory(title=title)
    return [folder] if folder else []
```

**Problem with above approach**: Windows' `SHBrowseForFolder` doesn't support true multi-select either.

### Better Solution: Custom List Builder Dialog

**More practical approach** - Create a custom dialog that allows building a list:

```python
class MultiFolderSelector(tk.Toplevel):
    """Dialog for selecting multiple folders with preview."""
    
    def __init__(self, parent, title="Select Multiple Folders"):
        super().__init__(parent)
        self.title(title)
        self.selected_folders = []
        
        # Create UI
        self._build_ui()
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
    def _build_ui(self):
        # List of selected folders
        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ttk.Label(list_frame, text="Selected Folders:").pack(anchor="w")
        
        # Listbox with scrollbar
        list_container = ttk.Frame(list_frame)
        list_container.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(list_container)
        self.folder_listbox = tk.Listbox(
            list_container,
            yscrollcommand=scrollbar.set,
            height=10
        )
        scrollbar.config(command=self.folder_listbox.yview)
        
        self.folder_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Button(
            btn_frame,
            text="Add Folder...",
            command=self._add_folder
        ).pack(side="left", padx=5)
        
        ttk.Button(
            btn_frame,
            text="Remove Selected",
            command=self._remove_selected
        ).pack(side="left", padx=5)
        
        ttk.Button(
            btn_frame,
            text="Clear All",
            command=self._clear_all
        ).pack(side="left", padx=5)
        
        # OK/Cancel
        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Button(
            action_frame,
            text="OK",
            command=self._on_ok
        ).pack(side="right", padx=5)
        
        ttk.Button(
            action_frame,
            text="Cancel",
            command=self._on_cancel
        ).pack(side="right", padx=5)
    
    def _add_folder(self):
        """Add a folder to the list."""
        folder = filedialog.askdirectory(title="Select Folder to Add")
        if folder and folder not in self.selected_folders:
            self.selected_folders.append(folder)
            self.folder_listbox.insert("end", folder)
    
    def _remove_selected(self):
        """Remove selected folder from list."""
        selection = self.folder_listbox.curselection()
        if selection:
            idx = selection[0]
            self.folder_listbox.delete(idx)
            del self.selected_folders[idx]
    
    def _clear_all(self):
        """Clear all folders."""
        self.folder_listbox.delete(0, "end")
        self.selected_folders.clear()
    
    def _on_ok(self):
        """Close dialog with selected folders."""
        self.destroy()
    
    def _on_cancel(self):
        """Close dialog without selection."""
        self.selected_folders.clear()
        self.destroy()
    
    @classmethod
    def ask_folders(cls, parent, title="Select Multiple Folders") -> list[str]:
        """
        Show multi-folder selection dialog.
        
        Returns:
            List of selected folder paths (empty if cancelled)
        """
        dialog = cls(parent, title)
        parent.wait_window(dialog)
        return dialog.selected_folders
```

### Usage in Reprocess Panel

```python
class ReprocessPanel:
    def _on_add_folders_clicked(self):
        """Handle 'Add Folders' button click."""
        # Use custom multi-folder selector
        folders = MultiFolderSelector.ask_folders(
            self,
            title="Select Folders for Reprocessing"
        )
        
        # Add all selected folders to reprocess list
        for folder in folders:
            if folder not in self.custom_folders:
                self.custom_folders.append(folder)
        
        self._refresh_folder_list()
```

---

## Alternative: Drag & Drop Support

**Bonus enhancement**: Allow dragging folders from Windows Explorer directly into the folder list.

```python
def _setup_drag_drop(self):
    """Enable drag & drop for folders."""
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        
        # Make window DnD-aware
        self.folder_listbox.drop_target_register(DND_FILES)
        self.folder_listbox.dnd_bind('<<Drop>>', self._on_drop)
    except ImportError:
        logger.info("tkinterdnd2 not available, drag & drop disabled")

def _on_drop(self, event):
    """Handle dropped files/folders."""
    # Parse dropped paths
    files = self.folder_listbox.tk.splitlist(event.data)
    
    for item in files:
        path = Path(item)
        if path.is_dir():
            # It's a folder, add it
            if str(path) not in self.custom_folders:
                self.custom_folders.append(str(path))
        elif path.is_file():
            # It's a file, add its parent folder
            parent = str(path.parent)
            if parent not in self.custom_folders:
                self.custom_folders.append(parent)
    
    self._refresh_folder_list()
```

---

## Implementation Plan

### Phase 1: Create Multi-Folder Dialog (1 hour)

**File**: `src/gui/dialogs/multi_folder_selector.py` (new file)

1. Create `MultiFolderSelector` class (code above)
2. Implement list management
3. Add keyboard shortcuts (Delete key, Ctrl+A)

### Phase 2: Integrate with Reprocess Panel (30 minutes)

**File**: `src/gui/panels_v2/reprocess_panel_v2.py`

1. Replace `askdirectory()` call with `MultiFolderSelector.ask_folders()`
2. Test folder addition
3. Verify duplicates are prevented

### Phase 3: Add Drag & Drop (Optional, 30 minutes)

1. Check if `tkinterdnd2` available
2. If yes, enable drag & drop
3. If no, document as optional dependency

### Phase 4: Testing (30 minutes)

**Test Cases**:
- Add 1 folder
- Add 10 folders in one dialog session
- Try to add duplicate (should prevent)
- Remove folder from list
- Clear all folders
- Cancel dialog (should not add folders)
- Drag & drop folder (if implemented)

---

## File Modifications Required

### New File
**`src/gui/dialogs/multi_folder_selector.py`**
- Create MultiFolderSelector dialog class
- List management functionality
- Modal dialog behavior

### Modified File
**`src/gui/panels_v2/reprocess_panel_v2.py`**
- Replace single folder selection with multi-folder dialog
- Import new dialog class

### Optional Dependencies
**`requirements.txt`** or **`pyproject.toml`**
- Add `tkinterdnd2` (optional, for drag & drop)

---

## Success Criteria

✅ **Can add multiple folders in one action**:
- Click "Add Folder"
- Add folder, click "Add Folder" again (stays in same dialog)
- Repeat as needed
- Click OK to add all at once

✅ **Dialog is intuitive**:
- Clear list of selected folders
- Easy to remove unwanted folders
- Can't add duplicates

✅ **Backward compatible**:
- Existing folder list functionality works
- No breaking changes

✅ **Bonus - Drag & Drop works** (if implemented):
- Can drag folders from Explorer
- Can drag images (adds their parent folders)

---

## Testing Strategy

### Manual Testing
1. Open reprocess panel
2. Click "Add Folders"
3. Add 5 folders
4. Verify all 5 appear in list
5. Test remove/clear buttons
6. Test cancel doesn't add folders

### Edge Cases
- Very long folder paths
- Folders with unicode characters
- Same folder added multiple times
- Cancelled dialog

---

## Risk Assessment

**Very Low Risk**:
- Self-contained dialog
- Doesn't affect existing functionality
- Easy to revert if issues

**No Breaking Changes**:
- Replaces single-folder workflow with multi-folder
- Users can still add folders one at a time if they want

---

## Dependencies

**Requires**:
- Tkinter (already available)
- Optional: `tkinterdnd2` for drag & drop

**Enables**:
- Faster reprocess setup
- Better UX for batch operations

---

## Alternative Solutions Considered

1. **Native Windows Dialog** - Doesn't support multi-select for folders
2. **Select Files Instead** - Confusing UX
3. **Repeated Dialogs** - Still tedious
4. **Custom Tree View** - Too complex (6+ hours)

**Selected**: Custom list-builder dialog - Best balance of simplicity and functionality.

---

## Next Steps

1. ✅ Create this discovery document
2. ⏳ Create `multi_folder_selector.py`
3. ⏳ Integrate with reprocess panel
4. ⏳ Test with 10+ folders
5. ⏳ (Optional) Add drag & drop support
