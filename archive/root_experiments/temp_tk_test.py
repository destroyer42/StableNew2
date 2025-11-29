import tkinter as tk

root = tk.Tk()
lb = tk.Listbox(root)
for i in range(3):
    lb.insert(tk.END, str(i))
called = []


def on_sel(evt=None):
    called.append("x")
    print("event called")


lb.bind("<<ListboxSelect>>", on_sel)
lb.selection_set(0)
lb.event_generate("<<ListboxSelect>>")
root.update()
print("called len:", len(called))
