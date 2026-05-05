"""Dynamic text formatter driven by mode profiles."""

from __future__ import annotations

import re

from core.modes import Mode, resolve_active_mode


def _normalize_punctuation_spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return text
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"([\(\[\{])\s+", r"\1", text)
    text = re.sub(r"\s+([\)\]\}])", r"\1", text)
    text = re.sub(r"(?<=\d)([.,])\s+(?=\d)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _format_davinci(text: str) -> str:
    text = text.strip().lower()
    for ch in ".,!?;:\"'()-":
        text = text.replace(ch, "")
    return " ".join(text.split())


def _format_screenwriting(text: str) -> str:
    text = _normalize_punctuation_spacing(text)
    if not text:
        return text
    scene_heading_pattern = re.compile(r"^(int\.|ext\.|int/ext\.|i/e\.)\s*", re.IGNORECASE)
    if scene_heading_pattern.match(text):
        return text.upper()
    if text.startswith("(") and text.endswith(")"):
        return text.lower()
    if len(text.split()) <= 3 and text.isupper():
        return text.upper()
    if text and text[-1] not in ".!?:":
        text += "."
    return text


def _format_standard(text: str) -> str:
    text = _normalize_punctuation_spacing(text)
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text and text[-1] not in ".!?:":
        text += "."
    for old, new in ((" i ", " I "), (" i'", " I'")):
        text = text.replace(old, new)
    return text


def _remove_punctuation(text: str) -> str:
    for ch in ".,!?;:\"'()[]{}":
        text = text.replace(ch, "")
    return " ".join(text.split())


def _apply_prompt_rules(text: str, prompt: str) -> str | None:
    prompt_lower = (prompt or "").lower()
    if not prompt_lower.strip():
        return None
    formatted = text.strip()
    if not formatted:
        return formatted

    if any(phrase in prompt_lower for phrase in ("all caps", "uppercase", "upper case", "capital letters")):
        formatted = formatted.upper()
    elif any(phrase in prompt_lower for phrase in ("lowercase", "lower case", "all lowercase")):
        formatted = formatted.lower()
    else:
        return None

    if any(phrase in prompt_lower for phrase in ("no punctuation", "remove punctuation", "without punctuation")):
        formatted = _remove_punctuation(formatted)
    else:
        formatted = _normalize_punctuation_spacing(formatted)
    return formatted


def format_transcription(raw_text: str, active_app: str = "", window_title: str = "", mode: Mode | None = None) -> str:
    """Format raw Whisper output according to the currently active mode."""
    mode = mode or resolve_active_mode(active_app, window_title)
    if mode.name == "DaVinci Marker":
        return _format_davinci(raw_text)
    if mode.name == "Screenwriting":
        return _format_screenwriting(raw_text)
    if mode.output_format == "code":
        return raw_text.strip()
    prompt_result = _apply_prompt_rules(raw_text, mode.formatting_prompt)
    if prompt_result is not None:
        return prompt_result
    return _format_standard(raw_text)
