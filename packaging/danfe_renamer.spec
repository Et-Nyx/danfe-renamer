# PyInstaller spec for the standalone Windows application.
#
# Build with::
#
#     PYTHONPATH= .venv/Scripts/pyinstaller.exe packaging/danfe_renamer.spec
#
# The result is dist/DANFE_Renamer/DANFE_Renamer.exe: no console window, no
# Python installation needed on the target machine, and nothing in the bundled
# application reaches the network.

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    *collect_submodules("pymupdf"),
]

analysis = Analysis(  # noqa: F821 - provided by PyInstaller
    ["../run_danfe_renamer.py"],
    pathex=[".."],
    hiddenimports=hidden_imports,
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
    console=False,  # the user never sees a terminal
    disable_windowed_traceback=False,
    upx=False,
)
