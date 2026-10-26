"""
Sync engine for SaveVault.

Recursively compares a local save directory (including all subdirectories)
against the mirrored folder tree in Google Drive, produces a SyncPlan
describing what needs to happen, and executes it.

Drive folder structure mirrors local structure exactly:

    My Drive/Save Games/<Game>/          ← game.drive_folder_id
        save.dat
        profile.sav
        slots/                           ← subfolder created automatically
            slot1.dat
            slot2.dat
        backups/
            auto_save.dat

File status categories
----------------------
IN_SYNC       Both sides exist and timestamps are within tolerance (±2 s).
LOCAL_ONLY    File exists locally but not on Drive.
DRIVE_ONLY    File exists on Drive but not locally.
LOCAL_NEWER   Both exist; local mtime is newer than Drive mtime.
DRIVE_NEWER   Both exist; Drive mtime is newer than local mtime.
CONFLICT      Both sides were modified after the last successful sync.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from googleapiclient.errors import HttpError

from .drive import DriveClient, DriveFile
from .storage import GameEntry

# Timestamp comparison tolerance in seconds
_MTIME_TOLERANCE = 2.0


class FileStatus(Enum):
    IN_SYNC     = auto()
    LOCAL_ONLY  = auto()
    DRIVE_ONLY  = auto()
    LOCAL_NEWER = auto()
    DRIVE_NEWER = auto()
    CONFLICT    = auto()


@dataclass
class FileDiff:
    """The comparison result for a single file (anywhere in the tree)."""

    # Relative path from the game root, using forward slashes: "slots/slot1.dat"
    rel_path:    str
    status:      FileStatus
    local_path:  Optional[Path]     = None
    local_mtime: Optional[datetime] = None
    local_size:  int                = 0
    drive_file:  Optional[DriveFile] = None
    # Drive folder ID that directly contains this file
    drive_parent_id: Optional[str]  = None

    @property
    def name(self) -> str:
        """Filename only (last component of rel_path)."""
        return self.rel_path.split("/")[-1]

    @property
    def drive_mtime(self) -> Optional[datetime]:
        """Parse the Drive modified_time string to a timezone-aware datetime."""
        if self.drive_file is None or not self.drive_file.modified_time:
            return None
        try:
            dt = datetime.fromisoformat(
                self.drive_file.modified_time.replace("Z", "+00:00")
            )
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


class ConflictResolution(Enum):
    """User's choice for a CONFLICT file."""
    KEEP_LOCAL = auto()
    KEEP_DRIVE = auto()


@dataclass
class SyncPlan:
    """The full planned sync for one game, before execution."""

    game:  GameEntry
    diffs: list[FileDiff] = field(default_factory=list)

    @property
    def uploads(self) -> list[FileDiff]:
        return [d for d in self.diffs
                if d.status in (FileStatus.LOCAL_ONLY, FileStatus.LOCAL_NEWER)]

    @property
    def downloads(self) -> list[FileDiff]:
        return [d for d in self.diffs
                if d.status in (FileStatus.DRIVE_ONLY, FileStatus.DRIVE_NEWER)]

    @property
    def conflicts(self) -> list[FileDiff]:
        return [d for d in self.diffs if d.status == FileStatus.CONFLICT]

    @property
    def in_sync(self) -> list[FileDiff]:
        return [d for d in self.diffs if d.status == FileStatus.IN_SYNC]

    @property
    def has_work(self) -> bool:
        return bool(self.uploads or self.downloads or self.conflicts)


# ---------------------------------------------------------------------- #
# Progress reporting                                                       #
# ---------------------------------------------------------------------- #

@dataclass
class SyncProgress:
    """Progress snapshot delivered via callback."""
    current_file: str        = ""
    files_done:   int        = 0
    files_total:  int        = 0
    bytes_sent:   int        = 0
    bytes_total:  int        = 0
    message:      str        = ""
    error:        Optional[str] = None
    done:         bool       = False


ProgressCallback = Callable[[SyncProgress], None]


# ---------------------------------------------------------------------- #
# Core engine                                                              #
# ---------------------------------------------------------------------- #

