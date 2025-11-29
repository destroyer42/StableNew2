import tkinter as tk

from src.gui.prompt_pack_panel import PromptPackPanel

root = tk.Tk()
changes = []

panel = PromptPackPanel(root, on_selection_changed=lambda packs: changes.append(packs))
if panel.packs_listbox.size() > 0:
    panel.packs_listbox.selection_set(0)
    panel._on_pack_selection_changed()
    root.update()
    print("changes length:", len(changes))
else:
    print("no packs")
