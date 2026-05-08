"""Context extraction: foreground window, OCR, clipboard, and UI Automation."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time

import config
from core.term_filter import extract_useful_terms

try:
    import mss
    from PIL import Image

    _SCREENSHOT_AVAILABLE = True
except Exception:
    mss = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    _SCREENSHOT_AVAILABLE = False

try:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
    _TESSERACT_AVAILABLE = True
except Exception:
    pytesseract = None  # type: ignore[assignment]
    _TESSERACT_AVAILABLE = False


_OCR_CACHE_TTL_S = 12.0
_ocr_cache_lock = threading.RLock()
_ocr_cache: dict[str, object] = {"key": None, "text": "", "ts": 0.0, "refreshing": False}


def _get_active_window_rect() -> tuple[int, int, int, int] | None:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = ctypes.wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass
    return None


def _get_active_process_name() -> str:
    import psutil
    import win32gui
    import win32process

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return ""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def get_active_window_name() -> str:
    try:
        return _get_active_process_name()
    except Exception:
        return ""


def get_active_window_title() -> str:
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd) if hwnd else ""
    except Exception:
        return ""


def _capture_screen_context_uncached(rect: tuple[int, int, int, int]) -> str:
    if not config.OCR_ENABLED or not _TESSERACT_AVAILABLE or not _SCREENSHOT_AVAILABLE:
        return ""
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return ""
    try:
        with mss.mss() as sct:  # type: ignore[union-attr]
            screenshot = sct.grab({"left": left, "top": top, "width": width, "height": height})
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")  # type: ignore[union-attr]
    except Exception:
        return ""

    max_dim = 1920
    if img.width > max_dim or img.height > max_dim:
        ratio = max_dim / max(img.width, img.height)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.BILINEAR)  # type: ignore[union-attr]
    try:
        raw_text = pytesseract.image_to_string(img, config="--psm 6")  # type: ignore[union-attr]
    except Exception:
        return ""
    return " ".join(extract_useful_terms(raw_text, limit=90, source="ocr", include_phrases=False))


def capture_screen_context() -> str:
    rect = _get_active_window_rect()
    if rect is None:
        return ""
    text = _capture_screen_context_uncached(rect)
    key = (_get_active_process_name(), rect)
    with _ocr_cache_lock:
        _ocr_cache.update({"key": key, "text": text, "ts": time.time(), "refreshing": False})
    return text


def capture_screen_context_cached(blocking: bool = False) -> str:
    rect = _get_active_window_rect()
    if rect is None:
        return ""
    key = (_get_active_process_name(), rect)
    now = time.time()
    with _ocr_cache_lock:
        cached_key = _ocr_cache.get("key")
        cached_text = str(_ocr_cache.get("text") or "")
        cached_ts = float(_ocr_cache.get("ts") or 0.0)
        refreshing = bool(_ocr_cache.get("refreshing"))
        if cached_key == key and now - cached_ts <= _OCR_CACHE_TTL_S:
            return cached_text
        if refreshing and cached_key == key:
            return cached_text
        if blocking:
            _ocr_cache["refreshing"] = True
        else:
            _ocr_cache.update({"key": key, "refreshing": True})

    def _refresh() -> None:
        text = _capture_screen_context_uncached(rect)
        with _ocr_cache_lock:
            _ocr_cache.update({"key": key, "text": text, "ts": time.time(), "refreshing": False})

    if blocking:
        _refresh()
        with _ocr_cache_lock:
            return str(_ocr_cache.get("text") or "")
    threading.Thread(target=_refresh, daemon=True).start()
    return cached_text if cached_key == key else ""


def capture_selected_text() -> str:
    try:
        import keyboard
        import pyperclip
    except Exception:
        return ""
    try:
        before = pyperclip.paste()
    except Exception:
        before = ""
    try:
        keyboard.send("ctrl+c")
    except Exception:
        return ""
    time.sleep(0.05)
    try:
        after = pyperclip.paste()
    except Exception:
        return ""
    if after == before:
        return ""

    def _restore() -> None:
        try:
            pyperclip.copy(before)
        except Exception:
            pass

    threading.Timer(0.2, _restore).start()
    return after


_last_clipboard_change = 0.0
_last_clipboard_text = ""


def capture_clipboard_context() -> str:
    global _last_clipboard_change, _last_clipboard_text
    try:
        import pyperclip

        text = pyperclip.paste()
        if text != _last_clipboard_text:
            _last_clipboard_text = text
            _last_clipboard_change = time.time()
        if time.time() - _last_clipboard_change <= 30:
            return _last_clipboard_text
    except Exception:
        pass
    return ""


def mark_clipboard_pasted() -> None:
    global _last_clipboard_change, _last_clipboard_text
    _last_clipboard_change = 0.0
    _last_clipboard_text = ""


def capture_ui_automation_text(hwnd: int | None = None) -> str:
    try:
        import comtypes.client

        automation = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
        if hwnd is None:
            import win32gui

            hwnd = win32gui.GetForegroundWindow()
        del hwnd
        element = automation.GetFocusedElement()
        if element is None:
            return ""
        text = element.CurrentName or ""
        value_pattern = element.GetCurrentPattern(10002)
        if value_pattern:
            text += " " + (value_pattern.CurrentValue or "")
        return text.strip()
    except Exception:
        return ""


def get_text_before_cursor(max_chars: int = 4) -> str:
    try:
        max_chars = max(1, min(16, int(max_chars)))
    except (TypeError, ValueError):
        max_chars = 4
    try:
        import comtypes.client

        automation = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
        element = automation.GetFocusedElement()
        if element is None:
            return ""
        for pattern_id in (10024, 10014):
            try:
                text_pattern = element.GetCurrentPattern(pattern_id)
            except Exception:
                text_pattern = None
            if not text_pattern:
                continue
            try:
                ranges = text_pattern.GetSelection()
                if getattr(ranges, "Length", 0) <= 0:
                    continue
                caret_range = ranges.GetElement(0)
            except Exception:
                continue
            try:
                if caret_range.CompareEndpoints(0, caret_range, 1) != 0:
                    return ""
            except Exception:
                pass
            try:
                before = caret_range.Clone()
                before.MoveEndpointByUnit(0, 1, -max_chars)
                return str(before.GetText(max_chars) or "")
            except Exception:
                continue
    except Exception:
        return ""
    return ""
