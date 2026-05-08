"""Rolling last-dictation audio backup."""

from __future__ import annotations

import json
import os
import time
import wave
from pathlib import Path

import numpy as np

import config
from core.paths import get_app_data_dir


BACKUP_DIR_NAME = "cache"
RAW_FILENAME = "last-dictation.raw"
WAV_FILENAME = "last-dictation.wav"
MANIFEST_FILENAME = "last-dictation.json"
PCM_SAMPLE_WIDTH = 2
PCM_DTYPE = np.dtype("<i2")


def get_backup_dir() -> str:
    path = Path(get_app_data_dir()) / BACKUP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_last_dictation_raw_path() -> str:
    return str(Path(get_backup_dir()) / RAW_FILENAME)


def get_last_dictation_wav_path() -> str:
    return str(Path(get_backup_dir()) / WAV_FILENAME)


def get_last_dictation_manifest_path() -> str:
    return str(Path(get_backup_dir()) / MANIFEST_FILENAME)


def _sample_rate() -> int:
    return int(config.AUDIO_SAMPLE_RATE)


def float32_to_pcm16_bytes(samples: np.ndarray) -> bytes:
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return b""
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(PCM_DTYPE, copy=False).tobytes()


def reset_last_dictation_backup() -> str:
    raw_path = Path(get_last_dictation_raw_path())
    for path in (raw_path, Path(get_last_dictation_wav_path()), Path(get_last_dictation_manifest_path())):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    manifest = {
        "sampleRate": _sample_rate(),
        "channels": 1,
        "sampleWidth": PCM_SAMPLE_WIDTH,
        "startedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        Path(get_last_dictation_manifest_path()).write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass
    return str(raw_path)


def finalize_last_dictation_wav() -> str:
    raw_path = Path(get_last_dictation_raw_path())
    wav_path = Path(get_last_dictation_wav_path())
    try:
        if not raw_path.exists() or raw_path.stat().st_size <= 0:
            return str(wav_path) if wav_path.exists() else ""
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(PCM_SAMPLE_WIDTH)
            wf.setframerate(_sample_rate())
            with raw_path.open("rb") as raw_file:
                while chunk := raw_file.read(1024 * 1024):
                    wf.writeframes(chunk)
        return str(wav_path)
    except Exception:
        return str(wav_path) if wav_path.exists() else ""


def _resample_if_needed(audio: np.ndarray, source_rate: int) -> np.ndarray:
    target_rate = _sample_rate()
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if source_rate == target_rate or audio.size == 0:
        return audio
    target_len = max(1, int(round(audio.size * target_rate / source_rate)))
    source_x = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    target_x = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
    return np.interp(target_x, source_x, audio).astype(np.float32)


def _load_raw_audio(path: str) -> np.ndarray:
    data = Path(path).read_bytes()
    usable = len(data) - (len(data) % PCM_SAMPLE_WIDTH)
    if usable <= 0:
        raise FileNotFoundError("No last dictation audio has been captured yet.")
    pcm = np.frombuffer(data[:usable], dtype=PCM_DTYPE)
    return (pcm.astype(np.float32) / 32768.0).astype(np.float32, copy=False)


def _load_wav_audio(path: str) -> np.ndarray:
    with wave.open(path, "rb") as wf:
        channels = max(1, int(wf.getnchannels()))
        rate = int(wf.getframerate())
        width = int(wf.getsampwidth())
        frames = wf.readframes(wf.getnframes())
    if not frames:
        raise FileNotFoundError("No last dictation audio has been captured yet.")
    if width == 2:
        audio = np.frombuffer(frames, dtype=PCM_DTYPE).astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError("Unsupported last dictation backup format.")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return _resample_if_needed(audio.astype(np.float32, copy=False), rate)


def load_last_dictation_audio() -> np.ndarray:
    raw_path = Path(get_last_dictation_raw_path())
    if raw_path.exists() and raw_path.stat().st_size > 0:
        return _load_raw_audio(str(raw_path))
    wav_path = Path(get_last_dictation_wav_path())
    if wav_path.exists() and wav_path.stat().st_size > 44:
        return _load_wav_audio(str(wav_path))
    raise FileNotFoundError("No last dictation audio has been captured yet.")


def last_dictation_backup_metadata() -> dict:
    raw_path = Path(get_last_dictation_raw_path())
    wav_path = Path(get_last_dictation_wav_path())
    raw_size = raw_path.stat().st_size if raw_path.exists() else 0
    wav_size = wav_path.stat().st_size if wav_path.exists() else 0
    modified = 0.0
    for path in (raw_path, wav_path):
        try:
            if path.exists():
                modified = max(modified, path.stat().st_mtime)
        except OSError:
            pass
    available = raw_size > 0 or wav_size > 44
    duration = raw_size / float(_sample_rate() * PCM_SAMPLE_WIDTH) if raw_size > 0 else 0.0
    return {
        "available": available,
        "rawPath": str(raw_path),
        "wavPath": str(wav_path),
        "sizeBytes": max(raw_size, wav_size),
        "durationSeconds": round(duration, 2),
        "modifiedAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(modified)) if modified else "",
    }
