"""
settings_dialog.py

In-app Settings dialog (opened via the Settings button).

Tabs: Engine / Applications / Formats / Preview / Pipeline / Appearance.
Everything saves machine-local to data/settings.json through
AppSettings, then reloads straight into the live Config — no restart,
no config.py editing, no rebuild. Empty path fields mean auto-detect.
"""

import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

from files.app_settings import AppSettings


INT_FIELDS = (
    ("PREVIEW_WIDTH", "Preview max width (px)", "Preview"),
    ("PREVIEW_HEIGHT", "Preview max height (px)", "Preview"),
    ("THUMB_WIDTH", "Thumbnail width (px)", "Preview"),
    ("THUMB_HEIGHT", "Thumbnail height (px)", "Preview"),
    ("AVIF_QUALITY", "AVIF quality (0-100)", "Preview"),
    ("AVIF_SPEED", "AVIF speed (0=best, 10=fastest)", "Preview"),
    ("THUMB_QUALITY", "Thumbnail quality (0-100)", "Preview"),
    ("ADOBE_STARTUP_WAIT", "Adobe launch wait (s)", "Pipeline"),
    ("ADOBE_RECOVERY_WAIT", "Adobe recovery wait (s)", "Pipeline"),
    ("AFFINITY_STARTUP_WAIT", "Affinity launch wait (s)", "Pipeline"),
    ("AFFINITY_RECOVERY_WAIT", "Affinity recovery wait (s)", "Pipeline"),
    ("AFFINITY_MCP_PORT", "Affinity MCP port", "Pipeline"),
    ("DOCUMENT_TIMEOUT", "Document open timeout (s)", "Pipeline"),
    ("MAX_RETRIES", "Auto-retries on error", "Pipeline"),
    ("MINIMUM_FREE_SPACE_GB", "Min free space (GB)", "Pipeline"),
)

PATH_FIELDS = (
    ("PHOTOSHOP_PATH", "Photoshop"),
    ("ILLUSTRATOR_PATH", "Illustrator"),
    ("AFFINITY_PATH", "Affinity"),
    ("WINRAR_PATH", "WinRAR (Rar.exe)"),
)

FORMAT_FIELDS = (".psd", ".ai", ".eps", ".afphoto", ".afdesign", ".afpub")

PREVIEW_FORMATS = ["AVIF", "PNG", "WEBP", "JPEG"]
NAMING_MODES = ["manual", "automation"]


