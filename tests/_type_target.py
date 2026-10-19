"""A small window for the typing test: a text box that reports what it holds.

Writes "focused" to <status> only while its own window is the foreground
window, and mirrors the text box into <out> every 100 ms. Exits after 30 s.
Not a test module itself (no test_ prefix), so pytest does not collect it.
"""

import ctypes
import pathlib
import sys
import tkinter as tk

status, out = map(pathlib.Path, sys.argv[1:3])

root = tk.Tk()
root.title("remote-pc-mcp typing test")
root.geometry("600x200+80+80")
root.attributes("-topmost", True)
box = tk.Text(root)
box.pack(fill="both", expand=True)


def grab_focus():
    root.deiconify()
    root.lift()
    root.focus_force()
    box.focus_set()


def report():
    hwnd = int(root.wm_frame(), 16)
    focused = ctypes.windll.user32.GetForegroundWindow() == hwnd
    status.write_text("focused" if focused else "waiting", encoding="utf-8")
    out.write_text(box.get("1.0", "end-1c"), encoding="utf-8")
    if not focused:
        grab_focus()
    root.after(100, report)


grab_focus()
root.after(100, report)
root.after(30000, root.destroy)
root.mainloop()
