"""Output delivery: paste, type, clipboard restore, auto-send."""

from __future__ import annotations

import time
import threading

try:
    import pyperclip
    _CLIPBOARD_AVAILABLE = True
except Exception:
    _CLIPBOARD_AVAILABLE = False

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except Exception:
    _KEYBOARD_AVAILABLE = False


def _restore_clipboard_later(old: str, delay: float = 0.8):
    def _restore():
        try:
            pyperclip.copy(old)
        except Exception:
            pass
    threading.Timer(delay, _restore).start()


def paste_text(
    text: str,
    method: str = "clipboard_paste",
    restore_clipboard: bool = False,
    auto_send: bool = False,
    active_app: str = "",
    paste_delay_ms: int = 50,
) -> bool:
    """
    Deliver text to the active window.

    method:
        clipboard_paste — copy to clipboard then Ctrl+V
        simulate_keys   — type character by character (keyboard.write)
        copy_only       — copy to clipboard but do not paste

    Returns True if the method executed without known errors.
    """
    if method == "copy_only":
        if _CLIPBOARD_AVAILABLE:
            pyperclip.copy(text)
        return True

    old_clipboard = ""
    if restore_clipboard and _CLIPBOARD_AVAILABLE:
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            old_clipboard = ""

    if method == "clipboard_paste":
        if _CLIPBOARD_AVAILABLE:
            pyperclip.copy(text)
        # tiny pause so the OS registers the clipboard update
        try:
            delay_s = max(0, int(paste_delay_ms)) / 1000.0
        except (TypeError, ValueError):
            delay_s = 0.05
        time.sleep(delay_s)
        if _KEYBOARD_AVAILABLE:
            keyboard.send("ctrl+v")
        if restore_clipboard and _CLIPBOARD_AVAILABLE:
            _restore_clipboard_later(old_clipboard)
        if auto_send and _KEYBOARD_AVAILABLE:
            keyboard.send("enter")
        return True

    if method == "simulate_keys":
        if _KEYBOARD_AVAILABLE:
            keyboard.write(text, delay=0.01)
        if auto_send and _KEYBOARD_AVAILABLE:
            keyboard.send("enter")
        return True

    return False
