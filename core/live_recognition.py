"""Optional Vosk live-preview recognizer."""

from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import urllib.request
import zipfile

import numpy as np

import config


VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOSK_DOWNLOAD_ENV = "WHISPERER_ENABLE_VOSK_DOWNLOAD"


def _download_file(url: str, target: str, timeout_s: int = 60) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"Whisperer/{config.VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response, open(target, "wb") as output:
        shutil.copyfileobj(response, output)


def _safe_extract(zip_path: str, target_dir: str) -> None:
    target_root = os.path.abspath(target_dir)
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            destination = os.path.abspath(os.path.join(target_root, member.filename))
            if destination != target_root and not destination.startswith(target_root + os.sep):
                raise ValueError(f"Unsafe path in Vosk archive: {member.filename}")
        zip_ref.extractall(target_root)


class LiveRecognizer:
    """Background Vosk recognizer used only for low-stakes live overlay text."""

    def __init__(self, text_callback=None):
        self.text_callback = text_callback
        self.queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=256)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.model = None
        self.recognizer = None
        self.finalized_text = ""
        threading.Thread(target=self._ensure_model, daemon=True).start()

    def _ensure_model(self) -> None:
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError:
            print("Vosk not installed.", flush=True)
            return

        base_dir = os.path.join(config.MODEL_CACHE_DIR, "vosk")
        os.makedirs(base_dir, exist_ok=True)
        model_dir = os.path.join(base_dir, VOSK_MODEL_NAME)
        if not os.path.exists(model_dir) or not os.listdir(model_dir):
            if os.environ.get(VOSK_DOWNLOAD_ENV) != "1":
                print(
                    f"Vosk live preview model is not cached; skipping optional download. Set {VOSK_DOWNLOAD_ENV}=1 to enable it.",
                    flush=True,
                )
                return
            zip_path = os.path.join(base_dir, "vosk_model.zip")
            try:
                print(f"Downloading Vosk live preview model ({VOSK_MODEL_NAME})...", flush=True)
                _download_file(VOSK_MODEL_URL, zip_path)
                _safe_extract(zip_path, base_dir)
            except Exception as exc:
                print(f"Failed to prepare Vosk model: {exc}", flush=True)
                return
            finally:
                try:
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                except OSError:
                    pass
        try:
            self.model = Model(model_dir)
            self.recognizer = KaldiRecognizer(self.model, int(config.AUDIO_SAMPLE_RATE))
            self.recognizer.SetWords(False)
            print("Live Recognizer engine loaded successfully.", flush=True)
        except Exception as exc:
            print(f"Failed to initialize Vosk recognizer: {exc}", flush=True)

    def start(self) -> None:
        if not self.model or not self.recognizer:
            print("Cannot start live recognition: model not loaded yet.", flush=True)
            return
        self.finalized_text = ""
        self._drain_queue()
        self._stop_event.clear()
        self.recognizer.Reset()
        if self.text_callback:
            self.text_callback("")
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def feed_audio(self, float_array: np.ndarray) -> None:
        if self._stop_event.is_set():
            return
        try:
            self.queue.put_nowait(np.asarray(float_array, dtype=np.float32).copy())
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(np.asarray(float_array, dtype=np.float32).copy())
            except Exception:
                pass

    def _drain_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                return

    def _process_loop(self) -> None:
        while not self._stop_event.is_set() or not self.queue.empty():
            try:
                chunk = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            int16_data = (np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            if self.recognizer.AcceptWaveform(int16_data):
                payload = json.loads(self.recognizer.Result())
                text = payload.get("text", "")
                if text:
                    self.finalized_text += " " + text
                current_text = self.finalized_text.strip()
            else:
                payload = json.loads(self.recognizer.PartialResult())
                current_text = (self.finalized_text + " " + payload.get("partial", "")).strip()
            if self.text_callback:
                self.text_callback(current_text)
