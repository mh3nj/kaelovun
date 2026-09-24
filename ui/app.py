"""
ui.py

Minimal control interface with progress tracking,
name history (arrow keys), and dark/light theme toggle.
"""

import tkinter as tk
from tkinter import filedialog, scrolledtext
from pathlib import Path
from PIL import Image, ImageTk

from pipeline.job import Job
from files.app_settings import AppSettings
from ui.settings_dialog import SettingsDialog


THEMES = {
    "dark": {
        "bg": "#2b2b2b",
        "fg": "#ffffff",
        "entry_bg": "#3c3c3c",
        "entry_fg": "#ffffff",
        "button_bg": "#4a4a4a",
        "button_fg": "#ffffff",
        "frame_bg": "#2b2b2b",
        "preview_bg": "#1e1e1e",
        "log_bg": "#1e1e1e",
        "log_fg": "#cccccc",
        "select_bg": "#3c3c3c",
    },
    "light": {
        "bg": "#f0f0f0",
        "fg": "#000000",
        "entry_bg": "#ffffff",
        "entry_fg": "#000000",
        "button_bg": "#e0e0e0",
        "button_fg": "#000000",
        "frame_bg": "#f0f0f0",
        "preview_bg": "#d0d0d0",
        "log_bg": "#ffffff",
        "log_fg": "#333333",
        "select_bg": "#ffffff",
    }
}


