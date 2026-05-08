"""Local vocabulary and deterministic replacement rules."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from collections.abc import Iterable
from typing import Pattern

from core.paths import get_dictionary_db_path
from core.term_filter import is_useful_term, normalize_term


_LOCK = threading.RLock()
_prompt_cache: dict[int, str] = {}
_replacement_cache: list[tuple[Pattern[str], str]] | None = None


def _invalidate_caches() -> None:
    global _replacement_cache
    with _LOCK:
        _prompt_cache.clear()
        _replacement_cache = None


def _get_connection() -> sqlite3.Connection:
    path = get_dictionary_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def init_db() -> None:
    """Initialize the dictionary database."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE NOT NULL,
                count INTEGER DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT DEFAULT 'ocr',
                context TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS replacement_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_text TEXT UNIQUE NOT NULL,
                replace_with TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                whole_word INTEGER DEFAULT 1,
                case_sensitive INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_words_count ON words(count DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_words_source ON words(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_words_last_seen ON words(last_seen DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_replacement_rules_enabled ON replacement_rules(enabled)")
        conn.commit()
    finally:
        conn.close()
    _invalidate_caches()


def _clean_word(word: str, source: str) -> str:
    cleaned = normalize_term(word)
    if source != "manual" and not is_useful_term(cleaned, source=source):
        return ""
    return cleaned.lower()


def add_word(word: str, source: str = "ocr", context: str = "") -> None:
    cleaned = _clean_word(word, source)
    if not cleaned:
        return
    add_words_from_list([cleaned], source=source, context=context)


def add_words_from_list(words: Iterable[str], source: str = "ocr", context: str = "") -> None:
    """Insert or bump many words in a single transaction."""
    data: list[tuple[str, str, str, str, str]] = []
    seen: set[str] = set()
    for word in words:
        cleaned = _clean_word(str(word), source)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        data.append((cleaned, source, context, source, context))
    if not data:
        return

    with _LOCK:
        conn = _get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO words (word, count, last_seen, source, context)
                VALUES (?, 1, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    count = count + 1,
                    last_seen = CURRENT_TIMESTAMP,
                    source = COALESCE(?, source),
                    context = COALESCE(?, context)
                """,
                data,
            )
            conn.commit()
        finally:
            conn.close()
        _invalidate_caches()


def get_top_words(limit: int = 100) -> list[str]:
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT word FROM words ORDER BY count DESC, last_seen DESC LIMIT ?",
            (max(0, int(limit)),),
        )
        return [row["word"] for row in rows]
    finally:
        conn.close()


def get_prompt_words(limit: int = 80) -> str:
    limit = max(0, int(limit))
    with _LOCK:
        cached = _prompt_cache.get(limit)
        if cached is not None:
            return cached
    prompt = ", ".join(get_top_words(limit))
    with _LOCK:
        _prompt_cache[limit] = prompt
    return prompt


def get_all_words() -> list[str]:
    conn = _get_connection()
    try:
        return [row["word"] for row in conn.execute("SELECT word FROM words ORDER BY count DESC")]
    finally:
        conn.close()


def get_words(limit: int = 500, search: str = "") -> list[dict]:
    conn = _get_connection()
    try:
        params: list[object] = []
        query = "SELECT word, count, source, context, last_seen FROM words"
        search = (search or "").strip()
        if search:
            pattern = f"%{search.lower()}%"
            query += """
                WHERE lower(word) LIKE ?
                   OR lower(COALESCE(source, '')) LIKE ?
                   OR lower(COALESCE(context, '')) LIKE ?
            """
            params.extend([pattern, pattern, pattern])
        query += " ORDER BY count DESC, last_seen DESC LIMIT ?"
        params.append(max(0, int(limit)))
        return [dict(row) for row in conn.execute(query, params)]
    finally:
        conn.close()


def get_word_count() -> int:
    conn = _get_connection()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM words").fetchone()[0])
    finally:
        conn.close()


def clear_dict() -> None:
    with _LOCK:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM words")
            conn.commit()
        finally:
            conn.close()
        _invalidate_caches()


def export_to_list() -> list[tuple]:
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT word, count, first_seen, last_seen, source, context
            FROM words
            ORDER BY count DESC
            """
        )
        return [tuple(row) for row in rows]
    finally:
        conn.close()


def add_replacement_rule(
    match_text: str,
    replace_with: str,
    whole_word: bool = True,
    case_sensitive: bool = False,
    enabled: bool = True,
) -> int | None:
    match_text = " ".join((match_text or "").strip().split())
    replace_with = (replace_with or "").strip()
    if not match_text:
        return None

    with _LOCK:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO replacement_rules
                    (match_text, replace_with, enabled, whole_word, case_sensitive, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(match_text) DO UPDATE SET
                    replace_with = excluded.replace_with,
                    enabled = excluded.enabled,
                    whole_word = excluded.whole_word,
                    case_sensitive = excluded.case_sensitive,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (match_text, replace_with, int(enabled), int(whole_word), int(case_sensitive)),
            )
            conn.commit()
            rule_id = cursor.lastrowid
            if not rule_id:
                row = cursor.execute("SELECT id FROM replacement_rules WHERE match_text = ?", (match_text,)).fetchone()
                rule_id = row["id"] if row else None
        finally:
            conn.close()
        _invalidate_caches()
    return int(rule_id) if rule_id is not None else None


def delete_replacement_rule(rule_id: int) -> None:
    with _LOCK:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM replacement_rules WHERE id = ?", (int(rule_id),))
            conn.commit()
        finally:
            conn.close()
        _invalidate_caches()


def get_replacement_rules(enabled_only: bool = False, search: str = "") -> list[dict]:
    conn = _get_connection()
    try:
        query = """
            SELECT id, match_text, replace_with, enabled, whole_word, case_sensitive
            FROM replacement_rules
        """
        clauses: list[str] = []
        params: list[object] = []
        if enabled_only:
            clauses.append("enabled = 1")
        search = (search or "").strip()
        if search:
            pattern = f"%{search.lower()}%"
            clauses.append("(lower(match_text) LIKE ? OR lower(replace_with) LIKE ?)")
            params.extend([pattern, pattern])
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY LENGTH(match_text) DESC, match_text ASC"
        return [dict(row) for row in conn.execute(query, params)]
    finally:
        conn.close()


def _compile_replacements() -> list[tuple[Pattern[str], str]]:
    compiled: list[tuple[Pattern[str], str]] = []
    for rule in get_replacement_rules(enabled_only=True):
        flags = 0 if rule["case_sensitive"] else re.IGNORECASE
        escaped = re.escape(rule["match_text"])
        pattern = rf"(?<!\w){escaped}(?!\w)" if rule["whole_word"] else escaped
        compiled.append((re.compile(pattern, flags=flags), rule["replace_with"]))
    return compiled


def apply_replacements(text: str) -> str:
    if not text:
        return text
    global _replacement_cache
    with _LOCK:
        if _replacement_cache is None:
            _replacement_cache = _compile_replacements()
        replacements = list(_replacement_cache)
    result = text
    for pattern, replace_with in replacements:
        result = pattern.sub(replace_with, result)
    return result


init_db()
