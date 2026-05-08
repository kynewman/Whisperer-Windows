import os
import shutil
import subprocess
import sys
import traceback

from core.diagnostics import (
    append_log_line,
    configure_process_logging,
    enable_fault_logging,
    install_excepthook,
    install_qt_message_handler,
    log_path,
    log_process_snapshot,
)


_PROCESS_LOG_NAME = (
    "engine"
    if "--engine" in sys.argv
    else "file-transcriber"
    if any(arg.startswith("--file=") for arg in sys.argv[1:])
    else "launcher"
)
_LOG = configure_process_logging(_PROCESS_LOG_NAME)
enable_fault_logging(_PROCESS_LOG_NAME)
log_process_snapshot(_LOG, "launcher-entry")


def _write_startup_crash_log(text: str) -> str:
    try:
        path = log_path("launcher-crash.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path
    except Exception:
        return ""


def _show_startup_crash_message(path: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        detail = f"\n\nA crash log was written to:\n{path}" if path else ""
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Whisperer could not start.{detail}",
            "Whisperer",
            0x00000010,
        )
    except Exception:
        pass


def _show_startup_problem_message(message: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Whisperer",
            0x00000010,
        )
    except Exception:
        pass


def _handle_startup_exception(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    _LOG.error("unhandled startup exception\n%s", text)
    path = _write_startup_crash_log(text)
    _show_startup_crash_message(path)


if "--engine" not in sys.argv and not any(arg.startswith("--file=") for arg in sys.argv[1:]):
    install_excepthook(_LOG, lambda text: _show_startup_crash_message(_write_startup_crash_log(text)))


def _prefer_external_python_packages_for_installed_source() -> None:
    """
    When the frozen EXE hands the UI to system Python, app code lives in
    ``_internal`` beside partial PyInstaller package folders. Keep app code
    importable, but let real site-packages resolve third-party imports first.
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


def _external_python() -> str | None:
    candidates = [
        os.environ.get("WHISPERER_PYTHON"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python310", "python.exe"),
        shutil.which("python"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _handoff_frozen_ui_to_python() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    if os.environ.get("WHISPERER_ALLOW_FROZEN_UI_HANDOFF") != "1":
        return False
    if os.environ.get("WHISPERER_FORCE_FROZEN_UI") == "1":
        return False
    if os.environ.get("WHISPERER_FROZEN_UI_HANDOFF") == "1":
        return False
    if "--engine" in sys.argv or any(arg.startswith("--file=") for arg in sys.argv[1:]):
        return False

    source_root = os.path.join(os.path.dirname(sys.executable), "_internal")
    launcher_path = os.path.join(source_root, "launcher.py")
    python_exe = _external_python()
    if not python_exe or not os.path.exists(launcher_path):
        return False

    env = os.environ.copy()
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    env["WHISPERER_PROJECT_ROOT"] = source_root
    env["WHISPERER_FROZEN_UI_HANDOFF"] = "1"
    env["WHISPERER_LAUNCHER_EXE"] = sys.executable
    create_no_window = 0x08000000
    subprocess.Popen(
        [python_exe, "-u", launcher_path, *sys.argv[1:]],
        cwd=source_root,
        env=env,
        creationflags=create_no_window if os.name == "nt" else 0,
    )
    _LOG.info("handed off frozen UI to python=%s launcher=%s cwd=%s", python_exe, launcher_path, source_root)
    return True


if _handoff_frozen_ui_to_python():
    sys.exit(0)

if getattr(sys, "frozen", False):
    # PyTorch's CUDA DLLs live beside torch inside the PyInstaller _internal
    # folder. Register that path before any engine import touches torch.
    torch_lib = os.path.join(sys._MEIPASS, "torch", "lib")
    qt_root = os.path.join(sys._MEIPASS, "PyQt6", "Qt6")
    qt_bin = os.path.join(qt_root, "bin")
    extra_dll_dirs = [sys._MEIPASS, qt_bin, torch_lib]
    _dll_directory_handles = []
    for dll_dir in extra_dll_dirs:
        if os.path.isdir(dll_dir):
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                _dll_directory_handles.append(os.add_dll_directory(dll_dir))

    plugin_root = os.path.join(qt_root, "plugins")
    platform_plugins = os.path.join(plugin_root, "platforms")
    webengine_process = os.path.join(qt_bin, "QtWebEngineProcess.exe")
    webengine_resources = os.path.join(qt_root, "resources")
    webengine_locales = os.path.join(qt_root, "translations", "qtwebengine_locales")
    if os.path.isdir(plugin_root):
        os.environ["QT_PLUGIN_PATH"] = plugin_root
    if os.path.isdir(platform_plugins):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platform_plugins
    if os.path.exists(webengine_process):
        os.environ["QTWEBENGINEPROCESS_PATH"] = webengine_process
    if os.path.isdir(webengine_resources):
        os.environ["QTWEBENGINE_RESOURCES_PATH"] = webengine_resources
    if os.path.isdir(webengine_locales):
        os.environ["QTWEBENGINE_LOCALES_PATH"] = webengine_locales
    _LOG.info(
        "frozen paths configured meipass=%s qt_root=%s qt_plugin_path=%s webengine_process=%s exists=%s",
        getattr(sys, "_MEIPASS", ""),
        qt_root,
        os.environ.get("QT_PLUGIN_PATH", ""),
        webengine_process,
        os.path.exists(webengine_process),
    )


def _check_frozen_ui_bundle_integrity() -> bool:
    if not getattr(sys, "frozen", False):
        return True
    if "--engine" in sys.argv or any(arg.startswith("--file=") for arg in sys.argv[1:]):
        return True
    root = getattr(sys, "_MEIPASS", "")
    if not root:
        root = os.path.join(os.path.dirname(sys.executable), "_internal")
    required = [
        ("Qt platform plugin", os.path.join(root, "PyQt6", "Qt6", "plugins", "platforms", "qwindows.dll")),
        ("QtWebEngine process", os.path.join(root, "PyQt6", "Qt6", "bin", "QtWebEngineProcess.exe")),
        ("QtWebEngine resources", os.path.join(root, "PyQt6", "Qt6", "resources", "qtwebengine_resources.pak")),
        ("V8 context snapshot", os.path.join(root, "PyQt6", "Qt6", "resources", "v8_context_snapshot.bin")),
        ("QtWebEngine locale", os.path.join(root, "PyQt6", "Qt6", "translations", "qtwebengine_locales", "en-US.pak")),
        ("React dashboard", os.path.join(root, "whisperer-app", "dist", "index.html")),
    ]
    missing = [(label, path) for label, path in required if not os.path.exists(path)]
    if not missing:
        return True

    lines = [
        "Whisperer installation integrity check failed.",
        f"exe={sys.executable}",
        f"bundleRoot={root}",
        "missing=" + repr(missing),
    ]
    text = "\n".join(lines)
    _LOG.error(text)
    append_log_line("startup-integrity.log", text)
    message = (
        "Whisperer could not start because the installation appears to be incomplete or damaged.\n\n"
        "Try reinstalling the latest Whisperer setup file. If antivirus software quarantined files, "
        "restore them or allow Whisperer, then reinstall.\n\n"
        f"Diagnostic logs:\n{log_path('startup-integrity.log')}\n\n"
        "Missing files:\n"
        + "\n".join(f"- {label}: {path}" for label, path in missing[:6])
    )
    _show_startup_problem_message(message)
    return False


if "--engine" in sys.argv:
    import importlib

    args = [arg for arg in sys.argv[1:] if arg != "--engine"]
    sys.argv = [sys.argv[0], *args]
    _LOG.info("entering bundled engine mode argv=%r", sys.argv)
    try:
        main_module = importlib.import_module("main")
        model_arg = next((arg.split("=", 1)[1] for arg in args if arg.startswith("--model=")), "")
        if model_arg:
            main_module.config.WHISPER_MODEL_SIZE = model_arg
            _LOG.info("bundled engine model arg applied model=%s", model_arg)
        main_module.WhisperApp().run()
    except Exception:
        _LOG.exception("bundled engine mode failed")
        raise

def _frozen_engine_source_root() -> str | None:
    candidates = [
        getattr(sys, "_MEIPASS", ""),
        os.path.join(os.path.dirname(sys.executable), "_internal"),
        os.path.dirname(sys.executable),
        os.environ.get("WHISPERER_PROJECT_ROOT", ""),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(os.path.join(candidate, "main.py")):
            return candidate
    return None


def _external_engine_python() -> str | None:
    return _external_python()


if any(arg.startswith("--file=") for arg in sys.argv[1:]):

    file_arg = next(arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--file="))
    _LOG.info("file transcription requested file=%s frozen=%s", file_arg, bool(getattr(sys, "frozen", False)))
    try:
        if getattr(sys, "frozen", False):
            source_root = _frozen_engine_source_root()
            python_exe = _external_engine_python()
            if not source_root or not python_exe:
                raise RuntimeError("External Python engine is required for frozen file transcription.")
            env = os.environ.copy()
            env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
            result = subprocess.run(
                [python_exe, "-u", os.path.join(source_root, "main.py"), f"--file={file_arg}"],
                cwd=source_root,
                env=env,
                text=True,
            )
            sys.exit(result.returncode)
        else:
            from core.file_transcriber import transcribe_file
            result = transcribe_file(file_arg)
            print(result["final_text"], flush=True)
    except Exception:
        text = traceback.format_exc()
        _LOG.error("file transcription failed\n%s", text)
        path = _write_startup_crash_log(text)
        _show_startup_crash_message(path)
        print(text, flush=True)
        sys.exit(1)
    sys.exit(0)

if not _check_frozen_ui_bundle_integrity():
    sys.exit(1)

# QWebEngine/Chromium can crash or paint blank on some Windows DirectComposition
# paths. Keep that specific guard, but avoid the heavy all-software compositor
# path unless explicitly requested because it makes scrolling and page changes
# feel sluggish.
_raw_webengine = os.environ.get("WHISPERER_RAW_WEBENGINE") == "1"
_safe_webengine = False
_chromium_log = ""
if not _raw_webengine:
    _disabled_webengine_features = ["DCompPresenter"]
    _webengine_flags = "--disable-direct-composition"
    _safe_webengine = (
        os.environ.get("WHISPERER_SAFE_WEBENGINE") == "1"
        or (getattr(sys, "frozen", False) and os.environ.get("WHISPERER_FAST_WEBENGINE") != "1")
    )
    if _safe_webengine:
        os.environ.setdefault("QT_OPENGL", "software")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        os.environ.setdefault("QSG_RENDER_LOOP", "basic")
        if getattr(sys, "frozen", False):
            os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
        _disabled_webengine_features.extend(["UseSkiaRenderer", "VizDisplayCompositor"])
        _webengine_flags += (
            " --disable-gpu"
            " --disable-gpu-compositing"
        )
    _webengine_flags += f" --disable-features={','.join(_disabled_webengine_features)}"
    if os.environ.get("WHISPERER_VERBOSE_CHROMIUM_LOGS") == "1":
        _chromium_log = log_path("chromium.log").replace("\\", "/")
        _webengine_flags += f' --enable-logging --log-level=0 --log-file="{_chromium_log}"'
    if os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS"):
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{os.environ['QTWEBENGINE_CHROMIUM_FLAGS']} {_webengine_flags}"
    else:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _webengine_flags
_LOG.info(
    "webengine env safe=%s raw=%s qt_opengl=%s chromium_flags=%s chromium_log=%s",
    _safe_webengine,
    _raw_webengine,
    os.environ.get("QT_OPENGL", ""),
    os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
    _chromium_log,
)

from PyQt6.QtCore import Qt, QCoreApplication
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
if os.environ.get("WHISPERER_DISABLE_QT_LOG_HANDLER") != "1":
    install_qt_message_handler()
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
import PyQt6.QtWebEngineWidgets  # noqa: F401  must precede QApplication for Qt WebEngine

from core.single_instance import acquire as acquire_single_instance
from ui.app_icon import APP_USER_MODEL_ID, app_icon_path
from ui.fonts import san_francisco, san_francisco_family
from ui.main_window import MainWindow


def _show_existing_ui_window() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd_match = wintypes.HWND()
        current_pid = os.getpid()
        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @enum_proc_type
        def enum_proc(hwnd, lparam):
            if not user32.IsWindow(hwnd):
                return True
            is_match = False
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                is_match = buffer.value.startswith("Whisperer v")
            if not is_match:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value and pid.value != current_pid:
                    try:
                        import psutil

                        cmdline = " ".join(psutil.Process(pid.value).cmdline()).lower()
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


if __name__ == "__main__":
    try:
        _LOG.info("launcher main entered")
        if not acquire_single_instance("WhispererWindowsUI"):
            _LOG.info("single instance already running; attempting to show existing UI")
            _show_existing_ui_window()
            sys.exit(0)
        if os.name == "nt":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
            except Exception:
                pass
        app = QApplication(sys.argv)
        _LOG.info("QApplication created")
        append_log_line("web-ui.log", f"launcher created QApplication pid={os.getpid()} frozen={bool(getattr(sys, 'frozen', False))}")
        icon = QIcon(app_icon_path())
        app.setWindowIcon(icon)
        app.setQuitOnLastWindowClosed(False)
        app.setFont(san_francisco(10))
        app.setStyleSheet(f"* {{ font-family: '{san_francisco_family()}'; }}")
        window = MainWindow()
        _LOG.info("MainWindow created")
        window.setWindowIcon(icon)
        window.show()
        _LOG.info("MainWindow shown; entering app event loop")
        sys.exit(app.exec())
    except Exception:
        text = traceback.format_exc()
        print(text, flush=True)
        _LOG.error("launcher main failed\n%s", text)
        path = _write_startup_crash_log(text)
        _show_startup_crash_message(path)
        sys.exit(1)
