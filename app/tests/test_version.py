"""The version is declared in three places, and they must say the same thing.

A release carries the version in the window title, in the reports and in the
file properties Windows shows for the ``.exe``, and the tag that publishes it is
refused when it disagrees with ``app.__version__``. Nothing used to compare the
declarations with each other, so a forgotten one shipped quietly - 1.3.3 left
``packaging/version_info.txt`` saying 1.3.2, and the built ``.exe`` would have
shown the wrong build in its own properties. These tests fail on the version
that was forgotten and name the file it is in.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import app

#: The repository root, whatever directory the suite was started from.
ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_declares_the_application_version():
    """The build metadata and the code are one version."""
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["version"] == app.__version__


def test_the_executable_carries_the_application_version():
    """Right-clicking the ``.exe`` must show the version the code is.

    Both the numeric pair and the text strings are checked: Windows reads the
    numbers for sorting and the strings for the Properties page, and the fourth
    number is the build, always zero here.
    """
    text = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    strings = dict(re.findall(r'StringStruct\("(\w+)", "([^"]*)"\)', text))
    assert strings["FileVersion"] == app.__version__
    assert strings["ProductVersion"] == app.__version__
    numbers = re.findall(r"(?:filevers|prodvers)=\(([\d, ]+)\)", text)
    assert numbers, "version_info.txt declares no numeric version"
    for declared in numbers:
        parts = [part.strip() for part in declared.split(",")]
        assert ".".join(parts[:3]) == app.__version__


def test_the_version_has_release_notes():
    """The release page is written from these notes, not from the commit."""
    notes = ROOT / "packaging" / "release-notes" / f"v{app.__version__}.md"
    assert notes.is_file(), f"{notes.relative_to(ROOT)} is missing"
