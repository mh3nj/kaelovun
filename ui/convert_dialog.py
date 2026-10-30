"""
convert_dialog.py

"Convert Archives" window: change the format of archives you already have
(RAR <-> 7z <-> ZIP, TAR.* -> any) without touching the Adobe/Affinity pipeline.

Safe by construction (see pipeline/convert.py): the original is never modified,
the result is verified before it appears, and "remove original" means the
Recycle Bin. Drag files or folders onto the list if tkinterdnd2 is installed.
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from files.app_settings import AppSettings
from files.archive import ArchiveManager
from files.archive_backends import human_size
from files.archive_prefs import load_prefs
from pipeline.convert import ArchiveConverter, ConvertOptions

TARGET_LABELS = {"zip": "ZIP  (most compatible)", "7z": "7-Zip  (7z, smallest)", "rar": "WinRAR  (RAR5)"}
ORIGINAL_LABELS = {"keep": "Keep the original", "recycle": "Move the original to the Recycle Bin"}
LEVEL_NAMES = {"fast": "Fast", "normal": "Normal", "best": "Best"}
LEVEL_HINTS = {"fast": "7z -mx1, RAR -m1, ZIP 1",
               "normal": "7z -mx5, RAR -m3, ZIP 6",
               "best": "7z -mx9, RAR -m5, ZIP 9"}


class ConvertDialog(tk.Toplevel):

    def __init__(self, parent, config, logger, theme: dict, initial_paths=None):
        super().__init__(parent)
        self.config, self.logger, self.theme = config, logger, theme
        self.title("Convert Archives")
        self.geometry("720x720")
        self.minsize(640, 620)
        self.transient(parent)

        self._events: "queue.Queue" = queue.Queue()
        self._cancel = threading.Event()
        self._worker = None
        self._paths = []

        stored = AppSettings(config.SETTINGS_FILE).get("CONVERT_DEFAULTS", {}) or {}
        default_level = load_prefs(config).level
        self.level_labels = {"": f"Settings default ({LEVEL_NAMES.get(default_level, default_level)})"}
        self.level_labels.update({key: f"{name} ({LEVEL_HINTS[key]})" for key, name in LEVEL_NAMES.items()})
        self.target = tk.StringVar(value=TARGET_LABELS.get(stored.get("target", "7z"), TARGET_LABELS["7z"]))
        self.level = tk.StringVar(value=self.level_labels.get(stored.get("level", ""), self.level_labels[""]))
        self.original = tk.StringVar(value=ORIGINAL_LABELS.get(stored.get("original", "keep"), ORIGINAL_LABELS["keep"]))
        self.only_smaller = tk.BooleanVar(value=stored.get("only_if_smaller", True))
        self.recursive = tk.BooleanVar(value=stored.get("recursive", True))
        self.paranoid = tk.BooleanVar(value=stored.get("paranoid", False))
        self.output_dir = tk.StringVar(value=stored.get("output_dir", ""))
        self.password = tk.StringVar()

        self._build()
        self._apply_theme()
        self._tool_status()
        self._enable_drop()
        if initial_paths:
            self.add_paths(initial_paths)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._pump)

    # ── layout ───────────────────────────────────────────────

    def _build(self):
        top = tk.Frame(self)
        top.pack(fill="both", expand=False, padx=10, pady=(10, 4))
        tk.Label(top, text="Archives and folders to convert (drag them here, or use the buttons):",
                 anchor="w").pack(fill="x")
        body = tk.Frame(top)
        body.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(body, height=7, selectmode="extended", activestyle="none")
        sb = tk.Scrollbar(body, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        btns = tk.Frame(top)
        btns.pack(fill="x", pady=4)
        for text, cmd in (("Add archives...", self._add_files), ("Add folder...", self._add_folder),
                          ("Remove selected", self._remove), ("Clear", self._clear)):
            tk.Button(btns, text=text, command=cmd).pack(side="left", padx=(0, 5))
        self.count_label = tk.Label(btns, text="", anchor="e")
        self.count_label.pack(side="right")

        opts = tk.LabelFrame(self, text="Options")
        opts.pack(fill="x", padx=10, pady=4)
        self._opt_row(opts, "Convert to", ttk.Combobox(opts, textvariable=self.target, state="readonly",
                                                       values=list(TARGET_LABELS.values()), width=36))
        self._opt_row(opts, "Compression", ttk.Combobox(opts, textvariable=self.level, state="readonly",
                                                        values=list(self.level_labels.values()), width=38))
        self._opt_row(opts, "Original file", ttk.Combobox(opts, textvariable=self.original, state="readonly",
                                                          values=list(ORIGINAL_LABELS.values()), width=36))
        row = tk.Frame(opts)
        row.pack(fill="x", padx=8, pady=2)
        tk.Label(row, text="Save results in", width=14, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.output_dir, width=34).pack(side="left")
        tk.Button(row, text="Browse", command=self._pick_output).pack(side="left", padx=4)
        tk.Label(row, text="(blank = next to each original)", fg="gray").pack(side="left")
        row = tk.Frame(opts)
        row.pack(fill="x", padx=8, pady=2)
        tk.Label(row, text="Password", width=14, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.password, show="*", width=22).pack(side="left")
        tk.Label(row, text="only for encrypted archives; the result is NOT encrypted", fg="gray").pack(side="left", padx=6)
        for text, var in (("Only keep a result that is smaller than the original", self.only_smaller),
                          ("Look inside sub-folders", self.recursive),
                          ("Paranoid check (compare CRC32 of every file; slower)", self.paranoid)):
            tk.Checkbutton(opts, text=text, variable=var, anchor="w").pack(fill="x", padx=8)

        self.tool_label = tk.Label(self, text="", anchor="w", justify="left")
        self.tool_label.pack(fill="x", padx=12)

        run = tk.Frame(self)
        run.pack(fill="x", padx=10, pady=6)
        self.plan_btn = tk.Button(run, text="Preview (change nothing)", command=lambda: self._start(True))
        self.plan_btn.pack(side="left", padx=(0, 5))
        self.go_btn = tk.Button(run, text="Convert", width=12, command=lambda: self._start(False))
        self.go_btn.pack(side="left", padx=(0, 5))
        self.stop_btn = tk.Button(run, text="Stop", width=8, command=self._stop, state="disabled")
        self.stop_btn.pack(side="left")
        tk.Button(run, text="Close", width=8, command=self._close).pack(side="right")

        self.stage_label = tk.Label(self, text="", anchor="w")
        self.stage_label.pack(fill="x", padx=12)
        self.bar = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.bar.pack(fill="x", padx=12, pady=(0, 4))

        self.log = tk.Text(self, height=10, state="disabled", wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    @staticmethod
    def _opt_row(parent, label, widget):
        row = tk.Frame(parent)
        row.pack(fill="x", padx=8, pady=2)
        tk.Label(row, text=label, width=14, anchor="w").pack(side="left")
        widget.pack(in_=row, side="left")

    def _apply_theme(self):
        t = self.theme
        self.configure(bg=t["bg"])
        for w in self.winfo_children():
            self._theme_widget(w, t)
        self.listbox.configure(bg=t["entry_bg"], fg=t["entry_fg"], selectbackground="#555555")
        self.log.configure(bg=t["log_bg"], fg=t["log_fg"])

    def _theme_widget(self, w, t):
        cls = w.winfo_class()
        try:
            if cls in ("Frame", "Labelframe", "Toplevel"):
                w.configure(bg=t["frame_bg"])
                if cls == "Labelframe":
                    w.configure(fg=t["fg"])
            elif cls == "Label":
                if w is not self.tool_label:
                    w.configure(bg=t["frame_bg"], fg=w.cget("fg") if w.cget("fg") == "gray" else t["fg"])
                else:
                    w.configure(bg=t["frame_bg"])
            elif cls == "Button":
                w.configure(bg=t["button_bg"], fg=t["button_fg"])
            elif cls == "Checkbutton":
                w.configure(bg=t["frame_bg"], fg=t["fg"], selectcolor=t["entry_bg"], activebackground=t["frame_bg"])
            elif cls == "Entry":
                w.configure(bg=t["entry_bg"], fg=t["entry_fg"], insertbackground=t["fg"])
        except tk.TclError:
            pass
        for child in w.winfo_children():
            self._theme_widget(child, t)

    def _tool_status(self):
        status = ArchiveManager(self.config, self.logger).format_status()
        lines = []
        for fmt, name in (("7z", "7-Zip (7z output, reads RAR)"), ("rar", "WinRAR (RAR output)")):
            ok, why = status[fmt]
            lines.append(f"{name}: {'found' if ok else 'NOT FOUND - ' + why}")
        self.tool_label.config(text="\n".join(lines),
                               fg="green" if all(status[f][0] for f in ("7z", "rar")) else "#c07000")

    # ── drag & drop (optional) ───────────────────────────────

    def _enable_drop(self):
        try:
            from tkinterdnd2 import DND_FILES
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", lambda e: self.add_paths(self.tk.splitlist(e.data)))
        except Exception:
            pass  # tkinterdnd2 not installed or root is a plain Tk: buttons still work

    # ── list handling ────────────────────────────────────────

    def add_paths(self, paths):
        for raw in paths:
            p = Path(raw)
            if p.exists() and p not in self._paths:
                self._paths.append(p)
                self.listbox.insert("end", str(p))
        self._update_count()

    def _add_files(self):
        picked = filedialog.askopenfilenames(
            parent=self, title="Choose archives",
            filetypes=[("Archives", "*.zip *.rar *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz *.001"),
                       ("All files", "*.*")])
        self.add_paths(picked)

    def _add_folder(self):
        picked = filedialog.askdirectory(parent=self, title="Choose a folder of archives")
        if picked:
            self.add_paths([picked])

    def _remove(self):
        for index in reversed(self.listbox.curselection()):
            self.listbox.delete(index)
            del self._paths[index]
        self._update_count()

    def _clear(self):
        self.listbox.delete(0, "end")
        self._paths.clear()
        self._update_count()

    def _pick_output(self):
        picked = filedialog.askdirectory(parent=self, title="Save converted archives in")
        if picked:
            self.output_dir.set(picked)

    def _update_count(self):
        self.count_label.config(text=f"{len(self._paths)} item(s)")

    # ── running ──────────────────────────────────────────────

    def _invert(self, labels, value):
        return next((k for k, v in labels.items() if v == value), "")

    def _build_options(self, dry_run: bool) -> ConvertOptions:
        return ConvertOptions(
            target=self._invert(TARGET_LABELS, self.target.get()) or "7z",
            level=self._invert(self.level_labels, self.level.get()) or None,
            keep_original=self._invert(ORIGINAL_LABELS, self.original.get()) or "keep",
            output_dir=Path(self.output_dir.get()) if self.output_dir.get().strip() else None,
            only_if_smaller=self.only_smaller.get(),
            password=self.password.get() or None,
            dry_run=dry_run,
            verify="paranoid" if self.paranoid.get() else None,
        )

    def _remember(self, opts: ConvertOptions):
        try:
            AppSettings(self.config.SETTINGS_FILE).set("CONVERT_DEFAULTS", {
                "target": opts.target, "level": opts.level or "", "original": opts.keep_original,
                "only_if_smaller": opts.only_if_smaller, "recursive": self.recursive.get(),
                "paranoid": self.paranoid.get(), "output_dir": self.output_dir.get().strip(),
            })
        except Exception:
            pass

    def _start(self, dry_run: bool):
        if self._worker and self._worker.is_alive():
            return
        if not self._paths:
            messagebox.showinfo("Convert Archives", "Add some archives or folders first.", parent=self)
            return
        opts = self._build_options(dry_run)
        ok, why = ArchiveManager(self.config, self.logger).format_status()[opts.target]
        if not ok:
            messagebox.showerror("Convert Archives", why, parent=self)
            return
        if opts.keep_original == "recycle" and not dry_run:
            if not messagebox.askyesno(
                    "Convert Archives",
                    "After each VERIFIED conversion the original goes to the Recycle Bin.\n\nContinue?",
                    parent=self):
                return
        self._remember(opts)
        self._cancel.clear()
        self._set_running(True)
        self._write(f"{'Previewing' if dry_run else 'Converting'} to {opts.target}...\n")

        converter = ArchiveConverter(self.config, self.logger)
        paths, recursive = list(self._paths), self.recursive.get()

        def work():
            try:
                targets = converter.discover(paths, recursive=recursive)
                if not targets:
                    self._events.put(("log", "No archives found in the selection.\n"))
                results = converter.convert_many(
                    targets, opts,
                    progress=lambda stage, pct: self._events.put(("progress", stage, pct)),
                    cancel=self._cancel.is_set,
                    on_result=lambda r: self._events.put(("log", r.line() + "\n")))
                self._events.put(("done", ArchiveConverter.summarize(results)))
            except Exception as exc:
                self._events.put(("done", f"Stopped: {exc}"))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _stop(self):
        self._cancel.set()
        self.stage_label.config(text="Stopping after the current step...")

    def _set_running(self, running: bool):
        for b in (self.plan_btn, self.go_btn):
            b.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")

    def _pump(self):
        try:
            while True:
                event = self._events.get_nowait()
                if event[0] == "progress":
                    _, stage, pct = event
                    self.stage_label.config(text=stage)
                    if pct is None:
                        self.bar.config(mode="indeterminate")
                        self.bar.start(15)
                    else:
                        self.bar.stop()
                        self.bar.config(mode="determinate", value=pct)
                elif event[0] == "log":
                    self._write(event[1])
                elif event[0] == "done":
                    self.bar.stop()
                    self.bar.config(mode="determinate", value=0)
                    self.stage_label.config(text="")
                    self._write("\n" + event[1] + "\n")
                    self._set_running(False)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._pump)

    def _write(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _close(self):
        if self._worker and self._worker.is_alive():
            if not messagebox.askyesno("Convert Archives", "A conversion is running. Stop it and close?", parent=self):
                return
            self._cancel.set()
        self.destroy()
