# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Whisperer.
Builds a one-directory bundle for faster startup and easier updates.

Usage:
    pyinstaller --noconfirm whisperer.spec

Output:
    dist/Whisperer/Whisperer.exe
"""

import os
import sys

import PyQt6

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(".")
PYQT6_QT6_ROOT = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6")


def collect_source_tree(dirname):
    entries = []
    source_root = os.path.join(PROJECT_ROOT, dirname)
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        dest = os.path.relpath(dirpath, PROJECT_ROOT)
        for filename in filenames:
            if filename.endswith((".pyc", ".pyo")):
                continue
            entries.append((os.path.join(dirpath, filename), dest))
    return entries


def collect_file_tree(source_root, dest_root):
    entries = []
    if not os.path.isdir(source_root):
        return entries
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        dest = os.path.join(dest_root, os.path.relpath(dirpath, source_root))
        if dest.endswith(os.curdir):
            dest = dest_root
        for filename in filenames:
            if filename.endswith((".pyc", ".pyo")):
                continue
            entries.append((os.path.join(dirpath, filename), dest))
    return entries


SOURCE_DATAS = [
    (os.path.join(PROJECT_ROOT, "main.py"), "."),
    (os.path.join(PROJECT_ROOT, "config.py"), "."),
    (os.path.join(PROJECT_ROOT, "launcher.py"), "."),
]
for source_dir in ("core", "ui", "rules", "scripts"):
    SOURCE_DATAS.extend(collect_source_tree(source_dir))
SOURCE_DATAS.extend(collect_source_tree("assets"))
SOURCE_DATAS.extend(collect_source_tree(os.path.join("whisperer-app", "dist")))

APP_ICON = os.path.join(PROJECT_ROOT, "assets", "whisperer.ico")
QT_BIN_DEST = os.path.join("PyQt6", "Qt6", "bin")
QT_BINARIES = []
for qt_binary in (
    # Qt WebEngine uses these DLLs dynamically, but PyInstaller 6.19 does not
    # collect all of them from the PyQt6 6.10 wheels.
    "avcodec-61.dll",
    "avformat-61.dll",
    "avutil-59.dll",
    "concrt140.dll",
    "d3dcompiler_47.dll",
    "Qt6OpenGLWidgets.dll",
    "Qt6QmlModels.dll",
    "Qt6SvgWidgets.dll",
    "swresample-5.dll",
    "swscale-8.dll",
):
    qt_binary_path = os.path.join(PYQT6_QT6_ROOT, "bin", qt_binary)
    if os.path.exists(qt_binary_path):
        QT_BINARIES.append((qt_binary_path, QT_BIN_DEST))

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
block_cipher = None

a = Analysis(
    [os.path.join(PROJECT_ROOT, "launcher.py")],
    pathex=[PROJECT_ROOT],
    binaries=QT_BINARIES,
    datas=SOURCE_DATAS,
    hiddenimports=[
        # Core modules that may be imported dynamically
        "core.dictionary",
        "core.context",
        "core.modes",
        "core.history",
        "core.settings",
        "core.paths",
        "core.dictation_backup",
        "core.migrations",
        "core.secrets",
        "core.perf",
        "core.single_instance",
        "ui.tray",
        "ui.main_window",
        "ui.fonts",
        "scripts.diagnostics",
        # Third-party packages with dynamic imports
        "PyQt6",
        "PyQt6.sip",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtNetwork",
        "PyQt6.QtOpenGL",
        "PyQt6.QtPositioning",
        "PyQt6.QtPrintSupport",
        "PyQt6.QtWidgets",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "keyboard",
        "sounddevice",
        "numpy",
        "PIL",
        "PIL._imagingtk",
        "PIL._tkinter_finder",
        "pytesseract",
        "mss",
        "pyperclip",
        "keyring",
        "keyring.backends.Windows",
        "colorama",
        "riva",
        "riva.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude large model files — they are downloaded at runtime
        "models",
        # Exclude test frameworks and dev tools
        "pytest",
        "unittest",
        "pdb",
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "sklearn",
        # The frozen app is now the lightweight UI shell. Local STT runs through
        # the external Python engine, so do not bundle ML runtimes into the UI EXE.
        "torch",
        "torch._C",
        "nemo",
        "nemo_toolkit",
        "pytorch_lightning",
        "lightning",
        "lightning_fabric",
        "torchmetrics",
        "bitsandbytes",
        "llvmlite",
        "numba",
        "librosa",
        "soundfile",
        "transformers",
        "accelerate",
        "peft",
        "safetensors",
        "tokenizers",
        "sentencepiece",
        "huggingface_hub",
        "hf_xet",
        "h5py",
        "av",
        "cuda",
        "cuda.bindings",
        "pyannote",
        "lhotse",
        "webdataset",
        "kaldialign",
        "jiwer",
        "pycocotools",
        "gdown",
        "fastapi",
        "uvicorn",
        "aiohttp",
        "httpx",
        "faster_whisper",
        "ctranslate2",
        "pyqtgraph",
        # Optional ML/export/training/web stacks pulled in by torch, transformers,
        # and NeMo hooks. Whisperer does not use these at runtime, and ONNX
        # reference imports can crash PyInstaller's isolated dependency scanner.
        "onnx",
        "onnx.reference",
        "onnxruntime",
        "torchvision",
        "torchvision.io",
        "torchvision.datasets",
        "torchaudio",
        "plotly",
        "gradio",
        "wandb",
        "tensorboard",
        "IPython",
        "ipywidgets",
        "notebook",
        "jupyter",
        "altair",
        "datasets",
        "diffusers",
        "optuna",
        "cv2",
        "pyarrow",
        "polars",
        "sqlalchemy",
        "alembic",
        # Exclude unnecessary PyQt6 modules
        "PyQt6.QtSql",
        "PyQt6.QtTest",
        "PyQt6.QtXml",
        "PyQt6.QtMultimedia",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ---------------------------------------------------------------------------
# Remove any accidentally-collected model files
# ---------------------------------------------------------------------------
MODEL_EXCLUDES = [".cache", "whisper-large", "faster-whisper"]
BUNDLE_PACKAGE_EXCLUDES = {
    "accelerate",
    "ctranslate2",
    "faster_whisper",
    "huggingface_hub",
    "lightning",
    "lightning_fabric",
    "nemo",
    "nemo_toolkit",
    "safetensors",
    "sentencepiece",
    "tokenizers",
    "torch",
    "torchaudio",
    "torchmetrics",
    "torchvision",
    "transformers",
}


def is_excluded_bundle_package(dest: str) -> bool:
    normalized = dest.replace("\\", "/").lower().lstrip("./")
    first = normalized.split("/", 1)[0]
    return first in BUNDLE_PACKAGE_EXCLUDES


def is_required_qt_resource(dest: str) -> bool:
    normalized = dest.replace("\\", "/").lower().lstrip("./")
    return (
        normalized.startswith("pyqt6/qt6/resources/")
        and os.path.basename(normalized) in {"v8_context_snapshot.bin", "v8_context_snapshot.debug.bin"}
    )

def exclude_large_files(binaries, datas):
    """Filter out model weights and cache files from the bundle."""
    filtered_binaries = []
    for dest, src, typecode in binaries:
        lower = dest.lower()
        if is_required_qt_resource(dest):
            filtered_binaries.append((dest, src, typecode))
            continue
        if is_excluded_bundle_package(dest):
            continue
        if any(exc in lower for exc in MODEL_EXCLUDES):
            continue
        if lower.endswith((".bin", ".pt", ".pth", ".safetensors", ".ckpt", ".onnx")):
            continue
        filtered_binaries.append((dest, src, typecode))

    filtered_datas = []
    for dest, src, typecode in datas:
        lower = dest.lower()
        if is_required_qt_resource(dest):
            filtered_datas.append((dest, src, typecode))
            continue
        if is_excluded_bundle_package(dest):
            continue
        if any(exc in lower for exc in MODEL_EXCLUDES):
            continue
        if lower.endswith((".bin", ".pt", ".pth", ".safetensors", ".ckpt", ".onnx")):
            continue
        filtered_datas.append((dest, src, typecode))

    return filtered_binaries, filtered_datas

a.binaries, a.datas = exclude_large_files(a.binaries, a.datas)

# ---------------------------------------------------------------------------
# PYZ / EXE / COLLECT (one-directory build)
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Whisperer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window for GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON if os.path.exists(APP_ICON) else None,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Whisperer",
)
