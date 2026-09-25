"""
session.py

Persistent queue/session storage and per-folder asset state tracking.

SessionManager: global job queue persistence (data/session.json).
AssetStateManager: per-folder .kaelovun_state.json for resume after interruption.
"""

import json
from pathlib import Path
from datetime import datetime, timezone


class SessionManager:

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def save(self, jobs):
        data = []
        for job in jobs:
            data.append({
                "source": str(job.source_file),
                "preview": str(job.preview_file) if job.preview_file else None,
                "archive": str(job.archive_file) if job.archive_file else None,
                "name": job.final_name,
                "status": job.status.value,
                "error": job.error_message,
                "retry": job.retry_count,
            })
        with open(self.config.SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        self.logger.info("Session saved.")

    def load(self):
        file = self.config.SESSION_FILE
        if not file.exists():
            return []
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.logger.info("Session loaded.")
        return data

    def failed_jobs(self):
        """
        Entries from the last session that never reached "done". Filters to
        ones whose source file is still on disk — a job only gets renamed
        after it fully succeeds, so an incomplete job's source is always
        still sitting at its original path, safe to reprocess from scratch.
        """
        recoverable = []
        for entry in self.load():
            if entry.get("status") == "done":
                continue
            source = Path(entry["source"])
            if source.exists():
                recoverable.append(source)
            else:
                self.logger.warning(f"Skipping unrecoverable session entry (source missing): {entry['source']}")
        return recoverable


class AssetStateManager:
    """
    Per-folder state tracking for resume after interruption.

    Creates .kaelovun_state.json in each processed folder.

    State file format:
    {
        "folder": "C:\\\\project",
        "status": "completed",          // pending | processing | completed | interrupted
        "started_at": "2026-09-25T10:00:00Z",
        "completed_at": "2026-09-25T10:05:00Z",
        "interrupted_at": null,
        "files": {
            "logo.psd": {
                "status": "completed",
                "archive": "project.rar",
                "preview": "logo.avif",
                "thumb": "logo.thumb.avif",
                "layers_hidden": true,
                "error": null
            }
        }
    }
    """

    STATE_FILE_NAME = ".kaelovun_state.json"

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def state_path(self, folder: Path) -> Path:
        """Return the path to the state file for a given folder."""
        return folder / self.STATE_FILE_NAME

    def load_state(self, folder: Path) -> dict:
        """Load the state file for a folder. Returns empty state if not found."""
        path = self.state_path(folder)
        if not path.exists():
            return self._empty_state(folder)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load state file {path}: {e}")
            return self._empty_state(folder)

    def save_state(self, folder: Path, state: dict):
        """Save the state file for a folder."""
        path = self.state_path(folder)
        state["folder"] = str(folder)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
        self.logger.info(f"State saved: {path}")

    def _empty_state(self, folder: Path) -> dict:
        return {
            "folder": str(folder),
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "interrupted_at": None,
            "files": {}
        }

    def start_processing(self, folder: Path):
        """Mark the folder as being processed."""
        state = self.load_state(folder)
        state["status"] = "processing"
        state["started_at"] = datetime.now(timezone.utc).isoformat()
        state["interrupted_at"] = None
        self.save_state(folder, state)

    def mark_file_completed(self, folder: Path, filename: str, archive_name: str = None,
                            preview_name: str = None, thumb_name: str = None):
        """Mark a single file as completed."""
        state = self.load_state(folder)
        state["files"][filename] = {
            "status": "completed",
            "archive": archive_name,
            "preview": preview_name,
            "thumb": thumb_name,
            "layers_hidden": True,
            "error": None
        }
        self.save_state(folder, state)

    def mark_file_failed(self, folder: Path, filename: str, error: str):
        """Mark a single file as failed."""
        state = self.load_state(folder)
        if filename in state["files"]:
            state["files"][filename]["status"] = "failed"
            state["files"][filename]["error"] = error
        self.save_state(folder, state)

    def mark_interrupted(self, folder: Path):
        """Mark the folder as interrupted (power loss, crash, etc.)."""
        state = self.load_state(folder)
        state["status"] = "interrupted"
        state["interrupted_at"] = datetime.now(timezone.utc).isoformat()
        self.save_state(folder, state)

    def mark_completed(self, folder: Path):
        """Mark the folder as fully completed."""
        state = self.load_state(folder)
        state["status"] = "completed"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        state["interrupted_at"] = None
        self.save_state(folder, state)

    def get_pending_files(self, folder: Path, scannable_files: list) -> list:
        """
        Return files that need processing.

        A file needs processing if:
        - It's not in the state file (new folder)
        - Its status is "interrupted" or "failed"
        - Its corresponding .rar archive doesn't exist on disk

        Returns list of (filename, Job) tuples for pending files.
        """
        state = self.load_state(folder)
        pending = []
        existing_archives = set()

        # Check for existing .rar archives in the folder
        for f in folder.rglob("*.rar"):
            existing_archives.add(f.name)

        for item in scannable_files:
            filename = item.source_file.name
            file_state = state["files"].get(filename)

            # If state says completed AND archive exists, skip
            if file_state and file_state["status"] == "completed":
                archive_name = file_state.get("archive")
                if archive_name and archive_name in existing_archives:
                    continue

            # If archive already exists on disk (from previous run), skip
            if item.source_file.stem + ".rar" in existing_archives:
                continue

            pending.append(item)

        return pending