class ApplicationUI:

    def __init__(self, config, logger, scanner, queue, session=None):
        self.config = config
        self.logger = logger
        self.scanner = scanner
        self.queue = queue
        self.session = session
        self._theme = getattr(config, "THEME", "dark")

        self.current_request = None
        self.current_preview = None
        self._prompt_shown_for = None
        self._last_preview_version = -1

        # Name history
        self._name_history = []
        self._name_history_index = -1
        self._name_saved_typing = ""

        self.root = tk.Tk()
        self.root.title("Kaelovun")
        self.root.geometry("700x810+100+50")

        self._logo_images = {}
        self._current_logo_image = None
        self._load_logos()
        self._apply_window_icon()

        self.create_widgets()
        self.apply_theme()

    def create_widgets(self):
        # ── Branding: theme-aware logo + title ──
        self.brand_bar = tk.Frame(self.root)
        self.brand_bar.pack(fill="x", padx=10, pady=(10, 0))

        self.brand_logo = tk.Label(self.brand_bar, text="")
        self.brand_logo.pack(side="left", padx=(0, 8))

        self.brand_title = tk.Label(
            self.brand_bar, text="Kaelovun", font=("Arial", 14, "bold"), anchor="w"
        )
        self.brand_title.pack(side="left", fill="x", expand=True)
        self._refresh_brand_logo()

        # ── Top: folder + theme toggle ──
        top = tk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=(10, 0))

        self.folder_button = tk.Button(top, text="Select Folder", command=self.select_folder, width=14)
        self.folder_button.pack(side="left", padx=(0, 5))

        self.file_button = tk.Button(top, text="Select File", command=self.select_file, width=12)
        self.file_button.pack(side="left", padx=(0, 5))

        self.resume_failed_button = tk.Button(top, text="Resume Failed", command=self.resume_failed, width=13)
        self.resume_failed_button.pack(side="left", padx=(0, 5))

        self.theme_button = tk.Button(top, text="Theme", command=self.toggle_theme, width=8)
        self.theme_button.pack(side="right")

        self.settings_button = tk.Button(top, text="⚙ Settings", command=self.open_settings, width=10)
        self.settings_button.pack(side="right", padx=(0, 5))

        self.status_label = tk.Label(top, text=self._ready_text(), anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, padx=5)

        # ── Progress ──
        self.progress_label = tk.Label(self.root, text="", anchor="w", font=("Arial", 10))
        self.progress_label.pack(fill="x", padx=10, pady=(2, 0))

        # ── Preview ──
        self.preview_frame = tk.Frame(self.root)
        self.preview_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.preview_label = tk.Label(self.preview_frame, text="No preview")
        self.preview_label.pack(expand=True)

        # ── Name entry ──
        name_frame = tk.Frame(self.root)
        name_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(name_frame, text="Asset name:").pack(side="left")

        self.name_entry = tk.Entry(name_frame, font=("Arial", 12))
        self.name_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.name_entry.bind("<Return>", self.confirm_name)
        self.name_entry.bind("<Up>", self.history_up)
        self.name_entry.bind("<Down>", self.history_down)

        self.regen_button = tk.Button(name_frame, text="Regen Preview", command=self.regenerate_preview, width=12)
        self.regen_button.pack(side="right", padx=(5, 0))

        self.confirm_button = tk.Button(name_frame, text="Confirm", command=self.confirm_name, width=10)
        self.confirm_button.pack(side="right")

        # ── Controls ──
        ctrl = tk.Frame(self.root)
        ctrl.pack(fill="x", padx=10, pady=5)

        self.start_button = tk.Button(ctrl, text="Start Queue", command=self.start_queue, width=12)
        self.start_button.pack(side="left", padx=(0, 5))

        self.pause_button = tk.Button(ctrl, text="Pause", command=self.pause_queue, width=10)
        self.pause_button.pack(side="left", padx=5)

        self.resume_button = tk.Button(ctrl, text="Resume", command=self.resume_queue, width=10)
        self.resume_button.pack(side="left", padx=5)

        # ── Log ──
        self.log_area = scrolledtext.ScrolledText(
            self.root, height=10, state="disabled", font=("Consolas", 9)
        )
        self.log_area.pack(fill="x", padx=10, pady=(0, 10))

    # ──────────────────────────────────────────────
    # Theme
    # ──────────────────────────────────────────────

    def toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        self.config.THEME = self._theme
        try:
            AppSettings(self.config.SETTINGS_FILE).set("THEME", self._theme)
        except Exception:
            pass
        self.apply_theme()

    def _ready_text(self) -> str:
        engine = getattr(self.config, "ENGINE", "adobe").capitalize()
        return f"Ready ({engine})"

    # ──────────────────────────────────────────────
    # Settings
    # ──────────────────────────────────────────────

    def open_settings(self):
        SettingsDialog(self.root, self.config, on_saved=self._on_settings_saved)

    def _on_settings_saved(self):
        self._theme = getattr(self.config, "THEME", "dark")
        self.apply_theme()
        self.status_label.config(text=self._ready_text())
        self.logger.info("Settings saved.")

    def apply_theme(self):
        t = THEMES[self._theme]
        self.root.configure(bg=t["bg"])
        self.status_label.configure(bg=t["bg"], fg=t["fg"])
        self.progress_label.configure(bg=t["bg"], fg=t["fg"])
        self.preview_frame.configure(bg=t["preview_bg"])
        self.preview_label.configure(bg=t["preview_bg"], fg=t["fg"])
        self.name_entry.configure(bg=t["entry_bg"], fg=t["entry_fg"], insertbackground=t["fg"])
        self.log_area.configure(bg=t["log_bg"], fg=t["log_fg"])
        for w in (self.folder_button, self.resume_failed_button, self.theme_button, self.settings_button, self.start_button,
                  self.pause_button, self.resume_button, self.regen_button, self.confirm_button):
            w.configure(bg=t["button_bg"], fg=t["button_fg"])
        for child in self.root.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=t["frame_bg"])
                for grandchild in child.winfo_children():
                    if isinstance(grandchild, tk.Label):
                        grandchild.configure(bg=t["frame_bg"], fg=t["fg"])
        self._refresh_brand_logo()

    # ──────────────────────────────────────────────
    # Branding (theme-aware logo)
    # ──────────────────────────────────────────────

    def _icon_candidates(self, filename: str):
        """Possible on-disk locations for a branding asset."""
        import sys
        base = Path(__file__).resolve().parent.parent
        candidates = [
            base / "assets" / "icons" / filename,
            base / filename,
        ]
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            candidates.append(exe_dir / "_internal" / "assets" / "icons" / filename)
            candidates.append(exe_dir / "assets" / "icons" / filename)
        return candidates

    def _find_icon(self, filename: str):
        for candidate in self._icon_candidates(filename):
            try:
                if candidate.is_file():
                    return candidate
            except Exception:
                continue
        return None

    def _load_logos(self):
        """Load white/dark logos once; missing files simply disable branding."""
        for theme, filename in (("light", "icon-white.png"), ("dark", "icon-dark.png")):
            try:
                path = self._find_icon(filename)
                if not path:
                    continue
                img = Image.open(path)
                img.thumbnail((40, 40))
                self._logo_images[theme] = ImageTk.PhotoImage(img)
            except Exception:
                continue

    def _apply_window_icon(self):
        try:
            path = self._find_icon("icon-dark.png") or self._find_icon("icon-white.png")
            if not path:
                return
            img = Image.open(path)
            img.thumbnail((64, 64))
            icon = ImageTk.PhotoImage(img)
            # Keep a reference for the lifetime of the window.
            self._window_icon = icon
            self.root.iconphoto(True, icon)
        except Exception:
            pass

    def _refresh_brand_logo(self):
        """Swap the header logo to match the active theme."""
        try:
            # Dark UI pairs with the dark-background mark, light UI with white.
            logo = self._logo_images.get(self._theme)
            if logo is None:
                # Fall back to whichever mark loaded.
                logo = next(iter(self._logo_images.values()), None)
            if logo is None:
                return
            self._current_logo_image = logo
            if hasattr(self, "brand_logo"):
                self.brand_logo.config(image=logo, text="")
        except Exception:
            pass

    # ──────────────────────────────────────────────
    # Name history (arrow keys)
    # ──────────────────────────────────────────────

    def history_up(self, event=None):
        if not self._name_history:
            return
        if self._name_history_index == -1:
            self._name_saved_typing = self.name_entry.get()
            self._name_history_index = len(self._name_history) - 1
        elif self._name_history_index > 0:
            self._name_history_index -= 1
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, self._name_history[self._name_history_index])

    def history_down(self, event=None):
        if self._name_history_index == -1:
            return
        self._name_history_index += 1
        if self._name_history_index >= len(self._name_history):
            self._name_history_index = -1
            self.name_entry.delete(0, tk.END)
            self.name_entry.insert(0, self._name_saved_typing)
        else:
            self.name_entry.delete(0, tk.END)
            self.name_entry.insert(0, self._name_history[self._name_history_index])

    # ──────────────────────────────────────────────
    # Folder / Queue
    # ──────────────────────────────────────────────

    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        path = Path(folder)
        self.logger.info(f"Folder selected: {path}")
        self.status_label.config(text=f"Scanning: {path.name}...")
        self.root.update()
        jobs = self.scanner.scan_input(path)
        self.queue.add_jobs(jobs)
        self.status_label.config(text=f"{len(jobs)} package(s) queued from {path.name}")

    def select_file(self):
        """Select a single file or archive for processing."""
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("All supported", "*.psd *.ai *.eps *.indd *.afphoto *.afdesign *.afpub *.zip *.rar *.7z *.tar *.tar.gz *.tgz"),
                ("Adobe files", "*.psd *.ai *.eps *.indd"),
                ("Affinity files", "*.afphoto *.afdesign *.afpub"),
                ("Archives", "*.zip *.rar *.7z *.tar *.tar.gz *.tgz"),
                ("All files", "*.*")
            ]
        )
        if not file_path:
            return
        path = Path(file_path)
        self.logger.info(f"File selected: {path}")
        self.status_label.config(text=f"Scanning: {path.name}...")
        self.root.update()
        jobs = self.scanner.scan_input(path)
        self.queue.add_jobs(jobs)
        self.status_label.config(text=f"{len(jobs)} package(s) queued from {path.name}")

    def resume_failed(self):
        if not self.session:
            self.status_label.config(text="No session available")
            return
        sources = self.session.failed_jobs()
        if not sources:
            self.status_label.config(text="No incomplete jobs from last session")
            return
        jobs = [Job(source) for source in sources]
        self.queue.add_jobs(jobs)
        self.status_label.config(text=f"{len(jobs)} incomplete job(s) re-queued from last session")

    def start_queue(self):
        self.queue.start()
        self.status_label.config(text="Queue running...")
        self.monitor_requests()
        self.poll_progress()

    # ──────────────────────────────────────────────
    # Preview
    # ──────────────────────────────────────────────

    def show_preview(self, image_path: Path):
        if not image_path or not image_path.exists():
            return
        img = Image.open(image_path)
        img.thumbnail((500, 500))
        self.current_preview = ImageTk.PhotoImage(img)
        self.preview_label.config(image=self.current_preview, text="")

    # ──────────────────────────────────────────────
    # Naming
    # ──────────────────────────────────────────────

    def ask_for_name(self, request, preview):
        self.current_request = request
        self.show_preview(preview)
        self.name_entry.delete(0, tk.END)
        self.name_entry.focus()

    def confirm_name(self, event=None):
        name = self.name_entry.get().strip()
        if not name:
            return
        if self.current_request:
            self._name_history.append(name)
            self._name_history_index = -1
            self.current_request.submit(name)
            self.current_request = None
            self._prompt_shown_for = None
            self.name_entry.delete(0, tk.END)

    # ──────────────────────────────────────────────
    # Regenerate preview
    # ──────────────────────────────────────────────

    def regenerate_preview(self):
        if not self.queue.running:
            return
        processor = self.queue.processor
        if processor.name_request and processor.name_request.preview:
            self.status_label.config(text="Regenerating preview...")
            processor.name_request.request_regenerate()

    # ──────────────────────────────────────────────
    # Queue controls
    # ──────────────────────────────────────────────

    def pause_queue(self):
        self.queue.pause()
        self.status_label.config(text="Queue paused")

    def resume_queue(self):
        self.queue.resume()
        self.status_label.config(text="Queue running...")

    # ──────────────────────────────────────────────
    # Polling
    # ──────────────────────────────────────────────

    def monitor_requests(self):
        processor = self.queue.processor
        request = processor.name_request
        if request and request.preview and not request.name:
            preview_changed = request.preview_version != self._last_preview_version
            if id(request) != self._prompt_shown_for or preview_changed:
                self._prompt_shown_for = id(request)
                self._last_preview_version = request.preview_version
                self.ask_for_name(request, request.preview)
        if self.queue.running:
            self.root.after(500, self.monitor_requests)

    def poll_progress(self):
        p = self.queue.processor
        total = p._total_assets
        done = p._processed
        failed = p._failed
        left = total - done - failed
        if left < 0:
            left = 0

        if total > 0:
            self.progress_label.config(
                text=f"{done} done / {total} total — {left} left"
                + (f"  ({failed} failed)" if failed else "")
            )

        if self.queue.running or self.queue.paused:
            self.root.after(1000, self.poll_progress)

    # ──────────────────────────────────────────────
    # Log
    # ──────────────────────────────────────────────

    def log(self, message: str):
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    # ──────────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────────

    def run(self):
        self.root.mainloop()
