"""Dictation history persistence and reprocessing."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from core.migrations import get_connection


_LOCK = threading.RLock()


def save_dictation(
    started_at: str,
    duration_ms: int,
    app_name: str,
    window_title: str,
    mode_id: int | None,
    stt_provider: str,
    stt_model: str,
    raw_transcript: str,
    final_text: str,
    replacements_applied: int = 0,
    llm_processed: int = 0,
    paste_method: str = "clipboard_paste",
    paste_succeeded: int | None = None,
    error: str | None = None,
    audio_path: str | None = None,
) -> int:
    with _LOCK:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO dictations
                    (started_at, duration_ms, app_name, window_title, mode_id,
                     stt_provider, stt_model, raw_transcript, final_text,
                     replacements_applied, llm_processed, paste_method,
                     paste_succeeded, error, audio_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    int(duration_ms or 0),
                    app_name,
                    window_title,
                    mode_id,
                    stt_provider,
                    stt_model,
                    raw_transcript,
                    final_text,
                    int(replacements_applied or 0),
                    int(llm_processed or 0),
                    paste_method,
                    paste_succeeded,
                    error,
                    audio_path,
                ),
            )
            dictation_id = int(cursor.lastrowid)
            conn.commit()
            return dictation_id
        finally:
            conn.close()


def save_context(dictation_id: int, source: str, content: str) -> None:
    with _LOCK:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO dictation_contexts (dictation_id, source, content) VALUES (?, ?, ?)",
                (int(dictation_id), source, content),
            )
            conn.commit()
        finally:
            conn.close()


def list_dictations(search: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        params: list[object] = []
        query = """
            SELECT d.*, m.name as mode_name
            FROM dictations d
            LEFT JOIN modes m ON d.mode_id = m.id
        """
        if search:
            like = f"%{search}%"
            query += """
                WHERE d.raw_transcript LIKE ?
                   OR d.final_text LIKE ?
                   OR d.app_name LIKE ?
                   OR d.error LIKE ?
            """
            params.extend([like, like, like, like])
        query += " ORDER BY d.started_at DESC LIMIT ? OFFSET ?"
        params.extend([max(0, int(limit)), max(0, int(offset))])
        return [dict(row) for row in conn.execute(query, params)]
    finally:
        conn.close()


def get_dictation(dictation_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT d.*, m.name as mode_name
            FROM dictations d
            LEFT JOIN modes m ON d.mode_id = m.id
            WHERE d.id = ?
            """,
            (int(dictation_id),),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["contexts"] = [
            dict(item)
            for item in conn.execute("SELECT * FROM dictation_contexts WHERE dictation_id = ?", (int(dictation_id),))
        ]
        return result
    finally:
        conn.close()


def delete_dictation(dictation_id: int) -> bool:
    with _LOCK:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            row = cursor.execute("SELECT audio_path FROM dictations WHERE id = ?", (int(dictation_id),)).fetchone()
            if row is None:
                return False
            audio_path = row["audio_path"]
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
            cursor.execute("DELETE FROM dictation_contexts WHERE dictation_id = ?", (int(dictation_id),))
            cursor.execute("DELETE FROM dictations WHERE id = ?", (int(dictation_id),))
            conn.commit()
            return True
        finally:
            conn.close()


def reprocess(dictation_id: int, mode_id: int | None = None) -> int | None:
    """Re-run stored transcript formatting and save the result as a new record."""
    from core.dictionary import apply_replacements
    from core.formatter import format_transcription
    from core.modes import get_mode

    original = get_dictation(dictation_id)
    if original is None:
        return None
    raw = original.get("raw_transcript") or ""
    if not raw:
        return None

    mode = get_mode(mode_id) if mode_id else None
    if mode is None and original.get("mode_id"):
        mode = get_mode(int(original["mode_id"]))
    app_name = original.get("app_name", "")
    window_title = original.get("window_title", "")
    final_text = apply_replacements(format_transcription(raw, app_name, window_title, mode), app_name, window_title)
    return save_dictation(
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        duration_ms=int(original.get("duration_ms") or 0),
        app_name=app_name,
        window_title=window_title,
        mode_id=mode.id if mode else original.get("mode_id"),
        stt_provider=original.get("stt_provider", ""),
        stt_model=original.get("stt_model", ""),
        raw_transcript=raw,
        final_text=final_text,
        replacements_applied=1,
        llm_processed=0,
        paste_method=original.get("paste_method", "clipboard_paste"),
        paste_succeeded=None,
        error=None,
        audio_path=None,
    )


def save_error_event(
    started_at: str,
    app_name: str,
    window_title: str,
    mode_id: int | None,
    stt_provider: str,
    stt_model: str,
    error: str,
    duration_ms: int = 0,
) -> None:
    save_dictation(
        started_at=started_at,
        duration_ms=duration_ms,
        app_name=app_name,
        window_title=window_title,
        mode_id=mode_id,
        stt_provider=stt_provider,
        stt_model=stt_model,
        raw_transcript="",
        final_text="",
        error=error,
    )
