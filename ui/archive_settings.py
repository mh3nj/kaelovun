"""
archive_settings.py

The "Archive" tab of the Settings dialog: output format, compression, safety
limits, tools and scratch folder. Kept in its own module so settings_dialog.py
only needs two calls (build + collect).

Everything saves into data/settings.json and takes effect on the very next archive.
"""

import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

from files.app_settings import AppSettings
from files.archive_backends import ToolLocator
from files.archive_prefs import DICT_SIZES_MB, load_prefs

FORMAT_LABELS = {
    "rar": "RAR5  (needs WinRAR)",
    "7z": "7z  (smallest files, needs 7-Zip)",
    "zip": "ZIP  (most compatible, built in)",
    "smallest": "Smallest  (build 7z and RAR, keep the winner)",
}
LEVEL_LABELS = {"fast": "Fast", "normal": "Normal", "best": "Best (slowest)"}
SOLID_LABELS = {
    "solid": "Solid  (best ratio)",
    "type": "Solid per file type  (good ratio, faster)",
    "off": "Off  (fastest; one damaged file can't hurt the rest)",
}
VERIFY_LABELS = {
    "standard": "Standard  (integrity test + names + sizes)",
    "paranoid": "Paranoid  (also CRC32 of every file)",
}


def _invert(mapping):
    return {v: k for k, v in mapping.items()}


def _combo(parent, var, labels, width=44):
    combo = ttk.Combobox(parent, textvariable=var, values=list(labels.values()),
                         state="readonly", width=width)
    return combo


def _row(parent, label):
    row = tk.Frame(parent)
    row.pack(fill="x", padx=10, pady=3)
    tk.Label(row, text=label, width=24, anchor="w").pack(side="left")
    return row


def build_archive_tab(dialog, tabs):
    """Create the tab and its variables on ``dialog`` (as ``dialog.arc``)."""
    prefs = load_prefs(dialog.config)
    stored = AppSettings(dialog.config.SETTINGS_FILE).load()

    v = dialog.arc = {
        "format": tk.StringVar(value=FORMAT_LABELS[prefs.format]),
        "level": tk.StringVar(value=LEVEL_LABELS[prefs.level]),
        "solid": tk.StringVar(value=SOLID_LABELS[prefs.solid]),
        "dict_mb": tk.StringVar(value=str(prefs.dict_mb)),
        "recovery_pct": tk.StringVar(value=str(prefs.recovery_pct)),
        "verify": tk.StringVar(value=VERIFY_LABELS[prefs.verify]),
        "store_precompressed": tk.BooleanVar(value=prefs.store_precompressed),
        "test": tk.BooleanVar(value=prefs.test),
        "write_sidecar": tk.BooleanVar(value=prefs.write_sidecar),
        "export_previews": tk.BooleanVar(value=prefs.export_previews),
        "max_extract_gb": tk.StringVar(value=f"{prefs.max_extract_gb:g}"),
        "max_ratio": tk.StringVar(value=f"{prefs.max_ratio:g}"),
        "sevenzip": tk.StringVar(value=str(stored.get("SEVENZIP_PATH", ""))),
        "workspace": tk.StringVar(value=str(stored.get("WORKSPACE_DIR", ""))),
    }

    outer = tk.Frame(tabs)
    tabs.add(outer, text="Archive")

    tk.Label(outer, text="What Kaelovun builds", font=("Arial", 10, "bold")).pack(
        anchor="w", padx=10, pady=(8, 2))
    _combo(_row(outer, "Output format"), v["format"], FORMAT_LABELS).pack(side="left")
    _combo(_row(outer, "Compression level"), v["level"], LEVEL_LABELS, 24).pack(side="left")
    _combo(_row(outer, "Solid mode"), v["solid"], SOLID_LABELS).pack(side="left")

    row = _row(outer, "Dictionary size (MB)")
    ttk.Combobox(row, textvariable=v["dict_mb"], values=[str(x) for x in DICT_SIZES_MB],
                 width=8).pack(side="left")
    dialog.arc_ram = tk.Label(row, text="", fg="gray")
    dialog.arc_ram.pack(side="left", padx=8)
    v["dict_mb"].trace_add("write", lambda *_: _refresh_ram(dialog))
    _refresh_ram(dialog)

    row = _row(outer, "RAR recovery record (%)")
    tk.Spinbox(row, from_=0, to=10, textvariable=v["recovery_pct"], width=6).pack(side="left")
    tk.Label(row, text="0 = off. Lets WinRAR repair a damaged archive.", fg="gray").pack(side="left", padx=8)

    tk.Checkbutton(outer, text="Store already-compressed files (AVIF/JPG/MP4...) in RAR instead of recompressing",
                   variable=v["store_precompressed"]).pack(anchor="w", padx=10)
    tk.Checkbutton(outer, text="Save the preview next to each archive (<name>.avif + <name>.thumb.avif; Evoury needs these)",
                   variable=v["export_previews"]).pack(anchor="w", padx=10)
    tk.Checkbutton(outer, text="Write a sidecar file next to each archive (<name>.kaelovun.json)",
                   variable=v["write_sidecar"]).pack(anchor="w", padx=10)

    tk.Label(outer, text="How carefully it checks", font=("Arial", 10, "bold")).pack(
        anchor="w", padx=10, pady=(10, 2))
    _combo(_row(outer, "Verification"), v["verify"], VERIFY_LABELS).pack(side="left")
    tk.Checkbutton(outer, text="Run the archiver's own integrity test on every archive",
                   variable=v["test"]).pack(anchor="w", padx=10)

    tk.Label(outer, text="Safety limits (archives Kaelovun opens)", font=("Arial", 10, "bold")).pack(
        anchor="w", padx=10, pady=(10, 2))
    row = _row(outer, "Max unpacked size (GB)")
    tk.Entry(row, textvariable=v["max_extract_gb"], width=8).pack(side="left")
    row = _row(outer, "Max unpack ratio (x:1)")
    tk.Entry(row, textvariable=v["max_ratio"], width=8).pack(side="left")
    tk.Label(row, text="Refuses likely archive bombs before unpacking.", fg="gray").pack(side="left", padx=8)

    tk.Label(outer, text="Tools and scratch space", font=("Arial", 10, "bold")).pack(
        anchor="w", padx=10, pady=(10, 2))
    _path_row(dialog, outer, "7-Zip (7z.exe)", v["sevenzip"], file=True)
    dialog.arc_tools = tk.Label(outer, text="", anchor="w", justify="left")
    dialog.arc_tools.pack(fill="x", padx=10)
    _path_row(dialog, outer, "Workspace folder", v["workspace"], file=False)
    tk.Label(outer, text="Blank = automatic. Packages are copied/unpacked here, so pick a roomy, fast drive.",
             fg="gray", anchor="w").pack(fill="x", padx=10)
    v["sevenzip"].trace_add("write", lambda *_: refresh_tools(dialog))
    refresh_tools(dialog)
    return outer


