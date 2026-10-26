"""
Left-panel game list widget for SaveVault.

Displays all tracked games in a scrollable list.  Each row shows:
  • game name
  • truncated local path
  • last-sync time ("Never" / "2 hours ago")
  • a coloured status dot (green = synced, yellow = pending, red = error)

Clicking a row fires the on_select callback with the game's id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

import customtkinter as ctk

from ..storage import GameEntry

# Status dot colours
_DOT_SYNCED = "#22c55e"   # green
_DOT_PENDING = "#eab308"  # yellow
_DOT_ERROR = "#ef4444"    # red
_DOT_NEVER = "#6b7280"    # grey

# Row colours
_ROW_BG = "#1e1e2e"
_ROW_HOVER = "#2a2a3d"
_ROW_SELECTED = "#313147"
_TEXT_PRIMARY = "#cdd6f4"
_TEXT_MUTED = "#6c7086"


def _time_ago(dt: Optional[datetime]) -> str:
    """Return a human-friendly string like '2 hours ago' or 'Never'."""
    if dt is None:
        return "Never"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = seconds // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _truncate_path(path: str, max_len: int = 32) -> str:
    """Shorten a long path for display."""
    if len(path) <= max_len:
        return path
    return "…" + path[-(max_len - 1):]


class GameRow(ctk.CTkFrame):
    """
    A single row in the game list representing one tracked game.
    """

    def __init__(
        self,
        parent,
        game: GameEntry,
        on_select: Callable[[str], None],
        status: str = "pending",   # "synced" | "pending" | "error" | "never"
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            fg_color=_ROW_BG,
            corner_radius=8,
            **kwargs,
        )
        self.game_id = game.id
        self._on_select = on_select
        self._selected = False

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)

        # ---- Left text block ----
        text_frame = ctk.CTkFrame(self, fg_color="transparent")
        text_frame.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=8)

        self._name_label = ctk.CTkLabel(
            text_frame,
            text=game.name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_TEXT_PRIMARY,
            anchor="w",
        )
        self._name_label.pack(fill="x")

        self._path_label = ctk.CTkLabel(
            text_frame,
            text=_truncate_path(game.local_path) if game.local_path else "(no path set)",
            font=ctk.CTkFont(size=11),
            text_color=_TEXT_MUTED,
            anchor="w",
        )
        self._path_label.pack(fill="x")

        self._sync_label = ctk.CTkLabel(
            text_frame,
            text=_time_ago(game.last_sync_dt()),
            font=ctk.CTkFont(size=10),
            text_color=_TEXT_MUTED,
            anchor="w",
        )
        self._sync_label.pack(fill="x")

        # ---- Status dot ----
        dot_color = {
            "synced": _DOT_SYNCED,
            "pending": _DOT_PENDING,
            "error": _DOT_ERROR,
            "never": _DOT_NEVER,
        }.get(status, _DOT_PENDING)

        self._dot = ctk.CTkLabel(
            self,
            text="●",
            font=ctk.CTkFont(size=14),
            text_color=dot_color,
            width=24,
        )
        self._dot.grid(row=0, column=1, padx=(4, 10))

        # ---- Click bindings on every child widget ----
        for widget in (self, text_frame, self._name_label, self._path_label,
                        self._sync_label, self._dot):
            widget.bind("<Button-1>", self._clicked)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_selected(self, selected: bool) -> None:
        """Highlight or un-highlight this row."""
        self._selected = selected
        self.configure(fg_color=_ROW_SELECTED if selected else _ROW_BG)

    def refresh(self, game: GameEntry, status: str = "pending") -> None:
        """Update all displayed values from a (possibly modified) GameEntry."""
        self._name_label.configure(text=game.name)
        self._path_label.configure(
            text=_truncate_path(game.local_path) if game.local_path else "(no path set)"
        )
        self._sync_label.configure(text=_time_ago(game.last_sync_dt()))
        dot_color = {
            "synced": _DOT_SYNCED,
            "pending": _DOT_PENDING,
            "error": _DOT_ERROR,
            "never": _DOT_NEVER,
        }.get(status, _DOT_PENDING)
        self._dot.configure(text_color=dot_color)

    # ------------------------------------------------------------------ #
    # Event handlers                                                       #
    # ------------------------------------------------------------------ #

    def _clicked(self, _event=None) -> None:
        self._on_select(self.game_id)

    def _on_enter(self, _event=None) -> None:
        if not self._selected:
            self.configure(fg_color=_ROW_HOVER)

    def _on_leave(self, _event=None) -> None:
        if not self._selected:
            self.configure(fg_color=_ROW_BG)


class GameListPanel(ctk.CTkFrame):
    """
    Scrollable left-panel widget that lists all tracked games.

    Args:
        parent:      The parent widget.
        on_select:   Called with the game ID when the user clicks a row.
        on_add_game: Called when the user clicks the [+ Add Game] button.
    """

    def __init__(
        self,
        parent,
        on_select: Callable[[str], None],
        on_add_game: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(parent, fg_color="#181825", corner_radius=0, **kwargs)

        self._on_select = on_select
        self._rows: dict[str, GameRow] = {}   # game_id → GameRow
        self._selected_id: Optional[str] = None

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        # ---- Scrollable area ----
        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color="#313147",
            scrollbar_button_hover_color="#45455e",
        )
        self._scroll.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 0))
        self._scroll.columnconfigure(0, weight=1)

        # ---- "No games" placeholder ----
        self._empty_label = ctk.CTkLabel(
            self._scroll,
            text="No games tracked yet.\nClick [+ Add Game] to get started.",
            font=ctk.CTkFont(size=12),
            text_color=_TEXT_MUTED,
            justify="center",
        )

        # ---- Add Game button ----
        self._add_btn = ctk.CTkButton(
            self,
            text="＋  Add Game",
            font=ctk.CTkFont(size=13),
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            corner_radius=8,
            command=on_add_game,
        )
        self._add_btn.grid(row=1, column=0, sticky="ew", padx=8, pady=8)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def populate(
        self,
        games: list[GameEntry],
        statuses: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Rebuild the list from scratch.

        Args:
            games:    All GameEntry objects to display.
            statuses: Optional map of game_id → status string.
        """
        # Destroy old rows
        for row in self._rows.values():
            row.destroy()
        self._rows.clear()
        self._empty_label.grid_forget()

        if not games:
            self._empty_label.grid(row=0, column=0, pady=40)
            return

        for idx, game in enumerate(games):
            status = (statuses or {}).get(game.id, "never" if not game.last_sync else "pending")
            row = GameRow(
                self._scroll,
                game=game,
                on_select=self._row_selected,
                status=status,
            )
            row.grid(row=idx, column=0, sticky="ew", pady=(0, 4))
            self._rows[game.id] = row

        # Restore selection
        if self._selected_id and self._selected_id in self._rows:
            self._rows[self._selected_id].set_selected(True)

    def refresh_row(self, game: GameEntry, status: str = "pending") -> None:
        """Update a single row's display without rebuilding the whole list."""
        row = self._rows.get(game.id)
        if row:
            row.refresh(game, status)

    def select(self, game_id: str) -> None:
        """Programmatically select a row."""
        self._row_selected(game_id)

    def get_selected_id(self) -> Optional[str]:
        """Return the currently selected game ID, or None."""
        return self._selected_id

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _row_selected(self, game_id: str) -> None:
        # Deselect previous
        if self._selected_id and self._selected_id in self._rows:
            self._rows[self._selected_id].set_selected(False)
        self._selected_id = game_id
        if game_id in self._rows:
            self._rows[game_id].set_selected(True)
        self._on_select(game_id)
