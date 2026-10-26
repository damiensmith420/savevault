"""
Main CustomTkinter Application class for SaveVault.

Responsible for:
  1. Configuring the CustomTkinter theme and root window.
  2. Showing the sign-in screen when the user is not authenticated.
  3. Loading config + initialising Drive after successful auth.
  4. Running the startup Link dialog if unlinked Drive saves are found.
  5. Mounting the MainWindow once everything is ready.
  6. Handling sign-out and returning to the sign-in screen.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from .auth import AuthManager
from .drive import DriveClient
from .storage import AppConfig, GameEntry, load_config
from .ui.link_dialog import LinkDialog
from .ui.main_window import MainWindow

# App-wide appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

_BG = "#11111b"
_SURFACE = "#1e1e2e"
_PANEL = "#313147"
_TEXT = "#cdd6f4"
_MUTED = "#6c7086"
_ACCENT = "#7c3aed"
_ACCENT_HOVER = "#6d28d9"
_ERROR = "#ef4444"

WINDOW_TITLE = "SaveVault"
WINDOW_SIZE = "1100x680"
WINDOW_MIN_SIZE = (820, 520)


class SaveVaultApp(ctk.CTk):
    """
    Root application window.

    Extends CTk to manage the full application lifecycle:
    sign-in → Drive setup → optional link dialog → main window.
    """

    def __init__(self) -> None:
        super().__init__()

        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(*WINDOW_MIN_SIZE)
        self.configure(fg_color=_BG)

        # Set icon if available
        icon_path = Path(__file__).parent.parent / "assets" / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        self._auth = AuthManager()
        self._config: Optional[AppConfig] = None
        self._drive: Optional[DriveClient] = None
        self._main_window: Optional[MainWindow] = None

        # Boot
        self._show_signin_screen()

    # ================================================================== #
    # Sign-in screen                                                       #
    # ================================================================== #

    def _show_signin_screen(self) -> None:
        """Render the initial sign-in / splash screen."""
        self._clear_root()

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        # Logo
        ctk.CTkLabel(
            frame,
            text="🔒",
            font=ctk.CTkFont(size=64),
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            frame,
            text="SaveVault",
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color=_TEXT,
        ).pack()

        ctk.CTkLabel(
            frame,
            text="Game save backups — straight to your Google Drive.",
            font=ctk.CTkFont(size=14),
            text_color=_MUTED,
        ).pack(pady=(4, 32))

        # Try silent sign-in first
        if self._auth.load_or_refresh():
            self._post_auth_setup()
            return

        self._signin_error = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=12), text_color=_ERROR
        )
        self._signin_error.pack(pady=(0, 8))

        self._signin_btn = ctk.CTkButton(
            frame,
            text="Sign in with Google",
            width=220,
            height=44,
            fg_color=_ACCENT,
            hover_color=_ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._do_signin,
        )
        self._signin_btn.pack()

        ctk.CTkLabel(
            frame,
            text=(
                "SaveVault only accesses files it creates.\n"
                "Your other Drive files are never touched."
            ),
            font=ctk.CTkFont(size=11),
            text_color=_MUTED,
            justify="center",
        ).pack(pady=(16, 0))

    def _do_signin(self) -> None:
        """Launch the OAuth browser flow on a background thread."""
        self._signin_btn.configure(state="disabled", text="Opening browser…")
        self._signin_error.configure(text="")

        def _worker():
            try:
                success = self._auth.sign_in()
            except RuntimeError as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._signin_failed(m))
                return
            except Exception as exc:
                msg = f"Sign-in failed: {exc}"
                self.after(0, lambda m=msg: self._signin_failed(m))
                return

            if success:
                self.after(0, self._post_auth_setup)
            else:
                self.after(0, lambda: self._signin_failed("Sign-in was cancelled."))

        threading.Thread(target=_worker, daemon=True).start()

    def _signin_failed(self, message: str) -> None:
        self._signin_btn.configure(state="normal", text="Sign in with Google")
        self._signin_error.configure(text=message)

    # ================================================================== #
    # Post-authentication setup                                            #
    # ================================================================== #

    def _post_auth_setup(self) -> None:
        """Load config, connect to Drive, then check for unlinked saves."""
        self._clear_root()

        loading = ctk.CTkLabel(
            self,
            text="Connecting to Google Drive…",
            font=ctk.CTkFont(size=14),
            text_color=_MUTED,
        )
        loading.place(relx=0.5, rely=0.5, anchor="center")

        def _worker():
            creds = self._auth.get_credentials()
            if creds is None:
                self.after(0, lambda: self._signin_failed("No credentials available."))
                self.after(0, self._show_signin_screen)
                return

            try:
                self._drive = DriveClient(creds)
                self._config = load_config()
                # Fetch unlinked folders from Drive
                unlinked = self._get_unlinked_folders()
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._show_error_screen(m))
                return

            self.after(0, lambda: self._on_drive_ready(unlinked))

        threading.Thread(target=_worker, daemon=True).start()

    def _get_unlinked_folders(self) -> list:
        """Return Drive game folders not present in the local config."""
        try:
            drive_folders = self._drive.list_game_folders()
        except Exception:
            return []

        known_names = {g.name.lower() for g in self._config.games}
        return [f for f in drive_folders if f.name.lower() not in known_names]

    def _on_drive_ready(self, unlinked: list) -> None:
        """Called on the main thread once Drive is connected."""
        if unlinked:
            LinkDialog(
                self,
                config=self._config,
                unlinked=unlinked,
                on_done=self._after_link_dialog,
            )
        else:
            self._launch_main_window()

    def _after_link_dialog(
        self, linked: list[GameEntry], sync_mode: str
    ) -> None:
        """Handle the result of the link dialog, then launch the main window."""
        self._launch_main_window()

        if not linked or sync_mode == "none":
            return

        # Trigger syncs from the main window after it's mounted
        def _trigger():
            if self._main_window is None:
                return
            if sync_mode == "all":
                self._main_window._sync_all()
            elif sync_mode == "ask":
                for game in linked:
                    self._main_window._sync_game(game)

        self.after(300, _trigger)

    # ================================================================== #
    # Main window                                                          #
    # ================================================================== #

    def _launch_main_window(self) -> None:
        """Mount the MainWindow frame."""
        self._clear_root()

        email = self._auth.account_email or "Signed in"

        self._main_window = MainWindow(
            self,
            config=self._config,
            drive=self._drive,
            account_email=email,
            on_sign_out=self._do_signout,
        )

    def _do_signout(self) -> None:
        self._auth.sign_out()
        self._config = None
        self._drive = None
        self._main_window = None
        self._show_signin_screen()

    # ================================================================== #
    # Helpers                                                              #
    # ================================================================== #

    def _clear_root(self) -> None:
        """Destroy all widgets currently in the root window."""
        for widget in self.winfo_children():
            widget.destroy()

    def _show_error_screen(self, message: str) -> None:
        """Display a full-window error with a Retry button."""
        self._clear_root()
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            frame,
            text="Something went wrong",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=_TEXT,
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            frame,
            text=message,
            font=ctk.CTkFont(size=12),
            text_color=_ERROR,
            wraplength=400,
            justify="center",
        ).pack(pady=(0, 20))

        ctk.CTkButton(
            frame,
            text="Sign Out & Retry",
            width=160,
            fg_color=_SURFACE,
            hover_color=_PANEL,
            text_color=_TEXT,
            command=self._do_signout,
        ).pack()