class SettingsDialog(tk.Toplevel):

    def __init__(self, parent, config, on_saved=None):
        super().__init__(parent)
        self.config = config
        self.on_saved = on_saved
        self.title("Settings")
        self.geometry("560x560")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.engine_var = tk.StringVar(value=getattr(config, "ENGINE", "adobe"))
        self.theme_var = tk.StringVar(value=getattr(config, "THEME", "dark"))
        self.preview_format_var = tk.StringVar(value=getattr(config, "PREVIEW_FORMAT", "AVIF"))
        self.thumb_format_var = tk.StringVar(value=getattr(config, "THUMB_FORMAT", "AVIF"))
        self.naming_mode_var = tk.StringVar(value=getattr(config, "NAMING_MODE", "manual"))
        self.int_vars = {k: tk.StringVar(value=str(getattr(config, k, "")))
                         for k, _, _ in INT_FIELDS}
        self.path_vars = {k: tk.StringVar(value=self._stored_path(k))
                          for k, _ in PATH_FIELDS}
        self.format_vars = {e: tk.BooleanVar(
            value=e in getattr(config, "SUPPORTED_SOURCE_EXTENSIONS", []))
            for e in FORMAT_FIELDS}

        self._build()
        self._refresh_mcp_status()

    # ── current values ──

    def _stored_path(self, key) -> str:
        """What settings.json overrides ('' means auto-detect default)."""
        return str(AppSettings(self.config.SETTINGS_FILE).load().get(key, ""))

    def _resolved_path(self, key) -> Path:
        override = self.path_vars[key].get().strip()
        if override:
            return Path(override)
        return Path(getattr(self.config, key))

    # ── layout ──

    def _build(self):
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_engine(tabs)
        self._build_apps(tabs)
        self._build_formats(tabs)
        self._build_preview(tabs)
        self._build_numbers(tabs, "Pipeline")
        self._build_appearance(tabs)

        self.error_label = tk.Label(self, text="", fg="red", anchor="w")
        self.error_label.pack(fill="x", padx=12)

        buttons = tk.Frame(self)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(buttons, text="Save", width=12, command=self._save).pack(side="right")
        tk.Button(buttons, text="Cancel", width=12, command=self.destroy).pack(side="right", padx=5)
        tk.Button(buttons, text="Reset defaults", command=self._reset).pack(side="left")

    def _build_engine(self, tabs):
        frame = tk.Frame(tabs)
        tabs.add(frame, text="Engine")
        tk.Label(frame, text="Which app opens PSD / AI / EPS files?",
                 font=("Arial", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 5))
        tk.Radiobutton(frame, text="Adobe — Photoshop / Illustrator via COM",
                       variable=self.engine_var, value="adobe").pack(anchor="w", padx=20)
        tk.Label(frame, text="Classic pipeline. Needs Photoshop and/or Illustrator installed.",
                 fg="gray").pack(anchor="w", padx=42)
        tk.Radiobutton(frame, text="Affinity — unified app via MCP scripting",
                       variable=self.engine_var, value="affinity").pack(anchor="w", padx=20, pady=(8, 0))
        tk.Label(frame, text="Opens PSD/AI/EPS in Affinity. Also enables native\n.afphoto / .afdesign / .afpub files.",
                 fg="gray").pack(anchor="w", padx=42)
        self.mcp_label = tk.Label(frame, text="MCP: …", anchor="w")
        self.mcp_label.pack(anchor="w", padx=10, pady=(15, 0))
        tk.Button(frame, text="Test Affinity connection",
                  command=self._refresh_mcp_status).pack(anchor="w", padx=10, pady=5)

    def _build_apps(self, tabs):
        frame = tk.Frame(tabs)
        tabs.add(frame, text="Applications")
        tk.Label(frame, text="Empty field = auto-detect from Program Files.",
                 fg="gray").pack(anchor="w", padx=10, pady=(10, 5))
        self.path_status = {}
        for key, label in PATH_FIELDS:
            row = tk.Frame(frame)
            row.pack(fill="x", padx=10, pady=3)
            tk.Label(row, text=label, width=18, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=self.path_vars[key]).pack(
                side="left", fill="x", expand=True, padx=5)
            tk.Button(row, text="Browse",
                      command=lambda k=key: self._browse(k)).pack(side="left")
            tk.Button(row, text="Auto",
                      command=lambda k=key: self._auto(k)).pack(side="left", padx=(3, 0))
            status = tk.Label(row, text="", width=12, anchor="w")
            status.pack(side="left", padx=5)
            self.path_status[key] = status
        self._refresh_path_status()
        for var in self.path_vars.values():
            var.trace_add("write", lambda *_: self._refresh_path_status())

    def _build_formats(self, tabs):
        frame = tk.Frame(tabs)
        tabs.add(frame, text="Formats")
        tk.Label(frame, text="File types picked up by Select Folder.",
                 font=("Arial", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 5))
        for ext in FORMAT_FIELDS:
            tk.Checkbutton(frame, text=ext, variable=self.format_vars[ext]).pack(
                anchor="w", padx=20)
        tk.Label(frame, text="Note: .afphoto / .afdesign / .afpub are only\nprocessed when the engine is Affinity.",
                 fg="gray").pack(anchor="w", padx=10, pady=10)

    def _build_preview(self, tabs):
        frame = tk.Frame(tabs)
        tabs.add(frame, text="Preview")

        # Preview format
        tk.Label(frame, text="Preview output format", font=("Arial", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5))
        row = tk.Frame(frame)
        row.pack(fill="x", padx=20, pady=3)
        tk.Label(row, text="Format:", width=14, anchor="w").pack(side="left")
        combo = ttk.Combobox(row, textvariable=self.preview_format_var,
                             values=PREVIEW_FORMATS, state="readonly", width=10)
        combo.pack(side="left")
        tk.Label(frame, text="Applies to full preview and contact sheets.",
                 fg="gray").pack(anchor="w", padx=20)

        # Thumbnail format
        tk.Label(frame, text="Thumbnail output format", font=("Arial", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5))
        row = tk.Frame(frame)
        row.pack(fill="x", padx=20, pady=3)
        tk.Label(row, text="Format:", width=14, anchor="w").pack(side="left")
        combo = ttk.Combobox(row, textvariable=self.thumb_format_var,
                             values=PREVIEW_FORMATS, state="readonly", width=10)
        combo.pack(side="left")
        tk.Label(frame, text="Applies to thumbnail tier.",
                 fg="gray").pack(anchor="w", padx=20)

        # Preview dimensions
        tk.Label(frame, text="Preview max dimensions (px)", font=("Arial", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5))
        for key in ("PREVIEW_WIDTH", "PREVIEW_HEIGHT", "THUMB_WIDTH", "THUMB_HEIGHT"):
            label_map = {
                "PREVIEW_WIDTH": "Preview width",
                "PREVIEW_HEIGHT": "Preview height",
                "THUMB_WIDTH": "Thumbnail width",
                "THUMB_HEIGHT": "Thumbnail height",
            }
            row = tk.Frame(frame)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label_map[key], width=14, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=self.int_vars[key], width=10).pack(side="left")

        # Quality settings
        tk.Label(frame, text="Quality", font=("Arial", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5))
        for key in ("AVIF_QUALITY", "AVIF_SPEED", "THUMB_QUALITY"):
            label_map = {
                "AVIF_QUALITY": "AVIF quality (0-100)",
                "AVIF_SPEED": "AVIF speed (0=best, 10=fastest)",
                "THUMB_QUALITY": "Thumbnail quality (0-100)",
            }
            row = tk.Frame(frame)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label_map[key], width=28, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=self.int_vars[key], width=10).pack(side="left")

    def _build_numbers(self, tabs, tab_name):
        frame = tk.Frame(tabs)
        tabs.add(frame, text=tab_name)
        for key, label, tab in INT_FIELDS:
            if tab != tab_name:
                continue
            row = tk.Frame(frame)
            row.pack(fill="x", padx=10, pady=3)
            tk.Label(row, text=label, width=28, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=self.int_vars[key], width=10).pack(side="left")

        # Naming mode in Pipeline tab
        if tab_name == "Pipeline":
            tk.Label(frame, text="", height=1).pack()  # spacer
            tk.Label(frame, text="Naming mode", font=("Arial", 10, "bold")).pack(
                anchor="w", padx=10, pady=(10, 5))
            row = tk.Frame(frame)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text="Mode:", width=14, anchor="w").pack(side="left")
            combo = ttk.Combobox(row, textvariable=self.naming_mode_var,
                                 values=NAMING_MODES, state="readonly", width=14)
            combo.pack(side="left")
            tk.Label(frame, text="manual = prompt per asset; automation = use source name",
                     fg="gray").pack(anchor="w", padx=20)

    def _build_appearance(self, tabs):
        frame = tk.Frame(tabs)
        tabs.add(frame, text="Appearance")
        tk.Label(frame, text="Theme", font=("Arial", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5))
        tk.Radiobutton(frame, text="Dark", variable=self.theme_var,
                       value="dark").pack(anchor="w", padx=20)
        tk.Radiobutton(frame, text="Light", variable=self.theme_var,
                       value="light").pack(anchor="w", padx=20)

    # ── actions ──

    def _browse(self, key):
        picked = filedialog.askopenfilename(title=f"Locate {key}",
                                            filetypes=[("Executables", "*.exe"),
                                                       ("All files", "*.*")])
        if picked:
            self.path_vars[key].set(picked)

    def _auto(self, key):
        self.path_vars[key].set("")

    def _refresh_path_status(self):
        for key, label in PATH_FIELDS:
            status = self.path_status.get(key)
            if status is None:
                continue
            found = self._resolved_path(key).exists()
            status.config(text="found ✓" if found else "missing ✗",
                          fg="green" if found else "red")

    def _refresh_mcp_status(self):
        from requirements_check import _mcp_reachable
        try:
            ok = _mcp_reachable(self.config)
        except Exception:
            ok = False
        url = getattr(self.config, "AFFINITY_MCP_URL", "?")
        self.mcp_label.config(
            text=f"MCP: {url} — {'reachable ✓' if ok else 'not answering ✗ (open Affinity, enable Settings → MCP Server)'}",
            fg="green" if ok else "red")

    def _reset(self):
        AppSettings(self.config.SETTINGS_FILE).save({})
        self.config._apply_user_settings()
        self.destroy()
        if self.on_saved:
            self.on_saved()

    def _save(self):
        values = {
            "ENGINE": self.engine_var.get(),
            "THEME": self.theme_var.get(),
            "PREVIEW_FORMAT": self.preview_format_var.get(),
            "THUMB_FORMAT": self.thumb_format_var.get(),
            "NAMING_MODE": self.naming_mode_var.get(),
        }
        try:
            for key, var in self.int_vars.items():
                values[key] = int(var.get().strip())
            for key, var in self.path_vars.items():
                text = var.get().strip()
                if text:
                    values[key] = text
            values["SUPPORTED_SOURCE_EXTENSIONS"] = sorted(
                e for e, var in self.format_vars.items() if var.get())
            saved = AppSettings(self.config.SETTINGS_FILE).save(values)
            self.config._apply_user_settings()
        except ValueError as error:
            self.error_label.config(text=f"Invalid number: {error}")
            return
        _ = saved
        self.destroy()
        if self.on_saved:
            self.on_saved()