class SyncEngine:
    """
    Handles recursive diffing and execution of syncs between a local
    directory tree and the mirrored Google Drive folder tree.
    """

    def __init__(self, drive: DriveClient) -> None:
        self._drive        = drive
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Signal any running sync to stop after the current file."""
        self._cancel_event.set()

    # ------------------------------------------------------------------ #
    # build_plan                                                           #
    # ------------------------------------------------------------------ #

    def build_plan(self, game: GameEntry) -> SyncPlan:
        """
        Recursively compare the local save directory against Drive and
        return a SyncPlan.

        Args:
            game: The GameEntry to inspect.

        Raises:
            FileNotFoundError: If the local path does not exist.
            HttpError:         On Drive API errors.
        """
        local_root = Path(game.local_path)
        if not local_root.exists():
            raise FileNotFoundError(f"Local path not found: {local_root}")

        last_sync_dt = game.last_sync_dt()

        # Walk local tree: rel_path (str, forward slashes) → local Path
        local_files: dict[str, Path] = {}
        try:
            for dirpath, dirnames, filenames in os.walk(local_root):
                # Skip hidden directories (e.g. .git)
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in filenames:
                    if fname.startswith("."):
                        continue
                    abs_path = Path(dirpath) / fname
                    rel = abs_path.relative_to(local_root).as_posix()
                    local_files[rel] = abs_path
        except PermissionError as exc:
            raise PermissionError(f"Cannot read local directory: {exc}") from exc

        # Walk Drive tree: rel_path → (DriveFile, parent_folder_id)
        drive_files: dict[str, tuple[DriveFile, str]] = {}
        if game.drive_folder_id:
            self._walk_drive(
                folder_id=game.drive_folder_id,
                prefix="",
                out=drive_files,
            )

        # Build diffs
        all_paths = set(local_files) | set(drive_files)
        diffs: list[FileDiff] = []

        for rel_path in sorted(all_paths):
            has_local = rel_path in local_files
            has_drive = rel_path in drive_files

            local_path  = local_files.get(rel_path)
            drive_tuple = drive_files.get(rel_path)
            drive_file      = drive_tuple[0] if drive_tuple else None
            drive_parent_id = drive_tuple[1] if drive_tuple else None

            local_mtime: Optional[datetime] = None
            local_size:  int = 0
            if local_path:
                try:
                    stat       = local_path.stat()
                    local_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    local_size  = stat.st_size
                except OSError:
                    has_local = False

            diff = FileDiff(
                rel_path=rel_path,
                status=FileStatus.IN_SYNC,
                local_path=local_path,
                local_mtime=local_mtime,
                local_size=local_size,
                drive_file=drive_file,
                drive_parent_id=drive_parent_id,
            )

            if has_local and not has_drive:
                diff.status = FileStatus.LOCAL_ONLY
            elif has_drive and not has_local:
                diff.status = FileStatus.DRIVE_ONLY
            else:
                drive_mtime = diff.drive_mtime
                if local_mtime and drive_mtime:
                    delta = (local_mtime - drive_mtime).total_seconds()
                    if abs(delta) <= _MTIME_TOLERANCE:
                        diff.status = FileStatus.IN_SYNC
                    elif last_sync_dt:
                        local_changed = local_mtime > last_sync_dt
                        drive_changed = drive_mtime > last_sync_dt
                        if local_changed and drive_changed:
                            diff.status = FileStatus.CONFLICT
                        elif delta > 0:
                            diff.status = FileStatus.LOCAL_NEWER
                        else:
                            diff.status = FileStatus.DRIVE_NEWER
                    else:
                        # No prior sync — whichever is newer wins
                        if delta > 0:
                            diff.status = FileStatus.LOCAL_NEWER
                        elif delta < 0:
                            diff.status = FileStatus.DRIVE_NEWER
                else:
                    diff.status = FileStatus.IN_SYNC

            diffs.append(diff)

        return SyncPlan(game=game, diffs=diffs)

    # ------------------------------------------------------------------ #
    # execute_plan                                                         #
    # ------------------------------------------------------------------ #

    def execute_plan(
        self,
        plan: SyncPlan,
        conflict_resolutions: Optional[dict[str, ConflictResolution]] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> Optional[str]:
        """
        Execute a SyncPlan, creating Drive subfolders as needed and
        uploading/downloading files recursively.

        Args:
            plan:                 The plan to execute.
            conflict_resolutions: Map of rel_path → ConflictResolution.
            progress_cb:          Optional progress callback (called on
                                  worker thread — marshal via root.after()).

        Returns:
            None on success, or an error message string on failure.
        """
        self._cancel_event.clear()

        if conflict_resolutions is None:
            conflict_resolutions = {}

        game      = plan.game
        local_root = Path(game.local_path)

        if not game.drive_folder_id:
            return "Drive folder ID is not set — add the game first."

        # Cache of rel_dir → Drive folder ID (avoids redundant API calls)
        # "" maps to the game root folder
        folder_id_cache: dict[str, str] = {"": game.drive_folder_id}

        # Collect actions
        actions: list[FileDiff] = []
        for diff in plan.diffs:
            if diff.status in (FileStatus.LOCAL_ONLY, FileStatus.LOCAL_NEWER):
                actions.append(diff)
            elif diff.status in (FileStatus.DRIVE_ONLY, FileStatus.DRIVE_NEWER):
                actions.append(diff)
            elif diff.status == FileStatus.CONFLICT:
                if diff.rel_path in conflict_resolutions:
                    actions.append(diff)

        total = len(actions)
        _report(progress_cb, SyncProgress(files_total=total, message="Starting sync…"))

        for idx, diff in enumerate(actions):
            if self._cancel_event.is_set():
                _report(progress_cb, SyncProgress(
                    files_done=idx, files_total=total,
                    message="Sync cancelled.", done=True,
                ))
                return "Sync cancelled by user."

            _report(progress_cb, SyncProgress(
                current_file=diff.rel_path,
                files_done=idx,
                files_total=total,
                message=f"Processing {diff.rel_path}…",
            ))

            try:
                effective_status = diff.status
                if diff.status == FileStatus.CONFLICT:
                    resolution = conflict_resolutions.get(diff.rel_path)
                    if resolution == ConflictResolution.KEEP_LOCAL:
                        effective_status = FileStatus.LOCAL_NEWER
                    elif resolution == ConflictResolution.KEEP_DRIVE:
                        effective_status = FileStatus.DRIVE_NEWER
                    else:
                        continue

                if effective_status in (FileStatus.LOCAL_ONLY, FileStatus.LOCAL_NEWER):
                    # Ensure the Drive subfolder path exists
                    parent_id = self._ensure_drive_path(
                        rel_path=diff.rel_path,
                        game_folder_id=game.drive_folder_id,
                        cache=folder_id_cache,
                    )
                    existing_id = diff.drive_file.file_id if diff.drive_file else None
                    self._drive.upload_file(
                        local_path=diff.local_path,
                        folder_id=parent_id,
                        existing_file_id=existing_id,
                        progress_callback=lambda sent, tot, _cb=progress_cb, _n=diff.rel_path: _report(
                            _cb, SyncProgress(current_file=_n, bytes_sent=sent, bytes_total=tot)
                        ),
                    )

                elif effective_status in (FileStatus.DRIVE_ONLY, FileStatus.DRIVE_NEWER):
                    # Reconstruct the local path (creating parent dirs as needed)
                    dest = local_root / Path(diff.rel_path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    self._drive.download_file(
                        file_id=diff.drive_file.file_id,
                        local_path=dest,
                        progress_callback=lambda recv, tot, _cb=progress_cb, _n=diff.rel_path: _report(
                            _cb, SyncProgress(current_file=_n, bytes_sent=recv, bytes_total=tot)
                        ),
                    )

            except HttpError as exc:
                msg = f"Drive API error on '{diff.rel_path}': {exc}"
                _report(progress_cb, SyncProgress(
                    current_file=diff.rel_path, files_done=idx,
                    files_total=total, error=msg, done=True,
                ))
                return msg
            except (FileNotFoundError, PermissionError, OSError) as exc:
                msg = f"File error on '{diff.rel_path}': {exc}"
                _report(progress_cb, SyncProgress(
                    current_file=diff.rel_path, files_done=idx,
                    files_total=total, error=msg, done=True,
                ))
                return msg

        _report(progress_cb, SyncProgress(
            files_done=total, files_total=total,
            message="Sync complete.", done=True,
        ))
        return None

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _walk_drive(
        self,
        folder_id: str,
        prefix:    str,
        out:       dict[str, tuple[DriveFile, str]],
    ) -> None:
        """
        Recursively list all files under a Drive folder.

        Populates ``out`` with:
            rel_path (forward-slash, no leading slash) →
                (DriveFile, parent_folder_id)

        Folders themselves are not added to ``out`` — only files.
        """
        items = self._drive.list_files_in_folder(folder_id)
        for item in items:
            rel = f"{prefix}{item.name}" if not prefix else f"{prefix}/{item.name}"
            if item.mime_type == "application/vnd.google-apps.folder":
                # Recurse into subfolder
                self._walk_drive(
                    folder_id=item.file_id,
                    prefix=rel,
                    out=out,
                )
            else:
                out[rel] = (item, folder_id)

    def _ensure_drive_path(
        self,
        rel_path:       str,
        game_folder_id: str,
        cache:          dict[str, str],
    ) -> str:
        """
        Walk the directory components of rel_path, creating Drive
        subfolders as needed, and return the Drive folder ID that
        should directly contain the file.

        Args:
            rel_path:       Relative path like "slots/slot1.dat"
            game_folder_id: Drive ID of the game root folder.
            cache:          Mutable cache of rel_dir → Drive folder ID.

        Returns:
            Drive folder ID of the immediate parent of the file.
        """
        parts = rel_path.split("/")
        # File is at the game root level — no subfolders needed
        if len(parts) == 1:
            return game_folder_id

        # Walk through directory components (all parts except the filename)
        current_id  = game_folder_id
        current_rel = ""
        for part in parts[:-1]:
            current_rel = f"{current_rel}/{part}" if current_rel else part
            if current_rel in cache:
                current_id = cache[current_rel]
            else:
                current_id = self._drive.get_or_create_subfolder(
                    name=part, parent_id=current_id
                )
                cache[current_rel] = current_id

        return current_id


# ---------------------------------------------------------------------- #
# Helpers                                                                  #
# ---------------------------------------------------------------------- #

def _report(cb: Optional[ProgressCallback], progress: SyncProgress) -> None:
    """Safely call the progress callback if one was provided."""
    if cb is not None:
        try:
            cb(progress)
        except Exception:
            pass
