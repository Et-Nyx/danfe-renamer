# PyInstaller spec for the standalone Windows application.
#
# Build with::
#
#     PYTHONPATH= .venv/Scripts/pyinstaller.exe packaging/danfe_renamer.spec
#
# The result is dist/DANFE_Renamer.exe: one file, no console window, no Python
# installation needed on the target machine, and nothing in the bundled
# application reaches the network.

import os
import sys

import _tkinter
from PyInstaller.depend.bindepend import get_imports
from PyInstaller.utils.hooks import collect_submodules

hidden_imports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    *collect_submodules("pymupdf"),
]


def tcl_tk_binaries():
    """Return the Tcl/Tk shared libraries ``_tkinter`` links against.

    PyInstaller resolves a binary's DLL imports by searching the binary's own
    directory plus PATH. A conda/Anaconda interpreter keeps ``tcl86t.dll`` and
    ``tk86t.dll`` in ``<sys.base_prefix>/Library/bin`` and makes them loadable
    by registering that directory at interpreter startup - which the dependency
    walk cannot see. The DLLs are then silently left out of the bundle and the
    frozen app fails at startup with "DLL load failed while importing
    _tkinter", while the CLI mode (which never imports tkinter) still works,
    so the bug is easy to miss.

    To keep that from ever shipping again, resolve ``_tkinter.pyd``'s imports
    the same way PyInstaller does, follow them while they keep coming from the
    interpreter's own installation directories, and bundle every DLL that
    nothing else owns. If a Tcl/Tk DLL still cannot be found, abort the build
    instead of producing a .exe that cannot open its window.
    """
    base = sys.base_prefix
    candidate_dirs = (
        os.path.join(base, "Library", "bin"),  # conda / Anaconda layout
        base,  # python.org installer layout
        os.path.join(base, "DLLs"),  # a few alternative layouts
    )
    system_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32")

    # A built-in _tkinter (compiled into the Python DLL) has no file of its own
    # and no shared libraries for us to collect.
    tkinter_extension = getattr(_tkinter, "__file__", None)
    if not tkinter_extension:
        return []

    binaries = {}
    queue = [tkinter_extension]
    scanned = set()
    while queue:
        binary = queue.pop()
        if binary in scanned:
            continue
        scanned.add(binary)
        for name, resolved_path in get_imports(binary):
            if resolved_path:
                # PyInstaller's dependency analysis collects this one itself.
                continue
            if not name.lower().endswith(".dll"):
                continue
            if name.lower().startswith("api-ms-"):
                # An API-set name: resolved by the OS loader itself, not a
                # file that belongs in the bundle.
                continue
            if os.path.isfile(os.path.join(system_dir, name)):
                # Ships with Windows; must stay a system component.
                continue
            if name.startswith("python"):
                # The bootloader bundles the Python runtime DLL itself.
                continue
            if name in binaries:
                continue
            found = next(
                (
                    os.path.join(directory, name)
                    for directory in candidate_dirs
                    if os.path.isfile(os.path.join(directory, name))
                ),
                None,
            )
            if found:
                binaries[name] = (found, ".")
                queue.append(found)  # follow this DLL's own dependencies
            elif name.startswith(("tcl", "tk")):
                raise SystemExit(
                    f"ERROR: _tkinter links against {name!r}, which was not "
                    f"found in {candidate_dirs}. The .exe would fail at "
                    "startup with 'DLL load failed while importing _tkinter'."
                )
    if binaries:
        print("Bundling Tcl/Tk shared libraries:", list(binaries))
    return list(binaries.values())


analysis = Analysis(  # noqa: F821 - provided by PyInstaller
    ["../run_danfe_renamer.py"],
    pathex=[".."],
    hiddenimports=hidden_imports,
    binaries=tcl_tk_binaries(),
    excludes=["matplotlib", "numpy", "pandas", "scipy", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name="DANFE_Renamer",
    version="../packaging/version_info.txt",
    console=False,  # the user never sees a terminal
    disable_windowed_traceback=False,
    upx=False,
)
