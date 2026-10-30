"""summary_dialog.py - what just happened, shown when the queue finishes."""

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

from files.archive_backends import human_size


def open_folder(path: Path):
    """Show ``path`` in the system file manager (selecting it on Windows)."""
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception:
        pass


class SummaryDialog(tk.Toplevel):

    def __init__(self, parent, theme, summary: str, reports: list):
        super().__init__(parent)
        self.title("Queue finished")
        self.geometry("620x380")
        self.transient(parent)
        self.configure(bg=theme["bg"])

        tk.Label(self, text=summary, anchor="w", justify="left", bg=theme["bg"], fg=theme["fg"],
                 font=("Arial", 10, "bold"), wraplength=580).pack(fill="x", padx=12, pady=(12, 6))

        box = tk.Text(self, wrap="none", bg=theme["log_bg"], fg=theme["log_fg"], font=("Consolas", 9))
        box.pack(fill="both", expand=True, padx=12)
        for r in reports:
            saved = r["source_bytes"] - r["archive_bytes"]
            box.insert("end", f"{r['name']}.{r['format']}\n")
            box.insert("end", f"    {human_size(r['source_bytes'])} -> {human_size(r['archive_bytes'])}"
                              f"   ({r['files']} files, {r['transformed']} processed, {r['seconds']}s)\n")
            for w in r["warnings"]:
                box.insert("end", f"    ! {w}\n")
        if not reports:
            box.insert("end", "No archives were produced. See the log for details.")
        box.config(state="disabled")

        row = tk.Frame(self, bg=theme["bg"])
        row.pack(fill="x", padx=12, pady=10)
        last = Path(reports[-1]["archive"]) if reports else None
        if last and last.exists():
            tk.Button(row, text="Show last archive", bg=theme["button_bg"], fg=theme["button_fg"],
                      command=lambda: open_folder(last)).pack(side="left")
        tk.Button(row, text="Close", width=10, bg=theme["button_bg"], fg=theme["button_fg"],
                  command=self.destroy).pack(side="right")
