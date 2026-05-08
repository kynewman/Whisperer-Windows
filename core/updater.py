"""GitHub release update checking and installer launch helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config


GITHUB_OWNER = "kynewman"
GITHUB_REPO = "Whisperer-Windows"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
INSTALLER_NAME_RE = re.compile(r"^Whisperer-Setup-(\d+\.\d+\.\d+(?:\.\d+)?)\.exe$", re.IGNORECASE)
ALLOW_UNSIGNED_UPDATE_ENV = "WHISPERER_ALLOW_UNSIGNED_UPDATE_INSTALLER"
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class ReleaseAsset:
    name: str
    url: str
    size: int = 0


@dataclass(slots=True)
class UpdateCheck:
    ok: bool
    current_version: str
    latest_version: str = ""
    update_available: bool = False
    release_name: str = ""
    release_url: str = GITHUB_RELEASES_URL
    published_at: str = ""
    body: str = ""
    asset: ReleaseAsset | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "currentVersion": self.current_version,
            "latestVersion": self.latest_version,
            "updateAvailable": self.update_available,
            "releaseName": self.release_name,
            "releaseUrl": self.release_url,
            "publishedAt": self.published_at,
            "body": self.body,
            "error": self.error,
        }
        if self.asset:
            payload["asset"] = {"name": self.asset.name, "size": self.asset.size}
        return payload


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(part) for part in parts[:4]) or (0,)


def _is_newer(latest: str, current: str) -> bool:
    latest_parts = _version_tuple(latest)
    current_parts = _version_tuple(current)
    width = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (width - len(latest_parts)) > current_parts + (0,) * (width - len(current_parts))


def _request_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Whisperer/{config.VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=18) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _select_windows_installer(assets: list[dict[str, Any]]) -> ReleaseAsset | None:
    candidates: list[tuple[int, ReleaseAsset]] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not name or not url or not INSTALLER_NAME_RE.match(name):
            continue
        lower = name.lower()
        score = int("setup" in lower or "installer" in lower) * 5 + int("whisperer" in lower) * 2 + int("windows" in lower or "win" in lower)
        candidates.append((score, ReleaseAsset(name=name, url=url, size=int(asset.get("size") or 0))))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _installer_version(name: str) -> str:
    match = INSTALLER_NAME_RE.match(name)
    return match.group(1) if match else ""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _powershell_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _authenticode_status(path: str) -> str:
    if os.name != "nt":
        return "Unavailable"
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"$sig = Get-AuthenticodeSignature -LiteralPath {_powershell_single_quote(path)}; Write-Output ([string]$sig.Status)",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=0x08000000,
        )
        lines = (completed.stdout or "").strip().splitlines()
        return lines[-1].strip() if lines else "Unknown"
    except Exception:
        return "Unknown"


def check_for_update() -> UpdateCheck:
    current = config.VERSION
    try:
        release = _request_json(GITHUB_RELEASES_API)
    except urllib.error.HTTPError as exc:
        return UpdateCheck(ok=False, current_version=current, error=f"GitHub returned HTTP {exc.code}.")
    except Exception as exc:
        return UpdateCheck(ok=False, current_version=current, error=f"Could not check GitHub releases: {exc}")

    latest = str(release.get("tag_name") or release.get("name") or "")
    asset = _select_windows_installer(release.get("assets") if isinstance(release.get("assets"), list) else [])
    if asset:
        latest_numbers = ".".join(str(part) for part in _version_tuple(latest)[:3])
        asset_numbers = ".".join(str(part) for part in _version_tuple(_installer_version(asset.name))[:3])
        if latest_numbers and asset_numbers and latest_numbers != asset_numbers:
            asset = None
    return UpdateCheck(
        ok=True,
        current_version=current,
        latest_version=latest,
        update_available=_is_newer(latest, current),
        release_name=str(release.get("name") or latest),
        release_url=str(release.get("html_url") or GITHUB_RELEASES_URL),
        published_at=str(release.get("published_at") or ""),
        body=str(release.get("body") or "")[:1800],
        asset=asset,
    )


def _emit(progress_callback: ProgressCallback | None, **payload: Any) -> None:
    if progress_callback:
        try:
            progress_callback(payload)
        except Exception:
            pass


def _update_target_dir() -> str:
    path = Path(tempfile.gettempdir()) / "WhispererUpdates"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _validate_downloaded_installer_path(path: str) -> str:
    target_dir = Path(_update_target_dir()).resolve()
    candidate = Path(path).resolve()
    if candidate.parent != target_dir:
        raise ValueError("Installer path is outside the update download folder.")
    if not INSTALLER_NAME_RE.match(candidate.name):
        raise ValueError("Installer file name does not look like a Whisperer setup package.")
    if not candidate.exists():
        raise FileNotFoundError(str(candidate))
    return str(candidate)


def _launch_installer(target: str, check: UpdateCheck | None = None, *, allow_unsigned: bool = False) -> dict[str, Any]:
    target = _validate_downloaded_installer_path(target)
    downloaded_hash = _sha256(target)
    signature_status = _authenticode_status(target)
    if signature_status != "Valid" and not allow_unsigned and os.environ.get(ALLOW_UNSIGNED_UPDATE_ENV) != "1":
        payload = check.to_dict() if check else {"ok": False, "currentVersion": config.VERSION}
        payload.update(
            {
                "ok": False,
                "sha256": downloaded_hash,
                "signatureStatus": signature_status,
                "installerPath": target,
                "unsignedBlocked": True,
                "error": "The downloaded installer is not signed by a trusted publisher. Install it anyway?",
            }
        )
        return payload
    try:
        setup_log = os.path.join(_update_target_dir(), "installer-update.log")
        subprocess.Popen([target, f"/LOG={setup_log}"], cwd=os.path.dirname(target), close_fds=True)
    except Exception as exc:
        payload = check.to_dict() if check else {"ok": False, "currentVersion": config.VERSION}
        payload["ok"] = False
        payload["error"] = f"Could not launch the installer: {exc}"
        return payload
    payload = check.to_dict() if check else {"currentVersion": config.VERSION}
    payload.update(
        {
            "ok": True,
            "installerPath": target,
            "sha256": downloaded_hash,
            "signatureStatus": signature_status,
            "shouldCloseApp": True,
            "pythonExecutable": sys.executable,
        }
    )
    return payload


def launch_downloaded_update(installer_path: str, *, allow_unsigned: bool = False) -> dict[str, Any]:
    return _launch_installer(installer_path, allow_unsigned=allow_unsigned)


def download_and_launch_update(progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    _emit(progress_callback, phase="checking", percent=0, message="Checking GitHub releases...")
    check = check_for_update()
    if not check.ok:
        _emit(progress_callback, phase="error", percent=0, message=check.error)
        return check.to_dict()
    if not check.update_available:
        payload = check.to_dict()
        payload.update({"ok": False, "error": "Whisperer is already up to date."})
        _emit(progress_callback, phase="error", percent=0, message=payload["error"])
        return payload
    if not check.asset:
        payload = check.to_dict()
        payload.update({"ok": False, "error": "The latest release does not include a Windows installer asset."})
        _emit(progress_callback, phase="error", percent=0, message=payload["error"])
        return payload

    target = os.path.join(_update_target_dir(), check.asset.name)
    req = urllib.request.Request(check.asset.url, headers={"User-Agent": f"Whisperer/{config.VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(target, "wb") as handle:
            total = int(resp.headers.get("Content-Length") or check.asset.size or 0)
            downloaded = 0
            _emit(progress_callback, phase="downloading", percent=1, downloadedBytes=0, totalBytes=total, message=f"Downloading {check.asset.name}...")
            while chunk := resp.read(1024 * 256):
                handle.write(chunk)
                downloaded += len(chunk)
                percent = int(downloaded * 100 / total) if total > 0 else 0
                _emit(
                    progress_callback,
                    phase="downloading",
                    percent=max(1, min(99, percent)) if total > 0 else 0,
                    downloadedBytes=downloaded,
                    totalBytes=total,
                    message="Downloading update...",
                )
    except Exception as exc:
        payload = check.to_dict()
        payload.update({"ok": False, "error": f"Could not download the update: {exc}"})
        _emit(progress_callback, phase="error", percent=0, message=payload["error"])
        return payload

    _emit(progress_callback, phase="verifying", percent=100, message="Verifying installer...")
    payload = _launch_installer(target, check, allow_unsigned=False)
    if payload.get("unsignedBlocked"):
        _emit(progress_callback, phase="unsignedBlocked", percent=100, message=payload.get("error", ""), payload=payload)
    elif payload.get("ok"):
        _emit(progress_callback, phase="installing", percent=100, message="Installer launched.", payload=payload)
    else:
        _emit(progress_callback, phase="error", percent=100, message=payload.get("error", "Could not install update."), payload=payload)
    return payload
