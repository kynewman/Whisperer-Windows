"""Small, dependency-free diagnostics helpers for installed builds."""

from __future__ import annotations

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import re
import sys
import tempfile
import threading
import time
import traceback
from typing import Iterable


_FAULT_HANDLES = []
_LOCK = threading.Lock()
_REDACT_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
_PATH_MARKERS = ("PATH", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES")


def _candidate_log_dirs() -> list[str]:
    return [
        os.environ.get("WHISPERER_LOG_DIR", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Whisperer", "logs"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Whisperer", "logs"),
        os.path.join(tempfile.gettempdir(), "Whisperer", "logs"),
    ]


def log_dir() -> str:
    candidates = _candidate_log_dirs()
    for candidate in candidates:
        if not candidate:
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except Exception:
            continue
    return os.getcwd()


def log_path(filename: str) -> str:
    return os.path.join(log_dir(), filename)


def _writable_log_path(filename: str) -> str | None:
    seen: set[str] = set()
    for directory in [log_dir(), *_candidate_log_dirs(), os.getcwd()]:
        if not directory:
            continue
        try:
            directory = os.path.abspath(directory)
        except Exception:
            continue
        if directory in seen:
            continue
        seen.add(directory)
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, filename)
            with open(path, "a", encoding="utf-8", errors="replace"):
                pass
            return path
        except Exception:
            continue
    return None


def append_log_line(filename: str, message: str) -> None:
    try:
        with _LOCK:
            with open(log_path(filename), "a", encoding="utf-8", errors="replace") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {_scrub_text(str(message))}\n")
    except Exception:
        pass


def configure_process_logging(process_name: str) -> logging.Logger:
    path = _writable_log_path(f"{process_name}.log")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers:
        if getattr(handler, "_whisperer_log_path", None) == path:
            return logging.getLogger(f"whisperer.{process_name}")

    logger = logging.getLogger(f"whisperer.{process_name}")
    if not path:
        root.addHandler(logging.NullHandler())
        return logger

    try:
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=4, encoding="utf-8")
    except Exception:
        root.addHandler(logging.NullHandler())
        return logger
    handler._whisperer_log_path = path  # type: ignore[attr-defined]
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d %(levelname)s "
            "[pid=%(process)d thread=%(threadName)s] %(name)s: %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    logger.info("logging initialized file=%s", _scrub_text(path))
    return logger


def enable_fault_logging(process_name: str) -> str:
    path = log_path(f"fatal-{process_name}.log")
    try:
        handle = open(path, "a", encoding="utf-8", errors="replace")
        handle.write(f"\n--- faulthandler enabled {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} ---\n")
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        _FAULT_HANDLES.append(handle)
    except Exception:
        pass
    return path


def _redact_env_value(key: str, value: str) -> str:
    upper = key.upper()
    if any(marker in upper for marker in _REDACT_MARKERS):
        return "<redacted>"
    return _scrub_text(value, limit=500)


def _scrub_text(value: str, *, limit: int | None = None) -> str:
    text = value or ""
    userprofile = os.environ.get("USERPROFILE") or ""
    username = os.environ.get("USERNAME") or ""
    if userprofile:
        text = text.replace(userprofile, "%USERPROFILE%")
    if username:
        text = re.sub(rf"(?i)(C:\\Users\\){re.escape(username)}", r"\1%USERNAME%", text)
        text = text.replace(username, "%USERNAME%")
    if limit and len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


def scrub_text(value: str, *, limit: int | None = None) -> str:
    return _scrub_text(value, limit=limit)


def selected_environment(keys: Iterable[str] | None = None) -> dict[str, str]:
    if keys is None:
        prefixes = ("WHISPERER_", "QT", "PYTHON", "PATH", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES")
        items = ((key, value) for key, value in os.environ.items() if key.upper().startswith(prefixes))
    else:
        items = ((key, os.environ.get(key, "")) for key in keys)
    return {key: _redact_env_value(key, value) for key, value in sorted(items)}


def log_process_snapshot(logger: logging.Logger, label: str) -> None:
    try:
        try:
            import config

            version = getattr(config, "VERSION", "unknown")
        except Exception:
            version = "unknown"
        logger.info(
            "%s snapshot version=%s pid=%s ppid=%s frozen=%s cwd=%s executable=%s argv=%r",
            label,
            version,
            os.getpid(),
            os.getppid() if hasattr(os, "getppid") else "unknown",
            bool(getattr(sys, "frozen", False)),
            _scrub_text(os.getcwd()),
            _scrub_text(sys.executable),
            [_scrub_text(str(arg), limit=500) for arg in sys.argv],
        )
        logger.info(
            "%s python=%s prefix=%s base_prefix=%s platform=%s win32=%r meipass=%s",
            label,
            sys.version.replace("\n", " "),
            sys.prefix,
            getattr(sys, "base_prefix", ""),
            platform.platform(),
            platform.win32_ver(),
            _scrub_text(getattr(sys, "_MEIPASS", "")),
        )
        logger.info("%s env=%r", label, selected_environment())
    except Exception:
        logger.debug("could not write process snapshot", exc_info=True)


def install_excepthook(logger: logging.Logger, show_callback=None) -> None:
    def _hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.error("unhandled exception\n%s", text)
        if show_callback:
            try:
                show_callback(text)
            except Exception:
                logger.debug("startup exception callback failed", exc_info=True)

    sys.excepthook = _hook


def install_qt_message_handler() -> None:
    try:
        from PyQt6.QtCore import qInstallMessageHandler
    except Exception:
        return

    logger = logging.getLogger("whisperer.qt")
    append_log_line("qt.log", "Qt message handler installed")

    def _handler(mode, context, message: str) -> None:
        mode_name = getattr(mode, "name", str(mode))
        category = getattr(context, "category", "") or ""
        file_name = getattr(context, "file", "") or ""
        line = getattr(context, "line", 0) or 0
        text = f"{mode_name} {category} {file_name}:{line}: {message}"
        append_log_line("qt.log", text)
        if "warning" in mode_name.lower() or "critical" in mode_name.lower() or "fatal" in mode_name.lower():
            logger.warning(text)
        else:
            logger.info(text)

    qInstallMessageHandler(_handler)
