"""
SaveVault — entry point.

Run with:
    python main.py

Or, after building:
    SaveVault.exe
"""

from __future__ import annotations

import sys
import os


def main() -> None:
    """Bootstrap and run the SaveVault application."""
    # When frozen by PyInstaller the working directory is the temp _MEIPASS
    # folder; make sure relative imports still resolve by adding the script
    # directory to sys.path.
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    # Import here so the path manipulation above takes effect first.
    from src.app import SaveVaultApp  # noqa: PLC0415

    app = SaveVaultApp()
    app.mainloop()


if __name__ == "__main__":
    main()
