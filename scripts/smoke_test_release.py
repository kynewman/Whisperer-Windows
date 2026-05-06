"""Offline release smoke checks for the packaged Whisperer installer build."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = PROJECT_ROOT / "dist"
BUNDLE_ROOT = DIST_ROOT / "Whisperer"
INTERNAL = BUNDLE_ROOT / "_internal"


def release_version() -> str:
    try:
        text = (PROJECT_ROOT / "config.py").read_text(encoding="utf-8")
        match = re.search(r"^VERSION\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "0.0.0"


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    print(f"{status} - {label}: {detail}")
    return ok


def file_exists(label: str, path: Path) -> bool:
    return check(label, path.exists(), str(path))


def has_no_remote_assets() -> bool:
    asset_patterns = [
        re.compile(r"<script[^>]+src=[\"']https?://", re.IGNORECASE),
        re.compile(r"<link[^>]+href=[\"']https?://", re.IGNORECASE),
        re.compile(r"@import\s+url\([\"']?https?://", re.IGNORECASE),
    ]
    roots = [
        INTERNAL / "whisperer-app" / "dist",
        PROJECT_ROOT / "whisperer-app" / "dist",
    ]
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".html", ".js", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(pattern.search(text) for pattern in asset_patterns):
                offenders.append(str(path))
    return check("frontend has no remote asset URLs", not offenders, ", ".join(offenders[:3]))


def has_no_model_weights() -> bool:
    forbidden = {".pt", ".pth", ".safetensors", ".ckpt", ".onnx"}
    offenders = [path for path in INTERNAL.rglob("*") if path.suffix.lower() in forbidden]
    return check("bundle excludes local model weights", not offenders, ", ".join(str(p) for p in offenders[:3]))


def has_no_debug_qt_payload() -> bool:
    offenders: list[Path] = []
    qml_root = INTERNAL / "PyQt6" / "Qt6" / "qml"
    if qml_root.exists():
        offenders.append(qml_root)
    resource_root = INTERNAL / "PyQt6" / "Qt6" / "resources"
    if resource_root.exists():
        for path in resource_root.iterdir():
            name = path.name.lower()
            if name.startswith("qtwebengine_devtools_resources") or name.endswith((".debug.pak", ".debug.bin")):
                offenders.append(path)
    return check("bundle excludes Qt debug/devtools/QML payload", not offenders, ", ".join(str(p) for p in offenders[:3]))


def installer_has_upgrade_cleanup() -> bool:
    installer_script = PROJECT_ROOT / "installer.iss"
    try:
        text = installer_script.read_text(encoding="utf-8", errors="replace").lower()
    except Exception as exc:
        return check("installer upgrade cleanup rules", False, f"could not read installer.iss: {exc}")
    required = [
        "[installdelete]",
        "qtwebengine_devtools_resources",
        "*.debug.pak",
        "pyqt6\\qt6\\qml",
        "whisperer-app\\dist\\assets\\*.js",
        "setupmutex=whispererwindowsinstaller",
        "deinitializesetup",
        "installer-latest.log",
    ]
    missing = [item for item in required if item not in text]
    return check("installer upgrade cleanup rules", not missing, ", ".join(missing))


def authenticode_status(path: Path) -> str:
    if os.name != "nt" or not path.exists():
        return "Unavailable"
    escaped_path = str(path).replace("'", "''")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"(Get-AuthenticodeSignature -LiteralPath '{escaped_path}').Status",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        return (result.stdout or result.stderr or "").strip() or "Unknown"
    except Exception as exc:
        return f"Error: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-signed", action="store_true", help="Fail if the installer or exe is not signed.")
    args = parser.parse_args(argv)

    version = release_version()
    installer = DIST_ROOT / f"Whisperer-Setup-{version}.exe"
    exe = BUNDLE_ROOT / "Whisperer.exe"
    ok = True

    ok &= file_exists("packaged exe", exe)
    ok &= file_exists("installer", installer)
    ok &= file_exists("React entrypoint", INTERNAL / "whisperer-app" / "dist" / "index.html")
    ok &= file_exists("React JS asset", INTERNAL / "whisperer-app" / "dist" / "assets" / "index.js")
    ok &= file_exists("React CSS asset", INTERNAL / "whisperer-app" / "dist" / "assets" / "index.css")
    ok &= file_exists("QtWebEngineProcess", INTERNAL / "PyQt6" / "Qt6" / "bin" / "QtWebEngineProcess.exe")
    ok &= file_exists("QtWebEngine resources", INTERNAL / "PyQt6" / "Qt6" / "resources" / "qtwebengine_resources.pak")
    ok &= file_exists("QtWebEngine locales", INTERNAL / "PyQt6" / "Qt6" / "translations" / "qtwebengine_locales")
    ok &= file_exists("V8 context snapshot", INTERNAL / "PyQt6" / "Qt6" / "resources" / "v8_context_snapshot.bin")
    ok &= file_exists("Python runtime", INTERNAL / "python310.dll")
    ok &= file_exists("VC runtime", INTERNAL / "VCRUNTIME140.dll")
    ok &= has_no_remote_assets()
    ok &= has_no_model_weights()
    ok &= has_no_debug_qt_payload()
    ok &= installer_has_upgrade_cleanup()

    installer_sig = authenticode_status(installer)
    exe_sig = authenticode_status(exe)
    signed_ok = installer_sig == "Valid" and exe_sig == "Valid"
    ok &= check("Authenticode signatures", signed_ok or not args.require_signed, f"installer={installer_sig} exe={exe_sig}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
