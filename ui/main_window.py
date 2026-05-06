"""Main Whisperer window.

The dashboard is rendered by the React app in ``whisperer-app/dist`` while this
module keeps ownership of the real Windows/Python behavior: tray integration,
engine subprocess lifecycle, settings persistence, GPU selection, and device
discovery. The dictation overlay remains in the engine process.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import ctypes
import urllib.error
import urllib.request
import logging
from datetime import date, datetime, timedelta
from typing import Any

from PyQt6.QtCore import Qt, QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QPalette
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from core.diagnostics import append_log_line, log_dir, scrub_text
from core.paths import get_app_data_dir
from core.settings import load_settings, save_settings
from ui.app_icon import APP_USER_MODEL_ID, app_icon_path
from ui.overlay import WaveformOverlay
from ui.tray import TrayIcon


ENGINE_FORCE_STOP_RESTART_CODE = 42
GPU_AUTO_VALUE = "auto"
GROQ_API_GPU_VALUE = "groq_api"
GROQ_API_LEGACY_GPU_VALUE = "grok_api"
GROQ_API_STT_PROVIDER = "groq_whisper"
NVIDIA_API_GPU_VALUE = "nvidia_api"
NVIDIA_API_STT_PROVIDER = "nvidia_parakeet"
API_GPU_VALUES = {GROQ_API_GPU_VALUE, GROQ_API_LEGACY_GPU_VALUE, NVIDIA_API_GPU_VALUE}
LOADING_PREVIEW_HIDE_MS = 1400
LOADING_READY_MORPH_HIDE_MS = 900
LOADING_INTERACTION_HIDE_RETRY_MS = 450
LOADING_HOTKEY_RELEASE_RETRY_MS = 120
LOADING_RELEASE_POLL_MS = 35
NOISY_ENGINE_LINE_PARTS = (
    "OneLogger:",
    "No exporters were provided.",
    "error_handling_strategy",
    "no telemetry data will be collected",
)
WINDOW_BACKING_HEX = "#f8f7f3"
WINDOW_BACKING_COLOR = QColor(248, 247, 243)
UI_LOG = logging.getLogger("whisperer.ui")

QUIET_MODEL_ENV = {
    "NEMO_LOGGING_LEVEL": "ERROR",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8:replace",
}


class _DwmMargins(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]

MODEL_OPTIONS = [
    {
        "value": "nvidia/parakeet-tdt-0.6b-v2",
        "label": "NVIDIA Parakeet TDT 0.6B RNNT streaming",
        "size": "0.6 B",
        "badge": "Local",
        "speed": "Streaming",
    },
    {
        "value": "nvidia/parakeet-ctc-0.6b",
        "label": "NVIDIA Parakeet CTC 0.6B (RNNT streaming)",
        "size": "0.6 B",
        "badge": "Local",
        "speed": "Streaming",
    },
    {
        "value": "nvidia/parakeet-unified-en-0.6b",
        "label": "NVIDIA Parakeet Unified 0.6B (RNNT streaming)",
        "size": "0.6 B",
        "badge": "Local",
        "speed": "Streaming",
    },
    {
        "value": "deepdml/faster-whisper-large-v3-turbo-ct2",
        "label": "Whisper v3 Turbo",
        "size": "1.6 B",
        "badge": "Local",
        "speed": "Balanced",
    },
    {
        "value": "large-v3",
        "label": "Whisper Large v3",
        "size": "1.55 B",
        "badge": "Local",
        "speed": "Accurate",
    },
]


def _react_index_candidates() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    candidates: list[str] = []
    if getattr(sys, "frozen", False):
        candidates.extend(
            [
                os.path.join(getattr(sys, "_MEIPASS", ""), "whisperer-app", "dist", "index.html"),
                os.path.join(os.path.dirname(sys.executable), "whisperer-app", "dist", "index.html"),
                os.path.join(os.path.dirname(sys.executable), "_internal", "whisperer-app", "dist", "index.html"),
            ]
        )
    candidates.append(os.path.join(project_root, "whisperer-app", "dist", "index.html"))
    return candidates


def _react_index_url() -> QUrl:
    """Return the file URL for the built React entrypoint."""
    candidates = _react_index_candidates()
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return QUrl.fromLocalFile(candidate)
    return QUrl.fromLocalFile(candidates[-1])


def _normalize_keyboard_hotkey(hotkey: str | None) -> str | None:
    """Convert Qt key names into names understood by the keyboard package."""
    if not hotkey:
        return hotkey

    parts = []
    for part in str(hotkey).split("+"):
        key = part.strip().lower()
        if key in {"meta", "win", "windows"}:
            key = "left windows"
        elif key == "control":
            key = "ctrl"
        elif key == "esc":
            key = "escape"
        parts.append(key)
    return "+".join(parts)


class Bridge(QObject):
    """Object exposed to JavaScript through QWebChannel."""

    engineStateChanged = pyqtSignal(str)
    settingsChanged = pyqtSignal(str)
    sttBenchmarkFinished = pyqtSignal(str)

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._window = window

    @pyqtSlot()
    def minimize(self):
        self._window.showMinimized()

    @pyqtSlot()
    def maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    @pyqtSlot()
    def close(self):
        self._window.close()

    @pyqtSlot()
    def showWindow(self):
        self._window.show_window()

    @pyqtSlot()
    def startDrag(self):
        if self._window.isMaximized():
            return
        self._window.prepare_for_system_move()
        handle = self._window.windowHandle()
        if handle:
            handle.startSystemMove()

    @pyqtSlot()
    def startResize(self):
        if self._window.isMaximized():
            return
        self._window.prepare_for_system_move()
        handle = self._window.windowHandle()
        if handle:
            handle.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge)

    @pyqtSlot()
    def startEngine(self):
        self._window.start_engine()

    @pyqtSlot()
    def stopEngine(self):
        self._window.stop_engine()

    @pyqtSlot(result=str)
    def engineState(self) -> str:
        return self._window.engine_state()

    @pyqtSlot(result=str)
    def appSnapshot(self) -> str:
        return self._window.snapshot_json()

    @pyqtSlot(result=str)
    def vocabularySnapshot(self) -> str:
        return self._window.vocabulary_snapshot_json()

    @pyqtSlot(str, result=str)
    def searchVocabulary(self, query: str) -> str:
        return self._window.vocabulary_snapshot_json(query)

    @pyqtSlot(result=str)
    def historySnapshot(self) -> str:
        return self._window.history_snapshot_json()

    @pyqtSlot(result=str)
    def modesSnapshot(self) -> str:
        return self._window.modes_snapshot_json()

    @pyqtSlot(result=str)
    def micLevel(self) -> str:
        return self._window.mic_level_json()

    @pyqtSlot(str, result=str)
    def setModel(self, value: str) -> str:
        return self._window.set_model(value)

    @pyqtSlot(str, result=str)
    def setGpu(self, value: str) -> str:
        return self._window.set_gpu(value)

    @pyqtSlot(str, result=str)
    def modelCacheStatus(self, value: str) -> str:
        return self._window.model_cache_status(value)

    @pyqtSlot(str, result=str)
    def localEngineStatus(self, value: str = "") -> str:
        return self._window.local_engine_status_json(value)

    @pyqtSlot(str, str, result=str)
    def setApiKey(self, service: str, value: str) -> str:
        return self._window.set_api_key(service, value)

    @pyqtSlot(str, result=str)
    def testApiKey(self, service: str) -> str:
        return self._window.test_api_key(service)

    @pyqtSlot(str, result=str)
    def setMicrophone(self, value: str) -> str:
        return self._window.set_microphone(value)

    @pyqtSlot(str, result=str)
    def setInputChannel(self, value: str) -> str:
        return self._window.set_input_channel(value)

    @pyqtSlot(str, result=str)
    def addVocabularyWord(self, word: str) -> str:
        return self._window.add_vocabulary_word(word)

    @pyqtSlot(str, str, result=str)
    def addReplacementRule(self, match_text: str, replace_with: str) -> str:
        return self._window.add_replacement_rule(match_text, replace_with)

    @pyqtSlot(str, result=str)
    def copyText(self, text: str) -> str:
        QApplication.clipboard().setText(text or "")
        return self._window.history_snapshot_json()

    @pyqtSlot(result=str)
    def transcribeLastDictation(self) -> str:
        return self._window.transcribe_last_dictation()

    @pyqtSlot(result=str)
    def runSttBenchmark(self) -> str:
        return self._window.run_stt_benchmark()

    @pyqtSlot(int, result=str)
    def deleteDictation(self, dictation_id: int) -> str:
        return self._window.delete_dictation(dictation_id)

    @pyqtSlot(result=str)
    def purgeHistory(self) -> str:
        return self._window.purge_history()

    @pyqtSlot(str, result=str)
    def addMode(self, name: str) -> str:
        return self._window.add_mode(name)

    @pyqtSlot(int, result=str)
    def deleteMode(self, mode_id: int) -> str:
        return self._window.delete_mode(mode_id)

    @pyqtSlot(int, str, result=str)
    def updateMode(self, mode_id: int, patch_json: str) -> str:
        return self._window.update_mode(mode_id, patch_json)

    @pyqtSlot(int, str, str, int, result=str)
    def addAutoRule(self, mode_id: int, match_type: str, match_value: str, priority: int) -> str:
        return self._window.add_auto_rule(mode_id, match_type, match_value, priority)

    @pyqtSlot(int, result=str)
    def deleteAutoRule(self, rule_id: int) -> str:
        return self._window.delete_auto_rule(rule_id)

    @pyqtSlot(str, str, result=str)
    def setShortcut(self, name: str, value: str) -> str:
        return self._window.set_shortcut(name, value)

    @pyqtSlot(str, str, str, result=str)
    def setSetting(self, section: str, key: str, value_json: str) -> str:
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError:
            value = value_json
        return self._window.set_setting(section, key, value)

    @pyqtSlot(result=str)
    def checkForUpdates(self) -> str:
        return self._window.check_for_updates()

    @pyqtSlot(result=str)
    def installUpdate(self) -> str:
        return self._window.install_update()


_BRIDGE_SHIM = r"""
(function() {
  function install() {
    new QWebChannel(qt.webChannelTransport, function(channel) {
      var b = channel.objects.bridge;
      function callResult(name) {
        var args = Array.prototype.slice.call(arguments, 1);
        return new Promise(function(resolve) {
          args.push(function(result) { resolve(result); });
          b[name].apply(b, args);
        });
      }
      window.bridge = b;
      window.whisperer = {
        minimize: function() { b.minimize(); },
        maximize: function() { b.maximize(); },
        close: function() { b.close(); },
        showWindow: function() { b.showWindow(); },
        startDrag: function() { b.startDrag(); },
        startResize: function() { b.startResize(); },
        startEngine: function() { b.startEngine(); },
        stopEngine: function() { b.stopEngine(); },
        engineState: function() { return callResult("engineState"); },
        appSnapshot: function() { return callResult("appSnapshot"); },
        vocabularySnapshot: function() { return callResult("vocabularySnapshot"); },
        searchVocabulary: function(query) { return callResult("searchVocabulary", query || ""); },
        historySnapshot: function() { return callResult("historySnapshot"); },
        modesSnapshot: function() { return callResult("modesSnapshot"); },
        micLevel: function() { return callResult("micLevel"); },
        setModel: function(value) { return callResult("setModel", value); },
        setGpu: function(value) { return callResult("setGpu", value); },
        modelCacheStatus: function(value) { return callResult("modelCacheStatus", value); },
        setApiKey: function(service, value) { return callResult("setApiKey", service, value); },
        testApiKey: function(service) { return callResult("testApiKey", service); },
        setMicrophone: function(value) { return callResult("setMicrophone", value); },
        setInputChannel: function(value) { return callResult("setInputChannel", value); },
        addVocabularyWord: function(word) { return callResult("addVocabularyWord", word); },
        addReplacementRule: function(matchText, replaceWith) { return callResult("addReplacementRule", matchText, replaceWith); },
        copyText: function(text) { return callResult("copyText", text); },
        transcribeLastDictation: function() { return callResult("transcribeLastDictation"); },
        runSttBenchmark: function() { return callResult("runSttBenchmark"); },
        deleteDictation: function(dictationId) { return callResult("deleteDictation", dictationId); },
        purgeHistory: function() { return callResult("purgeHistory"); },
        addMode: function(name) { return callResult("addMode", name || "New Mode"); },
        deleteMode: function(modeId) { return callResult("deleteMode", modeId); },
        updateMode: function(modeId, patch) { return callResult("updateMode", modeId, JSON.stringify(patch)); },
        addAutoRule: function(modeId, type, value, priority) {
          return callResult("addAutoRule", modeId, type, value, priority || 0);
        },
        deleteAutoRule: function(ruleId) { return callResult("deleteAutoRule", ruleId); },
        setShortcut: function(name, value) { return callResult("setShortcut", name, value); },
        setSetting: function(section, key, value) {
          return callResult("setSetting", section, key, JSON.stringify(value));
        },
        checkForUpdates: function() { return callResult("checkForUpdates"); },
        installUpdate: function() { return callResult("installUpdate"); }
      };
      b.engineStateChanged.connect(function(state) {
        window.dispatchEvent(new CustomEvent("whisperer:engineState", { detail: state }));
      });
      b.settingsChanged.connect(function(snapshot) {
        window.dispatchEvent(new CustomEvent("whisperer:settings", { detail: snapshot }));
      });
      b.sttBenchmarkFinished.connect(function(result) {
        window.dispatchEvent(new CustomEvent("whisperer:sttBenchmarkResult", { detail: result }));
      });
      window.dispatchEvent(new Event("whisperer:ready"));
    });
  }
  if (window.QWebChannel) {
    install();
    return;
  }
  var script = document.createElement("script");
  script.src = "qrc:///qtwebchannel/qwebchannel.js";
  script.onload = install;
  document.head.appendChild(script);
})();
"""


_WEB_DIAGNOSTIC_SHIM = r"""
(function() {
  if (window.__whispererDiagnosticsInstalled) {
    return;
  }
  window.__whispererDiagnosticsInstalled = true;
  window.addEventListener("error", function(event) {
    console.error("[whisperer-diagnostic] window.error", event.message || "", event.filename || "", event.lineno || 0, event.colno || 0);
  });
  window.addEventListener("unhandledrejection", function(event) {
    var reason = event.reason;
    var text = reason && (reason.stack || reason.message) ? (reason.stack || reason.message) : String(reason);
    console.error("[whisperer-diagnostic] unhandledrejection", text);
  });
  console.info("[whisperer-diagnostic] document", document.readyState, location.href, "scripts=" + document.scripts.length);
})();
"""


def _apply_quiet_model_env(env: dict[str, str]) -> None:
    for key, value in QUIET_MODEL_ENV.items():
        env.setdefault(key, value)


class DiagnosticPage(QWebEnginePage):
    def __init__(self, window: "MainWindow", profile: QWebEngineProfile | None = None):
        if profile is not None:
            super().__init__(profile, window)
        else:
            super().__init__(window)
        self._window = window

    def javaScriptConsoleMessage(self, level, message: str, line: int, source: str):
        self._window._log_web_ui(f"{level.name} {source}:{line}: {message}")


class MainWindow(QMainWindow):
    """Frameless WebEngine host for the React UI."""

    loadingPreviewRequested = pyqtSignal()
    backupTranscriptionFinished = pyqtSignal(str, bool, str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Whisperer v{config.VERSION}")
        self.setWindowIcon(QIcon(app_icon_path()))
        self.setObjectName("whisperer-main-window")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        self.setMinimumSize(980, 640)
        self.resize(1280, 840)
        self._apply_widget_backing(self)

        self._web_load_started = False
        self._web_load_finished = False
        self._web_load_ok = False
        self._web_load_progress = -1
        self._web_timeout_reported = False
        self._web_probe_pending = False
        self._react_mounted = False
        self._showing_web_ui_error = False
        self._diagnostic_panel: QWidget | None = None
        self._react_index_url = _react_index_url()
        self._log_web_ui(
            f"MainWindow init version={config.VERSION} pid={os.getpid()} "
            f"frozen={bool(getattr(sys, 'frozen', False))} logDir={log_dir()}"
        )
        self._log_react_index_candidates()

        self.settings = load_settings()
        self._local_engine_status_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._gpu_options = self._load_gpu_options()
        self._engine_output_queue: queue.Queue[str] = queue.Queue()
        self._engine_output_lines: list[str] = []
        self._engine_state = "stopped"
        self._engine_ready_file = ""
        self._engine_log_dir = log_dir()
        self._paused = False
        self._force_quitting = False
        self.process: subprocess.Popen | None = None
        self._mic_level_lock = threading.Lock()
        self._mic_level_db = -96.0
        self._mic_level_value = 0.0
        self._mic_level_error = ""
        self._backup_transcription_busy = False
        self._backup_transcription_status = ""
        self._backup_transcription_error = ""
        self._backup_transcription_request_id = ""
        self._backup_transcription_source = ""
        self._stt_benchmark_busy = False
        self._stt_benchmark_request_id = ""
        self._microphone_cache: list[dict[str, str]] = []
        self._microphone_cache_ts = 0.0
        self._input_channel_count_cache: dict[str, tuple[float, int]] = {}
        self._active_mode_cache = "Voice"
        self._active_mode_cache_ts = 0.0
        self._loading_preview_enabled = self._should_auto_start_engine()
        self._loading_preview_hotkeys: list = []
        self._loading_preview_locked = False
        self._loading_preview_overlay = WaveformOverlay()
        self._loading_preview_overlay.open_ui_requested.connect(self.show_window)
        self._loading_preview_overlay.force_stop_requested.connect(self.stop_engine)
        self._loading_preview_hide_timer = QTimer(self)
        self._loading_preview_hide_timer.setSingleShot(True)
        self._loading_preview_hide_timer.timeout.connect(self._hide_loading_preview)
        self._loading_preview_release_timer = QTimer(self)
        self._loading_preview_release_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._loading_preview_release_timer.timeout.connect(self._check_loading_preview_release)
        self._backup_transcription_timeout_timer = QTimer(self)
        self._backup_transcription_timeout_timer.setSingleShot(True)
        self._backup_transcription_timeout_timer.timeout.connect(self._on_backup_transcription_timeout)
        self._stt_benchmark_timeout_timer = QTimer(self)
        self._stt_benchmark_timeout_timer.setSingleShot(True)
        self._stt_benchmark_timeout_timer.timeout.connect(self._on_stt_benchmark_timeout)
        self.loadingPreviewRequested.connect(self._show_loading_preview)
        self.backupTranscriptionFinished.connect(self._finish_last_dictation_transcription)
        if self._loading_preview_enabled:
            self._register_loading_preview_shortcuts()

        self.view = QWebEngineView(self)
        self.view.setObjectName("whisperer-web-view")
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self.view.setAutoFillBackground(True)
        self._apply_widget_backing(self.view)
        self.web_profile = QWebEngineProfile("Whisperer", self)
        try:
            webengine_dir = os.path.join(get_app_data_dir(), "webengine")
            cache_dir = os.path.join(webengine_dir, "cache")
            storage_dir = os.path.join(webengine_dir, "storage")
            os.makedirs(cache_dir, exist_ok=True)
            os.makedirs(storage_dir, exist_ok=True)
            self.web_profile.setCachePath(cache_dir)
            self.web_profile.setPersistentStoragePath(storage_dir)
            self._log_web_ui(f"WebEngine profile paths cache={cache_dir} storage={storage_dir}")
        except Exception as exc:
            self._log_web_ui(f"WebEngine profile path setup failed error={exc}")
        self.page = DiagnosticPage(self, self.web_profile)
        self.view.setPage(self.page)
        web_settings = self.view.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.view.page().setBackgroundColor(WINDOW_BACKING_COLOR)

        central = QWidget(self)
        central.setObjectName("whisperer-main-central")
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        central.setAutoFillBackground(True)
        self._apply_widget_backing(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)
        self._central_layout = layout
        self.setCentralWidget(central)

        self.bridge = Bridge(self)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.loadStarted.connect(self._on_load_started)
        self.view.loadProgress.connect(self._on_load_progress)
        self.view.page().loadFinished.connect(self._on_load_finished)
        try:
            self.view.page().renderProcessTerminated.connect(self._on_render_process_terminated)
        except Exception:
            self._log_web_ui("renderProcessTerminated signal unavailable")
        self._log_web_ui(f"Loading React URL {self._react_index_url.toString()}")
        self.view.load(self._react_index_url)
        QTimer.singleShot(9000, self._diagnose_web_ui_startup_timeout)

        self.tray = TrayIcon(self)
        self.tray.show()
        QTimer.singleShot(0, self._enable_native_shadow)

        self.output_timer = QTimer(self)
        self.output_timer.timeout.connect(self._drain_engine_output)
        self.output_timer.start(150)
        self.engine_start_timer = QTimer(self)
        self.engine_start_timer.setSingleShot(True)
        self.engine_start_timer.timeout.connect(self.start_engine)

        if self._loading_preview_enabled:
            self.engine_start_timer.start(400)

    def _apply_widget_backing(self, widget):
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Window, WINDOW_BACKING_COLOR)
        palette.setColor(QPalette.ColorRole.Base, WINDOW_BACKING_COLOR)
        widget.setPalette(palette)
        object_name = widget.objectName()
        if object_name:
            widget.setStyleSheet(f"#{object_name} {{ background-color: {WINDOW_BACKING_HEX}; }}")
        else:
            widget.setStyleSheet(f"background-color: {WINDOW_BACKING_HEX};")

    def prepare_for_system_move(self):
        self._apply_widget_backing(self)
        central = self.centralWidget()
        if central:
            self._apply_widget_backing(central)
        self._apply_widget_backing(self.view)
        self.view.page().setBackgroundColor(WINDOW_BACKING_COLOR)
        self.view.update()
        self.update()
        self.view.repaint()
        self.repaint()
        app = QApplication.instance()
        if app:
            app.processEvents()

    def _log_react_index_candidates(self):
        for candidate in _react_index_candidates():
            try:
                exists = os.path.exists(candidate)
                size = os.path.getsize(candidate) if exists else 0
                self._log_web_ui(f"React candidate exists={exists} size={size} path={candidate}")
            except Exception as exc:
                self._log_web_ui(f"React candidate check failed path={candidate} error={exc}")

    def _on_load_started(self):
        self._web_load_started = True
        self._web_load_progress = 0
        self._log_web_ui(f"loadStarted url={self.view.url().toString()}")

    def _on_load_progress(self, progress: int):
        previous = self._web_load_progress
        self._web_load_progress = int(progress)
        if progress in {0, 25, 50, 75, 100} or previous < 0 or progress - previous >= 20:
            self._log_web_ui(f"loadProgress {progress} url={self.view.url().toString()}")

    def _on_load_finished(self, ok: bool):
        self._web_load_finished = True
        self._web_load_ok = bool(ok)
        if self._showing_web_ui_error:
            self._log_web_ui(f"diagnostic fallback loadFinished ok={ok}")
            return
        if not ok:
            self._show_web_ui_error("Whisperer UI did not load.", self.view.url().toString())
            return
        self._log_web_ui(f"Loaded {self.view.url().toString()}")
        self.view.page().runJavaScript(_WEB_DIAGNOSTIC_SHIM)
        self.view.page().runJavaScript(_BRIDGE_SHIM)
        QTimer.singleShot(120, self._emit_snapshot)
        QTimer.singleShot(1200, self._verify_web_ui_mounted)

    def _verify_web_ui_mounted(self):
        self._web_probe_pending = True
        self.view.page().runJavaScript(
            """
            (() => JSON.stringify({
              readyState: document.readyState,
              href: location.href,
              title: document.title || "",
              bodyText: (document.body && document.body.innerText || "").trim().slice(0, 160),
              rootText: (document.getElementById("root") && document.getElementById("root").innerText || "").trim().slice(0, 160),
              rootChildren: document.getElementById("root") ? document.getElementById("root").children.length : -1,
              scripts: Array.from(document.scripts).map(function(s) { return s.src || "inline"; }).slice(0, 10)
            }))()
            """,
            self._handle_web_ui_probe,
        )

    def _handle_web_ui_probe(self, result: str):
        self._web_probe_pending = False
        try:
            payload = json.loads(result or "{}")
        except Exception:
            payload = {"raw": result}
        text = str(payload.get("rootText") or payload.get("bodyText") or "")
        self._log_web_ui(f"React mount probe payload={json.dumps(payload, ensure_ascii=False, default=str)}")
        if text:
            self._react_mounted = True
            self._log_web_ui(f"React mounted: {text[:80]!r}")
            return
        detail = (
            f"url={self.view.url().toString()}\n"
            f"logDir={log_dir()}\n"
            f"probe={json.dumps(payload, ensure_ascii=False, default=str, indent=2)}"
        )
        self._log_web_ui("React mount probe returned no visible text")
        self._show_web_ui_error("Whisperer UI opened, but the page stayed blank.", detail)

    def _diagnose_web_ui_startup_timeout(self):
        if self._react_mounted or self._showing_web_ui_error:
            return
        self._web_timeout_reported = True
        detail = (
            f"url={self.view.url().toString()}\n"
            f"target={self._react_index_url.toString()}\n"
            f"loadStarted={self._web_load_started}\n"
            f"loadFinished={self._web_load_finished}\n"
            f"loadOk={self._web_load_ok}\n"
            f"progress={self._web_load_progress}\n"
            f"logDir={log_dir()}"
        )
        self._log_web_ui("Web UI startup timeout\n" + detail)
        if self._web_load_finished:
            self._verify_web_ui_mounted()
            return
        self._show_web_ui_error("Whisperer UI is taking too long to load.", detail)

    def _on_render_process_terminated(self, status, exit_code: int):
        detail = (
            f"status={getattr(status, 'name', status)} exitCode={exit_code}\n"
            f"url={self.view.url().toString()}\n"
            f"logDir={log_dir()}"
        )
        self._log_web_ui("WebEngine render process terminated " + detail.replace("\n", " "))
        self._show_web_ui_error("Whisperer UI renderer stopped.", detail)

    def _show_web_ui_error(self, title: str, detail: str):
        if self._showing_web_ui_error:
            self._log_web_ui(f"Diagnostic fallback already visible; additional title={title!r}")
            return
        self._showing_web_ui_error = True
        self._log_web_ui(f"Showing diagnostic fallback title={title!r} detail={detail!r}")
        try:
            self.view.hide()
        except Exception:
            pass
        panel = QWidget(self)
        panel.setObjectName("whisperer-diagnostic-panel")
        self._apply_widget_backing(panel)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(28, 28, 28, 28)
        panel_layout.setSpacing(12)

        title_label = QLabel(title, panel)
        title_label.setStyleSheet("font-size:20px;font-weight:600;color:#24231f;background:transparent;")
        title_label.setWordWrap(True)
        panel_layout.addWidget(title_label)

        help_label = QLabel("Send this log folder for diagnostics:", panel)
        help_label.setStyleSheet("font-size:14px;color:#4b4943;background:transparent;")
        help_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel_layout.addWidget(help_label)

        details = QPlainTextEdit(panel)
        details.setReadOnly(True)
        details.setPlainText(f"{detail}\n\nLog folder:\n{log_dir()}")
        details.setStyleSheet(
            "QPlainTextEdit { background:#ffffff; color:#24231f; border:1px solid #ddd7ce; "
            "border-radius:8px; padding:10px; font:12px Consolas, monospace; }"
        )
        panel_layout.addWidget(details, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        open_logs = QPushButton("Open log folder", panel)
        open_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        open_logs.clicked.connect(self._open_log_folder)
        actions.addWidget(open_logs)

        copy_details = QPushButton("Copy diagnostics", panel)
        copy_details.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_details.clicked.connect(lambda: self._copy_diagnostics_to_clipboard(details.toPlainText()))
        actions.addWidget(copy_details)
        actions.addStretch(1)
        panel_layout.addLayout(actions)

        self._diagnostic_panel = panel
        self._central_layout.addWidget(panel)

    def _open_log_folder(self):
        folder = log_dir()
        self._log_web_ui(f"Opening diagnostic log folder {folder}")
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception:
            UI_LOG.exception("Could not open log folder")

    def _copy_diagnostics_to_clipboard(self, detail: str):
        try:
            QApplication.clipboard().setText(detail)
            self._log_web_ui("Copied diagnostic details to clipboard")
        except Exception:
            UI_LOG.exception("Could not copy diagnostic details")

    def _log_web_ui(self, message: str):
        if len(message) > 4000:
            message = message[:4000] + "...<truncated>"
        message = scrub_text(message)
        append_log_line("web-ui.log", message)
        UI_LOG.info("web-ui: %s", message)

    def _should_auto_start_engine(self) -> bool:
        startup = self.settings.get("startup", {})
        perf = self.settings.get("performance", {})
        return bool(startup.get("auto_start_engine", True)) and perf.get("engine_preload", "app_start") != "off"

    def _loading_preview_hotkey_values(self) -> list[str | None]:
        shortcuts = self.settings.get("shortcuts", {})
        return [
            shortcuts.get("dictation") or config.DICTATION_HOTKEY,
            shortcuts.get("toggle_recording"),
        ]

    def _loading_preview_hotkey_is_pressed(self) -> bool:
        try:
            import keyboard
        except Exception:
            return False
        for hotkey in self._loading_preview_hotkey_values():
            normalized = _normalize_keyboard_hotkey(hotkey)
            if not normalized:
                continue
            try:
                if keyboard.is_pressed(normalized):
                    return True
            except Exception:
                continue
        return False

    def _loading_preview_alt_is_pressed(self) -> bool:
        try:
            import keyboard
        except Exception:
            return False
        for key in ("alt", "left alt", "right alt", "menu"):
            try:
                if keyboard.is_pressed(key):
                    return True
            except Exception:
                continue
        return False

    def _request_loading_preview(self):
        self.loadingPreviewRequested.emit()

    def _register_loading_preview_shortcuts(self):
        self._unregister_loading_preview_shortcuts()
        if not self._loading_preview_enabled or self._engine_state == "running":
            return
        try:
            import keyboard
        except Exception:
            return

        seen: set[str] = set()
        for hotkey in self._loading_preview_hotkey_values():
            normalized = _normalize_keyboard_hotkey(hotkey)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            try:
                handle = keyboard.add_hotkey(normalized, self._request_loading_preview, suppress=False)
                self._loading_preview_hotkeys.append(handle)
            except Exception:
                pass

    def _unregister_loading_preview_shortcuts(self):
        if not self._loading_preview_hotkeys:
            return
        try:
            import keyboard
        except Exception:
            self._loading_preview_hotkeys.clear()
            return
        for handle in self._loading_preview_hotkeys:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self._loading_preview_hotkeys.clear()

    def _show_loading_preview(self):
        if not self._loading_preview_enabled or self._engine_state == "running":
            return
        self._loading_preview_overlay.show_model_loading()
        alt_pressed = self._loading_preview_alt_is_pressed()
        if alt_pressed:
            self._loading_preview_locked = True
        self._loading_preview_overlay.set_locked(self._loading_preview_locked or alt_pressed)
        if self._loading_preview_locked:
            self._loading_preview_hide_timer.stop()
        else:
            self._loading_preview_hide_timer.start(LOADING_PREVIEW_HIDE_MS)
        if not self._loading_preview_release_timer.isActive():
            self._loading_preview_release_timer.start(LOADING_RELEASE_POLL_MS)

    def _finish_loading_preview(self):
        self._loading_preview_hide_timer.stop()
        if not self._loading_preview_overlay.isVisible():
            return
        self._loading_preview_overlay.finish_model_loading()
        self._loading_preview_hide_timer.start(LOADING_READY_MORPH_HIDE_MS)
        if not self._loading_preview_release_timer.isActive():
            self._loading_preview_release_timer.start(LOADING_RELEASE_POLL_MS)

    def _check_loading_preview_release(self):
        if not self._loading_preview_overlay.isVisible():
            self._loading_preview_release_timer.stop()
            return
        alt_pressed = self._loading_preview_alt_is_pressed()
        if alt_pressed:
            self._loading_preview_locked = True
        locked = self._loading_preview_locked or alt_pressed
        self._loading_preview_overlay.set_locked(locked)
        if locked:
            self._loading_preview_hide_timer.stop()
            return
        if not self._loading_preview_hotkey_is_pressed():
            self._loading_preview_release_timer.stop()
            self._hide_loading_preview()

    def _hide_loading_preview(self):
        self._loading_preview_hide_timer.stop()
        if self._loading_preview_overlay.isVisible():
            if self._loading_preview_locked:
                self._loading_preview_overlay.set_locked(True)
                return
            if self._loading_preview_hotkey_is_pressed():
                self._loading_preview_hide_timer.start(LOADING_HOTKEY_RELEASE_RETRY_MS)
                return
            if self._loading_preview_overlay.is_interacting():
                self._loading_preview_hide_timer.start(LOADING_INTERACTION_HIDE_RETRY_MS)
                return
            if self._loading_preview_alt_is_pressed():
                self._loading_preview_overlay.set_locked(True)
                return
            self._loading_preview_overlay.set_locked(False)
            self._loading_preview_release_timer.stop()
            self._loading_preview_overlay.fade_out()

    def _emit_snapshot(self):
        snapshot = self.snapshot_json()
        self.bridge.settingsChanged.emit(snapshot)
        self.bridge.engineStateChanged.emit(self._engine_state)

    def _set_engine_state(self, state: str):
        if state == self._engine_state:
            return
        self._engine_state = state
        if state == "running":
            if self._engine_ready_file:
                try:
                    os.remove(self._engine_ready_file)
                except OSError:
                    pass
                self._engine_ready_file = ""
            self._loading_preview_enabled = False
            self._finish_loading_preview()
            self._unregister_loading_preview_shortcuts()
        elif state == "loading":
            self._loading_preview_enabled = True
            self._register_loading_preview_shortcuts()
        elif state == "stopped":
            self._loading_preview_enabled = False
            self._loading_preview_locked = False
            self._loading_preview_overlay.set_locked(False)
            self._loading_preview_release_timer.stop()
            self._hide_loading_preview()
            self._unregister_loading_preview_shortcuts()
        self.bridge.engineStateChanged.emit(state)
        try:
            self.tray.set_status(state)
        except Exception:
            pass
        self._emit_snapshot()

    def engine_state(self) -> str:
        return self._engine_state

    def check_for_updates(self) -> str:
        try:
            from core.updater import check_for_update

            return json.dumps(check_for_update().to_dict(), separators=(",", ":"))
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "currentVersion": config.VERSION,
                    "updateAvailable": False,
                    "error": f"Could not check for updates: {exc}",
                },
                separators=(",", ":"),
            )

    def install_update(self) -> str:
        try:
            from core.updater import download_and_launch_update

            payload = download_and_launch_update()
        except Exception as exc:
            payload = {
                "ok": False,
                "currentVersion": config.VERSION,
                "updateAvailable": False,
                "error": f"Could not install update: {exc}",
            }
        if payload.get("ok") and payload.get("shouldCloseApp"):
            QTimer.singleShot(800, self.force_quit)
        return json.dumps(payload, separators=(",", ":"))

    def snapshot_json(self) -> str:
        self.settings = load_settings()
        self.settings.setdefault("startup", {})["launch_on_login"] = self._launch_on_login_enabled()
        microphones = self._load_microphone_options()
        selected_microphone = self._selected_microphone_value(microphones)
        snapshot = {
            "version": config.VERSION,
            "engineState": self._engine_state,
            "settings": self.settings,
            "models": MODEL_OPTIONS,
            "gpus": [{"value": value, "label": label} for label, value in self._gpu_options],
            "microphones": microphones,
            "inputChannels": self._load_input_channel_options(selected_microphone),
            "selectedModel": self._current_model_value(),
            "selectedGpu": self._current_gpu_value(),
            "selectedMicrophone": selected_microphone,
            "selectedInputChannel": str(self.settings.get("audio", {}).get("input_channel", 0) or 0),
            "activeMode": self._active_mode_name(),
            "shortcuts": self._shortcut_payload(),
            "micLevel": self._mic_level_payload(),
            "dictationBackup": self._dictation_backup_payload(),
            "apiKeys": self._api_key_payload(),
        }
        return json.dumps(snapshot, separators=(",", ":"))

    def mic_level_json(self) -> str:
        return json.dumps(self._mic_level_payload(), separators=(",", ":"))

    def vocabulary_snapshot_json(self, search: str = "") -> str:
        return json.dumps({"vocabulary": self._vocabulary_payload(search)}, separators=(",", ":"))

    def history_snapshot_json(self) -> str:
        return json.dumps({"history": self._history_payload()}, separators=(",", ":"))

    def modes_snapshot_json(self) -> str:
        return json.dumps({"modesData": self._modes_payload()}, separators=(",", ":"))

    def _save_and_emit(self) -> str:
        save_settings(self.settings)
        snapshot = self.snapshot_json()
        self.bridge.settingsChanged.emit(snapshot)
        return snapshot

    def _dictation_backup_payload(self) -> dict[str, Any]:
        try:
            from core.dictation_backup import last_dictation_backup_metadata

            payload = last_dictation_backup_metadata()
        except Exception:
            payload = {"available": False, "sizeBytes": 0, "durationSeconds": 0, "modifiedAt": ""}
        payload["busy"] = self._backup_transcription_busy
        payload["status"] = self._backup_transcription_status
        payload["error"] = self._backup_transcription_error
        return payload

    def _api_key_payload(self) -> dict[str, Any]:
        def _masked(service: str, fallback: str | None = None) -> dict[str, Any]:
            try:
                from core.secrets import get_key

                key = get_key(service) or (get_key(fallback) if fallback else "") or ""
            except Exception:
                key = ""
            if not key:
                return {"saved": False, "masked": ""}
            prefix = key[:6] if len(key) > 6 else key[:2]
            suffix = key[-4:] if len(key) > 10 else ""
            return {"saved": True, "masked": f"{prefix}...{suffix}" if suffix else f"{prefix}..."}

        return {
            "groq": _masked("groq", "groq_whisper"),
            "nvidia": _masked("nvidia", "nvidia_parakeet"),
            "openai": _masked("openai"),
            "deepgram": _masked("deepgram"),
        }

    def transcribe_last_dictation(self) -> str:
        if self._backup_transcription_busy:
            return self.snapshot_json()
        payload = self._dictation_backup_payload()
        if not payload.get("available"):
            self._backup_transcription_status = ""
            self._backup_transcription_error = "No last dictation backup is available yet."
            snapshot = self.snapshot_json()
            self.bridge.settingsChanged.emit(snapshot)
            return snapshot
        if self.process and self.process.poll() is None and self._engine_state != "running":
            self._backup_transcription_status = ""
            self._backup_transcription_error = "The dictation engine is still loading. Try again once it says Engine ready."
            snapshot = self.snapshot_json()
            self.bridge.settingsChanged.emit(snapshot)
            return snapshot

        self._backup_transcription_busy = True
        self._backup_transcription_status = "Transcribing last dictation..."
        self._backup_transcription_error = ""
        request_id = str(int(time.time() * 1000))
        self._backup_transcription_request_id = request_id
        snapshot = self.snapshot_json()
        self.bridge.settingsChanged.emit(snapshot)
        self._backup_transcription_timeout_timer.start(180000)
        if self._send_engine_backup_transcription_request(request_id):
            self._backup_transcription_source = "engine"
        else:
            self._backup_transcription_source = "subprocess"
            threading.Thread(target=self._transcribe_last_dictation_worker, args=(request_id,), daemon=True).start()
        return snapshot

    def _send_engine_backup_transcription_request(self, request_id: str) -> bool:
        if (
            self._engine_state != "running"
            or not self.process
            or self.process.poll() is not None
            or not self.process.stdin
        ):
            return False
        try:
            command = json.dumps(
                {"command": "transcribe_last_dictation", "requestId": request_id},
                separators=(",", ":"),
            )
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
            return True
        except Exception:
            return False

    def run_stt_benchmark(self) -> str:
        if self._stt_benchmark_busy:
            return json.dumps(
                {
                    "ok": True,
                    "busy": True,
                    "requestId": self._stt_benchmark_request_id,
                    "message": "Benchmark already running.",
                },
                separators=(",", ":"),
            )
        payload = self._dictation_backup_payload()
        if not payload.get("available"):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Record a dictation first so every provider can benchmark the same audio sample.",
                    "results": [],
                },
                separators=(",", ":"),
            )
        if self._engine_state != "running" or not self.process or self.process.poll() is not None:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Start the dictation engine before running the STT benchmark.",
                    "results": [],
                },
                separators=(",", ":"),
            )

        request_id = str(int(time.time() * 1000))
        self._stt_benchmark_busy = True
        self._stt_benchmark_request_id = request_id
        self._stt_benchmark_timeout_timer.start(240000)
        if not self._send_engine_benchmark_request(request_id):
            self._stt_benchmark_timeout_timer.stop()
            self._stt_benchmark_busy = False
            self._stt_benchmark_request_id = ""
            return json.dumps(
                {
                    "ok": False,
                    "error": "Could not send the benchmark request to the engine.",
                    "results": [],
                },
                separators=(",", ":"),
            )
        return json.dumps({"ok": True, "busy": True, "requestId": request_id}, separators=(",", ":"))

    def _send_engine_benchmark_request(self, request_id: str) -> bool:
        if (
            self._engine_state != "running"
            or not self.process
            or self.process.poll() is not None
            or not self.process.stdin
        ):
            return False
        try:
            command = json.dumps(
                {"command": "benchmark_stt", "requestId": request_id},
                separators=(",", ":"),
            )
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
            return True
        except Exception:
            return False

    def _finish_stt_benchmark(self, payload: dict[str, Any]):
        request_id = str(payload.get("requestId") or "")
        if request_id and request_id != self._stt_benchmark_request_id:
            return
        self._stt_benchmark_timeout_timer.stop()
        self._stt_benchmark_busy = False
        self._stt_benchmark_request_id = ""
        try:
            self.bridge.sttBenchmarkFinished.emit(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            pass

    def _on_stt_benchmark_timeout(self):
        if not self._stt_benchmark_busy:
            return
        self._finish_stt_benchmark(
            {
                "requestId": self._stt_benchmark_request_id,
                "ok": False,
                "error": "The STT benchmark took too long and was stopped.",
                "results": [],
            }
        )

    def _transcribe_last_dictation_worker(self, request_id: str):
        try:
            text = self._run_last_dictation_transcription()
            self.backupTranscriptionFinished.emit(request_id, True, text, "")
        except subprocess.TimeoutExpired:
            self.backupTranscriptionFinished.emit(
                request_id,
                False,
                "",
                "Last dictation transcription timed out. The engine may still be loading; try again once it is ready.",
            )
        except Exception as exc:
            self.backupTranscriptionFinished.emit(request_id, False, "", str(exc))

    def _finish_last_dictation_transcription(self, request_id: str, ok: bool, text: str, error: str):
        if request_id and request_id != self._backup_transcription_request_id:
            return
        self._backup_transcription_timeout_timer.stop()
        self._backup_transcription_busy = False
        self._backup_transcription_request_id = ""
        self._backup_transcription_source = ""
        if ok and text.strip():
            QApplication.clipboard().setText(text.strip())
            self._backup_transcription_status = "Copied last dictation to clipboard."
            self._backup_transcription_error = ""
        elif ok:
            self._backup_transcription_status = ""
            self._backup_transcription_error = "The backup did not contain transcribable speech."
        else:
            self._backup_transcription_status = ""
            self._backup_transcription_error = error or "Could not transcribe the last dictation."
        self._emit_snapshot()

    def _on_backup_transcription_timeout(self):
        if not self._backup_transcription_busy:
            return
        request_id = self._backup_transcription_request_id
        self._finish_last_dictation_transcription(
            request_id,
            False,
            "",
            "Last dictation transcription took too long and was stopped. Try again after the engine is ready.",
        )

    def _engine_python_context(self) -> tuple[str, str, dict[str, str]]:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if getattr(sys, "frozen", False):
            source_root = self._frozen_engine_source_root()
            python_exe = self._external_engine_python()
            if not source_root or not python_exe:
                raise RuntimeError("The external Python engine runtime could not be found.")
        else:
            source_root = project_root
            python_exe = sys.executable

        env = os.environ.copy()
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        env["WHISPERER_PROJECT_ROOT"] = source_root
        env["PYTHONUTF8"] = "1"
        env["WHISPERER_MODEL"] = self._current_model_value()
        _apply_quiet_model_env(env)
        self._apply_engine_gpu_env(env)
        return python_exe, source_root, env

    def _run_last_dictation_transcription(self) -> str:
        python_exe, source_root, env = self._engine_python_context()
        script = r'''
import json
import os
import sys

source_root = os.environ.get("WHISPERER_PROJECT_ROOT", "")
if source_root and source_root not in sys.path:
    sys.path.insert(0, source_root)

import config

model = os.environ.get("WHISPERER_MODEL", "")
if model:
    config.WHISPER_MODEL_SIZE = model

from core.dictation_backup import finalize_last_dictation_wav, load_last_dictation_audio
from core.dictionary import apply_replacements, get_prompt_words
from core.formatter import format_transcription
from core.transcriber import transcribe, transcribe_cloud
from core.secrets import get_key

finalize_last_dictation_wav()
audio = load_last_dictation_audio()
stt_provider = os.environ.get("WHISPERER_STT_PROVIDER")
if stt_provider == "groq_whisper":
    key = get_key("groq") or get_key("groq_whisper")
    if not key:
        raise RuntimeError("No Groq API key is configured.")
    raw_text = transcribe_cloud(audio, "groq_whisper", key, language=config.WHISPER_LANGUAGE, prompt=get_prompt_words(80))
elif stt_provider == "nvidia_parakeet":
    key = get_key("nvidia") or get_key("nvidia_parakeet")
    if not key:
        raise RuntimeError("No NVIDIA API key is configured.")
    raw_text = transcribe_cloud(audio, "nvidia_parakeet", key, language=config.WHISPER_LANGUAGE, prompt=get_prompt_words(80))
else:
    raw_text = transcribe(audio, context_words=get_prompt_words(80))
final_text = apply_replacements(
    format_transcription(
        raw_text,
        active_app="last-dictation",
        window_title="Last dictation backup",
    )
)
print("WHISPERER_BACKUP_RESULT " + json.dumps({"text": final_text, "raw": raw_text}, ensure_ascii=False), flush=True)
'''
        result = subprocess.run(
            [python_exe, "-u", "-c", script],
            cwd=source_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        output = result.stdout or ""
        clean_lines = [line for line in output.splitlines() if not self._is_noisy_engine_line(line)]
        if result.returncode != 0:
            tail = "\n".join(clean_lines[-8:]).strip()
            raise RuntimeError(tail or "Backup transcription failed.")
        for line in reversed(clean_lines):
            if line.startswith("WHISPERER_BACKUP_RESULT "):
                payload = json.loads(line.split(" ", 1)[1])
                return str(payload.get("text") or payload.get("raw") or "").strip()
        tail = "\n".join(clean_lines[-8:]).strip()
        if tail:
            raise RuntimeError(tail)
        raise RuntimeError("Backup transcription finished without returning text.")

    def set_model(self, value: str) -> str:
        valid_values = {item["value"] for item in MODEL_OPTIONS}
        if value not in valid_values:
            value = MODEL_OPTIONS[0]["value"]
        self.settings.setdefault("startup", {})["default_model"] = value
        snapshot = self._save_and_emit()
        if self.process and self.process.poll() is None:
            self.restart_engine()
        return snapshot

    def set_gpu(self, value: str) -> str:
        valid_values = {gpu_value for _label, gpu_value in self._gpu_options}
        if value not in valid_values:
            value = NVIDIA_API_GPU_VALUE
        self.settings.setdefault("startup", {})["gpu_device"] = value
        snapshot = self._save_and_emit()
        if self.process and self.process.poll() is None:
            self.restart_engine()
        return snapshot

    def model_cache_status(self, value: str) -> str:
        valid_values = {item["value"] for item in MODEL_OPTIONS}
        if value not in valid_values:
            value = MODEL_OPTIONS[0]["value"]
        return json.dumps(
            {"model": value, "cached": self._local_model_cache_exists(value)},
            separators=(",", ":"),
        )

    def set_api_key(self, service: str, value: str) -> str:
        service = (service or "").strip().lower()
        if service == "grok":
            service = "groq"
        if service in {"nvidia_parakeet", "nvidia_nim"}:
            service = "nvidia"
        if service not in {"groq", "nvidia", "openai", "openai_compat", "anthropic", "deepgram"}:
            return json.dumps({"ok": False, "error": "Unsupported API key service."}, separators=(",", ":"))
        from core.secrets import delete_key, set_key

        value = (value or "").strip()
        if value:
            set_key(service, value)
        else:
            delete_key(service)
        try:
            self.bridge.settingsChanged.emit(self.snapshot_json())
        except Exception:
            pass
        return json.dumps({"ok": True}, separators=(",", ":"))

    def test_api_key(self, service: str) -> str:
        service = (service or "").strip().lower()
        if service == "grok":
            service = "groq"
        if service in {"nvidia_parakeet", "nvidia_nim"}:
            service = "nvidia"
        if service == "nvidia":
            return self._test_nvidia_api_key()
        if service != "groq":
            return json.dumps({"ok": False, "error": "Unsupported API key service."}, separators=(",", ":"))

        from core.secrets import get_key

        key = get_key("groq") or get_key("groq_whisper")
        if not key:
            return json.dumps({"ok": False, "error": "No Groq API key is saved."}, separators=(",", ":"))

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "User-Agent": f"Whisperer/{config.VERSION}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            message = f"Groq rejected the key ({exc.code})."
            if body:
                try:
                    data = json.loads(body)
                    message = str(data.get("error", {}).get("message") or data.get("message") or message)
                except Exception:
                    message = body[:180]
            return json.dumps({"ok": False, "error": message}, separators=(",", ":"))
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"Could not reach Groq: {exc}"}, separators=(",", ":"))

        models = payload.get("data") if isinstance(payload, dict) else None
        count = len(models) if isinstance(models, list) else 0
        return json.dumps({"ok": True, "message": f"Groq key works. {count} models visible."}, separators=(",", ":"))

    def _test_nvidia_api_key(self) -> str:
        from core.secrets import get_key

        key = get_key("nvidia") or get_key("nvidia_parakeet")
        if not key:
            return json.dumps({"ok": False, "error": "No NVIDIA API key is saved."}, separators=(",", ":"))
        try:
            import numpy as np
            from core.transcriber import transcribe_cloud

            silence = np.zeros(config.AUDIO_SAMPLE_RATE // 2, dtype=np.float32)
            transcribe_cloud(silence, "nvidia_parakeet", key, language=config.WHISPER_LANGUAGE)
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"NVIDIA API test failed: {exc}"}, separators=(",", ":"))
        return json.dumps({"ok": True, "message": "NVIDIA Parakeet key works."}, separators=(",", ":"))

    def set_microphone(self, value: str) -> str:
        audio = self.settings.setdefault("audio", {})
        if value == "default":
            audio["input_device"] = None
            audio["input_device_name"] = None
        else:
            try:
                index = int(value)
                audio["input_device"] = index
                audio["input_device_name"] = self._device_name(index)
            except (TypeError, ValueError):
                audio["input_device"] = None
                audio["input_device_name"] = None
        max_channels = max(1, self._input_channel_count(value))
        try:
            channel = int(audio.get("input_channel", 0) or 0)
        except (TypeError, ValueError):
            channel = 0
        audio["input_channel"] = max(0, min(channel, max_channels - 1))
        return self._save_and_emit()

    def set_input_channel(self, value: str) -> str:
        try:
            channel = max(0, int(value))
        except (TypeError, ValueError):
            channel = 0
        selected = self._selected_microphone_value(self._load_microphone_options())
        max_channels = max(1, self._input_channel_count(selected))
        self.settings.setdefault("audio", {})["input_channel"] = min(channel, max_channels - 1)
        return self._save_and_emit()

    def set_setting(self, section: str, key: str, value: Any) -> str:
        if not section or not key:
            return self.snapshot_json()
        if section == "startup" and key == "launch_on_login":
            value = bool(value)
            try:
                from scripts.launch_on_login import set_launch_on_login

                set_launch_on_login(value)
            except Exception:
                pass
        if section == "audio" and key == "ducking_percent":
            try:
                value = max(0, min(100, int(round(int(value) / 25)) * 25))
            except (TypeError, ValueError):
                value = 75
        self.settings.setdefault(section, {})[key] = value
        snapshot = self._save_and_emit()
        if section == "performance" and key == "engine_preload" and value == "off":
            self.stop_engine()
        if section == "startup" and key == "auto_start_engine":
            if not value:
                self.stop_engine()
            elif self._should_auto_start_engine():
                self.start_engine()
        return snapshot

    def set_shortcut(self, name: str, value: str) -> str:
        name = (name or "").strip()
        value = (value or "").strip().lower()
        if not name:
            return self.snapshot_json()
        self.settings = load_settings()
        shortcuts = self.settings.setdefault("shortcuts", {})
        shortcuts[name] = value or None
        snapshot = self._save_and_emit()
        if self._loading_preview_enabled and self._engine_state != "running":
            self._register_loading_preview_shortcuts()
        if self.process and self.process.poll() is None:
            self.restart_engine()
        return snapshot

    def _launch_on_login_enabled(self) -> bool:
        try:
            from scripts.launch_on_login import is_launch_on_login_enabled

            return bool(is_launch_on_login_enabled())
        except Exception:
            return bool(self.settings.get("startup", {}).get("launch_on_login", False))

    def _current_model_value(self) -> str:
        value = self.settings.get("startup", {}).get("default_model", MODEL_OPTIONS[0]["value"])
        valid_values = {item["value"] for item in MODEL_OPTIONS}
        return value if value in valid_values else MODEL_OPTIONS[0]["value"]

    def _current_gpu_value(self) -> str:
        value = str(self.settings.get("startup", {}).get("gpu_device", NVIDIA_API_GPU_VALUE))
        valid_values = {gpu_value for _label, gpu_value in self._gpu_options}
        return value if value in valid_values else NVIDIA_API_GPU_VALUE

    def _local_model_cache_exists(self, model_name: str) -> bool:
        cache_dir_name = "models--" + model_name.replace("/", "--")
        candidates = [
            os.path.join(config.MODEL_CACHE_DIR, cache_dir_name),
            os.path.join(config.MODEL_CACHE_DIR, "huggingface", "hub", cache_dir_name),
        ]
        for root in candidates:
            snapshots = os.path.join(root, "snapshots")
            if not os.path.isdir(snapshots):
                continue
            for snapshot in os.listdir(snapshots):
                path = os.path.join(snapshots, snapshot)
                try:
                    if os.path.isdir(path) and any(os.scandir(path)):
                        return True
                except OSError:
                    pass
        return False

    def _load_gpu_options(self) -> list[tuple[str, str]]:
        options = [
            ("NVIDIA API Parakeet", NVIDIA_API_GPU_VALUE),
            ("Groq API (Whisper)", GROQ_API_GPU_VALUE),
        ]
        if getattr(sys, "frozen", False) and not self._external_engine_python():
            append_log_line(
                "engine-launch.log",
                "local engine options hidden reason='No external Python runtime found'",
            )
            return options

        options.append(("Auto (local CUDA GPU)", GPU_AUTO_VALUE))
        try:
            creationflags = 0x08000000 if os.name == "nt" else 0
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=creationflags,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = [part.strip() for part in line.split(",", 2)]
                    if len(parts) != 3:
                        continue
                    index, name, memory_mb = parts
                    try:
                        memory_gb = round(int(memory_mb) / 1024)
                        label = f"GPU {index} - {name} ({memory_gb} GB)"
                    except ValueError:
                        label = f"GPU {index} - {name}"
                    options.append((label, index))
        except Exception:
            pass
        return options

    def _local_engine_required_modules(self, model_name: str | None = None) -> list[str]:
        model = (model_name or self._current_model_value() or "").lower()
        required = ["numpy", "sounddevice", "keyboard"]
        if model.startswith("nvidia/parakeet"):
            required.extend(["torch", "nemo.collections.asr"])
        else:
            required.append("faster_whisper")
        return required

    def _local_engine_status(self, model_name: str | None = None) -> dict[str, Any]:
        model = model_name or self._current_model_value()
        if not getattr(sys, "frozen", False):
            return {
                "available": True,
                "mode": "source",
                "python": sys.executable,
                "model": model,
                "missing": [],
                "message": "Source checkout can use the active Python environment.",
            }

        python_exe = self._external_engine_python()
        if not python_exe:
            return {
                "available": False,
                "mode": "frozen",
                "python": "",
                "model": model,
                "missing": ["python"],
                "message": "Local GPU transcription requires a separate Python runtime with the local model dependencies installed.",
            }

        cache_key = (python_exe, model)
        cached = self._local_engine_status_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < 60:
            return dict(cached[1])

        required = self._local_engine_required_modules(model)
        probe = r'''
import importlib.util
import json
import sys

required = sys.argv[1:]
missing = []
for name in required:
    try:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    except Exception:
        missing.append(name)
print(json.dumps({"missing": missing}, separators=(",", ":")))
'''
        try:
            result = subprocess.run(
                [python_exe, "-c", probe, *required],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            payload = json.loads((result.stdout or "{}").strip().splitlines()[-1] or "{}")
            missing = [str(item) for item in payload.get("missing", [])]
            available = result.returncode == 0 and not missing
            message = (
                "Local engine runtime is available."
                if available
                else "Local GPU transcription requires these Python packages: " + ", ".join(missing)
            )
        except Exception as exc:
            missing = ["runtime_probe"]
            available = False
            message = f"Could not verify the local engine runtime: {exc}"

        status = {
            "available": available,
            "mode": "frozen",
            "python": python_exe,
            "model": model,
            "required": required,
            "missing": missing,
            "message": message,
        }
        self._local_engine_status_cache[cache_key] = (now, status)
        return dict(status)

    def local_engine_status_json(self, model_name: str = "") -> str:
        return json.dumps(self._local_engine_status(model_name or self._current_model_value()), separators=(",", ":"))

    def _apply_engine_gpu_env(self, env: dict[str, str]):
        gpu_value = self._current_gpu_value()
        if gpu_value in {GROQ_API_GPU_VALUE, GROQ_API_LEGACY_GPU_VALUE}:
            env["WHISPERER_STT_PROVIDER"] = GROQ_API_STT_PROVIDER
            env.pop("CUDA_VISIBLE_DEVICES", None)
        elif gpu_value == NVIDIA_API_GPU_VALUE:
            env["WHISPERER_STT_PROVIDER"] = NVIDIA_API_STT_PROVIDER
            env.pop("CUDA_VISIBLE_DEVICES", None)
        elif gpu_value and gpu_value != GPU_AUTO_VALUE:
            env.pop("WHISPERER_STT_PROVIDER", None)
            env["CUDA_VISIBLE_DEVICES"] = gpu_value
        else:
            env.pop("WHISPERER_STT_PROVIDER", None)
            env.pop("CUDA_VISIBLE_DEVICES", None)

    def _load_microphone_options(self) -> list[dict[str, str]]:
        now = time.monotonic()
        if self._microphone_cache and now - self._microphone_cache_ts < 8.0:
            return list(self._microphone_cache)
        options = [{"value": "default", "label": "System default microphone", "hint": "Auto"}]
        seen: set[str] = set()
        try:
            import sounddevice as sd

            for index, device in enumerate(sd.query_devices()):
                if int(device.get("max_input_channels", 0)) <= 0:
                    continue
                name = str(device.get("name", "")).strip() or f"Input device {index}"
                label = name if name not in seen else f"{name} ({index})"
                seen.add(name)
                channels = int(device.get("max_input_channels", 0))
                options.append({"value": str(index), "label": label, "hint": f"{channels} ch"})
        except Exception:
            pass
        self._microphone_cache = list(options)
        self._microphone_cache_ts = now
        return options

    def _selected_microphone_value(self, options: list[dict[str, str]]) -> str:
        audio = self.settings.get("audio", {})
        selected_index = audio.get("input_device")
        selected_name = audio.get("input_device_name")
        if isinstance(selected_index, int):
            value = str(selected_index)
            if any(option["value"] == value for option in options):
                return value
        if selected_name:
            for option in options:
                if option["label"] == selected_name:
                    return option["value"]
        return "default"

    def _device_name(self, index: int) -> str | None:
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            if 0 <= index < len(devices):
                return str(devices[index].get("name", "")).strip() or None
        except Exception:
            pass
        return None

    def _input_channel_count(self, selected_microphone: str) -> int:
        cache_key = selected_microphone or "default"
        now = time.monotonic()
        cached = self._input_channel_count_cache.get(cache_key)
        if cached and now - cached[0] < 8.0:
            return cached[1]
        try:
            import sounddevice as sd

            if selected_microphone != "default":
                device = sd.query_devices(int(selected_microphone), "input")
            else:
                device = sd.query_devices(kind="input")
            count = max(1, int(device.get("max_input_channels", 1) or 1))
        except Exception:
            count = 1
        self._input_channel_count_cache[cache_key] = (now, count)
        return count

    def _load_input_channel_options(self, selected_microphone: str) -> list[dict[str, str]]:
        count = self._input_channel_count(selected_microphone)
        return [{"value": str(index), "label": f"Channel {index + 1}"} for index in range(count)]

    def _active_mode_name(self) -> str:
        # Keep the dashboard process lightweight. Resolving the active mode needs
        # core.context, which imports OCR/pandas/pyarrow and can stall or crash
        # the Qt host. The engine process owns real active-mode resolution.
        return self._active_mode_cache

    def _shortcut_payload(self) -> dict[str, list[str]]:
        shortcuts = self.settings.get("shortcuts", {})
        return {name: self._hotkey_to_keys(value) for name, value in shortcuts.items() if value}

    def _hotkey_to_keys(self, hotkey: str | None) -> list[str]:
        if not hotkey:
            return []
        labels: list[str] = []
        for part in str(hotkey).split("+"):
            key = part.strip()
            lookup = {
                "ctrl": "Ctrl",
                "control": "Ctrl",
                "alt": "Alt",
                "shift": "Shift",
                "left windows": "Left Windows",
                "right windows": "Right Windows",
                "windows": "Windows",
                "win": "Windows",
                "escape": "Esc",
            }
            labels.append(lookup.get(key.lower(), key[:1].upper() + key[1:]))
        return labels

    def _timing_payload(self) -> dict[str, list[dict[str, Any]]]:
        try:
            from core.perf import timing_summary

            return timing_summary(limit=80)
        except Exception:
            return {"startup": [], "dictation": [], "other": []}

    def _vocabulary_payload(self, search: str = "") -> dict[str, Any]:
        try:
            from core.dictionary import get_replacement_rules, get_word_count, get_words, init_db

            init_db()
            search = (search or "").strip()
            rules = get_replacement_rules(enabled_only=False, search=search)
            words = get_words(limit=500, search=search)
            return {
                "wordCount": get_word_count(),
                "words": words,
                "rules": rules,
            }
        except Exception as exc:
            return {"wordCount": 0, "words": [], "rules": [], "error": str(exc)}

    def add_vocabulary_word(self, word: str) -> str:
        word = (word or "").strip()
        if word:
            from core.dictionary import add_word

            add_word(word, source="manual")
        return self.vocabulary_snapshot_json()

    def add_replacement_rule(self, match_text: str, replace_with: str) -> str:
        match_text = (match_text or "").strip()
        if match_text:
            from core.dictionary import add_replacement_rule

            add_replacement_rule(match_text, replace_with or "")
        return self.vocabulary_snapshot_json()

    def _history_payload(self) -> dict[str, Any]:
        try:
            from core.history import list_dictations

            rows = list_dictations(limit=220)
            today = time.strftime("%Y-%m-%d")
            items: list[dict[str, Any]] = []
            total_words = 0
            total_ms = 0
            today_count = 0
            for row in rows:
                final_text = row.get("final_text") or ""
                raw_text = row.get("raw_transcript") or ""
                text = final_text or raw_text
                words = len(text.split())
                duration_ms = int(row.get("duration_ms") or 0)
                started_at = str(row.get("started_at") or "")
                error = row.get("error") or ""
                total_words += words
                total_ms += max(0, duration_ms)
                if started_at.startswith(today):
                    today_count += 1
                items.append(
                    {
                        "id": int(row.get("id") or 0),
                        "startedAt": started_at,
                        "app": row.get("app_name") or "Unknown app",
                        "windowTitle": row.get("window_title") or "",
                        "mode": row.get("mode_name") or "Voice",
                        "duration": max(0, round(duration_ms / 1000)),
                        "words": words,
                        "text": text,
                        "rawText": raw_text,
                        "finalText": final_text,
                        "error": error,
                        "status": "error" if error else "ok",
                        "pasteSucceeded": row.get("paste_succeeded"),
                        "pasteMethod": row.get("paste_method") or "",
                        "sttProvider": row.get("stt_provider") or "",
                        "sttModel": row.get("stt_model") or "",
                        "audioPath": row.get("audio_path") or "",
                    }
                )
            return {
                "items": items,
                "totals": {
                    "today": today_count,
                    "words": total_words,
                    "minutes": round(total_ms / 60000),
                },
                "stats": self._history_stats_payload(),
            }
        except Exception as exc:
            return {
                "items": [],
                "totals": {"today": 0, "words": 0, "minutes": 0},
                "stats": self._empty_history_stats(),
                "error": str(exc),
            }

    def _empty_history_stats(self) -> dict[str, Any]:
        days = [date.today() - timedelta(days=offset) for offset in range(6, -1, -1)]
        return {
            "totalDictations": 0,
            "totalWords": 0,
            "totalMinutes": 0,
            "topWords": [],
            "last7Days": [
                {"date": day.isoformat(), "label": day.strftime("%a"), "words": 0, "minutes": 0, "dictations": 0}
                for day in days
            ],
        }

    def _history_stats_payload(self) -> dict[str, Any]:
        try:
            from core.migrations import get_connection

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT started_at, duration_ms, raw_transcript, final_text, error
                FROM dictations
                ORDER BY started_at ASC
            """)
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
        except Exception:
            return self._empty_history_stats()

        stopwords = {
            "the", "and", "that", "this", "with", "for", "you", "your", "are", "was", "were",
            "have", "has", "had", "but", "not", "from", "they", "them", "there", "then", "than",
            "what", "when", "where", "would", "could", "should", "about", "into", "just", "like",
            "over", "because", "really", "very", "can", "will", "all", "our", "out", "now",
        }
        days = [date.today() - timedelta(days=offset) for offset in range(6, -1, -1)]
        daily = {
            day.isoformat(): {"date": day.isoformat(), "label": day.strftime("%a"), "words": 0, "minutes": 0, "dictations": 0}
            for day in days
        }
        word_counts: dict[str, int] = {}
        total_words = 0
        total_ms = 0
        total_dictations = 0

        for row in rows:
            if row.get("error"):
                continue
            text = (row.get("final_text") or row.get("raw_transcript") or "").strip()
            words = re.findall(r"[A-Za-z][A-Za-z'-]{1,}", text.lower())
            word_count = len(words)
            duration_ms = max(0, int(row.get("duration_ms") or 0))
            total_words += word_count
            total_ms += duration_ms
            total_dictations += 1
            for word in words:
                clean = word.strip("'-")
                if len(clean) <= 2 or clean in stopwords:
                    continue
                word_counts[clean] = word_counts.get(clean, 0) + 1
            started_at = str(row.get("started_at") or "")
            day_key = started_at[:10]
            if day_key in daily:
                daily[day_key]["words"] += word_count
                daily[day_key]["minutes"] += round(duration_ms / 60000, 1)
                daily[day_key]["dictations"] += 1

        top_words = [
            {"word": word, "count": count}
            for word, count in sorted(word_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
        ]
        return {
            "totalDictations": total_dictations,
            "totalWords": total_words,
            "totalMinutes": round(total_ms / 60000),
            "topWords": top_words,
            "last7Days": list(daily.values()),
        }

    def delete_dictation(self, dictation_id: int) -> str:
        try:
            from core.history import delete_dictation

            delete_dictation(int(dictation_id))
        except Exception:
            pass
        return self.history_snapshot_json()

    def purge_history(self) -> str:
        try:
            from core.migrations import get_connection

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT audio_path FROM dictations WHERE audio_path IS NOT NULL AND audio_path != ''")
            audio_paths = [str(row["audio_path"]) for row in cursor.fetchall()]
            for audio_path in audio_paths:
                if audio_path and os.path.exists(audio_path):
                    try:
                        os.remove(audio_path)
                    except OSError:
                        pass
            cursor.execute("DELETE FROM dictation_contexts")
            cursor.execute("DELETE FROM dictations")
            conn.commit()
            conn.close()
        except Exception:
            pass
        return self.history_snapshot_json()

    def _modes_payload(self) -> list[dict[str, Any]]:
        try:
            from core.modes import list_auto_rules, list_modes, seed_builtins

            seed_builtins()
            rules_by_mode: dict[int, list[dict[str, Any]]] = {}
            for rule in list_auto_rules():
                mode_id = int(rule.get("mode_id") or 0)
                rules_by_mode.setdefault(mode_id, []).append(rule)
            modes = []
            for mode in list_modes(enabled_only=False):
                mode_id = int(mode.id or 0)
                modes.append(
                    {
                        "id": mode_id,
                        "name": mode.name,
                        "description": mode.description,
                        "builtin": mode.is_builtin,
                        "enabled": mode.enabled,
                        "stt": mode.stt_provider or "local",
                        "sttModel": mode.stt_model or "",
                        "format": mode.output_format or "plain",
                        "formattingPrompt": mode.formatting_prompt or "",
                        "llm": mode.llm_enabled,
                        "llmProvider": mode.llm_provider or "",
                        "llmModel": mode.llm_model or "",
                        "llmPrompt": mode.llm_prompt or "",
                        "pasteMethod": mode.paste_method or "clipboard_paste",
                        "autoSend": mode.auto_send,
                        "ctxOcr": mode.ctx_ocr,
                        "ctxSelectedText": mode.ctx_selected_text,
                        "ctxClipboard": mode.ctx_clipboard,
                        "auto": [
                            {
                                "id": int(rule.get("id") or 0),
                                "type": rule.get("match_type") or "",
                                "value": rule.get("match_value") or "",
                                "priority": int(rule.get("priority") or 0),
                                "enabled": bool(rule.get("enabled")),
                            }
                            for rule in rules_by_mode.get(mode_id, [])
                        ],
                    }
                )
            return modes
        except Exception:
            return []

    def update_mode(self, mode_id: int, patch_json: str) -> str:
        try:
            from core.modes import update_mode

            patch = json.loads(patch_json or "{}")
            mapping = {
                "name": "name",
                "description": "description",
                "enabled": "enabled",
                "format": "output_format",
                "llm": "llm_enabled",
                "llmProvider": "llm_provider",
                "llmModel": "llm_model",
                "llmPrompt": "llm_prompt",
                "stt": "stt_provider",
                "sttModel": "stt_model",
                "pasteMethod": "paste_method",
                "formattingPrompt": "formatting_prompt",
                "autoSend": "auto_send",
                "ctxOcr": "ctx_ocr",
                "ctxSelectedText": "ctx_selected_text",
                "ctxClipboard": "ctx_clipboard",
            }
            updates = {target: patch[source] for source, target in mapping.items() if source in patch}
            if updates:
                update_mode(int(mode_id), **updates)
        except Exception:
            pass
        return self.modes_snapshot_json()

    def add_mode(self, name: str) -> str:
        created_id = 0
        try:
            from core.modes import add_mode, list_modes

            base = (name or "New Mode").strip() or "New Mode"
            existing = {mode.name.lower() for mode in list_modes(enabled_only=False)}
            candidate = base
            suffix = 2
            while candidate.lower() in existing:
                candidate = f"{base} {suffix}"
                suffix += 1
            created_id = int(add_mode(candidate, description="Custom dictation mode.", output_format="plain") or 0)
        except Exception:
            pass
        try:
            payload = json.loads(self.modes_snapshot_json())
            if created_id:
                payload["createdModeId"] = created_id
            return json.dumps(payload, separators=(",", ":"))
        except Exception:
            return self.modes_snapshot_json()

    def delete_mode(self, mode_id: int) -> str:
        try:
            from core.modes import delete_mode

            delete_mode(int(mode_id))
        except Exception:
            pass
        return self.modes_snapshot_json()

    def add_auto_rule(self, mode_id: int, match_type: str, match_value: str, priority: int = 0) -> str:
        try:
            from core.modes import add_auto_rule

            match_type = (match_type or "process").strip()
            match_value = (match_value or "").strip()
            if match_value:
                add_auto_rule(int(mode_id), match_type, match_value, int(priority), True)
        except Exception:
            pass
        return self.modes_snapshot_json()

    def delete_auto_rule(self, rule_id: int) -> str:
        try:
            from core.modes import delete_auto_rule

            delete_auto_rule(int(rule_id))
        except Exception:
            pass
        return self.modes_snapshot_json()

    def _mic_level_payload(self) -> dict[str, Any]:
        with self._mic_level_lock:
            return {
                "db": round(self._mic_level_db, 1),
                "level": round(self._mic_level_value, 4),
                "error": self._mic_level_error,
            }

    def _set_mic_level(self, db: float, level: float, error: str = ""):
        with self._mic_level_lock:
            self._mic_level_db = max(-96.0, min(0.0, float(db)))
            self._mic_level_value = max(0.0, min(1.0, float(level)))
            self._mic_level_error = error

    def start_engine(self):
        if self.process and self.process.poll() is None:
            return
        self.settings = load_settings()
        self._loading_preview_enabled = True
        self._register_loading_preview_shortcuts()
        self._engine_output_lines.clear()
        create_no_window = 0x08000000
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_arg = self._current_model_value()

        if getattr(sys, "frozen", False):
            gpu_value = self._current_gpu_value()
            source_root = self._frozen_engine_source_root()
            python_exe = self._external_engine_python()
            if gpu_value not in API_GPU_VALUES:
                local_status = self._local_engine_status(model_arg)
                if not source_root or not python_exe or not local_status.get("available"):
                    message = str(
                        local_status.get("message")
                        or "Local GPU transcription is not available in this installation."
                    )
                    append_log_line(
                        "engine-launch.log",
                        f"local engine blocked model={model_arg!r} gpu={gpu_value!r} "
                        f"sourceRoot={source_root!r} python={python_exe!r} status={local_status!r}",
                    )
                    self._engine_output_lines.append(message)
                    self._loading_preview_enabled = False
                    self._hide_loading_preview()
                    self._unregister_loading_preview_shortcuts()
                    self._set_engine_state("stopped")
                    return
                command = [python_exe, "-u", os.path.join(source_root, "main.py"), f"--model={model_arg}"]
                cwd = source_root
                env = os.environ.copy()
                env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
                env.setdefault("WHISPERER_PROJECT_ROOT", source_root)
            else:
                command = [sys.executable, "--engine", f"--model={model_arg}"]
                cwd = project_root
                env = os.environ.copy()
        else:
            command = [sys.executable, "-u", os.path.join(project_root, "main.py"), f"--model={model_arg}"]
            cwd = project_root
            env = os.environ.copy()

        env["WHISPERER_UI_LOADING_PREVIEW"] = "1"
        env["WHISPERER_LOG_DIR"] = log_dir()
        _apply_quiet_model_env(env)
        self._apply_engine_gpu_env(env)
        try:
            log_root = log_dir()
            os.makedirs(log_root, exist_ok=True)
            self._engine_ready_file = os.path.join(log_root, f"engine-ready-{time.time_ns()}.json")
            if os.path.exists(self._engine_ready_file):
                os.remove(self._engine_ready_file)
            env["WHISPERER_ENGINE_READY_FILE"] = self._engine_ready_file
        except Exception:
            self._engine_ready_file = ""

        append_log_line(
            "engine-launch.log",
            "starting engine "
            f"command={command!r} cwd={cwd!r} frozen={bool(getattr(sys, 'frozen', False))} "
            f"model={model_arg!r} gpu={self._current_gpu_value()!r} provider={env.get('WHISPERER_STT_PROVIDER', '')!r} "
            f"readyFile={self._engine_ready_file!r}",
        )
        try:
            self.process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                creationflags=create_no_window if os.name == "nt" else 0,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                close_fds=True,
            )
            append_log_line("engine-launch.log", f"engine process started pid={self.process.pid}")
        except Exception as exc:
            append_log_line("engine-launch.log", f"failed to start engine error={exc!r}")
            self._engine_output_lines.append(f"Failed to start engine: {exc}")
            self._loading_preview_enabled = False
            self._hide_loading_preview()
            self._unregister_loading_preview_shortcuts()
            self._set_engine_state("stopped")
            return

        self._set_engine_state("loading")
        self._start_engine_output_reader()

    def stop_engine(self):
        self._loading_preview_enabled = False
        self._loading_preview_locked = False
        self._loading_preview_overlay.set_locked(False)
        self._loading_preview_release_timer.stop()
        self._hide_loading_preview()
        self._unregister_loading_preview_shortcuts()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self._engine_ready_file:
            try:
                os.remove(self._engine_ready_file)
            except OSError:
                pass
            self._engine_ready_file = ""
        if self._stt_benchmark_busy:
            self._finish_stt_benchmark(
                {
                    "requestId": self._stt_benchmark_request_id,
                    "ok": False,
                    "error": "The engine was stopped before the STT benchmark finished.",
                    "results": [],
                }
            )
        self._set_engine_state("stopped")

    def restart_engine(self):
        self.stop_engine()
        QTimer.singleShot(500, self.start_engine)

    # Tray compatibility with the legacy MainWindow.
    start_app = start_engine
    stop_app = stop_engine

    def set_paused(self, paused: bool):
        self._paused = paused
        if paused:
            self.stop_engine()
        elif self._should_auto_start_engine():
            self.start_engine()

    def show_window(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._enable_native_shadow)
        QTimer.singleShot(0, self._apply_taskbar_identity)

    def _taskbar_relaunch_exe(self) -> str | None:
        candidates = [
            os.environ.get("WHISPERER_LAUNCHER_EXE", ""),
            sys.executable if getattr(sys, "frozen", False) else "",
        ]
        project_root = os.environ.get("WHISPERER_PROJECT_ROOT", "")
        if project_root and os.path.basename(project_root).lower() == "_internal":
            candidates.append(os.path.join(os.path.dirname(project_root), "Whisperer.exe"))
        here_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.basename(here_root).lower() == "_internal":
            candidates.append(os.path.join(os.path.dirname(here_root), "Whisperer.exe"))
        candidates.append(os.path.join(here_root, "Whisperer.exe"))
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return os.path.abspath(candidate)
        return None

    def _apply_taskbar_identity(self):
        if os.name != "nt":
            return
        exe = self._taskbar_relaunch_exe()
        if not exe:
            return
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
        try:
            import pythoncom
            import win32com.propsys.propsys as propsys
            import win32com.propsys.pscon as pscon

            store = propsys.SHGetPropertyStoreForWindow(int(self.winId()), propsys.IID_IPropertyStore)
            text_type = pythoncom.VT_LPWSTR
            store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_USER_MODEL_ID, text_type))
            store.SetValue(pscon.PKEY_AppUserModel_RelaunchCommand, propsys.PROPVARIANTType(f'"{exe}"', text_type))
            store.SetValue(pscon.PKEY_AppUserModel_RelaunchIconResource, propsys.PROPVARIANTType(f"{exe},0", text_type))
            store.SetValue(pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, propsys.PROPVARIANTType("Whisperer", text_type))
            store.Commit()
        except Exception:
            pass

    def _enable_native_shadow(self):
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            gwl_style = -16
            ws_thickframe = 0x00040000
            ws_minimizebox = 0x00020000
            ws_maximizebox = 0x00010000
            ws_sysmenu = 0x00080000
            swp_nosize = 0x0001
            swp_nomove = 0x0002
            swp_nozorder = 0x0004
            swp_noactivate = 0x0010
            swp_framechanged = 0x0020
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            style = int(get_long(ctypes.c_void_p(hwnd), gwl_style))
            shadow_style = style | ws_thickframe | ws_minimizebox | ws_maximizebox | ws_sysmenu
            if shadow_style != style:
                set_long(ctypes.c_void_p(hwnd), gwl_style, shadow_style)
                user32.SetWindowPos(
                    ctypes.c_void_p(hwnd),
                    None,
                    0,
                    0,
                    0,
                    0,
                    swp_nomove | swp_nosize | swp_nozorder | swp_noactivate | swp_framechanged,
                )
            dwmapi = ctypes.windll.dwmapi
            policy = ctypes.c_int(2)  # DWMNCRP_ENABLED
            dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(2),  # DWMWA_NCRENDERING_POLICY
                ctypes.byref(policy),
                ctypes.sizeof(policy),
            )
            margins = _DwmMargins(1, 1, 1, 1)
            dwmapi.DwmExtendFrameIntoClientArea(ctypes.c_void_p(hwnd), ctypes.byref(margins))
            corner_preference = ctypes.c_int(2)  # DWMWCP_ROUND
            try:
                dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_uint(33),  # DWMWA_WINDOW_CORNER_PREFERENCE
                    ctypes.byref(corner_preference),
                    ctypes.sizeof(corner_preference),
                )
            except Exception:
                pass
            dark = ctypes.c_int(1)
            for attr in (20, 19):  # Newer and older DWMWA_USE_IMMERSIVE_DARK_MODE values.
                try:
                    dwmapi.DwmSetWindowAttribute(
                        ctypes.c_void_p(hwnd),
                        ctypes.c_uint(attr),
                        ctypes.byref(dark),
                        ctypes.sizeof(dark),
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def force_quit(self):
        self._force_quitting = True
        try:
            self.tray.hide()
        except Exception:
            pass
        self.stop_engine()
        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    def _frozen_engine_source_root(self) -> str | None:
        candidates = [
            os.environ.get("WHISPERER_PROJECT_ROOT", ""),
            getattr(sys, "_MEIPASS", ""),
            os.path.join(os.path.dirname(sys.executable), "_internal"),
            os.path.dirname(sys.executable),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(os.path.join(candidate, "main.py")):
                return candidate
        return None

    def _external_engine_python(self) -> str | None:
        candidates = [
            os.environ.get("WHISPERER_PYTHON"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python310", "python.exe"),
            shutil.which("python"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _start_engine_output_reader(self):
        if not self.process or not self.process.stdout:
            return

        def _reader():
            try:
                assert self.process and self.process.stdout
                for line in self.process.stdout:
                    line = line.rstrip()
                    append_log_line("engine-stdout.log", line)
                    self._engine_output_queue.put(line)
            except Exception as exc:
                append_log_line("engine-stdout.log", f"ENGINE_OUTPUT_ERROR {exc}")
                self._engine_output_queue.put(f"ENGINE_OUTPUT_ERROR {exc}")

        threading.Thread(target=_reader, daemon=True).start()

    @staticmethod
    def _is_noisy_engine_line(line: str) -> bool:
        lowered = line.lower()
        return any(part.lower() in lowered for part in NOISY_ENGINE_LINE_PARTS)

    def _check_engine_ready_file(self) -> bool:
        if (
            self._engine_state != "loading"
            or not self.process
            or self.process.poll() is not None
            or not self._engine_ready_file
            or not os.path.exists(self._engine_ready_file)
        ):
            return False
        self._log_web_ui("Engine ready file observed")
        self._set_engine_state("running")
        return True

    def _drain_engine_output(self):
        changed = False
        while True:
            try:
                line = self._engine_output_queue.get_nowait()
            except queue.Empty:
                break
            if not line:
                continue
            if line.startswith("MIC_LEVEL "):
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        self._set_mic_level(float(parts[1]), float(parts[2]))
                    except ValueError:
                        pass
                continue
            if line.startswith("BACKUP_TRANSCRIPTION_RESULT "):
                self._handle_backup_transcription_engine_result(line)
                continue
            if line.startswith("STT_BENCHMARK_RESULT "):
                self._handle_stt_benchmark_engine_result(line)
                continue
            if self._is_noisy_engine_line(line):
                continue
            changed = True
            self._engine_output_lines.append(line)
            self._engine_output_lines = self._engine_output_lines[-200:]
            print(f"[engine] {line}", flush=True)
            if line == "ENGINE_READY":
                self._set_engine_state("running")
            elif line == "DICTATION_STARTED":
                self._loading_preview_release_timer.stop()
                self._loading_preview_hide_timer.stop()
                self._loading_preview_locked = False
                if self._loading_preview_overlay.isVisible():
                    self._loading_preview_overlay.set_locked(False)
                    self._loading_preview_overlay.fade_out()

        if self._check_engine_ready_file():
            changed = True

        if self.process and self.process.poll() is not None:
            return_code = self.process.returncode
            append_log_line("engine-launch.log", f"engine process exited returnCode={return_code}")
            self.process = None
            self._set_engine_state("stopped")
            if self._backup_transcription_busy and self._backup_transcription_source == "engine":
                self._finish_last_dictation_transcription(
                    self._backup_transcription_request_id,
                    False,
                    "",
                    "The engine stopped before the last dictation could be transcribed.",
                )
            if self._stt_benchmark_busy:
                self._finish_stt_benchmark(
                    {
                        "requestId": self._stt_benchmark_request_id,
                        "ok": False,
                        "error": "The engine stopped before the STT benchmark finished.",
                        "results": [],
                    }
                )
            if (
                return_code == ENGINE_FORCE_STOP_RESTART_CODE
                and not self._paused
                and self.settings.get("startup", {}).get("auto_start_engine", True)
            ):
                self._set_engine_state("loading")
                QTimer.singleShot(350, self.start_engine)
                return
            changed = True

        # Engine stdout can be chatty during model startup. Avoid pushing full
        # dashboard snapshots for every line; state changes already notify React.

    def _handle_backup_transcription_engine_result(self, line: str):
        try:
            payload = json.loads(line.split(" ", 1)[1])
        except Exception as exc:
            self.backupTranscriptionFinished.emit(
                self._backup_transcription_request_id,
                False,
                "",
                f"Could not read engine transcription response: {exc}",
            )
            return
        request_id = str(payload.get("requestId") or "")
        ok = bool(payload.get("ok"))
        text = str(payload.get("text") or "")
        error = str(payload.get("error") or "")
        self.backupTranscriptionFinished.emit(request_id, ok, text, error)

    def _handle_stt_benchmark_engine_result(self, line: str):
        try:
            payload = json.loads(line.split(" ", 1)[1])
        except Exception as exc:
            payload = {
                "requestId": self._stt_benchmark_request_id,
                "ok": False,
                "error": f"Could not read benchmark response: {exc}",
                "results": [],
            }
        self._finish_stt_benchmark(payload)

    def closeEvent(self, event):
        if not self._force_quitting and self.tray and self.tray.isVisible():
            event.ignore()
            self.hide()
            return
        self.stop_engine()
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._enable_native_shadow)
        QTimer.singleShot(0, self._apply_taskbar_identity)
