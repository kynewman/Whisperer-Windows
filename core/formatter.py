"""Deterministic text formatting driven by mode profiles."""

from __future__ import annotations

import re

from core.modes import Mode, resolve_active_mode


_SPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?%])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([\(\[\{])\s+")
_SPACE_BEFORE_CLOSE_RE = re.compile(r"\s+([\)\]\}])")
_NUMBER_PUNCT_RE = re.compile(r"(?<=\d)([.,])\s+(?=\d)")
_SCENE_HEADING_RE = re.compile(r"^(int\.|ext\.|int/ext\.|i/e\.)\s*", re.IGNORECASE)
_PUNCT_TABLE = str.maketrans("", "", ".,!?;:\"'()[]{}")
_DAVINCI_PUNCT_TABLE = str.maketrans("", "", ".,!?;:\"'()-")
_CLAUSE_BEFORE_TERMINAL_RE = re.compile(r"[,;]+(?=[.!?]\s*$)")
_TRAILING_CLAUSE_PUNCT_RE = re.compile(r"[,;]\s*$")
_TERMINAL_PUNCTUATION = ".!?:"


def _normalize_punctuation_spacing(text: str) -> str:
    text = _SPACE_RE.sub(" ", (text or "").strip())
    if not text:
        return text
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN_RE.sub(r"\1", text)
    text = _SPACE_BEFORE_CLOSE_RE.sub(r"\1", text)
    text = _NUMBER_PUNCT_RE.sub(r"\1", text)
    return _SPACE_RE.sub(" ", text).strip()


def _format_davinci(text: str) -> str:
    return " ".join((text or "").strip().lower().translate(_DAVINCI_PUNCT_TABLE).split())


def _finish_sentence(text: str) -> str:
    text = _CLAUSE_BEFORE_TERMINAL_RE.sub("", text)
    if _TRAILING_CLAUSE_PUNCT_RE.search(text):
        return _TRAILING_CLAUSE_PUNCT_RE.sub(".", text)
    if text[-1] not in _TERMINAL_PUNCTUATION:
        return f"{text}."
    return text


def _format_screenwriting(text: str) -> str:
    text = _normalize_punctuation_spacing(text)
    if not text:
        return text
    if _SCENE_HEADING_RE.match(text):
        return text.upper()
    if text.startswith("(") and text.endswith(")"):
        return text.lower()
    if len(text.split()) <= 3 and text.isupper():
        return text.upper()
    return _finish_sentence(text)


def _format_standard(text: str) -> str:
    text = _normalize_punctuation_spacing(text)
    if not text:
        return text
    text = text[0].upper() + text[1:]
    text = _finish_sentence(text)
    return text.replace(" i ", " I ").replace(" i'", " I'")


def _remove_punctuation(text: str) -> str:
    return " ".join((text or "").translate(_PUNCT_TABLE).split())


def _apply_prompt_rules(text: str, prompt: str) -> str | None:
    prompt_lower = (prompt or "").lower()
    if not prompt_lower.strip():
        return None

    formatted = (text or "").strip()
    if not formatted:
        return formatted

    if any(phrase in prompt_lower for phrase in ("all caps", "uppercase", "upper case", "capital letters")):
        formatted = formatted.upper()
    elif any(phrase in prompt_lower for phrase in ("lowercase", "lower case", "all lowercase")):
        formatted = formatted.lower()
    else:
        return None

    if any(phrase in prompt_lower for phrase in ("no punctuation", "remove punctuation", "without punctuation")):
        return _remove_punctuation(formatted)
    return _normalize_punctuation_spacing(formatted)


def format_transcription(
    raw_text: str,
    active_app: str = "",
    window_title: str = "",
    mode: Mode | None = None,
) -> str:
    """Format raw STT output using the resolved active mode."""
    mode = mode or resolve_active_mode(active_app, window_title)
    if mode.name == "DaVinci Marker":
        return _format_davinci(raw_text)
    if mode.name == "Screenwriting":
        return _format_screenwriting(raw_text)
    if mode.output_format == "code":
        return (raw_text or "").strip()
    prompt_result = _apply_prompt_rules(raw_text, mode.formatting_prompt)
    if prompt_result is not None:
        return prompt_result
    return _format_standard(raw_text)
