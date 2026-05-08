"""Output delivery helpers for clipboard paste, typing, and copy-only flows."""

from __future__ import annotations

import threading
import time

try:
    import pyperclip

    _CLIPBOARD_AVAILABLE = True
except Exception:
    pyperclip = None  # type: ignore[assignment]
    _CLIPBOARD_AVAILABLE = False

try:
    import keyboard

    _KEYBOARD_AVAILABLE = True
except Exception:
    keyboard = None  # type: ignore[assignment]
    _KEYBOARD_AVAILABLE = False


def _restore_clipboard_later(old: str, delay: float = 0.8) -> None:
    if not _CLIPBOARD_AVAILABLE:
        return

    def _restore() -> None:
        try:
            pyperclip.copy(old)  # type: ignore[union-attr]
        except Exception:
            pass

    timer = threading.Timer(max(0.0, float(delay)), _restore)
    timer.daemon = True
    timer.start()


def paste_text(
    text: str,
    method: str = "clipboard_paste",
    restore_clipboard: bool = False,
    auto_send: bool = False,
    active_app: str = "",
    paste_delay_ms: int = 50,
) -> bool:
    """Deliver text to the active application.

    ``active_app`` is kept for compatibility with per-app callers; the delivery
    primitive itself stays intentionally small and deterministic.
    """
    del active_app
    text = text or ""

    if method == "copy_only":
        if _CLIPBOARD_AVAILABLE:
            pyperclip.copy(text)  # type: ignore[union-attr]
        return True

    old_clipboard = ""
    if restore_clipboard and _CLIPBOARD_AVAILABLE:
        try:
            old_clipboard = pyperclip.paste()  # type: ignore[union-attr]
        except Exception:
            old_clipboard = ""

    if method == "clipboard_paste":
        if _CLIPBOARD_AVAILABLE:
            pyperclip.copy(text)  # type: ignore[union-attr]
        try:
            delay_s = max(0.0, int(paste_delay_ms) / 1000.0)
        except (TypeError, ValueError):
            delay_s = 0.05
        if delay_s:
            time.sleep(delay_s)
        if _KEYBOARD_AVAILABLE:
            keyboard.send("ctrl+v")  # type: ignore[union-attr]
        if restore_clipboard:
            _restore_clipboard_later(old_clipboard)
        if auto_send and _KEYBOARD_AVAILABLE:
            keyboard.send("enter")  # type: ignore[union-attr]
        return True

    if method == "simulate_keys":
        if _KEYBOARD_AVAILABLE:
            keyboard.write(text, delay=0.01)  # type: ignore[union-attr]
            if auto_send:
                keyboard.send("enter")  # type: ignore[union-attr]
        return True

    return False
