"""One small settings file, so a choice survives the next start.

The application runs from an .exe on a machine the user may not control, so the
settings go where the user can write: ``%APPDATA%\DANFE_Renamer\settings.json``,
falling back to the home directory. Nothing about the documents is stored here,
only preferences such as the interface language.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .i18n import DEFAULT_LANGUAGE, STRINGS

APP_DIRECTORY_NAME = "DANFE_Renamer"
SETTINGS_FILE_NAME = "settings.json"


def settings_directory() -> Path:
    """Where preferences live; the first writable candidate wins."""
    candidates = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / APP_DIRECTORY_NAME)
    candidates.append(Path.home() / f".{APP_DIRECTORY_NAME.lower()}")
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.cwd()  # pragma: no cover - last resort on a locked-down machine


def settings_path() -> Path:
    return settings_directory() / SETTINGS_FILE_NAME


def load_settings() -> dict:
    """Read the settings file, treating anything unreadable as empty."""
    try:
        raw = settings_path().read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_settings(values: dict) -> None:
    """Write settings back, silently ignoring a machine that refuses to."""
    try:
        settings_path().write_text(
            json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def load_language() -> str:
    """The language to start in: the saved one, or English."""
    language = load_settings().get("language")
    return language if language in STRINGS else DEFAULT_LANGUAGE


def save_language(language: str) -> None:
    if language not in STRINGS:
        raise ValueError(f"unknown language: {language!r}")
    values = load_settings()
    values["language"] = language
    save_settings(values)
