"""
Conflict resolution dialog for SaveVault.

Shown when the sync engine detects files modified on both sides since
the last successful sync.

Each conflicting file gets its own row with:
  • Filename
  • Local: last-modified timestamp + size
  • Drive: last-modified timestamp + size
  • Radio buttons: [Keep Local] / [Keep Drive]

Bottom buttons:
  • [Apply Top Choice to All ↑] — bulk apply the first row's choice
  • [Confirm]
  • [Cancel]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import customtkinter as ctk

from ..sync import ConflictResolution, FileDiff

_BG = "#1e1e2e"
_SURFACE = "#313147"
_HEADER = "#252535"
_TEXT = "#cdd6f4"
_MUTED = "#6c7086"
_ACCENT = "#7c3aed"
_ACCENT_HOVER = "#6d28d9"
_LOCAL_COL = "#3b82f6"   # blue tint for local
_DRIVE_COL = "#22c55e"   # green tint for drive


def _fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class _ConflictRow(ctk.CTkFrame):
    """Single conflict row widget."""

    def __init__(self, parent, diff: FileDiff, **kwargs) -> None:
        super().__init__(parent, fg_color=_SURFACE, corner_radius=6, **kwargs)
        self.diff = diff
        self._choice = ctk.StringVar(value="local")   # "local" or "drive"

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)

        # File name header
        ctk.CTkLabel(
            self,
            text=diff.name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_TEXT,
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, padx=10, pady=(8, 4), sticky="w")

        # Local info
        local_dt_str = _fmt_dt(diff.local_mtime)
        local_size_str = _fmt_size(diff.local_size)
        ctk.CTkLabel(
            self,
            text=f"💻  Local\n{local_dt_str}\n{local_size_str}",
            font=ctk.CTkFont(size=11),
            text_color=_TEXT,
            justify="left",
        ).grid(row=1, column=0, padx=10, pady=(0, 4), sticky="nw")

        # Drive info
        drive_dt_str = _fmt_dt(diff.drive_mtime)
        drive_size_str = _fmt_size(diff.drive_file.size if diff.drive_file else 0)
        ctk.CTkLabel(
            self,
            text=f"☁  Drive\n{drive_dt_str}\n{drive_size_str}",
            font=ctk.CTkFont(size=11),
            text_color=_TEXT,
            justify="left",
        ).grid(row=1, column=1, padx=10, pady=(0, 4), sticky="nw")

        # Radio buttons
        radio_frame = ctk.CTkFrame(self, fg_color="transparent")
        radio_frame.grid(row=1, column=2, padx=(4, 10), pady=(0, 4), sticky="ns")

        ctk.CTkRadioButton(
            radio_frame,
            text="Keep Local",
            value="local",
            variable=self._choice,
            font=ctk.CTkFont(size=12),
            text_color=_TEXT,
            fg_color=_LOCAL_COL,
            hover_color="#2563eb",
        ).pack(pady=(4, 4))

        ctk.CTkRadioButton(
            radio_frame,
            text="Keep Drive",
            value="drive",
            variable=self._choice,
            font=ctk.CTkFont(size=12),
            text_color=_TEXT,
            fg_color=_DRIVE_COL,
            hover_color="#16a34a",
        ).pack(pady=(0, 4))

    @property
    def resolution(self) -> ConflictResolution:
        """The user's chosen resolution for this file."""
        if self._choice.get() == "local":
            return ConflictResolution.KEEP_LOCAL
        return ConflictResolution.KEEP_DRIVE

    def set_choice(self, value: str) -> None:
        """Programmatically set 'local' or 'drive'."""
        self._choice.set(value)


class SyncConflictDialog(ctk.CTkToplevel):
    """
    Modal dialog for resolving sync conflicts for a single game.

    Args:
        parent:      Parent window.
        game_name:   Game display name for the title bar.
        conflicts:   List of FileDiff objects with CONFLICT status.
        on_confirm:  Called with a dict[filename → ConflictResolution].
                     Called with None if the user cancelled.
    """

    def __init__(
        self,
        parent,
        game_name: str,
        conflicts: list[FileDiff],
        on_confirm,
    ) -> None:
        super().__init__(parent)
        self._conflicts = conflicts
        self._on_confirm = on_confirm
        self._rows: list[_ConflictRow] = []

        self.title(f"Sync Conflict — {game_name}")
        self.geometry("600x520")
        self.resizable(False, True)
        self.configure(fg_color=_BG)
        self.grab_set()
        self.focus_force()

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Header
        ctk.CTkLabel(
            self,
            text="Sync Conflicts Detected",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=_TEXT,
        ).grid(row=0, column=0, padx=24, pady=(20, 2), sticky="w")

        ctk.CTkLabel(
            self,
            text=(
                "These files were changed on both your computer and Google Drive\n"
                "since the last sync. Choose which version to keep for each file."
            ),
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            justify="left",
        ).grid(row=0, column=0, padx=24, pady=(48, 8), sticky="w")

        # Column headers
        hdr = ctk.CTkFrame(self, fg_color=_HEADER, corner_radius=6)
        hdr.grid(row=0, column=0, padx=16, pady=(90, 0), sticky="ew")
        hdr.columnconfigure(0, weight=1)
        hdr.columnconfigure(1, weight=1)
        hdr.columnconfigure(2, weight=0)

        for col, label in enumerate(("File", "Timestamps & Size", "Resolution")):
            ctk.CTkLabel(
                hdr, text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_MUTED,
            ).grid(row=0, column=col, padx=10, pady=4, sticky="w")

        # Scrollable conflict rows
        scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=_SURFACE,
        )
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=4)
        scroll.columnconfigure(0, weight=1)

        for idx, diff in enumerate(self._conflicts):
            row = _ConflictRow(scroll, diff)
            row.grid(row=idx, column=0, sticky="ew", pady=(0, 6))
            self._rows.append(row)

        # Bottom buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=16, pady=(4, 16), sticky="ew")
        btn_frame.columnconfigure(0, weight=1)

        ctk.CTkButton(
            btn_frame,
            text="Apply Top Choice to All ↑",
            width=200,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=12),
            command=self._apply_to_all,
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        right_btns = ctk.CTkFrame(btn_frame, fg_color="transparent")
        right_btns.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            right_btns,
            text="Cancel",
            width=90,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=13),
            command=self._cancel,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            right_btns,
            text="Confirm",
            width=100,
            fg_color=_ACCENT,
            hover_color=_ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._confirm,
        ).pack(side="left")

    # ------------------------------------------------------------------ #
    # Event handlers                                                       #
    # ------------------------------------------------------------------ #

    def _apply_to_all(self) -> None:
        """Broadcast the first row's choice to every row."""
        if not self._rows:
            return
        top_choice = self._rows[0]._choice.get()
        for row in self._rows:
            row.set_choice(top_choice)

    def _confirm(self) -> None:
        resolutions: dict[str, ConflictResolution] = {
            row.diff.name: row.resolution for row in self._rows
        }
        self.destroy()
        self._on_confirm(resolutions)

    def _cancel(self) -> None:
        self.destroy()
        self._on_confirm(None)