def _path_row(dialog, parent, label, var, file):
    row = _row(parent, label)
    tk.Entry(row, textvariable=var, width=34).pack(side="left")

    def browse():
        picked = (filedialog.askopenfilename(title=label, filetypes=[("Executables", "*.exe"), ("All files", "*.*")])
                  if file else filedialog.askdirectory(title=label))
        if picked:
            var.set(picked)

    tk.Button(row, text="Browse", command=browse).pack(side="left", padx=4)
    tk.Button(row, text="Auto", command=lambda: var.set("")).pack(side="left")


def _refresh_ram(dialog):
    try:
        mb = int(dialog.arc["dict_mb"].get())
        dialog.arc_ram.config(text=f"7z at 'Best' needs roughly {mb * 10.5 / 1024:.1f} GB of RAM")
    except (ValueError, tk.TclError):
        pass


def refresh_tools(dialog):
    """Show which archivers were found, using the path currently typed in the dialog."""
    try:
        prefs = load_prefs(dialog.config)
        typed = dialog.arc["sevenzip"].get().strip()
        if typed:
            prefs.sevenzip_path = Path(typed)
        loc = ToolLocator(prefs)
        z, r = loc.sevenzip(), loc.rar()
        dialog.arc_tools.config(
            text=(f"7-Zip: {'found - ' + str(z) if z else 'NOT FOUND (needed for 7z output and reading RAR)'}\n"
                  f"WinRAR: {'found - ' + str(r) if r else 'NOT FOUND (needed for RAR output; set its path in Applications)'}"),
            fg="green" if (z and r) else ("#c07000" if (z or r) else "red"))
    except tk.TclError:
        pass


def collect_archive_values(dialog) -> dict:
    """Validated settings.json entries for the Archive tab. Raises ValueError on bad input."""
    v = dialog.arc
    profile = {
        "format": _invert(FORMAT_LABELS)[v["format"].get()],
        "level": _invert(LEVEL_LABELS)[v["level"].get()],
        "solid": _invert(SOLID_LABELS)[v["solid"].get()],
        "dict_mb": int(v["dict_mb"].get()),
        "recovery_pct": int(v["recovery_pct"].get()),
        "verify": _invert(VERIFY_LABELS)[v["verify"].get()],
        "store_precompressed": bool(v["store_precompressed"].get()),
        "test": bool(v["test"].get()),
        "write_sidecar": bool(v["write_sidecar"].get()),
        "export_previews": bool(v["export_previews"].get()),
        "max_extract_gb": float(v["max_extract_gb"].get()),
        "max_ratio": float(v["max_ratio"].get()),
    }
    if not 1 <= profile["dict_mb"] <= 1024:
        raise ValueError("dictionary size must be between 1 and 1024 MB")
    if not 0 <= profile["recovery_pct"] <= 10:
        raise ValueError("recovery record must be 0-10 %")
    out = {"ARCHIVE_PROFILE": profile}
    if v["sevenzip"].get().strip():
        out["SEVENZIP_PATH"] = v["sevenzip"].get().strip()
    if v["workspace"].get().strip():
        out["WORKSPACE_DIR"] = v["workspace"].get().strip()
    return out
