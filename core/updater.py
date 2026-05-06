from __future__ import annotations

import json
import os
import re
import hashlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import config


GITHUB_OWNER = "kynewman"
GITHUB_REPO = "Whisperer-Windows"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
INSTALLER_NAME_RE = re.compile(r"^Whisperer-Setup-(\d+\.\d+\.\d+(?:\.\d+)?)\.exe$", re.IGNORECASE)
ALLOW_UNSIGNED_UPDATE_ENV = "WHISPERER_ALLOW_UNSIGNED_UPDATE_INSTALLER"


@dataclass
class ReleaseAsset:
    name: str
    url: str
    size: int = 0


@dataclass
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
    candidates: list[ReleaseAsset] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        download_url = str(asset.get("browser_download_url") or "")
        if not name or not download_url:
            continue
        lower = name.lower()
        match = INSTALLER_NAME_RE.match(name)
        if not match:
            continue
        score = 0
        if "setup" in lower or "installer" in lower:
            score += 5
        if "whisperer" in lower:
            score += 2
        if "windows" in lower or "win" in lower:
            score += 1
        candidates.append(ReleaseAsset(name=name, url=download_url, size=int(asset.get("size") or 0)))
        candidates[-1]._score = score  # type: ignore[attr-defined]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: getattr(item, "_score", 0), reverse=True)[0]


def _installer_version(name: str) -> str:
    match = INSTALLER_NAME_RE.match(name)
    return match.group(1) if match else ""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().upper()


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
                "$sig = Get-AuthenticodeSignature -LiteralPath $args[0]; "
                "Write-Output $sig.Status",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=0x08000000,
        )
        status = (completed.stdout or "").strip().splitlines()
        return status[-1].strip() if status else "Unknown"
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


def download_and_launch_update() -> dict[str, Any]:
    check = check_for_update()
    if not check.ok:
        return check.to_dict()
    if not check.update_available:
        payload = check.to_dict()
        payload["ok"] = False
        payload["error"] = "Whisperer is already up to date."
        return payload
    if not check.asset:
        payload = check.to_dict()
        payload["ok"] = False
        payload["error"] = "The latest release does not include a Windows installer asset."
        return payload

    target_dir = os.path.join(tempfile.gettempdir(), "WhispererUpdates")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, check.asset.name)
    req = urllib.request.Request(check.asset.url, headers={"User-Agent": f"Whisperer/{config.VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(target, "wb") as handle:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
    except Exception as exc:
        payload = check.to_dict()
        payload["ok"] = False
        payload["error"] = f"Could not download the update: {exc}"
        return payload

    downloaded_hash = _sha256(target)
    signature_status = _authenticode_status(target)
    if signature_status != "Valid" and os.environ.get(ALLOW_UNSIGNED_UPDATE_ENV) != "1":
        try:
            os.remove(target)
        except OSError:
            pass
        payload = check.to_dict()
        payload["ok"] = False
        payload["sha256"] = downloaded_hash
        payload["signatureStatus"] = signature_status
        payload["error"] = (
            "The downloaded installer is not signed by a trusted publisher. "
            "Open the GitHub release manually, or install a signed release."
        )
        return payload

    try:
        setup_log = os.path.join(tempfile.gettempdir(), "WhispererUpdates", "installer-update.log")
        subprocess.Popen([target, f"/LOG={setup_log}"], cwd=os.path.dirname(target), close_fds=True)
    except Exception as exc:
        payload = check.to_dict()
        payload["ok"] = False
        payload["error"] = f"Could not launch the installer: {exc}"
        return payload

    payload = check.to_dict()
    payload["ok"] = True
    payload["installerPath"] = target
    payload["sha256"] = downloaded_hash
    payload["signatureStatus"] = signature_status
    payload["shouldCloseApp"] = True
    payload["pythonExecutable"] = sys.executable
    return payload
