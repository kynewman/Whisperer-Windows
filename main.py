"""
=============================================================================
  Whisper Project  —  Main Entry Point
=============================================================================
  A local, high-performance speech-to-text app for Windows.

  Usage:
      python main.py

  Hotkeys (configurable in Settings > Shortcuts):
      Dictation hotkey (hold)  — Quick dictation. Release to transcribe & paste.
      Dictation + Alt          — Long-form mode. Keeps recording after release.
      Dictation double-tap     — Long-form mode without holding the shortcut.
      Toggle recording         — Start/stop recording without holding.
      Cancel                   — Discard current recording.
      Mode next / prev         — Cycle through enabled modes.
      Repeat last              — Paste the last dictation again.
=============================================================================
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback


def _prefer_external_python_packages_for_installed_source() -> None:
    """
    Installed builds run the engine with system Python against files in
    ``_internal``. Keep that app code importable, but let real site-packages win
    over PyInstaller's partial bundled package folders.
    """
    app_root = os.environ.get("WHISPERER_PROJECT_ROOT") or os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(app_root).lower() != "_internal":
        return
    try:
        app_root = os.path.normcase(os.path.abspath(app_root))
        moved = False
        next_path: list[str] = []
        for entry in sys.path:
            comparable = os.path.normcase(os.path.abspath(entry or os.curdir))
            if comparable == app_root:
                moved = True
                continue
            next_path.append(entry)
        if moved:
            next_path.append(app_root)
            sys.path[:] = next_path
    except Exception:
        pass


_prefer_external_python_packages_for_installed_source()

_PROCESS_START = time.perf_counter()

import config

_EARLY_MODEL_NAME = next(
    (arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--model=")),
    config.WHISPER_MODEL_SIZE,
)
if _EARLY_MODEL_NAME.lower().startswith("nvidia/parakeet"):
    import torch  # must be imported before PyQt6 to avoid c10.dll crash on Windows for NeMo/PyTorch
import numpy as np
import keyboard

from PyQt6.QtCore import QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import QApplication

from core.audio import AudioRecorder
from core.transcriber import (
    NVIDIA_RIVA_CTC_MODEL,
    NVIDIA_RIVA_TDT_MODEL,
    NvidiaStreamingTranscriber,
    load_model,
    nvidia_riva_model_supports_streaming,
    prewarm_nvidia_riva,
    transcribe,
    transcribe_cloud,
    transcribe_nvidia_riva_streaming,
    warmup_model,
)
from core.context import (
    capture_clipboard_context,
    capture_screen_context,
    capture_screen_context_cached,
    capture_selected_text,
    capture_ui_automation_text,
    get_active_window_name,
    get_active_window_title,
    get_text_before_cursor,
    mark_clipboard_pasted,
)
from core.formatter import format_transcription
from core.dictionary import add_words_from_list, apply_replacements, get_prompt_words
from core.term_filter import extract_useful_terms
from core.modes import resolve_active_mode, list_modes, get_mode_by_name
from core.history import save_dictation, save_context
from core.file_transcriber import transcribe_file
from core.settings import load_settings
from core.output import paste_text
from core.perf import record_timing, timed
from core.audio_ducking import AudioDucker
from core.single_instance import acquire as acquire_single_instance
from ui.overlay import WaveformOverlay


_SENTENCE_END_CHARS = ".?!\u2026"
_SENTENCE_CLOSING_CHARS = "\"')]}\u201d\u2019\u00bb"
_SMART_SPACING_CLIPBOARD_PROBE_SKIP_APPS = (
    "cmd.exe",
    "conhost.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "terminal.exe",
)


def _normalize_keyboard_hotkey(hotkey: str | None) -> str | None:
    """Convert Qt key names into names understood by the keyboard package."""
    if not hotkey:
        return hotkey

    parts = []
    for part in hotkey.split("+"):
        key = part.strip().lower()
        if key in {"meta", "win", "windows"}:
            key = "left windows"
        elif key == "control":
            key = "ctrl"
        elif key == "esc":
            key = "escape"
        parts.append(key)
    return "+".join(parts)


def _write_engine_ready_file(model_name: str) -> None:
    ready_file = os.environ.get("WHISPERER_ENGINE_READY_FILE")
    if not ready_file:
        return
    try:
        ready_dir = os.path.dirname(ready_file)
        if ready_dir:
            os.makedirs(ready_dir, exist_ok=True)
        with open(ready_file, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "model": model_name,
                    "readyAt": time.time(),
                },
                handle,
                separators=(",", ":"),
            )
    except Exception:
        pass

# Attempt to import Vosk for live recognition
try:
    from core.live_recognition import LiveRecognizer
    _VOSK_AVAILABLE = True
except Exception:
    _VOSK_AVAILABLE = False

ENGINE_FORCE_STOP_RESTART_CODE = 42
LONGFORM_POLL_INTERVAL_S = 0.006
LONGFORM_RELEASE_DEBOUNCE_S = 0.035
LONGFORM_LOCK_GRACE_S = 0.14
LONGFORM_STOP_ARM_DEBOUNCE_S = 0.06
DOUBLE_TAP_LOCK_WINDOW_S = 0.32
DOUBLE_TAP_LOCK_MAX_FIRST_PRESS_S = 0.50
LOADING_PREVIEW_HIDE_S = 1.4
WAVEFORM_FEED_INTERVAL_MS = 16


def _looks_silent(audio: np.ndarray, threshold: float = 0.0015) -> bool:
    if audio is None or len(audio) == 0:
        return True
    try:
        return float(np.sqrt(np.mean(audio.astype(np.float32, copy=False) ** 2))) < threshold
    except Exception:
        return False


class Signals(QObject):
    """Bridge between background threads and the Qt UI thread."""
    show_overlay = pyqtSignal()
    show_model_loading = pyqtSignal()
    hide_overlay = pyqtSignal()
    set_active = pyqtSignal(bool)
    set_status = pyqtSignal(str)
    set_transcribed_text = pyqtSignal(str)
    set_mode = pyqtSignal(str)
    set_processing = pyqtSignal(bool)
    mode_changed = pyqtSignal(str)
    open_history = pyqtSignal()
    set_locked = pyqtSignal(bool)
    set_model_loading = pyqtSignal(bool)


class WhisperApp:
    """
    Orchestrates the full dictation workflow with configurable shortcuts,
    cancel behavior, mode cycling, and flexible output delivery.
    """

    def __init__(self):
        if not acquire_single_instance("WhispererWindowsEngine"):
            raise SystemExit(0)
        self.app = QApplication(sys.argv)
        self.overlay = WaveformOverlay()
        self.signals = Signals()
        self._context_words = ""
        self._running = True
        self._session_lock = threading.Lock()
        self._cancelled = False
        self._toggle_mode = False
        self._longform_requested = threading.Event()
        self._session_started_monotonic = 0.0
        self._processing_job_active = threading.Event()
        self._model_ready = threading.Event()
        self._model_failed = ""
        self._loading_preview_visible = False
        self._loading_preview_lock = threading.Lock()
        self._pre_ready_hotkey_lock = threading.Lock()
        self._suppress_pre_ready_hotkey_until_release = False
        self._pre_ready_longform_requested = threading.Event()
        self._audio_ducker: AudioDucker | None = None
        self._audio_ducker_lock = threading.Lock()
        self._audio_ducking_ticket = 0
        self._stdin_command_reader_started = False
        self._last_dictation_text = ""
        self._last_mic_level_emit = 0.0
        self._registered_hotkeys: list = []
        self._modes_list: list = []
        self._current_mode_index = 0
        self._refresh_modes_list()

        # Word dictionary tracking
        self._recent_words = set()
        self._live_words = ""

        # Live Vosk recognizer. It is initialized after the main STT model is
        # ready so Vosk and NeMo never compete during startup imports.
        self._live_recognizer = None
        self.recorder = AudioRecorder(live_recognizer=None)
        self.app.aboutToQuit.connect(self.recorder.close)

        self.signals.show_overlay.connect(self.overlay.fade_in)
        self.signals.show_model_loading.connect(self.overlay.show_model_loading)
        self.signals.hide_overlay.connect(self.overlay.fade_out)
        self.signals.set_active.connect(self.overlay.set_active)
        self.signals.set_status.connect(self.overlay.set_status)
        self.signals.set_transcribed_text.connect(self.overlay.append_transcribed_text)
        self.signals.set_mode.connect(self.overlay.set_mode)
        self.signals.set_processing.connect(self.overlay.set_processing)
        self.signals.mode_changed.connect(self._on_mode_changed_overlay)
        self.signals.set_locked.connect(self.overlay.set_locked)
        self.signals.set_model_loading.connect(self.overlay.set_model_loading)
        self.overlay.open_ui_requested.connect(self._on_overlay_open_ui)
        self.overlay.force_stop_requested.connect(self._on_overlay_force_stop)

        self._feed_waveform = self._feed_waveform
        self._waveform_timer = QTimer()
        self._waveform_timer.timeout.connect(self._feed_waveform)
        self._waveform_timer.start(WAVEFORM_FEED_INTERVAL_MS)

    def _show_model_loading_overlay(self):
        if os.environ.get("WHISPERER_UI_LOADING_PREVIEW") == "1":
            return
        with self._loading_preview_lock:
            self._loading_preview_visible = True
        self.signals.set_processing.emit(False)
        self.signals.set_active.emit(False)
        self.signals.set_locked.emit(False)
        self.signals.set_status.emit("")
        self.signals.show_model_loading.emit()
        threading.Timer(LOADING_PREVIEW_HIDE_S, self._hide_loading_preview_quickly).start()

    def _mark_pre_ready_hotkey(self):
        with self._pre_ready_hotkey_lock:
            self._suppress_pre_ready_hotkey_until_release = True
        self._pre_ready_longform_requested.clear()

    def _clear_pre_ready_hotkey_after_release(self):
        dictation_hk = self._get_dictation_hotkey()
        while self._running and self._is_dictation_hotkey_pressed(dictation_hk):
            time.sleep(0.025)
        with self._pre_ready_hotkey_lock:
            self._suppress_pre_ready_hotkey_until_release = False
        self._pre_ready_longform_requested.clear()

    def _pre_ready_hotkey_still_held(self) -> bool:
        with self._pre_ready_hotkey_lock:
            suppress = self._suppress_pre_ready_hotkey_until_release
        if not suppress:
            return False
        if self._is_dictation_hotkey_pressed(self._get_dictation_hotkey()):
            return True
        if self._pre_ready_longform_requested.is_set():
            return True
        with self._pre_ready_hotkey_lock:
            self._suppress_pre_ready_hotkey_until_release = False
        self._pre_ready_longform_requested.clear()
        return False

    def _clear_pre_ready_hotkey_suppression(self):
        with self._pre_ready_hotkey_lock:
            self._suppress_pre_ready_hotkey_until_release = False
        self._pre_ready_longform_requested.clear()

    def _start_pre_ready_hotkey_dictation_if_held(self) -> bool:
        if not self._model_ready.is_set():
            return False
        longform_requested = self._pre_ready_longform_requested.is_set() or self._is_alt_pressed()
        hotkey_held = self._is_dictation_hotkey_pressed(self._get_dictation_hotkey())
        if not hotkey_held and not longform_requested:
            with self._pre_ready_hotkey_lock:
                self._suppress_pre_ready_hotkey_until_release = False
            return False
        if not self._session_lock.acquire(blocking=False):
            return False
        self._clear_pre_ready_hotkey_suppression()
        self._clear_longform_lock()
        self._prime_listening_overlay()
        if longform_requested:
            self._request_longform_lock()
        threading.Thread(
            target=lambda: self._run_one_dictation_session(lock_acquired=True, overlay_primed=True),
            daemon=True,
        ).start()
        return True

    def _hide_loading_preview_quickly(self):
        with self._loading_preview_lock:
            preview_visible = self._loading_preview_visible
            self._loading_preview_visible = False
        if (
            preview_visible
            and not self.recorder.is_recording
            and not self._session_lock.locked()
            and not self._processing_job_active.is_set()
        ):
            self.signals.hide_overlay.emit()

    def _hide_loading_overlay_if_idle(self):
        with self._loading_preview_lock:
            preview_visible = self._loading_preview_visible
            self._loading_preview_visible = False
        if (
            preview_visible
            and self._model_ready.is_set()
            and not self.recorder.is_recording
            and not self._session_lock.locked()
            and not self._processing_job_active.is_set()
        ):
            self.signals.hide_overlay.emit()

    def _on_live_word(self, text: str):
        """Callback for live word from Vosk."""
        if self._live_recognizer:
            self._live_words = text
            self.signals.set_transcribed_text.emit(text)

    def _ensure_live_recognizer(self):
        if self._live_recognizer or not _VOSK_AVAILABLE:
            return
        try:
            self._live_recognizer = LiveRecognizer(text_callback=self._on_live_word)
            self.recorder.live_recognizer = self._live_recognizer
        except Exception as exc:
            print(f"Live recognizer deferred initialization failed: {exc}", flush=True)

    def _feed_waveform(self):
        if self.recorder.is_recording:
            chunk = self.recorder.live_chunk
            self.overlay.set_audio_chunk(chunk)
            self._emit_mic_level(chunk)
        else:
            self.overlay.set_audio_chunk(None)

    def _emit_mic_level(self, chunk: np.ndarray | None):
        now = time.monotonic()
        if now - self._last_mic_level_emit < 0.12:
            return
        self._last_mic_level_emit = now
        if chunk is None or len(chunk) == 0:
            print("MIC_LEVEL -96.0 0.0000", flush=True)
            return
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32, copy=False) ** 2)))
        db = 20.0 * float(np.log10(max(rms, 1e-7)))
        level = max(0.0, min(1.0, (db + 60.0) / 52.0))
        print(f"MIC_LEVEL {db:.1f} {level:.4f}", flush=True)

    def _refresh_modes_list(self):
        """Reload enabled modes for cycling."""
        self._modes_list = list_modes(enabled_only=True)
        if not self._modes_list:
            self._modes_list = [get_mode_by_name("Voice") or resolve_active_mode()]

    def _on_mode_changed_overlay(self, mode_name: str):
        """Show a brief mode-change notification in the overlay."""
        self.overlay.set_mode(mode_name)
        self.signals.show_overlay.emit()
        self.signals.set_status.emit(f"Mode: {mode_name}")
        QTimer.singleShot(1200, self.signals.hide_overlay.emit)

    def _on_overlay_open_ui(self):
        if self._show_launcher_window():
            return
        try:
            launcher_path = os.path.join(config.PROJECT_ROOT, "launcher.py")
            subprocess.Popen(
                [sys.executable, launcher_path],
                cwd=config.PROJECT_ROOT,
                creationflags=0x08000000,
            )
        except Exception:
            pass

    def _show_launcher_window(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd_match = wintypes.HWND()

            enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            @enum_proc_type
            def enum_proc(hwnd, lparam):
                if not user32.IsWindow(hwnd):
                    return True
                is_match = False
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value
                    is_match = title.startswith("Whisperer v")
                if not is_match:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value:
                        try:
                            import psutil

                            proc = psutil.Process(pid.value)
                            cmdline = " ".join(proc.cmdline()).lower()
                            is_match = "launcher.py" in cmdline and "whisperer" in cmdline
                        except Exception:
                            is_match = False
                if is_match:
                    hwnd_match.value = hwnd
                    return False
                return True

            user32.EnumWindows(enum_proc, 0)
            if not hwnd_match.value:
                return False
            user32.ShowWindow(hwnd_match.value, 5)  # SW_SHOW
            user32.ShowWindow(hwnd_match.value, 9)  # SW_RESTORE
            user32.SetWindowPos(hwnd_match.value, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetWindowPos(hwnd_match.value, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetForegroundWindow(hwnd_match.value)
            return True
        except Exception:
            return False

    def _on_overlay_force_stop(self):
        self._cancelled = True
        if self.recorder.is_recording:
            self.signals.set_status.emit("Stopping...")
            return
        if self._processing_job_active.is_set() or self._session_lock.locked():
            os._exit(ENGINE_FORCE_STOP_RESTART_CODE)
        self.signals.set_processing.emit(False)
        self.signals.hide_overlay.emit()

    def _prime_listening_overlay(self):
        print("DICTATION_STARTED", flush=True)
        self.signals.set_model_loading.emit(False)
        self.signals.set_processing.emit(False)
        if not self._longform_requested.is_set():
            self.signals.set_locked.emit(False)
        self.signals.set_active.emit(True)
        self.signals.set_status.emit("Listening...")
        self.signals.show_overlay.emit()

    def _request_longform_lock(self):
        self._longform_requested.set()
        self.signals.set_locked.emit(True)

    def _clear_longform_lock(self):
        self._longform_requested.clear()

    def _get_dictation_hotkey(self) -> str:
        settings = load_settings()
        hotkey = settings.get("shortcuts", {}).get("dictation") or config.DICTATION_HOTKEY
        return _normalize_keyboard_hotkey(hotkey) or config.DICTATION_HOTKEY

    def _is_dictation_hotkey_pressed(self, dictation_hk: str) -> bool:
        try:
            if keyboard.is_pressed(dictation_hk):
                return True
        except Exception:
            pass
        parts = [part.strip() for part in dictation_hk.split("+") if part.strip()]
        if not parts:
            return False
        try:
            return all(keyboard.is_pressed(part) for part in parts)
        except Exception:
            return False

    def _longform_lock_requested(self) -> bool:
        return self._longform_requested.is_set() or self._is_alt_pressed()

    def _double_tap_lock_config(self, settings: dict | None = None) -> tuple[bool, float, float]:
        dictation_cfg = (settings or load_settings()).get("dictation", {})
        enabled = bool(dictation_cfg.get("double_tap_lock_enabled", True))
        try:
            window_s = int(dictation_cfg.get("double_tap_lock_window_ms", 320)) / 1000.0
        except (TypeError, ValueError):
            window_s = DOUBLE_TAP_LOCK_WINDOW_S
        try:
            max_first_press_s = int(dictation_cfg.get("double_tap_lock_max_first_press_ms", 500)) / 1000.0
        except (TypeError, ValueError):
            max_first_press_s = DOUBLE_TAP_LOCK_MAX_FIRST_PRESS_S
        return (
            enabled,
            max(0.12, min(0.80, window_s)),
            max(0.12, min(1.20, max_first_press_s)),
        )

    def _wait_for_release_or_longform(
        self,
        dictation_hk: str,
        settings: dict | None = None,
        started_monotonic: float | None = None,
    ) -> bool | None:
        """
        Poll while the hotkey is held. Returns True for longform, False for quick mode,
        None if cancelled.
        """
        time.sleep(0.015)
        double_tap_enabled, double_tap_window_s, double_tap_max_first_press_s = self._double_tap_lock_config(settings)
        started = started_monotonic or time.monotonic()
        release_seen_at: float | None = None
        release_grace_until: float | None = None
        double_tap_deadline: float | None = None
        while True:
            if self._cancelled:
                return None
            if self._longform_lock_requested():
                self._request_longform_lock()
                return True
            now = time.monotonic()
            if self._is_dictation_hotkey_pressed(dictation_hk):
                if double_tap_deadline is not None and now <= double_tap_deadline:
                    self._request_longform_lock()
                    return True
                release_seen_at = None
                release_grace_until = None
                double_tap_deadline = None
                time.sleep(LONGFORM_POLL_INTERVAL_S)
            else:
                if release_seen_at is None:
                    release_seen_at = now
                    release_grace_until = now + LONGFORM_LOCK_GRACE_S
                    if double_tap_enabled and now - started <= double_tap_max_first_press_s:
                        double_tap_deadline = now + double_tap_window_s
                if now - release_seen_at < LONGFORM_RELEASE_DEBOUNCE_S:
                    time.sleep(LONGFORM_POLL_INTERVAL_S)
                    continue
                if release_grace_until is not None and now < release_grace_until:
                    time.sleep(LONGFORM_POLL_INTERVAL_S)
                    continue
                if double_tap_deadline is not None and now < double_tap_deadline:
                    time.sleep(LONGFORM_POLL_INTERVAL_S)
                    continue
                if self._longform_lock_requested():
                    self._request_longform_lock()
                    return True
                return False

    def _is_alt_pressed(self) -> bool:
        for key in ("alt", "left alt", "right alt", "menu"):
            try:
                if keyboard.is_pressed(key):
                    return True
            except Exception:
                continue
        return False

    def _wait_for_longform_stop(self, dictation_hk: str):
        """In long-form mode, wait for the user to press the dictation hotkey again or cancel."""
        released_at: float | None = None
        while not self._cancelled:
            if self._is_dictation_hotkey_pressed(dictation_hk):
                released_at = None
            else:
                if released_at is None:
                    released_at = time.time()
                if time.time() - released_at >= LONGFORM_STOP_ARM_DEBOUNCE_S:
                    break
            time.sleep(0.02)

        while not self._cancelled:
            if self._is_dictation_hotkey_pressed(dictation_hk):
                time.sleep(0.05)
                while self._is_dictation_hotkey_pressed(dictation_hk):
                    time.sleep(0.02)
                return
            time.sleep(0.02)

    def _wait_for_toggle_stop(self, dictation_hk: str):
        """In toggle mode, wait for toggle hotkey again or cancel."""
        while not self._cancelled:
            if self._is_dictation_hotkey_pressed(dictation_hk):
                time.sleep(0.05)
                while self._is_dictation_hotkey_pressed(dictation_hk):
                    time.sleep(0.02)
                return
            time.sleep(0.02)

    def _on_alt_lock_pressed(self):
        """Request long-form mode whenever Alt is pressed during an active dictation session."""
        if not self._model_ready.is_set():
            with self._pre_ready_hotkey_lock:
                waiting_for_ready = self._suppress_pre_ready_hotkey_until_release
            if waiting_for_ready and self._is_dictation_hotkey_pressed(self._get_dictation_hotkey()):
                self._pre_ready_longform_requested.set()
                self.signals.set_locked.emit(True)
            return
        if self._model_ready.is_set() and self._pre_ready_hotkey_still_held():
            self._clear_pre_ready_hotkey_suppression()
            if not self._session_lock.acquire(blocking=False):
                self._request_longform_lock()
                return
            self._clear_longform_lock()
            self._request_longform_lock()
            self._prime_listening_overlay()
            threading.Thread(
                target=lambda: self._run_one_dictation_session(lock_acquired=True, overlay_primed=True),
                daemon=True,
            ).start()
            return
        if self._session_lock.locked() or self.recorder.is_recording:
            self._request_longform_lock()

    def _provider_model(self, stt_provider: str, mode) -> str | None:
        mode_model = str(getattr(mode, "stt_model", "") or "").strip()
        if mode_model:
            return mode_model
        if stt_provider in {"local", "nvidia_parakeet"}:
            return config.WHISPER_MODEL_SIZE
        return None

    def _cloud_api_key(self, stt_provider: str) -> str:
        from core.secrets import get_key

        key = get_key(stt_provider.replace("_whisper", ""))
        if not key and stt_provider == "groq_whisper":
            key = get_key("groq")
        if not key and stt_provider == "openai_whisper":
            key = get_key("openai")
        if not key and stt_provider == "nvidia_parakeet":
            key = get_key("nvidia")
        if not key and stt_provider == "deepgram":
            key = get_key("deepgram")
        return key or ""

    def _should_use_nvidia_streaming(self, stt_provider: str, model_name: str | None) -> bool:
        if not nvidia_riva_model_supports_streaming(model_name):
            return False
        if stt_provider == "nvidia_parakeet":
            return True
        return stt_provider == "local" and (model_name or "").lower().startswith("nvidia/parakeet")

    def _maybe_start_streaming_transcriber(self, stt_provider: str, model_name: str | None):
        if not self._should_use_nvidia_streaming(stt_provider, model_name):
            return None
        key = self._cloud_api_key("nvidia_parakeet")
        if not key:
            return None
        try:
            streaming = NvidiaStreamingTranscriber(key, language=config.WHISPER_LANGUAGE, model=model_name)
            streaming.start()
            self.recorder.add_audio_consumer(streaming.feed_audio)
            print("STREAMING_STT_STARTED provider=nvidia_riva", flush=True)
            return streaming
        except Exception as exc:
            print(f"STREAMING_STT_START_FAILED {exc}", flush=True)
            return None

    def _start_parallel_nvidia_final_transcription(self, audio: np.ndarray, model_name: str | None):
        key = self._cloud_api_key("nvidia_parakeet")
        if not key:
            return None
        state = {
            "done": threading.Event(),
            "text": "",
            "error": None,
        }

        def _run():
            try:
                with timed("dictation_transcribe_total"):
                    state["text"] = transcribe_cloud(
                        audio,
                        "nvidia_parakeet",
                        key,
                        language=config.WHISPER_LANGUAGE,
                        model=model_name,
                    )
            except Exception as exc:
                state["error"] = exc
            finally:
                state["done"].set()

        thread = threading.Thread(target=_run, daemon=True)
        state["thread"] = thread
        thread.start()
        return state

    def _wait_for_parallel_transcription(self, state) -> str:
        with timed("dictation_transcribe_wait"):
            state["done"].wait()
        error = state.get("error")
        if error:
            raise error
        return str(state.get("text") or "")

    def _streaming_finalize_timeout(self, streaming: NvidiaStreamingTranscriber | None, settings: dict) -> float:
        if streaming is None:
            return 0.0
        perf = settings.get("performance", {})
        try:
            wait_ms = int(perf.get("streaming_finalize_wait_ms", 450))
        except (TypeError, ValueError):
            wait_ms = 450
        try:
            fast_wait_ms = int(perf.get("streaming_fast_finalize_wait_ms", 120))
        except (TypeError, ValueError):
            fast_wait_ms = 120
        fast_wait_ms = max(fast_wait_ms, 220)
        return streaming.adaptive_finalize_timeout(
            adaptive_enabled=bool(perf.get("streaming_adaptive_finalize_enabled", True)),
            finalize_wait_ms=wait_ms,
            fast_wait_ms=fast_wait_ms,
        )

    def _usable_streaming_text(self, text: str, duration_ms: int = 0) -> bool:
        clean = (text or "").strip()
        if len(clean) < 2:
            return False
        if not re.search(r"[A-Za-z0-9]", clean):
            return False
        tokens = re.findall(r"[A-Za-z0-9]+", clean)
        if not tokens:
            return False
        duration_s = max(0.0, float(duration_ms) / 1000.0)
        alnum_len = sum(len(token) for token in tokens)
        if duration_s >= 4.0 and alnum_len < 4:
            return False
        if duration_s >= 6.0 and len(tokens) < 2:
            return False
        if duration_s >= 10.0 and len(tokens) < 3:
            return False
        return True

    def _needs_prompt_context(
        self,
        stt_provider: str,
        mode,
        context_mode: str,
        streaming_text: str = "",
        duration_ms: int = 0,
    ) -> bool:
        if context_mode == "off":
            return False
        if getattr(mode, "llm_enabled", False):
            return True
        if self._usable_streaming_text(streaming_text, duration_ms):
            return False
        if stt_provider in {"nvidia_parakeet", "deepgram"}:
            return False
        if stt_provider == "local" and config.WHISPER_MODEL_SIZE.lower().startswith("nvidia/parakeet"):
            return False
        return True

    def _resolve_paste_method(self, active_app: str, mode) -> tuple[str, bool, bool, int]:
        """
        Determine paste method, restore_clipboard, and auto_send for the current app.
        Priority: per-app override > mode setting > global setting.
        """
        settings = load_settings()
        paste_cfg = settings.get("paste", {})
        perf_cfg = settings.get("performance", {})

        method = mode.paste_method if mode.paste_method else paste_cfg.get("method", "clipboard_paste")
        restore = paste_cfg.get("restore_clipboard", False)
        auto_send = mode.auto_send if mode.auto_send else paste_cfg.get("auto_send_enter", False)
        paste_delay = int(perf_cfg.get("paste_delay_ms", 30))

        # Per-app overrides
        overrides = paste_cfg.get("per_app_overrides", {})
        active_lower = active_app.lower()
        for app_substring, override in overrides.items():
            if app_substring.lower() in active_lower:
                if "method" in override:
                    method = override["method"]
                if "restore_clipboard" in override:
                    restore = override["restore_clipboard"]
                if "auto_send_enter" in override:
                    auto_send = override["auto_send_enter"]
                break

        delay_overrides = perf_cfg.get("paste_delay_overrides", {})
        for app_substring, delay in delay_overrides.items():
            if app_substring.lower() in active_lower:
                try:
                    paste_delay = int(delay)
                except (TypeError, ValueError):
                    pass
                break

        if (
            method == "clipboard_paste"
            and bool(perf_cfg.get("paste_fast_path_enabled", True))
            and active_lower
        ):
            fast_apps = perf_cfg.get("paste_fast_apps", [])
            if not isinstance(fast_apps, list):
                fast_apps = []
            for app_substring in fast_apps:
                needle = str(app_substring or "").strip().lower()
                if needle and needle in active_lower:
                    try:
                        paste_delay = min(paste_delay, int(perf_cfg.get("paste_fast_delay_ms", 12)))
                    except (TypeError, ValueError):
                        paste_delay = min(paste_delay, 12)
                    break

        return method, restore, auto_send, paste_delay

    def _clipboard_probe_text_before_cursor(self, active_app: str = "", max_chars: int = 4) -> str:
        active_lower = (active_app or "").strip().lower()
        if active_lower in _SMART_SPACING_CLIPBOARD_PROBE_SKIP_APPS:
            return ""
        try:
            import pyperclip
        except Exception:
            return ""
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            old_clipboard = ""
        sentinel = f"__WHISPERER_CURSOR_PROBE_{time.time_ns()}__"
        try:
            pyperclip.copy(sentinel)
            keyboard.send("ctrl+c")
            time.sleep(0.018)
            selected_text = pyperclip.paste()
            if selected_text != sentinel:
                # The user is replacing a selection; do not add an insertion prefix.
                return ""

            keyboard.send("shift+left")
            time.sleep(0.012)
            keyboard.send("ctrl+c")
            time.sleep(0.018)
            captured = pyperclip.paste()
            if captured and captured != sentinel:
                keyboard.send("right")
                return str(captured)[-max(1, max_chars):]
        except Exception:
            return ""
        finally:
            try:
                pyperclip.copy(old_clipboard)
            except Exception:
                pass
        return ""

    def _read_text_before_cursor_fast(self, settings: dict, active_app: str = "", method: str = "clipboard_paste") -> str:
        paste_cfg = settings.get("paste", {})
        try:
            timeout_s = max(0.0, min(0.12, int(paste_cfg.get("smart_spacing_timeout_ms", 35)) / 1000.0))
        except (TypeError, ValueError):
            timeout_s = 0.035
        result = {"text": ""}

        def _read():
            result["text"] = get_text_before_cursor(4)

        thread = threading.Thread(target=_read, daemon=True)
        started = time.perf_counter()
        thread.start()
        thread.join(timeout=timeout_s)
        record_timing("paste_cursor_context", (time.perf_counter() - started) * 1000.0)
        text = str(result.get("text") or "")
        if (
            not text
            and method == "clipboard_paste"
            and bool(paste_cfg.get("smart_spacing_clipboard_probe_enabled", True))
        ):
            started = time.perf_counter()
            text = self._clipboard_probe_text_before_cursor(active_app=active_app, max_chars=4)
            record_timing("paste_cursor_clipboard_probe", (time.perf_counter() - started) * 1000.0)
        return text

    def _needs_leading_space_before_paste(self, text_before_cursor: str) -> bool:
        if not text_before_cursor:
            return False
        last = text_before_cursor[-1]
        if last.isspace():
            return False
        if last in _SENTENCE_END_CHARS:
            return True
        if last in _SENTENCE_CLOSING_CHARS and len(text_before_cursor) >= 2:
            return text_before_cursor[-2] in _SENTENCE_END_CHARS
        return False

    def _prepare_text_for_paste(self, text: str, method: str, settings: dict, active_app: str = "") -> str:
        if not text or text[0].isspace() or method == "copy_only":
            return text
        if not settings.get("paste", {}).get("smart_spacing_enabled", True):
            return text
        before = self._read_text_before_cursor_fast(settings, active_app=active_app, method=method)
        if self._needs_leading_space_before_paste(before):
            return " " + text
        return text

    def _save_dictation_background(
        self,
        started_at: str,
        duration_ms: int,
        active_app: str,
        window_title: str,
        mode_id: int | None,
        raw_text: str,
        final_text: str,
        contexts: dict[str, str],
        audio_path: str | None = None,
        error: str | None = None,
        stt_provider: str = "local",
        llm_processed: int = 0,
        paste_method: str = "clipboard_paste",
        paste_succeeded: int = 0,
    ):
        settings = load_settings()
        if not settings.get("privacy", {}).get("retain_history", True):
            return
        try:
            did = save_dictation(
                started_at=started_at,
                duration_ms=duration_ms,
                app_name=active_app,
                window_title=window_title,
                mode_id=mode_id,
                stt_provider=stt_provider,
                stt_model=config.WHISPER_MODEL_SIZE,
                raw_transcript=raw_text,
                final_text=final_text,
                replacements_applied=1,
                llm_processed=llm_processed,
                paste_method=paste_method,
                paste_succeeded=paste_succeeded,
                error=error,
                audio_path=audio_path,
            )
            for source, content in contexts.items():
                if content:
                    save_context(did, source, content)
        except Exception:
            pass

    def _next_audio_ducking_ticket(self) -> int:
        with self._audio_ducker_lock:
            self._audio_ducking_ticket += 1
            return self._audio_ducking_ticket

    def _begin_audio_ducking(self, ticket: int | None = None):
        with self._audio_ducker_lock:
            if ticket is not None and ticket != self._audio_ducking_ticket:
                return
            if self._audio_ducker is not None:
                return

        ducker = AudioDucker.from_settings(load_settings())
        ducker.duck()

        with self._audio_ducker_lock:
            should_restore = (
                (ticket is not None and ticket != self._audio_ducking_ticket)
                or self._audio_ducker is not None
            )
            if not should_restore:
                self._audio_ducker = ducker

        if should_restore:
            ducker.restore()

    def _restore_audio_ducking(self):
        with self._audio_ducker_lock:
            self._audio_ducking_ticket += 1
            ducker = self._audio_ducker
            self._audio_ducker = None
        if ducker is not None:
            ducker.restore()

    def _run_one_dictation_session(
        self,
        toggle_mode: bool = False,
        lock_acquired: bool = False,
        overlay_primed: bool = False,
    ):
        """Run a single dictation: show overlay, record, transcribe, paste. Runs in a background thread."""
        acquired_lock = lock_acquired
        if not acquired_lock:
            acquired_lock = self._session_lock.acquire(blocking=False)
            if not acquired_lock:
                return
        self._cancelled = False
        if self._is_alt_pressed():
            self._request_longform_lock()
        self._toggle_mode = toggle_mode
        self._session_started_monotonic = time.monotonic()
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        t0 = time.time()
        active_app = ""
        window_title = ""
        mode_id = None
        mode = None
        contexts: dict[str, str] = {}
        stt_provider = "local"
        settings: dict = {}
        streaming_transcriber: NvidiaStreamingTranscriber | None = None
        provider_model: str | None = None

        try:
            if not self._running:
                return
            try:
                active_app = get_active_window_name()
                window_title = get_active_window_title()
            except Exception:
                active_app = ""
                window_title = ""
            try:
                mode = resolve_active_mode(active_app, window_title)
            except Exception:
                mode = resolve_active_mode()
            mode_id = mode.id
            self.signals.set_mode.emit(mode.name)
            stt_provider = os.environ.get("WHISPERER_STT_PROVIDER") or mode.stt_provider or "local"
            settings = load_settings()
            provider_model = self._provider_model(stt_provider, mode)
            if not overlay_primed:
                self._prime_listening_overlay()

            streaming_transcriber = self._maybe_start_streaming_transcriber(stt_provider, provider_model)
            try:
                with timed("recorder_start"):
                    self.recorder.refresh_settings(settings)
                    self.recorder.start()
                if self._is_alt_pressed():
                    self._request_longform_lock()
            except Exception as exc:
                if streaming_transcriber is not None:
                    self.recorder.remove_audio_consumer(streaming_transcriber.feed_audio)
                    streaming_transcriber.finish(timeout_s=0.0)
                self.signals.set_active.emit(False)
                self.signals.set_locked.emit(False)
                self.signals.set_status.emit(f"Mic error: {exc}")
                time.sleep(1.2)
                self.signals.hide_overlay.emit()
                return

            if self._live_recognizer:
                self._live_recognizer.start()

            duck_ticket = self._next_audio_ducking_ticket()
            threading.Thread(target=lambda: self._begin_audio_ducking(duck_ticket), daemon=True).start()

            dictation_hk = self._get_dictation_hotkey()

            if toggle_mode:
                self.signals.set_status.emit("Toggle recording  —  Press toggle to finish")
                self._wait_for_toggle_stop(dictation_hk)
            else:
                longform = self._wait_for_release_or_longform(
                    dictation_hk,
                    settings=settings,
                    started_monotonic=self._session_started_monotonic,
                )
                if longform is None:  # cancelled
                    with timed("recorder_stop_cancelled"):
                        audio = self.recorder.stop()
                    if streaming_transcriber is not None:
                        self.recorder.remove_audio_consumer(streaming_transcriber.feed_audio)
                        streaming_transcriber.finish(timeout_s=0.0)
                    self._restore_audio_ducking()
                    self.signals.set_active.emit(False)
                    self.signals.set_locked.emit(False)
                    self.signals.set_processing.emit(False)
                    if self._live_recognizer:
                        self._live_recognizer.stop()
                    duration_ms = int((time.time() - t0) * 1000)
                    if duration_ms < 1000:
                        self.signals.set_status.emit("Cancelled.")
                    else:
                        self.signals.set_status.emit("Recording cancelled.")
                    time.sleep(0.8)
                    self.signals.hide_overlay.emit()
                    return
                if longform:
                    self.signals.set_locked.emit(True)
                    self.signals.set_status.emit("Long-form mode  —  Press dictation hotkey to finish")
                    self._wait_for_longform_stop(dictation_hk)

            if self._cancelled:
                with timed("recorder_stop_cancelled"):
                    audio = self.recorder.stop()
                if streaming_transcriber is not None:
                    self.recorder.remove_audio_consumer(streaming_transcriber.feed_audio)
                    streaming_transcriber.finish(timeout_s=0.0)
                print("MIC_LEVEL -96.0 0.0000", flush=True)
                self._restore_audio_ducking()
                self.signals.set_active.emit(False)
                self.signals.set_locked.emit(False)
                self.signals.set_processing.emit(False)
                if self._live_recognizer:
                    self._live_recognizer.stop()
                duration_ms = int((time.time() - t0) * 1000)
                if duration_ms < 1000:
                    self.signals.set_status.emit("Cancelled.")
                else:
                    self.signals.set_status.emit("Recording cancelled.")
                time.sleep(0.8)
                self.signals.hide_overlay.emit()
                return

            with timed("recorder_stop"):
                audio = self.recorder.stop()
            if streaming_transcriber is not None:
                self.recorder.remove_audio_consumer(streaming_transcriber.feed_audio)
            print("MIC_LEVEL -96.0 0.0000", flush=True)
            self._restore_audio_ducking()

            if self._live_recognizer:
                self._live_recognizer.stop()

            duration_ms = int((time.time() - t0) * 1000)
            audio_is_empty = len(audio) < config.AUDIO_SAMPLE_RATE * 0.3 or _looks_silent(audio)
            try:
                parallel_final_min_ms = int(
                    settings.get("performance", {}).get("streaming_parallel_final_min_ms", 2500)
                )
            except (TypeError, ValueError):
                parallel_final_min_ms = 2500
            parallel_nvidia_final = None
            if (
                not audio_is_empty
                and streaming_transcriber is not None
                and stt_provider == "nvidia_parakeet"
                and duration_ms >= max(0, parallel_final_min_ms)
            ):
                parallel_nvidia_final = self._start_parallel_nvidia_final_transcription(audio, provider_model)
            streaming_text = ""
            if streaming_transcriber is not None:
                with timed("streaming_finalize"):
                    streaming_text = streaming_transcriber.finish(
                        timeout_s=self._streaming_finalize_timeout(streaming_transcriber, settings)
                    ).strip()
                if streaming_transcriber.error:
                    print(f"STREAMING_STT_ERROR {streaming_transcriber.error}", flush=True)

            if audio_is_empty:
                self.signals.hide_overlay.emit()
                return

            self._processing_job_active.set()
            self.signals.set_active.emit(False)
            self.signals.set_locked.emit(False)
            self.signals.set_processing.emit(True)
            self.signals.set_status.emit("Processing...")

            perf_cfg = settings.get("performance", {})
            context_mode = str(perf_cfg.get("context_mode", "fast")).lower()
            needs_prompt_context = self._needs_prompt_context(
                stt_provider,
                mode,
                context_mode,
                streaming_text=streaming_text,
                duration_ms=duration_ms,
            )

            context_threads: list[threading.Thread] = []
            results: dict[str, str] = {}

            def _collect(name: str, fn):
                try:
                    with timed(f"context_{name}"):
                        results[name] = fn()
                except Exception:
                    results[name] = ""

            if needs_prompt_context:
                full_context = context_mode == "full"
                if mode.ctx_ocr:
                    ocr_fn = capture_screen_context if full_context else lambda: capture_screen_context_cached(blocking=False)
                    t = threading.Thread(target=lambda: _collect("ocr", ocr_fn), daemon=True)
                    context_threads.append(t)
                    t.start()
                if mode.ctx_selected_text and full_context:
                    t = threading.Thread(target=lambda: _collect("selected_text", capture_selected_text), daemon=True)
                    context_threads.append(t)
                    t.start()
                if mode.ctx_clipboard:
                    t = threading.Thread(target=lambda: _collect("clipboard", capture_clipboard_context), daemon=True)
                    context_threads.append(t)
                    t.start()
                t = threading.Thread(target=lambda: _collect("ui_automation", capture_ui_automation_text), daemon=True)
                context_threads.append(t)
                t.start()

            self.signals.set_status.emit("Transcribing...")
            # Keep context helpful without letting slow OCR/clipboard work block STT.
            context_budget = 0.25 if context_mode == "full" else 0.06
            context_deadline = time.time() + context_budget
            for t in context_threads:
                remaining = context_deadline - time.time()
                if remaining <= 0:
                    break
                t.join(timeout=remaining)
            contexts.update(results)

            vocab_limit = settings.get("dictation", {}).get("vocabulary_prompt_limit", 80)
            vocab_hints = ""
            if needs_prompt_context:
                with timed("dictionary_prompt"):
                    vocab_hints = get_prompt_words(vocab_limit)

            # Build context prompt for cloud/local
            prompt_parts: list[str] = []
            if vocab_hints:
                prompt_parts.append(f"Vocabulary hints:\n{vocab_hints}")
            if contexts.get("ui_automation", ""):
                prompt_parts.append(f"Focused control:\n{contexts['ui_automation']}")
            if contexts.get("clipboard", ""):
                prompt_parts.append(f"Recent clipboard:\n{contexts['clipboard']}")
            if contexts.get("selected_text", ""):
                prompt_parts.append(f"Selected text:\n{contexts['selected_text']}")
            prompt_text = "\n\n".join(prompt_parts) if prompt_parts else None

            raw_text = ""
            try:
                streaming_finished = bool(streaming_transcriber.finished) if streaming_transcriber else False
                streaming_usable = streaming_finished and self._usable_streaming_text(streaming_text, duration_ms)
                if streaming_text and not streaming_usable:
                    reason = "unfinished" if streaming_transcriber and not streaming_finished else "quality"
                    print(
                        "STREAMING_STT_DISCARDED "
                        f"reason={reason} chars={len(streaming_text.strip())} duration_ms={duration_ms}",
                        flush=True,
                    )
                if streaming_usable:
                    raw_text = streaming_text
                    print(
                        "STREAMING_STT_ACCEPTED "
                        f"chars={len(raw_text.strip())} final_count={streaming_transcriber.final_result_count if streaming_transcriber else 0}",
                        flush=True,
                    )
                elif stt_provider == "local":
                    with timed("dictation_transcribe_total"):
                        raw_text = transcribe(
                            audio,
                            context_words=vocab_hints,
                            selected_text=contexts.get("selected_text", ""),
                            clipboard_context=contexts.get("clipboard", ""),
                            ui_automation_text=contexts.get("ui_automation", ""),
                        )
                elif parallel_nvidia_final is not None:
                    self.signals.set_status.emit("Cloud transcribing...")
                    raw_text = self._wait_for_parallel_transcription(parallel_nvidia_final)
                else:
                    # Cloud STT
                    self.signals.set_status.emit("Cloud transcribing...")
                    key = self._cloud_api_key(stt_provider)
                    if not key:
                        raise RuntimeError(f"No API key configured for {stt_provider}")
                    with timed("dictation_transcribe_total"):
                        raw_text = transcribe_cloud(
                            audio,
                            stt_provider,
                            key,
                            language=config.WHISPER_LANGUAGE,
                            prompt=prompt_text,
                            model=provider_model,
                        )
            except Exception as exc:
                self.signals.set_processing.emit(False)
                self.signals.set_status.emit(f"Error: {exc}")
                time.sleep(2.0)
                self.signals.hide_overlay.emit()
                threading.Thread(
                    target=self._save_dictation_background,
                    args=(started_at, duration_ms, active_app, window_title, mode_id, "", ""),
                    kwargs={"contexts": contexts, "error": str(exc), "stt_provider": stt_provider},
                    daemon=True,
                ).start()
                return

            if self._cancelled:
                self.signals.set_processing.emit(False)
                self.signals.hide_overlay.emit()
                return

            if not raw_text.strip():
                self.signals.set_status.emit("No speech detected.")
                time.sleep(0.05)
                self.signals.hide_overlay.emit()
                threading.Thread(
                    target=self._save_dictation_background,
                    args=(started_at, duration_ms, active_app, window_title, mode_id, "", ""),
                    kwargs={"contexts": contexts, "error": "No speech detected", "stt_provider": stt_provider},
                    daemon=True,
                ).start()
                return

            with timed("format_and_replacements"):
                formatted = apply_replacements(format_transcription(raw_text, active_app, window_title, mode))

            llm_processed = 0
            if mode.llm_enabled and mode.llm_provider:
                self.signals.set_status.emit("LLM processing...")
                try:
                    from core.llm import process as llm_process
                    from core.secrets import get_key
                    base_url = ""
                    api_key = None
                    if mode.llm_provider == "ollama":
                        base_url = settings.get("llm", {}).get("ollama_url", "http://localhost:11434")
                    elif mode.llm_provider == "openai_compat":
                        base_url = settings.get("llm", {}).get("openai_compat_url", "http://localhost:8000")
                        api_key = get_key("openai_compat")
                    elif mode.llm_provider == "openai":
                        api_key = get_key("openai")
                    elif mode.llm_provider == "anthropic":
                        api_key = get_key("anthropic")
                    elif mode.llm_provider == "groq":
                        api_key = get_key("groq")
                    llm_result = llm_process(
                        formatted,
                        prompt_template=mode.llm_prompt,
                        provider_name=mode.llm_provider,
                        model=mode.llm_model or "llama3.1",
                        timeout_s=10,
                        base_url=base_url,
                        api_key=api_key,
                    )
                    if llm_result and llm_result != formatted:
                        formatted = llm_result
                        llm_processed = 1
                        self.signals.set_status.emit(f"Pasting: {formatted[:50]}...")
                except Exception as exc:
                    self.signals.set_status.emit(f"LLM error: {exc}")
                    time.sleep(1.5)

            if self._cancelled:
                self.signals.set_processing.emit(False)
                self.signals.hide_overlay.emit()
                return

            self.signals.set_status.emit(f"Pasting: {formatted[:50]}...")

            new_words = set()
            for word in extract_useful_terms(formatted, limit=80, source="transcription", include_phrases=False):
                clean = word.lower()
                if clean and clean not in self._recent_words:
                    new_words.add(clean)
                    self._recent_words.add(clean)
            if new_words:
                # Add to dictionary in a background thread to not delay pasting
                threading.Thread(target=add_words_from_list, args=(list(new_words),), kwargs={"source": "transcription"}, daemon=True).start()

            # Determine paste method
            paste_method, restore_clipboard, auto_send, paste_delay = self._resolve_paste_method(active_app, mode)
            text_to_paste = self._prepare_text_for_paste(formatted, paste_method, settings, active_app=active_app)
            paste_succeeded = 0
            try:
                with timed("paste_delivery"):
                    paste_text(
                        text_to_paste,
                        method=paste_method,
                        restore_clipboard=restore_clipboard,
                        auto_send=auto_send,
                        active_app=active_app,
                        paste_delay_ms=paste_delay,
                    )
                paste_succeeded = 1
            except Exception as paste_exc:
                self.signals.set_status.emit(f"Paste failed: {paste_exc}")
                time.sleep(1.5)

            self._last_dictation_text = formatted
            mark_clipboard_pasted()
            self.signals.hide_overlay.emit()

            # Determine if we should retain audio
            audio_path = None
            if settings.get("privacy", {}).get("store_audio_history", False):
                try:
                    from core.paths import get_app_data_dir
                    import wave
                    audio_dir = os.path.join(get_app_data_dir(), "audio")
                    os.makedirs(audio_dir, exist_ok=True)
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    audio_path = os.path.join(audio_dir, f"dictation_{ts}.wav")
                    with wave.open(audio_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(config.AUDIO_SAMPLE_RATE)
                        wf.writeframes((audio * 32767).astype(np.int16).tobytes())
                except Exception:
                    audio_path = None

            threading.Thread(
                target=self._save_dictation_background,
                args=(started_at, duration_ms, active_app, window_title, mode_id, raw_text, formatted),
                kwargs={
                    "contexts": contexts,
                    "audio_path": audio_path,
                    "stt_provider": stt_provider,
                    "llm_processed": llm_processed,
                    "paste_method": paste_method,
                    "paste_succeeded": paste_succeeded,
                },
                daemon=True,
            ).start()
        finally:
            self._restore_audio_ducking()
            self._processing_job_active.clear()
            self._clear_longform_lock()
            if acquired_lock:
                self._session_lock.release()

    def _on_hotkey_pressed(self):
        """Called when user presses the dictation hotkey. Start dictation session in a background thread."""
        if not self._model_ready.is_set():
            self._mark_pre_ready_hotkey()
            self._show_model_loading_overlay()
            return
        if self._pre_ready_hotkey_still_held():
            return
        if not self._session_lock.acquire(blocking=False):
            return
        self._clear_longform_lock()
        self._prime_listening_overlay()
        if self._is_alt_pressed():
            self._request_longform_lock()
        threading.Thread(
            target=lambda: self._run_one_dictation_session(lock_acquired=True, overlay_primed=True),
            daemon=True,
        ).start()

    def _on_toggle_pressed(self):
        """Called when user presses the toggle recording hotkey."""
        if not self._model_ready.is_set():
            self._mark_pre_ready_hotkey()
            self._show_model_loading_overlay()
            return
        if self._pre_ready_hotkey_still_held():
            return
        if self.recorder.is_recording:
            # If already recording, this acts like releasing the hotkey
            self._cancelled = False
            return
        if not self._session_lock.acquire(blocking=False):
            return
        self._clear_longform_lock()
        self._prime_listening_overlay()
        if self._is_alt_pressed():
            self._request_longform_lock()
        threading.Thread(
            target=lambda: self._run_one_dictation_session(
                toggle_mode=True,
                lock_acquired=True,
                overlay_primed=True,
            ),
            daemon=True,
        ).start()

    def _on_cancel_pressed(self):
        """Called when user presses the cancel hotkey during recording."""
        if self.recorder.is_recording:
            self._cancelled = True

    def _on_mode_next(self):
        """Cycle to the next enabled mode."""
        self._refresh_modes_list()
        if not self._modes_list:
            return
        self._current_mode_index = (self._current_mode_index + 1) % len(self._modes_list)
        mode = self._modes_list[self._current_mode_index]
        self.signals.mode_changed.emit(mode.name)

    def _on_mode_prev(self):
        """Cycle to the previous enabled mode."""
        self._refresh_modes_list()
        if not self._modes_list:
            return
        self._current_mode_index = (self._current_mode_index - 1) % len(self._modes_list)
        mode = self._modes_list[self._current_mode_index]
        self.signals.mode_changed.emit(mode.name)

    def _on_repeat_last(self):
        """Paste the last dictation text again."""
        if not self._last_dictation_text:
            return
        active_app = get_active_window_name()
        settings = load_settings()
        paste_cfg = settings.get("paste", {})
        perf_cfg = settings.get("performance", {})
        method = paste_cfg.get("method", "clipboard_paste")
        restore = paste_cfg.get("restore_clipboard", False)
        auto_send = paste_cfg.get("auto_send_enter", False)
        paste_delay = int(perf_cfg.get("paste_delay_ms", 30))
        # Check per-app override
        overrides = paste_cfg.get("per_app_overrides", {})
        active_lower = active_app.lower()
        for app_substring, override in overrides.items():
            if app_substring.lower() in active_lower:
                if "method" in override:
                    method = override["method"]
                if "restore_clipboard" in override:
                    restore = override["restore_clipboard"]
                if "auto_send_enter" in override:
                    auto_send = override["auto_send_enter"]
                break
        for app_substring, delay in perf_cfg.get("paste_delay_overrides", {}).items():
            if app_substring.lower() in active_lower:
                try:
                    paste_delay = int(delay)
                except (TypeError, ValueError):
                    pass
                break
        if method == "clipboard_paste" and bool(perf_cfg.get("paste_fast_path_enabled", True)):
            fast_apps = perf_cfg.get("paste_fast_apps", [])
            if isinstance(fast_apps, list):
                for app_substring in fast_apps:
                    needle = str(app_substring or "").strip().lower()
                    if needle and needle in active_lower:
                        try:
                            paste_delay = min(paste_delay, int(perf_cfg.get("paste_fast_delay_ms", 12)))
                        except (TypeError, ValueError):
                            paste_delay = min(paste_delay, 12)
                        break
        try:
            text_to_paste = self._prepare_text_for_paste(self._last_dictation_text, method, settings, active_app=active_app)
            paste_text(
                text_to_paste,
                method=method,
                restore_clipboard=restore,
                auto_send=auto_send,
                active_app=active_app,
                paste_delay_ms=paste_delay,
            )
        except Exception:
            pass

    def _on_open_history(self):
        """Signal to open the history window/tab."""
        self.signals.open_history.emit()

    def _unregister_shortcuts(self):
        """Remove all registered keyboard hotkeys."""
        for hk in self._registered_hotkeys:
            try:
                keyboard.remove_hotkey(hk)
            except Exception:
                pass
        self._registered_hotkeys.clear()

    def _register_shortcuts(self):
        """Register all configured keyboard shortcuts."""
        self._unregister_shortcuts()
        settings = load_settings()
        shortcuts = settings.get("shortcuts", {})

        def _add(hotkey_str: str | None, callback):
            hotkey_str = _normalize_keyboard_hotkey(hotkey_str)
            if not hotkey_str:
                return
            try:
                hk = keyboard.add_hotkey(hotkey_str, callback, suppress=False)
                self._registered_hotkeys.append(hk)
                print(f"Registered hotkey: {hotkey_str}", flush=True)
            except Exception as exc:
                print(f"Could not register hotkey '{hotkey_str}': {exc}", flush=True)

        dictation_hk = shortcuts.get("dictation") or config.DICTATION_HOTKEY
        _add(dictation_hk, self._on_hotkey_pressed)
        _add("alt", self._on_alt_lock_pressed)
        _add(shortcuts.get("toggle_recording"), self._on_toggle_pressed)
        _add(shortcuts.get("cancel"), self._on_cancel_pressed)
        _add(shortcuts.get("mode_next"), self._on_mode_next)
        _add(shortcuts.get("mode_prev"), self._on_mode_prev)
        _add(shortcuts.get("repeat_last"), self._on_repeat_last)
        _add(shortcuts.get("open_history"), self._on_open_history)

    def _load_engine_background(self):
        record_timing("engine_import_phase", (time.perf_counter() - _PROCESS_START) * 1000.0)
        cloud_stt_provider = os.environ.get("WHISPERER_STT_PROVIDER")
        model_name = config.WHISPER_MODEL_SIZE

        try:
            ready_name = model_name
            if cloud_stt_provider:
                ready_name = cloud_stt_provider
                print(f"Using cloud STT provider: {cloud_stt_provider}.", flush=True)
            else:
                engine_name = "NVIDIA Parakeet" if model_name.lower().startswith("nvidia/parakeet") else "Whisper"
                print(f"Loading {engine_name} model onto GPU...", flush=True)
                with timed("engine_startup_model_phase"):
                    load_model()
                    warmup_model()
                print(f"Model loaded. Whisper Project is running with {model_name}.", flush=True)

            try:
                self.recorder.refresh_settings(load_settings())
                with timed("recorder_prepare"):
                    self.recorder.prepare()
            except Exception as exc:
                print(f"Mic warmup skipped: {exc}", flush=True)

            self._model_ready.set()
            self.signals.set_model_loading.emit(False)
            _write_engine_ready_file(ready_name)
            print("ENGINE_READY", flush=True)
            self._start_stdin_command_reader()
            self._ensure_live_recognizer()
            threading.Thread(target=self._prewarm_nvidia_riva_background, daemon=True).start()
            if not self._start_pre_ready_hotkey_dictation_if_held():
                threading.Thread(target=self._clear_pre_ready_hotkey_after_release, daemon=True).start()
            settings = load_settings()
            shortcuts = settings.get("shortcuts", {})
            dictation_hk = _normalize_keyboard_hotkey(shortcuts.get("dictation") or config.DICTATION_HOTKEY) or config.DICTATION_HOTKEY
            print(f"Quick dictation:  {dictation_hk.replace('+', ' + ').title()} (hold)", flush=True)
            print(f"Long-form mode:   {dictation_hk.replace('+', ' + ').title()} + Alt (then let go)", flush=True)
            if shortcuts.get("toggle_recording"):
                print(f"Toggle recording: {shortcuts['toggle_recording'].replace('+', ' + ').title()}", flush=True)
            if shortcuts.get("cancel"):
                print(f"Cancel:           {shortcuts['cancel'].replace('+', ' + ').title()}", flush=True)
            print("Press Ctrl+C in this terminal to quit.\n", flush=True)
            threading.Timer(1.2, self._hide_loading_overlay_if_idle).start()
        except Exception as exc:
            self._model_failed = str(exc)
            self.signals.set_model_loading.emit(False)
            traceback.print_exc()
            os._exit(1)

    def _prewarm_nvidia_riva_background(self):
        key = self._cloud_api_key("nvidia_parakeet")
        if not key:
            return
        try:
            count = prewarm_nvidia_riva(key)
            if count:
                print(f"NVIDIA_RIVA_PREWARM_READY models={count}", flush=True)
        except Exception as exc:
            print(f"NVIDIA_RIVA_PREWARM_SKIPPED {exc}", flush=True)

    def _benchmark_candidate(self, label: str, provider: str, fn, key_name: str | None = None) -> dict:
        result = {
            "label": label,
            "provider": provider,
            "ok": False,
            "elapsedMs": None,
            "text": "",
            "error": "",
        }
        if key_name:
            key = self._cloud_api_key(key_name)
            if not key:
                result["error"] = f"No {key_name.replace('_parakeet', '').replace('_whisper', '').title()} API key saved."
                result["skipped"] = True
                return result
        started = time.perf_counter()
        try:
            text = fn()
            result["ok"] = bool(str(text or "").strip())
            result["text"] = str(text or "").strip()
            if not result["ok"]:
                result["error"] = "No transcript returned."
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            result["elapsedMs"] = round((time.perf_counter() - started) * 1000.0, 1)
        return result

    def _benchmark_stt_audio(self, audio: np.ndarray) -> list[dict]:
        settings = load_settings()
        perf = settings.get("performance", {})
        try:
            chunk_ms = int(perf.get("streaming_audio_chunk_ms", 32))
        except (TypeError, ValueError):
            chunk_ms = 32
        nvidia_key = self._cloud_api_key("nvidia_parakeet")
        groq_key = self._cloud_api_key("groq_whisper")
        openai_key = self._cloud_api_key("openai_whisper")
        deepgram_key = self._cloud_api_key("deepgram")

        def _missing(label: str, provider: str, key_name: str) -> dict:
            return {
                "label": label,
                "provider": provider,
                "ok": False,
                "elapsedMs": None,
                "text": "",
                "error": f"No {key_name} API key saved.",
                "skipped": True,
            }

        results: list[dict] = []
        if nvidia_key:
            results.append(self._benchmark_candidate(
                "NVIDIA Parakeet RNNT streaming",
                "nvidia_riva_streaming",
                lambda: transcribe_nvidia_riva_streaming(
                    audio,
                    nvidia_key,
                    language=config.WHISPER_LANGUAGE,
                    model=NVIDIA_RIVA_TDT_MODEL,
                    chunk_ms=chunk_ms,
                ),
            ))
            results.append(self._benchmark_candidate(
                "NVIDIA Parakeet TDT 0.6B final",
                "nvidia_parakeet",
                lambda: transcribe_cloud(
                    audio,
                    "nvidia_parakeet",
                    nvidia_key,
                    language=config.WHISPER_LANGUAGE,
                    model=NVIDIA_RIVA_TDT_MODEL,
                ),
            ))
            results.append(self._benchmark_candidate(
                "NVIDIA Parakeet CTC 0.6B final",
                "nvidia_parakeet",
                lambda: transcribe_cloud(
                    audio,
                    "nvidia_parakeet",
                    nvidia_key,
                    language=config.WHISPER_LANGUAGE,
                    model=NVIDIA_RIVA_CTC_MODEL,
                ),
            ))
        else:
            results.extend([
                _missing("NVIDIA Parakeet RNNT streaming", "nvidia_riva_streaming", "NVIDIA"),
                _missing("NVIDIA Parakeet TDT 0.6B final", "nvidia_parakeet", "NVIDIA"),
                _missing("NVIDIA Parakeet CTC 0.6B final", "nvidia_parakeet", "NVIDIA"),
            ])
        if groq_key:
            results.append(self._benchmark_candidate(
                "Groq Whisper v3 Turbo",
                "groq_whisper",
                lambda: transcribe_cloud(audio, "groq_whisper", groq_key, language=config.WHISPER_LANGUAGE),
            ))
        else:
            results.append(_missing("Groq Whisper v3 Turbo", "groq_whisper", "Groq"))
        if openai_key:
            results.append(self._benchmark_candidate(
                "OpenAI speech",
                "openai_whisper",
                lambda: transcribe_cloud(
                    audio,
                    "openai_whisper",
                    openai_key,
                    language=config.WHISPER_LANGUAGE,
                    model="gpt-4o-mini-transcribe",
                ),
            ))
        else:
            results.append(_missing("OpenAI speech", "openai_whisper", "OpenAI"))
        if deepgram_key:
            results.append(self._benchmark_candidate(
                "Deepgram Nova",
                "deepgram",
                lambda: transcribe_cloud(audio, "deepgram", deepgram_key, language=config.WHISPER_LANGUAGE),
            ))
        else:
            results.append(_missing("Deepgram Nova", "deepgram", "Deepgram"))
        return results

    def _emit_stt_benchmark_result(self, request_id: str, ok: bool, results: list[dict] | None = None, error: str = "", audio_ms: int = 0):
        payload = {
            "requestId": request_id,
            "ok": bool(ok),
            "audioMs": int(audio_ms or 0),
            "results": results or [],
            "error": error or "",
        }
        print("STT_BENCHMARK_RESULT " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

    def _run_stt_benchmark_command(self, request_id: str):
        if not self._model_ready.wait(timeout=180):
            error = self._model_failed or "The dictation engine is still loading."
            self._emit_stt_benchmark_result(request_id, False, error=error)
            return
        if not self._session_lock.acquire(blocking=False):
            self._emit_stt_benchmark_result(
                request_id,
                False,
                error="Finish the current dictation before running the STT benchmark.",
            )
            return
        try:
            from core.dictation_backup import finalize_last_dictation_wav, load_last_dictation_audio

            finalize_last_dictation_wav()
            audio = load_last_dictation_audio()
            audio_ms = round(len(audio) / float(config.AUDIO_SAMPLE_RATE or 16000) * 1000.0)
            results = self._benchmark_stt_audio(audio)
            self._emit_stt_benchmark_result(request_id, True, results=results, audio_ms=audio_ms)
        except Exception as exc:
            self._emit_stt_benchmark_result(request_id, False, error=str(exc))
        finally:
            try:
                self._session_lock.release()
            except RuntimeError:
                pass

    def _start_stdin_command_reader(self):
        if self._stdin_command_reader_started:
            return
        self._stdin_command_reader_started = True

        def _reader():
            try:
                for line in sys.stdin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("command") == "transcribe_last_dictation":
                        request_id = str(payload.get("requestId") or "")
                        threading.Thread(
                            target=lambda: self._transcribe_last_dictation_command(request_id),
                            daemon=True,
                        ).start()
                    elif payload.get("command") == "benchmark_stt":
                        request_id = str(payload.get("requestId") or "")
                        threading.Thread(
                            target=lambda: self._run_stt_benchmark_command(request_id),
                            daemon=True,
                        ).start()
            except Exception:
                pass

        threading.Thread(target=_reader, daemon=True).start()

    def _emit_backup_transcription_result(self, request_id: str, ok: bool, text: str = "", error: str = ""):
        payload = {
            "requestId": request_id,
            "ok": bool(ok),
            "text": text or "",
            "error": error or "",
        }
        print("BACKUP_TRANSCRIPTION_RESULT " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

    def _transcribe_last_dictation_command(self, request_id: str):
        if not self._model_ready.wait(timeout=180):
            error = self._model_failed or "The dictation engine is still loading."
            self._emit_backup_transcription_result(request_id, False, error=error)
            return
        if not self._session_lock.acquire(blocking=False):
            self._emit_backup_transcription_result(
                request_id,
                False,
                error="Finish the current dictation before transcribing the backup.",
            )
            return
        try:
            from core.dictation_backup import finalize_last_dictation_wav, load_last_dictation_audio

            finalize_last_dictation_wav()
            audio = load_last_dictation_audio()
            raw_text = transcribe(audio, context_words=get_prompt_words(80))
            final_text = apply_replacements(
                format_transcription(
                    raw_text,
                    active_app="last-dictation",
                    window_title="Last dictation backup",
                )
            )
            self._emit_backup_transcription_result(request_id, True, text=(final_text or raw_text).strip())
        except Exception as exc:
            self._emit_backup_transcription_result(request_id, False, error=str(exc))
        finally:
            try:
                self._session_lock.release()
            except RuntimeError:
                pass

    def run(self):
        self._register_shortcuts()
        threading.Thread(target=self._load_engine_background, daemon=True).start()
        sys.exit(self.app.exec())


if __name__ == "__main__":
    # Handle --file=path for headless file transcription (Open with integration)
    file_arg = None
    model_arg = None
    for arg in sys.argv[1:]:
        if arg.startswith("--file="):
            file_arg = arg.split("=", 1)[1]
        elif arg.startswith("--model="):
            model_arg = arg.split("=", 1)[1]
    if model_arg:
        config.WHISPER_MODEL_SIZE = model_arg
    if file_arg:
        print(f"Transcribing file: {file_arg}", flush=True)
        try:
            result = transcribe_file(file_arg)
            print(result["final_text"], flush=True)
        except Exception as exc:
            print(f"Error: {exc}", flush=True)
            sys.exit(1)
    else:
        WhisperApp().run()
