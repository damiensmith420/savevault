"""
Link dialog for SaveVault.

Shown on startup after authentication when Drive contains ``Save Games``
subfolders that have no matching local path in the config.

For each unlinked game the user can:
  • Browse for a local save directory, or
  • Skip (leave unlinked for now)

After resolving, the user is offered three sync options:
  • Yes to all  — sync every newly linked game immediately
  • Ask me each — open the conflict dialog per game
  • No          — skip syncing for now
"""

from __future__ import annotations

from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from ..drive import DriveFile
from ..storage import AppConfig, GameEntry, save_config, upsert_game

_BG = "#1e1e2e"
_SURFACE = "#313147"
_TEXT = "#cdd6f4"
_MUTED = "#6c7086"
_ACCENT = "#7c3aed"
_ACCENT_HOVER = "#6d28d9"


class _UnlinkedRow(ctk.CTkFrame):
    """One row for an unlinked Drive game folder."""

    def __init__(self, parent, folder: DriveFile, **kwargs) -> None:
        super().__init__(parent, fg_color=_SURFACE, corner_radius=6, **kwargs)
        self.folder = folder
        self._path: str = ""

        self.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text=folder.name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_TEXT,
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, padx=10, pady=(8, 2), sticky="w")

        self._path_var = ctk.StringVar(value="(not linked)")
        self._path_label = ctk.CTkLabel(
            self,
            textvariable=self._path_var,
            font=ctk.CTkFont(size=11),
            text_color=_MUTED,
            anchor="w",
        )
        self._path_label.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="ew")

        browse_btn = ctk.CTkButton(
            self,
            text="Browse…",
            width=80,
            fg_color="#45455e",
            hover_color="#555570",
            text_color=_TEXT,
            font=ctk.CTkFont(size=12),
            command=self._browse,
        )
        browse_btn.grid(row=1, column=2, padx=(4, 10), pady=(0, 8))

    def _browse(self) -> None:
        directory = filedialog.askdirectory(
            title=f"Select save directory for '{self.folder.name}'",
        )
        if directory:
            self._path = directory
            self._path_var.set(directory)

    @property
    def local_path(self) -> str:
        """The user-selected local path, or empty string if skipped."""
        return self._path


class LinkDialog(ctk.CTkToplevel):
    """
    Dialog shown when unlinked Drive save folders are detected.

    Args:
        parent:         Parent window.
        config:         Current AppConfig — will be mutated on confirm.
        unlinked:       List of DriveFile objects (folders) not in config.
        on_done:        Called with a list of newly linked GameEntry objects
                        and a sync_mode str: "all" | "ask" | "none".
    """

    def __init__(
        self,
        parent,
        config: AppConfig,
        unlinked: list[DriveFile],
        on_done: Callable[[list[GameEntry], str], None],
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._unlinked = unlinked
        self._on_done = on_done
        self._rows: list[_UnlinkedRow] = []

        n = len(unlinked)
        self.title("Unlinked Drive Saves Found")
        self.geometry("520x520")
        self.resizable(False, True)
        self.configure(fg_color=_BG)
        self.grab_set()
        self.focus_force()

        self._build_ui(n)

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self, n: int) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Header
        ctk.CTkLabel(
            self,
            text=f"{'1 game' if n == 1 else f'{n} games'} found in your Drive",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=_TEXT,
        ).grid(row=0, column=0, padx=24, pady=(20, 2), sticky="w")

        ctk.CTkLabel(
            self,
            text=(
                "The following save folders exist in your Google Drive but\n"
                "aren't linked to a local directory yet. "
                "Browse to link them, or skip."
            ),
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            justify="left",
        ).grid(row=0, column=0, padx=24, pady=(44, 8), sticky="w")

        # Scrollable rows
        scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=_SURFACE,
        )
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=4)
        scroll.columnconfigure(0, weight=1)

        for idx, folder in enumerate(self._unlinked):
            row = _UnlinkedRow(scroll, folder)
            row.grid(row=idx, column=0, sticky="ew", pady=(0, 6))
            self._rows.append(row)

        # Sync-mode question
        ctk.CTkLabel(
            self,
            text="After linking, would you like to sync now?",
            font=ctk.CTkFont(size=13),
            text_color=_TEXT,
        ).grid(row=2, column=0, padx=24, pady=(12, 4), sticky="w")

        self._sync_var = ctk.StringVar(value="all")
        modes = [
            ("Yes to all", "all"),
            ("Ask me each", "ask"),
            ("No thanks", "none"),
        ]
        radio_frame = ctk.CTkFrame(self, fg_color="transparent")
        radio_frame.grid(row=3, column=0, padx=24, sticky="w")

        for label, value in modes:
            ctk.CTkRadioButton(
                radio_frame,
                text=label,
                value=value,
                variable=self._sync_var,
                font=ctk.CTkFont(size=12),
                text_color=_TEXT,
                fg_color=_ACCENT,
                hover_color=_ACCENT_HOVER,
            ).pack(side="left", padx=(0, 16))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=4, column=0, padx=24, pady=(12, 20), sticky="e")

        ctk.CTkButton(
            btn_frame,
            text="Skip All",
            width=90,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=13),
            command=self.destroy,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame,
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

    def _confirm(self) -> None:
        """Persist all linked games to config, then invoke callback."""
        linked: list[GameEntry] = []

        for row in self._rows:
            if not row.local_path:
                continue  # user skipped this one

            # Check if already in config (shouldn't be, but be safe)
            already = next(
                (g for g in self._config.games if g.name == row.folder.name), None
            )
            if already:
                already.local_path = row.local_path
                already.drive_folder_id = row.folder.file_id
                linked.append(already)
            else:
                entry = GameEntry.new(
                    name=row.folder.name,
                    local_path=row.local_path,
                )
                entry.drive_folder_id = row.folder.file_id
                upsert_game(self._config, entry)
                linked.append(entry)

        try:
            save_config(self._config)
        except OSError:
            pass  # Non-fatal — we'll retry on next save

        sync_mode = self._sync_var.get()
        self.destroy()
        self._on_done(linked, sync_mode)
