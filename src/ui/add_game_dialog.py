"""
"Add Game" dialog for SaveVault.

A modal dialog that collects:
  • Game Name  (text field)
  • Local path (text field + Browse button)

On confirm, it creates the Drive subfolder and persists the new
GameEntry to config.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

import customtkinter as ctk

from ..drive import DriveClient
from ..storage import AppConfig, GameEntry, save_config, upsert_game

_BG = "#1e1e2e"
_SURFACE = "#313147"
_TEXT = "#cdd6f4"
_MUTED = "#6c7086"
_ACCENT = "#7c3aed"
_ACCENT_HOVER = "#6d28d9"
_ERROR = "#ef4444"


class AddGameDialog(ctk.CTkToplevel):
    """
    Modal dialog for adding a new tracked game.

    Args:
        parent:      The parent window.
        config:      The current AppConfig (will be mutated on success).
        drive:       An authenticated DriveClient.
        on_success:  Callback invoked with the newly created GameEntry.
    """

    def __init__(
        self,
        parent,
        config: AppConfig,
        drive: DriveClient,
        on_success: Callable[[GameEntry], None],
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._drive = drive
        self._on_success = on_success
        self._error_message: Optional[str] = None

        self.title("Add Game")
        self.geometry("460x310")
        self.resizable(False, False)
        self.configure(fg_color=_BG)
        self.grab_set()          # Modal
        self.focus_force()

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(
            self,
            text="Add a New Game",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=_TEXT,
        ).grid(row=0, column=0, padx=24, pady=(20, 4), sticky="w")

        ctk.CTkLabel(
            self,
            text="SaveVault will create a folder in your Google Drive.",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
        ).grid(row=1, column=0, padx=24, pady=(0, 16), sticky="w")

        # Game Name
        ctk.CTkLabel(
            self, text="Game Name", font=ctk.CTkFont(size=12), text_color=_TEXT
        ).grid(row=2, column=0, padx=24, sticky="w")

        self._name_var = ctk.StringVar()
        ctk.CTkEntry(
            self,
            textvariable=self._name_var,
            placeholder_text="e.g. The Witcher 3",
            fg_color=_SURFACE,
            border_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=13),
        ).grid(row=3, column=0, padx=24, pady=(2, 12), sticky="ew")

        # Local Path
        ctk.CTkLabel(
            self, text="Save Directory", font=ctk.CTkFont(size=12), text_color=_TEXT
        ).grid(row=4, column=0, padx=24, sticky="w")

        path_frame = ctk.CTkFrame(self, fg_color="transparent")
        path_frame.grid(row=5, column=0, padx=24, pady=(2, 4), sticky="ew")
        path_frame.columnconfigure(0, weight=1)

        self._path_var = ctk.StringVar()
        self._path_entry = ctk.CTkEntry(
            path_frame,
            textvariable=self._path_var,
            placeholder_text="C:\\Users\\…\\saves",
            fg_color=_SURFACE,
            border_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=13),
        )
        self._path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            path_frame,
            text="Browse…",
            width=80,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=12),
            command=self._browse,
        ).grid(row=0, column=1)

        # Error label (hidden until needed)
        self._error_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=_ERROR,
            anchor="w",
        )
        self._error_label.grid(row=6, column=0, padx=24, sticky="w")

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=7, column=0, padx=24, pady=(8, 20), sticky="e")

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=90,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=13),
            command=self.destroy,
        ).pack(side="left", padx=(0, 8))

        self._add_btn = ctk.CTkButton(
            btn_frame,
            text="Add Game",
            width=110,
            fg_color=_ACCENT,
            hover_color=_ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._confirm,
        )
        self._add_btn.pack(side="left")

    # ------------------------------------------------------------------ #
    # Event handlers                                                       #
    # ------------------------------------------------------------------ #

    def _browse(self) -> None:
        """Open a directory picker and populate the path field."""
        directory = filedialog.askdirectory(
            title="Select Save Directory",
            parent=self,
        )
        if directory:
            self._path_var.set(directory)

    def _confirm(self) -> None:
        """Validate inputs, create Drive folder, save config, call callback."""
        name = self._name_var.get().strip()
        local_path = self._path_var.get().strip()

        # --- Validate ---
        if not name:
            self._show_error("Please enter a game name.")
            return
        if not local_path:
            self._show_error("Please select the save directory.")
            return
        if not Path(local_path).exists():
            self._show_error("That directory does not exist.")
            return
        # Duplicate name check
        for g in self._config.games:
            if g.name.lower() == name.lower():
                self._show_error(f"A game named '{name}' is already tracked.")
                return

        self._add_btn.configure(state="disabled", text="Adding…")
        self._error_label.configure(text="")

        # Drive operations happen on the main thread here (dialog is blocking).
        # For a smoother UX the main window runs these in a thread; the dialog
        # itself is small enough that a brief freeze is acceptable.
        try:
            folder_id = self._drive.get_or_create_game_folder(name)
        except Exception as exc:
            self._show_error(f"Drive error: {exc}")
            self._add_btn.configure(state="normal", text="Add Game")
            return

        entry = GameEntry.new(name=name, local_path=local_path)
        entry.drive_folder_id = folder_id

        upsert_game(self._config, entry)
        try:
            save_config(self._config)
        except OSError as exc:
            self._show_error(f"Could not save config: {exc}")
            self._add_btn.configure(state="normal", text="Add Game")
            return

        self._on_success(entry)
        self.destroy()

    def _show_error(self, message: str) -> None:
        self._error_label.configure(text=message)
