"""SQLite schema versioning for Whisperer runtime data."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from core.paths import database_path


Migration = Callable[[sqlite3.Cursor], None]
MIGRATIONS: list[Migration] = []


def _migration_001_modes(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS modes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            is_builtin INTEGER DEFAULT 0,
            description TEXT DEFAULT '',
            stt_provider TEXT,
            stt_model TEXT,
            language TEXT DEFAULT 'en',
            formatting_prompt TEXT DEFAULT '',
            output_format TEXT DEFAULT 'plain',
            llm_enabled INTEGER DEFAULT 0,
            llm_provider TEXT,
            llm_model TEXT,
            llm_prompt TEXT DEFAULT '',
            paste_method TEXT DEFAULT 'clipboard_paste',
            auto_send INTEGER DEFAULT 0,
            ctx_ocr INTEGER DEFAULT 1,
            ctx_selected_text INTEGER DEFAULT 0,
            ctx_clipboard INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS auto_activation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode_id INTEGER NOT NULL REFERENCES modes(id) ON DELETE CASCADE,
            match_type TEXT NOT NULL,
            match_value TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        )
        """
    )


def _migration_002_history(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dictations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_ms INTEGER,
            app_name TEXT,
            window_title TEXT,
            mode_id INTEGER,
            stt_provider TEXT,
            stt_model TEXT,
            raw_transcript TEXT,
            final_text TEXT,
            replacements_applied INTEGER DEFAULT 0,
            llm_processed INTEGER DEFAULT 0,
            paste_method TEXT,
            paste_succeeded INTEGER,
            error TEXT,
            audio_path TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dictation_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dictation_id INTEGER NOT NULL REFERENCES dictations(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            content TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dictations_started ON dictations(started_at DESC)")


def _migration_003_deleted_builtin_modes(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS deleted_builtin_modes (
            name TEXT PRIMARY KEY,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _migration_004_indexes(cursor: sqlite3.Cursor) -> None:
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auto_rules_lookup ON auto_activation_rules(enabled, priority DESC, id ASC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auto_rules_mode ON auto_activation_rules(mode_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dictation_contexts_dictation ON dictation_contexts(dictation_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_modes_enabled ON modes(enabled, is_builtin DESC, name ASC)")


MIGRATIONS.extend([
    _migration_001_modes,
    _migration_002_history,
    _migration_003_deleted_builtin_modes,
    _migration_004_indexes,
])


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass


def ensure_migrated() -> None:
    """Run pending migrations in a single transaction."""
    path = Path(database_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    _configure(conn)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version")
        version = int(cursor.fetchone()[0])
        for index, migration in enumerate(MIGRATIONS[version:], start=version):
            migration(cursor)
            cursor.execute(f"PRAGMA user_version = {index + 1}")
        conn.commit()
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    """Return a configured SQLite connection to the main app database."""
    ensure_migrated()
    conn = sqlite3.connect(database_path())
    _configure(conn)
    return conn
