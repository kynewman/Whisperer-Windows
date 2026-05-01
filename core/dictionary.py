import os
import re
import sqlite3
from typing import List, Pattern

from core.paths import get_dictionary_db_path
from core.term_filter import is_useful_term, normalize_term


DB_PATH = get_dictionary_db_path()
_prompt_cache: dict[int, str] = {}
_replacement_cache: list[tuple[Pattern[str], str]] | None = None


def _invalidate_caches():
    _prompt_cache.clear()
    global _replacement_cache
    _replacement_cache = None

def _get_connection():
    """Get a SQLite connection with row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the dictionary database with required tables."""
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            count INTEGER DEFAULT 1,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'ocr',
            context TEXT
        )
    """)

    cursor.execute("""
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
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_words_count ON words(count DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_words_source ON words(source)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_replacement_rules_enabled
        ON replacement_rules(enabled)
    """)

    conn.commit()
    conn.close()
    _invalidate_caches()

def add_word(word: str, source: str = "ocr", context: str = ""):
    """Add or update a word in the dictionary."""
    raw_word = normalize_term(word)
    if source != "manual" and not is_useful_term(raw_word, source=source):
        return
    word = raw_word.lower()
    if not word:
        return
    
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO words (word, count, last_seen, source, context)
        VALUES (?, 1, CURRENT_TIMESTAMP, ?, ?)
        ON CONFLICT(word) DO UPDATE SET
            count = count + 1,
            last_seen = CURRENT_TIMESTAMP,
            source = COALESCE(?, source),
            context = COALESCE(?, context)
    """, (word, source, context, source, context))
    
    conn.commit()
    conn.close()
    _invalidate_caches()

def add_words_from_list(words: List[str], source: str = "ocr", context: str = ""):
    """Add multiple words to the dictionary efficiently in a single transaction."""
    words = [w for w in words if w.strip()]
    if not words:
        return
        
    conn = _get_connection()
    cursor = conn.cursor()
    
    # Bulk insert for speed
    data = []
    for word in set(words):
        raw_word = normalize_term(word)
        if source != "manual" and not is_useful_term(raw_word, source=source):
            continue
        word = raw_word.lower()
        if word:
            data.append((word, source, context, source, context))
            
    if data:
        cursor.executemany("""
            INSERT INTO words (word, count, last_seen, source, context)
            VALUES (?, 1, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(word) DO UPDATE SET
                count = count + 1,
                last_seen = CURRENT_TIMESTAMP,
                source = COALESCE(?, source),
                context = COALESCE(?, context)
        """, data)
        conn.commit()
        
    conn.close()
    _invalidate_caches()

def get_top_words(limit: int = 100) -> List[str]:
    """Get the top N most frequently used words."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT word FROM words
        ORDER BY count DESC, last_seen DESC
        LIMIT ?
    """, (limit,))
    words = [row['word'] for row in cursor.fetchall()]
    conn.close()
    return words


def get_prompt_words(limit: int = 80) -> str:
    """
    Return a compact vocabulary hint string for Whisper's initial prompt.

    Manual words and frequently seen words naturally rise to the top because
    this uses the existing count/recency ranking. The prompt remains bounded so
    vocabulary help does not become transcript noise.
    """
    if limit not in _prompt_cache:
        _prompt_cache[limit] = ", ".join(get_top_words(limit))
    return _prompt_cache[limit]

def get_all_words() -> List[str]:
    """Get all words in the dictionary."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT word FROM words ORDER BY count DESC")
    words = [row['word'] for row in cursor.fetchall()]
    conn.close()
    return words


def get_words(limit: int = 500, search: str = "") -> List[dict]:
    """Return vocabulary words with metadata for the UI."""
    conn = _get_connection()
    cursor = conn.cursor()
    params = []
    query = """
        SELECT word, count, source, context, last_seen
        FROM words
    """
    search = search.strip()
    if search:
        pattern = f"%{search.lower()}%"
        query += """
            WHERE lower(word) LIKE ?
               OR lower(COALESCE(source, '')) LIKE ?
               OR lower(COALESCE(context, '')) LIKE ?
        """
        params.extend([pattern, pattern, pattern])
    query += " ORDER BY count DESC, last_seen DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    words = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return words

def get_word_count() -> int:
    """Get the total number of unique words in the dictionary."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM words")
    count = cursor.fetchone()['cnt']
    conn.close()
    return count

def clear_dict():
    """Clear all words from the dictionary."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM words")
    conn.commit()
    conn.close()
    _invalidate_caches()

def export_to_list() -> List[tuple]:
    """Export all words with their counts and metadata."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT word, count, first_seen, last_seen, source, context FROM words
        ORDER BY count DESC
    """)
    data = [tuple(row) for row in cursor.fetchall()]
    conn.close()
    return data


def add_replacement_rule(
    match_text: str,
    replace_with: str,
    whole_word: bool = True,
    case_sensitive: bool = False,
    enabled: bool = True,
) -> int | None:
    """Create or update a deterministic replacement rule."""
    match_text = " ".join(match_text.strip().split())
    replace_with = replace_with.strip()
    if not match_text:
        return None

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO replacement_rules
            (match_text, replace_with, enabled, whole_word, case_sensitive, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(match_text) DO UPDATE SET
            replace_with = excluded.replace_with,
            enabled = excluded.enabled,
            whole_word = excluded.whole_word,
            case_sensitive = excluded.case_sensitive,
            updated_at = CURRENT_TIMESTAMP
    """, (
        match_text,
        replace_with,
        int(enabled),
        int(whole_word),
        int(case_sensitive),
    ))
    conn.commit()
    rule_id = cursor.lastrowid
    conn.close()
    _invalidate_caches()
    return rule_id


def delete_replacement_rule(rule_id: int):
    """Delete a replacement rule by id."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM replacement_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    _invalidate_caches()


def get_replacement_rules(enabled_only: bool = False, search: str = "") -> List[dict]:
    """Return replacement rules ordered longest-match first."""
    conn = _get_connection()
    cursor = conn.cursor()
    clauses = []
    params = []
    query = """
        SELECT id, match_text, replace_with, enabled, whole_word, case_sensitive
        FROM replacement_rules
    """
    if enabled_only:
        clauses.append("enabled = 1")
    search = search.strip()
    if search:
        pattern = f"%{search.lower()}%"
        clauses.append("(lower(match_text) LIKE ? OR lower(replace_with) LIKE ?)")
        params.extend([pattern, pattern])
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY LENGTH(match_text) DESC, match_text ASC"
    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def apply_replacements(text: str) -> str:
    """Apply enabled replacement rules to finalized transcription text."""
    if not text:
        return text

    global _replacement_cache
    if _replacement_cache is None:
        compiled: list[tuple[Pattern[str], str]] = []
        for rule in get_replacement_rules(enabled_only=True):
            match_text = rule["match_text"]
            replace_with = rule["replace_with"]
            flags = 0 if rule["case_sensitive"] else re.IGNORECASE
            escaped = re.escape(match_text)
            if rule["whole_word"]:
                pattern = rf"(?<!\w){escaped}(?!\w)"
            else:
                pattern = escaped
            compiled.append((re.compile(pattern, flags=flags), replace_with))
        _replacement_cache = compiled

    result = text
    for pattern, replace_with in _replacement_cache:
        result = pattern.sub(replace_with, result)
    return result

# Auto-initialize on import
init_db()
