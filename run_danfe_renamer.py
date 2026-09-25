"""Launcher for the application.

Packaging tools need a plain script to start from, and a plain script cannot use
relative imports, so this is the one place that imports the package by name.

* double-click / ``python run_danfe_renamer.py`` opens the window;
* ``python run_danfe_renamer.py <pdf or folder> [options]`` runs a batch.

The same file is the PyInstaller entry point (see ``packaging/danfe_renamer.spec``).
"""

from __future__ import annotations

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
