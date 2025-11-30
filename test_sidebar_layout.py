import tkinter as tk
from src.gui.sidebar_panel_v2 import SidebarPanelV2

root = tk.Tk()
root.withdraw()  # Hide the window

try:
    sidebar = SidebarPanelV2(root)
    print('SidebarPanelV2 instantiated successfully')
    print(f'Preset dropdown exists: {hasattr(sidebar, "preset_dropdown") and sidebar.preset_dropdown is not None}')
    print(f'Number of children: {len(sidebar.winfo_children())}')

    # Check grid layout
    children_info = []
    for child in sidebar.winfo_children():
        try:
            info = child.grid_info()
            row = info.get('row', 'N/A')
            children_info.append(f"{child.__class__.__name__}: row={row}")
        except:
            children_info.append(f"{child.__class__.__name__}: no grid info")

    print('Grid layout:')
    for child_info in children_info[:10]:  # Show first 10
        print(f'  {child_info}')

    root.destroy()
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
    root.destroy()