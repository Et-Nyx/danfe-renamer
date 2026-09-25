"""Application entry point.

* with no arguments it opens the window, which is what a double-click does;
* with arguments it behaves like the command line tool, which is how a batch can
  be run from a script or checked on a machine without a desktop session.

Kept thin on purpose: this file is also the PyInstaller entry point.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        from .cli import main as cli_main

        return cli_main(arguments)

    from .gui.app_window import build_window

    window = build_window()
    window.root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
