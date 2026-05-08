from __future__ import annotations

import importlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np


APP_DATA = tempfile.TemporaryDirectory(prefix="whisperer-rewrite-tests-")
os.environ["WHISPERER_APP_DATA_DIR"] = APP_DATA.name

import config
from core import audio, dictation_backup, dictionary, formatter, history, migrations, modes, settings, transcriber, updater


def reset_runtime_state() -> None:
    root = Path(APP_DATA.name)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    migrations.ensure_migrated()
    dictionary.init_db()


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()

    def test_settings_merge_defaults_and_preserve_unknowns(self) -> None:
        path = Path(settings.get_settings_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"startup": {"auto_start_engine": False}, "extra": {"x": 1}}), encoding="utf-8")

        loaded = settings.load_settings()

        self.assertFalse(loaded["startup"]["auto_start_engine"])
        self.assertEqual(loaded["startup"]["default_model"], "nvidia/parakeet-tdt-0.6b-v2")
        self.assertEqual(loaded["extra"], {"x": 1})

    def test_save_settings_is_atomic_json(self) -> None:
        loaded = settings.load_settings()
        loaded["ui"]["accent"] = "slate"
        settings.save_settings(loaded)

        saved = json.loads(Path(settings.get_settings_path()).read_text(encoding="utf-8"))
        self.assertEqual(saved["ui"]["accent"], "slate")


class ModeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        modes.seed_builtins()

    def test_builtin_modes_and_resolution(self) -> None:
        voice = modes.get_mode_by_name("Voice")
        self.assertIsNotNone(voice)
        custom_id = modes.add_mode("Resolve Notes")
        rule_id = modes.add_auto_rule(custom_id, "process", "resolve.exe", priority=10)

        resolved = modes.resolve_active_mode("DaVinciResolve.exe", "Timeline")

        self.assertEqual(resolved.name, "Resolve Notes")
        self.assertTrue(any(rule["id"] == rule_id for rule in modes.list_auto_rules(custom_id)))

    def test_update_and_delete_mode(self) -> None:
        mode_id = modes.add_mode("Scratch")
        self.assertTrue(modes.update_mode(mode_id, enabled=False, llm_enabled=True, ignored=True))
        updated = modes.get_mode(mode_id)
        self.assertIsNotNone(updated)
        self.assertFalse(updated.enabled)
        self.assertTrue(updated.llm_enabled)
        self.assertTrue(modes.delete_mode(mode_id))
        self.assertIsNone(modes.get_mode(mode_id))


class DictionaryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()

    def test_vocabulary_and_prompt_cache_invalidation(self) -> None:
        dictionary.add_word("OpenAI", source="manual")
        self.assertEqual(dictionary.get_prompt_words(10), "openai")
        dictionary.add_word("Whisperer", source="manual")
        self.assertIn("whisperer", dictionary.get_prompt_words(10))
        self.assertEqual(dictionary.get_word_count(), 2)

    def test_replacement_rules_longest_first(self) -> None:
        dictionary.add_replacement_rule("new york", "New York")
        dictionary.add_replacement_rule("new york city", "New York City")

        result = dictionary.apply_replacements("i love new york city and new york")

        self.assertEqual(result, "i love New York City and New York")


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        modes.seed_builtins()

    def test_history_lifecycle(self) -> None:
        voice = modes.get_mode_by_name("Voice")
        dictation_id = history.save_dictation(
            started_at="2026-05-07 13:00:00",
            duration_ms=1500,
            app_name="notepad.exe",
            window_title="Untitled",
            mode_id=voice.id if voice else None,
            stt_provider="local",
            stt_model="test",
            raw_transcript="hello world",
            final_text="Hello world.",
            paste_succeeded=1,
        )
        history.save_context(dictation_id, "clipboard", "nearby text")

        detail = history.get_dictation(dictation_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["contexts"][0]["content"], "nearby text")
        self.assertEqual(history.list_dictations("hello")[0]["id"], dictation_id)
        self.assertTrue(history.delete_dictation(dictation_id))
        self.assertIsNone(history.get_dictation(dictation_id))


class FormattingTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        modes.seed_builtins()

    def test_standard_and_prompt_rules(self) -> None:
        self.assertEqual(formatter.format_transcription("hello , world"), "Hello, world.")
        self.assertEqual(formatter.format_transcription("testing,"), "Testing.")
        self.assertEqual(formatter.format_transcription("testing,."), "Testing.")
        marker = modes.get_mode_by_name("DaVinci Marker")
        self.assertEqual(formatter.format_transcription("Cut, now!", mode=marker), "cut now")
        custom = modes.Mode(name="Lower", formatting_prompt="lowercase and no punctuation")
        self.assertEqual(formatter.format_transcription("Hello, World!", mode=custom), "hello world")


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()

    def test_last_dictation_backup_roundtrip(self) -> None:
        raw_path = Path(dictation_backup.reset_last_dictation_backup())
        samples = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
        raw_path.write_bytes(dictation_backup.float32_to_pcm16_bytes(samples))

        wav_path = dictation_backup.finalize_last_dictation_wav()
        loaded = dictation_backup.load_last_dictation_audio()
        meta = dictation_backup.last_dictation_backup_metadata()

        self.assertTrue(Path(wav_path).exists())
        self.assertTrue(meta["available"])
        self.assertEqual(len(loaded), len(samples))
        self.assertAlmostEqual(float(loaded[1]), 0.5, places=3)


class TranscriberHelperTests(unittest.TestCase):
    def test_audio_helpers_and_merge_logic(self) -> None:
        audio_data = np.concatenate([np.zeros(400), np.ones(800, dtype=np.float32) * 0.01, np.zeros(400)])
        trimmed = transcriber.trim_silence(audio_data, threshold=0.003, pad_ms=0)

        self.assertLess(len(trimmed), len(audio_data))
        self.assertEqual(len(transcriber._audio_to_pcm16_bytes(np.zeros(10, dtype=np.float32))), 20)
        self.assertEqual(transcriber._merge_transcript("hello brave", "brave world"), "hello brave world")
        self.assertEqual(transcriber._clean_riva_text("hello <unk> ,  world"), "hello, world")

    def test_nvidia_riva_model_normalization(self) -> None:
        self.assertEqual(
            transcriber._normalize_nvidia_riva_model("nvidia/parakeet-ctc-1.1b-asr"),
            transcriber.NVIDIA_RIVA_CTC_MODEL,
        )
        self.assertEqual(
            transcriber._normalize_nvidia_riva_model("nvidia/parakeet-1.1b-rnnt-multilingual-asr"),
            transcriber.NVIDIA_RIVA_STREAMING_MODEL,
        )
        self.assertEqual(
            transcriber._normalize_nvidia_riva_model("nvidia/parakeet-tdt-0.6b-v3"),
            transcriber.NVIDIA_RIVA_TDT_V3_MODEL,
        )

    def test_groq_model_normalization_rejects_non_groq_models(self) -> None:
        self.assertEqual(transcriber._normalize_groq_model("whisper-large-v3"), "whisper-large-v3")
        self.assertEqual(transcriber._normalize_groq_model(None), "whisper-large-v3-turbo")
        with self.assertRaises(ValueError):
            transcriber._normalize_groq_model("nvidia/parakeet-tdt-0.6b-v3")


class UpdaterTests(unittest.TestCase):
    def test_version_and_asset_selection(self) -> None:
        self.assertTrue(updater._is_newer("v6.0.10", "6.0.9"))
        self.assertFalse(updater._is_newer("6.0.9", "6.0.9"))

        asset = updater._select_windows_installer(
            [
                {"name": "notes.txt", "browser_download_url": "https://example.com/notes.txt"},
                {"name": "Whisperer-Setup-6.0.10.exe", "browser_download_url": "https://example.com/setup.exe", "size": 12},
            ]
        )

        self.assertIsNotNone(asset)
        self.assertEqual(asset.name, "Whisperer-Setup-6.0.10.exe")


class AudioHelperTests(unittest.TestCase):
    def test_input_device_scoring_prefers_real_inputs(self) -> None:
        real = {"name": "Focusrite USB Microphone", "max_input_channels": 2}
        virtual = {"name": "Steam Streaming Microphone", "max_input_channels": 2}

        self.assertGreater(audio._input_device_score(real), audio._input_device_score(virtual))
        self.assertLess(audio._input_device_score({"name": "Speakers", "max_input_channels": 0}), 0)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        APP_DATA.cleanup()
