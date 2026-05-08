"""Filesystem locations for Whisperer runtime state.

The application code can live in a source checkout, a PyInstaller ``_internal``
folder, or a portable install. User data should not live beside any of those
locations, so every database, cache, and log path is rooted in a per-user app
data directory unless an explicit environment override is provided.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


APP_NAME = "Whisperer Windows"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _candidate_dirs() -> list[Path]:
    values = [
        os.environ.get("WHISPERER_APP_DATA_DIR", ""),
        os.path.join(os.environ.get("APPDATA", ""), APP_NAME),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), APP_NAME),
        os.path.join(Path.home(), "AppData", "Roaming", APP_NAME),
        os.path.join(tempfile.gettempdir(), APP_NAME),
    ]
    return [Path(value) for value in values if value]


def _first_writable(candidates: list[Path]) -> Path:
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.cwd()


def get_app_data_dir() -> str:
    """Return the writable per-user data root."""
    return str(_first_writable(_candidate_dirs()))


def get_data_dir() -> str:
    """Return the directory used for SQLite databases and generated data."""
    data_dir = Path(get_app_data_dir()) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)


def get_dictionary_db_path() -> str:
    """Return the user dictionary database path.

    Older development builds stored ``data/dictionary.db`` in the project root.
    If that legacy database exists and the app-data database does not, copy it
    forward once so learned vocabulary survives the migration.
    """
    target = Path(get_data_dir()) / "dictionary.db"
    legacy = PROJECT_ROOT / "data" / "dictionary.db"
    if not target.exists() and legacy.exists():
        try:
            shutil.copy2(legacy, target)
        except OSError:
            pass
    return str(target)


def database_path() -> str:
    """Return the main application database path."""
    return str(Path(get_app_data_dir()) / "whisperer.db")
