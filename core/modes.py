"""Mode profiles and foreground-window auto-activation rules."""

from __future__ import annotations

import dataclasses
import sqlite3
from typing import Any

from core.migrations import get_connection


@dataclasses.dataclass(slots=True)
class Mode:
    id: int | None = None
    name: str = ""
    is_builtin: bool = False
    description: str = ""
    stt_provider: str | None = None
    stt_model: str | None = None
    language: str = "en"
    formatting_prompt: str = ""
    output_format: str = "plain"
    llm_enabled: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_prompt: str = ""
    paste_method: str = "clipboard_paste"
    auto_send: bool = False
    ctx_ocr: bool = True
    ctx_selected_text: bool = False
    ctx_clipboard: bool = False
    enabled: bool = True
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Mode":
        return cls(
            id=row["id"],
            name=row["name"] or "",
            is_builtin=bool(row["is_builtin"]),
            description=row["description"] or "",
            stt_provider=row["stt_provider"],
            stt_model=row["stt_model"],
            language=row["language"] or "en",
            formatting_prompt=row["formatting_prompt"] or "",
            output_format=row["output_format"] or "plain",
            llm_enabled=bool(row["llm_enabled"]),
            llm_provider=row["llm_provider"],
            llm_model=row["llm_model"],
            llm_prompt=row["llm_prompt"] or "",
            paste_method=row["paste_method"] or "clipboard_paste",
            auto_send=bool(row["auto_send"]),
            ctx_ocr=bool(row["ctx_ocr"]),
            ctx_selected_text=bool(row["ctx_selected_text"]),
            ctx_clipboard=bool(row["ctx_clipboard"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )


BUILTIN_MODES: list[dict[str, str]] = [
    {"name": "Voice", "description": "Raw transcription with minimal formatting.", "formatting_prompt": "", "output_format": "plain"},
    {"name": "Message", "description": "Clean up dictated message for chat apps.", "formatting_prompt": "Clean up the following dictated message for sending in a chat app. Keep it conversational and concise.", "output_format": "plain"},
    {"name": "Email", "description": "Polished professional email body.", "formatting_prompt": "Rewrite the following dictated text as a polished professional email body. Preserve the meaning exactly.", "output_format": "plain"},
    {"name": "Note", "description": "Clear, well-punctuated prose.", "formatting_prompt": "Clean up the following dictated text into clear, well-punctuated prose.", "output_format": "plain"},
    {"name": "Coding", "description": "Code comment or docstring formatting.", "formatting_prompt": "Reformat the following dictated text as a code comment or docstring.", "output_format": "plain"},
    {"name": "Meeting", "description": "Structured meeting notes with bullet points.", "formatting_prompt": "Rewrite the following dictated notes as structured meeting notes with bullet points.", "output_format": "markdown"},
    {"name": "DaVinci Marker", "description": "Informal, lowercase, no punctuation for edit markers.", "formatting_prompt": "Convert to all lowercase and remove punctuation for quick edit notes.", "output_format": "plain"},
    {"name": "Screenwriting", "description": "Basic screenwriting formatting heuristics.", "formatting_prompt": "Apply basic screenwriting formatting: scene headings in ALL CAPS, character names in ALL CAPS.", "output_format": "plain"},
    {"name": "Custom", "description": "User-defined mode.", "formatting_prompt": "", "output_format": "plain"},
]

_BOOL_FIELDS = {"llm_enabled", "auto_send", "ctx_ocr", "ctx_selected_text", "ctx_clipboard", "enabled"}
_MODE_FIELDS = {
    "name",
    "description",
    "stt_provider",
    "stt_model",
    "language",
    "formatting_prompt",
    "output_format",
    "llm_enabled",
    "llm_provider",
    "llm_model",
    "llm_prompt",
    "paste_method",
    "auto_send",
    "ctx_ocr",
    "ctx_selected_text",
    "ctx_clipboard",
    "enabled",
}


def _coerce_field(name: str, value: Any) -> Any:
    if name in _BOOL_FIELDS:
        return int(bool(value))
    return value


def seed_builtins() -> None:
    """Insert built-in modes while respecting deleted built-in tombstones."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        deleted = {str(row["name"]).lower() for row in cursor.execute("SELECT name FROM deleted_builtin_modes")}
        for item in BUILTIN_MODES:
            if item["name"].lower() in deleted:
                continue
            cursor.execute(
                """
                INSERT INTO modes (name, is_builtin, description, formatting_prompt, output_format, enabled)
                VALUES (?, 1, ?, ?, ?, 1)
                ON CONFLICT(name) DO NOTHING
                """,
                (item["name"], item["description"], item["formatting_prompt"], item["output_format"]),
            )
        conn.commit()
    finally:
        conn.close()


def add_mode(
    name: str,
    description: str = "",
    formatting_prompt: str = "",
    output_format: str = "plain",
    llm_enabled: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_prompt: str = "",
    paste_method: str = "clipboard_paste",
    auto_send: bool = False,
    ctx_ocr: bool = True,
    ctx_selected_text: bool = False,
    ctx_clipboard: bool = False,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO modes
                (name, description, formatting_prompt, output_format,
                 llm_enabled, llm_provider, llm_model, llm_prompt,
                 paste_method, auto_send, ctx_ocr, ctx_selected_text, ctx_clipboard)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                description,
                formatting_prompt,
                output_format,
                int(llm_enabled),
                llm_provider,
                llm_model,
                llm_prompt,
                paste_method,
                int(auto_send),
                int(ctx_ocr),
                int(ctx_selected_text),
                int(ctx_clipboard),
            ),
        )
        mode_id = int(cursor.lastrowid)
        conn.commit()
        return mode_id
    finally:
        conn.close()


def list_modes(enabled_only: bool = False) -> list[Mode]:
    conn = get_connection()
    try:
        query = "SELECT * FROM modes"
        params: tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE enabled = ?"
            params = (1,)
        query += " ORDER BY is_builtin DESC, name ASC"
        return [Mode.from_row(row) for row in conn.execute(query, params)]
    finally:
        conn.close()


def get_mode(mode_id: int) -> Mode | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM modes WHERE id = ?", (mode_id,)).fetchone()
        return Mode.from_row(row) if row else None
    finally:
        conn.close()


def get_mode_by_name(name: str) -> Mode | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM modes WHERE name = ?", (name,)).fetchone()
        return Mode.from_row(row) if row else None
    finally:
        conn.close()


def update_mode(mode_id: int, **kwargs: Any) -> bool:
    fields = {key: _coerce_field(key, value) for key, value in kwargs.items() if key in _MODE_FIELDS}
    if not fields:
        return False
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = [*fields.values(), int(mode_id)]
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE modes SET {assignments} WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_mode(mode_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        row = cursor.execute("SELECT name, is_builtin FROM modes WHERE id = ?", (mode_id,)).fetchone()
        if row is None:
            return False
        if row["is_builtin"]:
            cursor.execute(
                """
                INSERT INTO deleted_builtin_modes (name, deleted_at)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET deleted_at = CURRENT_TIMESTAMP
                """,
                (row["name"],),
            )
        cursor.execute("DELETE FROM auto_activation_rules WHERE mode_id = ?", (mode_id,))
        cursor.execute("DELETE FROM modes WHERE id = ?", (mode_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def add_auto_rule(mode_id: int, match_type: str, match_value: str, priority: int = 0, enabled: bool = True) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO auto_activation_rules (mode_id, match_type, match_value, priority, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(mode_id), match_type, match_value, int(priority), int(enabled)),
        )
        rule_id = int(cursor.lastrowid)
        conn.commit()
        return rule_id
    finally:
        conn.close()


def list_auto_rules(mode_id: int | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        if mode_id is None:
            rows = conn.execute("SELECT * FROM auto_activation_rules ORDER BY priority DESC, id ASC")
        else:
            rows = conn.execute(
                "SELECT * FROM auto_activation_rules WHERE mode_id = ? ORDER BY priority DESC, id ASC",
                (int(mode_id),),
            )
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_auto_rule(rule_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM auto_activation_rules WHERE id = ?", (int(rule_id),))
        conn.commit()
    finally:
        conn.close()


def resolve_active_mode(active_app: str = "", window_title: str = "") -> Mode:
    """Return the first enabled mode matching the active app/title."""
    app = (active_app or "").lower()
    title = (window_title or "").lower()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.*, r.match_type, r.match_value
            FROM modes m
            JOIN auto_activation_rules r ON r.mode_id = m.id
            WHERE r.enabled = 1 AND m.enabled = 1
            ORDER BY r.priority DESC, r.id ASC
            """
        )
        for row in rows:
            match_type = str(row["match_type"] or "")
            value = str(row["match_value"] or "").lower()
            if match_type == "process" and value in app:
                return Mode.from_row(row)
            if match_type == "window_title" and value in title:
                return Mode.from_row(row)
            if match_type == "exe_path" and value in app:
                return Mode.from_row(row)
    finally:
        conn.close()
    fallback = get_mode_by_name("Voice")
    return fallback if fallback else Mode(name="Voice")
