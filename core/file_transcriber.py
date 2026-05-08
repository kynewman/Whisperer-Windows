"""Headless file transcription using ffmpeg and the normal text pipeline."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from core.dictionary import apply_replacements, get_prompt_words
from core.formatter import format_transcription
from core.history import save_dictation
from core.transcriber import transcribe


SUPPORTED_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
    ".aac",
    ".ogg",
    ".flac",
}


def is_supported(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def extract_audio(input_path: str) -> np.ndarray:
    """Extract 16 kHz mono float32 PCM with ffmpeg."""
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        input_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "f32le",
        "pipe:1",
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="ignore")[:400].strip()
        raise RuntimeError(f"ffmpeg failed: {detail}")
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if audio.size == 0:
        raise RuntimeError("ffmpeg produced no audio output")
    return audio


def transcribe_file(
    input_path: str,
    mode_id: int | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> dict:
    path = Path(input_path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    if progress_callback:
        progress_callback(0.05)

    audio = extract_audio(str(path))
    duration_s = audio.size / 16000.0
    if progress_callback:
        progress_callback(0.15)

    raw_text = transcribe(audio, context_words=get_prompt_words(80))
    if progress_callback:
        progress_callback(0.70)

    final_text = apply_replacements(format_transcription(raw_text, active_app=path.suffix.lower(), window_title=path.name))
    if progress_callback:
        progress_callback(0.85)

    dictation_id = save_dictation(
        started_at=started_at,
        duration_ms=int(duration_s * 1000),
        app_name=path.name,
        window_title="",
        mode_id=mode_id,
        stt_provider="local",
        stt_model="file",
        raw_transcript=raw_text,
        final_text=final_text,
        replacements_applied=1,
    )
    if progress_callback:
        progress_callback(1.0)
    return {
        "dictation_id": dictation_id,
        "raw_transcript": raw_text,
        "final_text": final_text,
        "duration_s": duration_s,
        "mode_id": mode_id,
        "error": None,
    }
