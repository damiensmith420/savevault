"""
Main window layout for SaveVault.

Layout overview
---------------
┌─────────────────────────────────────────────────────────┐
│ HEADER: logo │               │ email  [Sign Out]         │
├──────────────┤  RIGHT PANEL                              │
│              │  ─────────────────────────────────────── │
│  GAME LIST   │  Game name (editable)                     │
│  (scrollable)│  Local path + Browse                      │
│              │  Drive folder link                        │
│              │  File table                               │
│              │  [Sync This Game]                         │
│  [+ Add Game]│                                           │
├──────────────┴───────────────────────────────────────── │
│ [Sync All]   ██████░░░░  status label                    │
└─────────────────────────────────────────────────────────┘

All long-running operations (sync) are dispatched to a background
thread.  Progress callbacks use root.after() to update the UI safely.
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

import customtkinter as ctk

from ..drive import DriveClient
from ..storage import AppConfig, GameEntry, find_game_by_id, save_config, upsert_game
from ..sync import (
    ConflictResolution,
    FileStatus,
    SyncEngine,
    SyncPlan,
    SyncProgress,
)
from .add_game_dialog import AddGameDialog
from .sync_dialog import SyncConflictDialog

_BG = "#11111b"
_PANEL_BG = "#1e1e2e"
_SURFACE = "#313147"
_HEADER_BG = "#181825"
_TEXT = "#cdd6f4"
_MUTED = "#6c7086"
_ACCENT = "#7c3aed"
_ACCENT_HOVER = "#6d28d9"
_DIVIDER = "#313147"

_STATUS_COLORS = {
    "synced": "#22c55e",
    "pending": "#eab308",
    "error": "#ef4444",
    "never": "#6b7280",
    "syncing": "#3b82f6",
}


class MainWindow(ctk.CTkFrame):
    """
    The primary application frame composing all UI panels.

    Args:
        parent:       The root CTk window.
        config:       The loaded AppConfig.
        drive:        An authenticated DriveClient.
        account_email: The authenticated user's e-mail for display.
        on_sign_out:  Called when the user clicks "Sign Out".
    """

    def __init__(
        self,
        parent,
        config: AppConfig,
        drive: DriveClient,
        account_email: str,
        on_sign_out: Callable[[], None],
    ) -> None:
        super().__init__(parent, fg_color=_BG, corner_radius=0)
        self._config = config
        self._drive = drive
        self._on_sign_out = on_sign_out
        self._account_email = account_email
        self._selected_game_id: Optional[str] = None
        self._sync_engine = SyncEngine(drive)
        self._syncing = False
        self._game_statuses: dict[str, str] = {}   # game_id → status string

        self.pack(fill="both", expand=True)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)

        self._build_header()
        self._build_left_panel()
        self._build_right_panel()
        self._build_toolbar()

        # Populate list
        self._refresh_game_list()

    # ================================================================== #
    # Panel construction                                                   #
    # ================================================================== #

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=_HEADER_BG, corner_radius=0, height=52)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)
        header.grid_propagate(False)

        # Logo
        ctk.CTkLabel(
            header,
            text="🔒  SaveVault",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=_TEXT,
        ).grid(row=0, column=0, padx=20, pady=12, sticky="w")

        # Account email + sign-out
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.grid(row=0, column=2, padx=16, pady=8, sticky="e")

        self._email_label = ctk.CTkLabel(
            right,
            text=self._account_email,
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
        )
        self._email_label.pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            right,
            text="Sign Out",
            width=80,
            height=28,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=12),
            command=self._sign_out,
        ).pack(side="left")

    def _build_left_panel(self) -> None:
        from .game_list import GameListPanel  # deferred import to avoid circular

        self._game_list = GameListPanel(
            self,
            on_select=self._on_game_selected,
            on_add_game=self._open_add_game,
            width=240,
        )
        self._game_list.grid(row=1, column=0, sticky="nsew")

    def _build_right_panel(self) -> None:
        self._right = ctk.CTkFrame(self, fg_color=_PANEL_BG, corner_radius=0)
        self._right.grid(row=1, column=1, sticky="nsew", padx=(1, 0))
        self._right.rowconfigure(5, weight=1)
        self._right.columnconfigure(0, weight=1)

        self._show_placeholder()

    def _build_toolbar(self) -> None:
        toolbar = ctk.CTkFrame(self, fg_color=_HEADER_BG, corner_radius=0, height=48)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        toolbar.grid_propagate(False)

        self._sync_all_btn = ctk.CTkButton(
            toolbar,
            text="⟳  Sync All",
            width=110,
            height=32,
            fg_color=_ACCENT,
            hover_color=_ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._sync_all,
        )
        self._sync_all_btn.grid(row=0, column=0, padx=12, pady=8)

        self._progress_bar = ctk.CTkProgressBar(
            toolbar,
            mode="determinate",
            progress_color=_ACCENT,
            fg_color=_SURFACE,
            height=8,
        )
        self._progress_bar.set(0)
        self._progress_bar.grid(row=0, column=1, padx=(0, 12), pady=8, sticky="ew")
        self._progress_bar.grid_remove()  # Hidden when idle

        self._status_label = ctk.CTkLabel(
            toolbar,
            text="Ready",
            font=ctk.CTkFont(size=11),
            text_color=_MUTED,
        )
        self._status_label.grid(row=0, column=1, padx=16, sticky="w")

    # ================================================================== #
    # Right panel — game detail view                                      #
    # ================================================================== #

    def _show_placeholder(self) -> None:
        """Show the 'select a game' placeholder on the right panel."""
        for widget in self._right.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self._right,
            text="Select a game from the list\nor add a new one to get started.",
            font=ctk.CTkFont(size=14),
            text_color=_MUTED,
            justify="center",
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _show_game_detail(self, game: GameEntry) -> None:
        """Populate the right panel with the selected game's details."""
        for widget in self._right.winfo_children():
            widget.destroy()

        frame = ctk.CTkScrollableFrame(self._right, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=16)
        frame.columnconfigure(1, weight=1)

        row = 0

        # ---- Game name ----
        ctk.CTkLabel(
            frame, text="Game Name", font=ctk.CTkFont(size=12), text_color=_MUTED
        ).grid(row=row, column=0, sticky="w", pady=(0, 2))
        row += 1

        self._detail_name_var = ctk.StringVar(value=game.name)
        ctk.CTkEntry(
            frame,
            textvariable=self._detail_name_var,
            fg_color=_SURFACE,
            border_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1

        # ---- Local path ----
        ctk.CTkLabel(
            frame, text="Save Directory", font=ctk.CTkFont(size=12), text_color=_MUTED
        ).grid(row=row, column=0, sticky="w", pady=(0, 2))
        row += 1

        path_frame = ctk.CTkFrame(frame, fg_color="transparent")
        path_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        path_frame.columnconfigure(0, weight=1)
        row += 1

        self._detail_path_var = ctk.StringVar(value=game.local_path)
        ctk.CTkEntry(
            path_frame,
            textvariable=self._detail_path_var,
            fg_color=_SURFACE,
            border_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            path_frame,
            text="Browse…",
            width=80,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=12),
            command=lambda: self._browse_path(game),
        ).grid(row=0, column=1)

        # ---- Save changes button ----
        ctk.CTkButton(
            frame,
            text="Save Changes",
            width=130,
            fg_color=_SURFACE,
            hover_color="#45455e",
            text_color=_TEXT,
            font=ctk.CTkFont(size=12),
            command=lambda: self._save_game_edits(game),
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 16))
        row += 1

        # ---- Drive folder link ----
        if game.drive_folder_id:
            drive_url = (
                f"https://drive.google.com/drive/folders/{game.drive_folder_id}"
            )
            link = ctk.CTkLabel(
                frame,
                text="☁  Open in Google Drive ↗",
                font=ctk.CTkFont(size=12),
                text_color=_ACCENT,
                cursor="hand2",
            )
            link.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 16))
            link.bind("<Button-1>", lambda _: webbrowser.open(drive_url))
        row += 1

        # ---- File table ----
        ctk.CTkLabel(
            frame,
            text="Files",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_TEXT,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        self._file_table_frame = ctk.CTkFrame(frame, fg_color=_SURFACE, corner_radius=6)
        self._file_table_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        self._file_table_frame.columnconfigure(0, weight=2)
        self._file_table_frame.columnconfigure(1, weight=1)
        self._file_table_frame.columnconfigure(2, weight=1)
        self._file_table_frame.columnconfigure(3, weight=0)
        row += 1

        # Table header
        for col, hdr in enumerate(("File", "Local Modified", "Drive Modified", "Status")):
            ctk.CTkLabel(
                self._file_table_frame,
                text=hdr,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_MUTED,
            ).grid(row=0, column=col, padx=8, pady=6, sticky="w")

        self._populate_file_table(game)

        # ---- Sync this game button ----
        ctk.CTkButton(
            frame,
            text="⟳  Sync This Game",
            fg_color=_ACCENT,
            hover_color=_ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._sync_game(game),
        ).grid(row=row, column=0, columnspan=2, sticky="w")

    def _populate_file_table(self, game: GameEntry) -> None:
        """Fill the file table by building a sync plan (non-blocking quick diff)."""
        # Clear existing rows (keep header row 0)
        for widget in self._file_table_frame.winfo_children():
            info = widget.grid_info()
            if info and int(info.get("row", 0)) > 0:
                widget.destroy()

        try:
            plan = self._sync_engine.build_plan(game)
        except Exception as exc:
            ctk.CTkLabel(
                self._file_table_frame,
                text=str(exc),
                font=ctk.CTkFont(size=11),
                text_color="#ef4444",
            ).grid(row=1, column=0, columnspan=4, padx=8, pady=6, sticky="w")
            return

        if not plan.diffs:
            ctk.CTkLabel(
                self._file_table_frame,
                text="No files found.",
                font=ctk.CTkFont(size=11),
                text_color=_MUTED,
            ).grid(row=1, column=0, columnspan=4, padx=8, pady=6, sticky="w")
            return

        status_symbols = {
            FileStatus.IN_SYNC: ("✓", "#22c55e"),
            FileStatus.LOCAL_ONLY: ("↑", "#3b82f6"),
            FileStatus.DRIVE_ONLY: ("↓", "#3b82f6"),
            FileStatus.LOCAL_NEWER: ("↑", "#eab308"),
            FileStatus.DRIVE_NEWER: ("↓", "#eab308"),
            FileStatus.CONFLICT: ("⚡", "#ef4444"),
        }

        def _fmt(dt) -> str:
            if dt is None:
                return "—"
            return dt.strftime("%Y-%m-%d %H:%M")

        for tbl_row, diff in enumerate(plan.diffs, start=1):
            sym, color = status_symbols.get(diff.status, ("?", _MUTED))
            bg = "#252535" if tbl_row % 2 == 0 else _SURFACE

            ctk.CTkLabel(
                self._file_table_frame, text=diff.name,
                font=ctk.CTkFont(size=12), text_color=_TEXT, anchor="w",
                fg_color=bg,
            ).grid(row=tbl_row, column=0, padx=8, pady=3, sticky="ew")

            ctk.CTkLabel(
                self._file_table_frame, text=_fmt(diff.local_mtime),
                font=ctk.CTkFont(size=11), text_color=_TEXT, anchor="w",
                fg_color=bg,
            ).grid(row=tbl_row, column=1, padx=8, pady=3, sticky="ew")

            ctk.CTkLabel(
                self._file_table_frame, text=_fmt(diff.drive_mtime),
                font=ctk.CTkFont(size=11), text_color=_TEXT, anchor="w",
                fg_color=bg,
            ).grid(row=tbl_row, column=2, padx=8, pady=3, sticky="ew")

            ctk.CTkLabel(
                self._file_table_frame, text=sym,
                font=ctk.CTkFont(size=13), text_color=color, anchor="center",
                fg_color=bg,
            ).grid(row=tbl_row, column=3, padx=8, pady=3)

    # ================================================================== #
    # Sync logic                                                           #
    # ================================================================== #

    def _sync_game(self, game: GameEntry) -> None:
        """Build a plan for one game, handle conflicts, then execute."""
        if self._syncing:
            return
        self._start_sync_ui()

        def _worker():
            try:
                plan = self._sync_engine.build_plan(game)
            except Exception as exc:
                msg = f"Error: {exc}"
                self.after(0, lambda m=msg: self._finish_sync_ui(m, error=True))
                return

            if not plan.has_work:
                self.after(0, lambda: self._finish_sync_ui("Already up to date."))
                return

            if plan.conflicts:
                # Ask user on the main thread
                self.after(0, lambda: self._ask_conflicts(plan, {}))
            else:
                self._execute_plan(plan, {})

        threading.Thread(target=_worker, daemon=True).start()

    def _ask_conflicts(
        self,
        plan: SyncPlan,
        resolutions: dict[str, ConflictResolution],
    ) -> None:
        """Open the conflict dialog on the main thread, then resume execution."""

        def _on_resolved(result):
            if result is None:
                self._finish_sync_ui("Sync cancelled.")
                return
            resolutions.update(result)
            threading.Thread(
                target=self._execute_plan,
                args=(plan, resolutions),
                daemon=True,
            ).start()

        SyncConflictDialog(
            self,
            game_name=plan.game.name,
            conflicts=plan.conflicts,
            on_confirm=_on_resolved,
        )

    def _execute_plan(
        self,
        plan: SyncPlan,
        resolutions: dict[str, ConflictResolution],
    ) -> None:
        """Execute the plan on a worker thread, reporting progress via after()."""

        def _progress(p: SyncProgress) -> None:
            def _update():
                if p.files_total > 0:
                    self._progress_bar.set(p.files_done / p.files_total)
                msg = p.error or p.message or p.current_file
                self._status_label.configure(text=msg)
                if p.done:
                    if p.error:
                        self._finish_sync_ui(p.error, error=True)
                        self._game_statuses[plan.game.id] = "error"
                    else:
                        plan.game.set_last_sync_now()
                        upsert_game(self._config, plan.game)
                        try:
                            save_config(self._config)
                        except OSError:
                            pass
                        self._finish_sync_ui("Sync complete.")
                        self._game_statuses[plan.game.id] = "synced"
                    self._refresh_game_list()
                    if self._selected_game_id == plan.game.id:
                        self._show_game_detail(plan.game)

            self.after(0, _update)

        err = self._sync_engine.execute_plan(plan, resolutions, _progress)
        if err and "cancelled" not in err.lower():
            self.after(
                0,
                lambda: self._finish_sync_ui(f"Sync error: {err}", error=True),
            )

    def _sync_all(self) -> None:
        """Sync every tracked game sequentially in a background thread."""
        if self._syncing or not self._config.games:
            return
        self._start_sync_ui()

        games = list(self._config.games)
        total = len(games)

        def _worker():
            for idx, game in enumerate(games):
                if not Path(game.local_path).exists():
                    self.after(0, lambda g=game: self._status_label.configure(
                        text=f"Skipping '{g.name}' — local path not found."
                    ))
                    continue

                self.after(0, lambda g=game: self._status_label.configure(
                    text=f"Syncing {g.name}…"
                ))
                self.after(0, lambda i=idx: self._progress_bar.set(i / total))

                try:
                    plan = self._sync_engine.build_plan(game)
                except Exception as exc:
                    self.after(0, lambda e=exc: self._status_label.configure(
                        text=f"Error building plan: {e}"
                    ))
                    continue

                if not plan.has_work:
                    self._game_statuses[game.id] = "synced"
                    continue

                if plan.conflicts:
                    # For Sync All, skip conflicts with a notice
                    self.after(0, lambda g=game: self._status_label.configure(
                        text=f"'{g.name}' has conflicts — open game to resolve."
                    ))
                    self._game_statuses[game.id] = "pending"
                    import time; time.sleep(1.5)
                    continue

                err = self._sync_engine.execute_plan(plan, {})
                if err:
                    self._game_statuses[game.id] = "error"
                else:
                    game.set_last_sync_now()
                    upsert_game(self._config, game)
                    self._game_statuses[game.id] = "synced"

            try:
                save_config(self._config)
            except OSError:
                pass

            self.after(0, lambda: self._finish_sync_ui("All games synced."))
            self.after(0, self._refresh_game_list)

        threading.Thread(target=_worker, daemon=True).start()

    # ================================================================== #
    # UI state helpers                                                     #
    # ================================================================== #

    def _start_sync_ui(self) -> None:
        self._syncing = True
        self._sync_all_btn.configure(state="disabled")
        self._progress_bar.set(0)
        self._progress_bar.grid()
        self._status_label.grid_remove()

    def _finish_sync_ui(self, message: str, error: bool = False) -> None:
        self._syncing = False
        self._sync_all_btn.configure(state="normal")
        self._progress_bar.grid_remove()
        self._status_label.grid()
        color = "#ef4444" if error else _MUTED
        self._status_label.configure(text=message, text_color=color)

    def _refresh_game_list(self) -> None:
        """Rebuild the left-panel game list from the current config."""
        self._game_list.populate(self._config.games, self._game_statuses)
        if self._selected_game_id:
            self._game_list.select(self._selected_game_id)

    # ================================================================== #
    # Event handlers                                                       #
    # ================================================================== #

    def _on_game_selected(self, game_id: str) -> None:
        self._selected_game_id = game_id
        game = find_game_by_id(self._config, game_id)
        if game:
            self._show_game_detail(game)

    def _open_add_game(self) -> None:
        def _on_added(entry: GameEntry) -> None:
            self._game_statuses[entry.id] = "never"
            self._refresh_game_list()
            self._game_list.select(entry.id)
            self._on_game_selected(entry.id)

        AddGameDialog(self, self._config, self._drive, _on_added)

    def _browse_path(self, game: GameEntry) -> None:
        directory = filedialog.askdirectory(
            title="Select Save Directory",
            initialdir=game.local_path or None,
        )
        if directory:
            self._detail_path_var.set(directory)

    def _save_game_edits(self, game: GameEntry) -> None:
        game.name = self._detail_name_var.get().strip() or game.name
        game.local_path = self._detail_path_var.get().strip() or game.local_path
        upsert_game(self._config, game)
        try:
            save_config(self._config)
        except OSError as exc:
            self._status_label.configure(
                text=f"Could not save: {exc}", text_color="#ef4444"
            )
            return
        self._refresh_game_list()
        self._status_label.configure(text="Changes saved.", text_color=_MUTED)

    def _sign_out(self) -> None:
        self._on_sign_out()
