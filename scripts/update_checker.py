"""Check for Whisperer updates from GitHub releases."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import NamedTuple

import config


GITHUB_RELEASES_API = "https://api.github.com/repos/kynewman/Whisperer-Windows/releases/latest"
GITHUB_RELEASES_URL = "https://github.com/kynewman/Whisperer-Windows/releases"


class UpdateInfo(NamedTuple):
    available: bool
    current_version: str
    latest_version: str
    release_url: str
    release_notes: str


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '1.2.7' into (1, 2, 7)."""
    # Strip leading 'v' if present
    v = v.lstrip("v")
    parts = []
    for part in v.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_update(timeout_s: float = 5.0) -> UpdateInfo:
    """
    Query GitHub releases for a newer version.
    Returns UpdateInfo with available=True if a newer version exists.
    """
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": f"Whisperer/{config.VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        return UpdateInfo(
            available=False,
            current_version=config.VERSION,
            latest_version="unknown",
            release_url=GITHUB_RELEASES_URL,
            release_notes=f"Could not check for updates: {exc}",
        )

    latest_tag = data.get("tag_name", "")
    latest_version = latest_tag.lstrip("v")
    release_notes = data.get("body", "")[:500]
    html_url = data.get("html_url", GITHUB_RELEASES_URL)

    current = _parse_version(config.VERSION)
    latest = _parse_version(latest_version)

    return UpdateInfo(
        available=latest > current,
        current_version=config.VERSION,
        latest_version=latest_version,
        release_url=html_url,
        release_notes=release_notes,
    )
