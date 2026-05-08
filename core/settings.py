"""Persistent application settings."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping

from core.diagnostics import append_log_line
from core.paths import get_app_data_dir


DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "startup": {
        "auto_start_engine": True,
        "launch_on_login": False,
        "default_model": "nvidia/parakeet-tdt-0.6b-v2",
        "gpu_device": "nvidia_api",
    },
    "dictation": {
        "restore_clipboard_after_paste": False,
        "vocabulary_prompt_limit": 80,
        "double_tap_lock_enabled": True,
        "double_tap_lock_window_ms": 320,
        "double_tap_lock_max_first_press_ms": 500,
    },
    "performance": {
        "engine_preload": "app_start",
        "warm_microphone_stream": True,
        "context_mode": "fast",
        "paste_delay_ms": 30,
        "paste_delay_overrides": {},
        "paste_fast_path_enabled": True,
        "paste_fast_delay_ms": 12,
        "paste_fast_apps": [
            "Codex",
            "TextEdit",
            "Notes",
            "Safari",
            "Chrome",
            "Arc",
            "Notion",
            "Slack",
            "Cursor",
            "Code",
            "Xcode",
            "Pages",
        ],
        "streaming_adaptive_finalize_enabled": True,
        "streaming_finalize_wait_ms": 450,
        "streaming_fast_finalize_wait_ms": 220,
        "streaming_parallel_final_min_ms": 2500,
        "streaming_audio_chunk_ms": 32,
        "silence_trim_enabled": True,
    },
    "audio": {
        "ducking_enabled": False,
        "ducking_percent": 75,
        "input_device": None,
        "input_device_name": None,
        "input_channel": 0,
        "input_channel_auto": True,
    },
    "sound": {
        "playback_when_recording": "lower",
        "effects_enabled": True,
        "effects_volume": 80,
        "auto_gain": True,
        "silence_removal": False,
        "dynamic_normalization": False,
    },
    "ui": {
        "theme": "sun",
        "accent": "moss",
        "density": "comfortable",
    },
    "overlay": {
        "position": None,
        "visualizer_style": "waveform",
    },
    "recording_window": {
        "style": "mini",
        "always_show_mini": True,
        "always_close": True,
    },
    "history": {
        "keep_recordings_for": "forever",
    },
    "privacy": {
        "store_audio_history": False,
        "retain_history": True,
        "capture_ocr_context": True,
    },
    "llm": {
        "ollama_url": "http://localhost:11434",
        "openai_compat_url": "http://localhost:8000",
    },
    "shortcuts": {
        "dictation": "ctrl+left windows",
        "toggle_recording": None,
        "cancel": "escape",
        "mode_next": "ctrl+alt+right",
        "mode_prev": "ctrl+alt+left",
        "open_history": None,
        "repeat_last": None,
        "push_to_talk": None,
        "mouse_shortcut": None,
    },
    "paste": {
        "method": "clipboard_paste",
        "restore_clipboard": False,
        "auto_send_enter": False,
        "smart_spacing_enabled": True,
        "smart_spacing_timeout_ms": 35,
        "smart_spacing_clipboard_probe_enabled": True,
        "per_app_overrides": {},
    },
    "onboarding": {
        "complete": True,
    },
}


_SAVE_LOCK = threading.RLock()


def get_settings_path() -> str:
    return str(Path(get_app_data_dir()) / "settings.json")


def _merge_defaults(value: Mapping[str, Any], defaults: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(dict(defaults))
    for key, item in value.items():
        existing = merged.get(key)
        if isinstance(item, Mapping) and isinstance(existing, Mapping):
            merged[key] = _merge_defaults(item, existing)
        else:
            merged[key] = copy.deepcopy(item)
    return merged


def load_settings() -> dict[str, Any]:
    path = Path(get_settings_path())
    if not path.exists():
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        save_settings(settings)
        return settings

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        append_log_line("settings.log", f"settings load fallback path={str(path)!r} error={exc!r}")
        return copy.deepcopy(DEFAULT_SETTINGS)

    if not isinstance(loaded, dict):
        append_log_line("settings.log", f"settings load fallback path={str(path)!r} error='root is not an object'")
        return copy.deepcopy(DEFAULT_SETTINGS)
    return _merge_defaults(loaded, DEFAULT_SETTINGS)


def save_settings(settings: dict[str, Any]) -> None:
    path = Path(get_settings_path())
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with _SAVE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp_path, path)
        except OSError as exc:
            append_log_line("settings.log", f"settings save failed path={str(path)!r} error={exc!r}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
