"""Speech-to-text providers and shared audio conversion helpers."""

from __future__ import annotations

import io
import json
import logging
import os
import queue
import re
import tempfile
import threading
import time
import urllib.request
import wave
from collections.abc import Iterable

import numpy as np

import config
from core.perf import timed
from core.settings import load_settings


log = logging.getLogger("whisperer.transcriber")

_model = None
_warmed_up = False
_PARAKEET_WARMUP_TRANSCRIBE = os.environ.get("WHISPERER_PARAKEET_WARMUP_TRANSCRIBE") == "1"

NVIDIA_RIVA_URI = "grpc.nvcf.nvidia.com:443"
NVIDIA_RIVA_TDT_MODEL = "parakeet-tdt-0.6b-v2"
NVIDIA_RIVA_TDT_V3_MODEL = "parakeet-tdt-0.6b-v3"
NVIDIA_RIVA_CTC_MODEL = "parakeet-ctc-1.1b-asr"
NVIDIA_RIVA_STREAMING_MODEL = "parakeet-1.1b-rnnt-multilingual-asr"
NVIDIA_RIVA_FUNCTION_IDS = {
    NVIDIA_RIVA_TDT_MODEL: "d3fe9151-442b-4204-a70d-5fcc597fd610",
    NVIDIA_RIVA_TDT_V3_MODEL: "d3fe9151-442b-4204-a70d-5fcc597fd610",
    NVIDIA_RIVA_CTC_MODEL: "1598d209-5e27-4d3c-8079-4751568b1081",
    NVIDIA_RIVA_STREAMING_MODEL: "71203149-d3b7-4460-8231-1be2543a1fca",
}
GROQ_WHISPER_TURBO_MODEL = "whisper-large-v3-turbo"
GROQ_WHISPER_LARGE_MODEL = "whisper-large-v3"
GROQ_WHISPER_MODELS = {GROQ_WHISPER_TURBO_MODEL, GROQ_WHISPER_LARGE_MODEL}


def _quiet_model_telemetry_logs() -> None:
    os.environ.setdefault("RANK", "0")
    os.environ.setdefault("LOCAL_RANK", "0")
    os.environ.setdefault("WORLD_SIZE", "1")
    os.environ.setdefault("NEMO_LOGGING_LEVEL", "ERROR")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    for name in ("nv_one_logger", "nemo.lightning.one_logger_callback"):
        logging.getLogger(name).addHandler(logging.NullHandler())
        logging.getLogger(name).setLevel(logging.ERROR)


def _is_parakeet_model(model_name: str | None = None) -> bool:
    return (model_name or config.WHISPER_MODEL_SIZE or "").lower().startswith("nvidia/parakeet")


def _normalize_nvidia_riva_model(model: str | None = None) -> str:
    value = (model or config.WHISPER_MODEL_SIZE or NVIDIA_RIVA_TDT_MODEL).strip().lower()
    if value.startswith("nvidia/"):
        value = value.split("/", 1)[1]
    value = value.replace("_", "-")
    if "rnnt" in value:
        return NVIDIA_RIVA_STREAMING_MODEL if "multilingual" not in value else value
    if "ctc" in value:
        return NVIDIA_RIVA_CTC_MODEL
    if "v3" in value:
        return NVIDIA_RIVA_TDT_V3_MODEL
    return NVIDIA_RIVA_TDT_MODEL


def nvidia_riva_streaming_model(model: str | None = None) -> str:
    normalized = _normalize_nvidia_riva_model(model)
    return normalized if "rnnt" in normalized else NVIDIA_RIVA_STREAMING_MODEL


def nvidia_riva_model_supports_streaming(model: str | None = None) -> bool:
    value = (model or config.WHISPER_MODEL_SIZE or "").strip().lower()
    return "parakeet" in value or "rnnt" in value


def _nvidia_riva_function_id(model: str | None = None, *, streaming: bool = False) -> str:
    normalized = nvidia_riva_streaming_model(model) if streaming else _normalize_nvidia_riva_model(model)
    return NVIDIA_RIVA_FUNCTION_IDS.get(normalized, NVIDIA_RIVA_FUNCTION_IDS[NVIDIA_RIVA_TDT_MODEL])


def _nvidia_language_code(language: str | None) -> str:
    value = (language or config.WHISPER_LANGUAGE or "en").strip()
    if not value:
        return "en-US"
    if value.lower() == "en" or value.lower().startswith("en_"):
        return "en-US"
    return value.replace("_", "-")


def _riva_auth(riva_client, api_key: str, function_id: str):
    return riva_client.Auth(
        uri=NVIDIA_RIVA_URI,
        use_ssl=True,
        metadata_args=[["function-id", function_id], ["authorization", f"Bearer {api_key}"]],
    )


def _riva_recognition_config(riva_client, language: str, model: str | None = None):
    del model
    kwargs = {
        "encoding": riva_client.AudioEncoding.LINEAR_PCM,
        "sample_rate_hertz": int(config.AUDIO_SAMPLE_RATE),
        "audio_channel_count": 1,
        "language_code": _nvidia_language_code(language),
        "max_alternatives": 1,
        "enable_automatic_punctuation": True,
        "enable_word_time_offsets": False,
    }
    try:
        return riva_client.RecognitionConfig(**kwargs)
    except TypeError:
        cfg = riva_client.RecognitionConfig()
        for key, value in kwargs.items():
            try:
                setattr(cfg, key, value)
            except Exception:
                pass
        return cfg


def _cache_dir_name(model_name: str) -> str:
    return "models--" + model_name.replace("/", "--")


def _model_cache_exists(model_name: str) -> bool:
    roots = [
        os.path.join(config.MODEL_CACHE_DIR, _cache_dir_name(model_name)),
        os.path.join(config.MODEL_CACHE_DIR, "huggingface", "hub", _cache_dir_name(model_name)),
    ]
    for root in roots:
        snapshots = os.path.join(root, "snapshots")
        if not os.path.isdir(snapshots):
            continue
        for snapshot in os.listdir(snapshots):
            path = os.path.join(snapshots, snapshot)
            if os.path.isdir(path) and any(os.scandir(path)):
                return True
    return False


def _configure_model_cache(model_name: str) -> bool:
    _quiet_model_telemetry_logs()
    os.environ.setdefault("HF_HOME", os.path.join(config.MODEL_CACHE_DIR, "huggingface"))
    os.environ.setdefault("NEMO_HOME", os.path.join(config.MODEL_CACHE_DIR, "nemo"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    cached = _model_cache_exists(model_name)
    if cached:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return cached


def trim_silence(audio: np.ndarray, threshold: float = 0.003, pad_ms: int = 220) -> np.ndarray:
    if audio is None:
        return np.zeros(0, dtype=np.float32)
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    if data.size == 0:
        return data
    sample_rate = int(config.AUDIO_SAMPLE_RATE)
    frame = max(1, int(sample_rate * 0.02))
    usable = (data.size // frame) * frame
    if usable <= 0:
        return data
    frames = data[:usable].reshape(-1, frame)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    active = np.flatnonzero(rms > threshold)
    if active.size == 0:
        return data
    pad = int(sample_rate * pad_ms / 1000)
    start = max(0, int(active[0]) * frame - pad)
    end = min(data.size, (int(active[-1]) + 1) * frame + pad)
    return data[start:end].astype(np.float32, copy=False)


def _silence_trim_enabled() -> bool:
    try:
        return bool(load_settings().get("performance", {}).get("silence_trim_enabled", True))
    except Exception:
        return True


def load_model():
    """Load the selected local STT model once."""
    global _model
    if _model is not None:
        return _model

    with timed("model_load"):
        if _is_parakeet_model():
            _configure_model_cache(config.WHISPER_MODEL_SIZE)
            try:
                import torch

                if hasattr(torch, "set_float32_matmul_precision"):
                    torch.set_float32_matmul_precision("high")
                if torch.cuda.is_available():
                    torch.backends.cudnn.benchmark = True
            except Exception:
                pass
            try:
                with timed("import_nemo_asr"):
                    import nemo.collections.asr as nemo_asr
            except Exception as exc:
                raise RuntimeError(
                    "NVIDIA Parakeet requires NeMo ASR. Install it with "
                    "\"pip install 'nemo_toolkit[asr]'\" in the Whisperer Python environment."
                ) from exc
            model = nemo_asr.models.ASRModel.from_pretrained(model_name=config.WHISPER_MODEL_SIZE)
            try:
                from omegaconf import OmegaConf

                OmegaConf.set_struct(model.cfg, False)
            except Exception:
                pass
            if getattr(model.cfg, "validation_ds", None) is None:
                model.cfg.validation_ds = {}
            if getattr(model.cfg, "test_ds", None) is None:
                model.cfg.test_ds = {}
            if hasattr(model, "to"):
                model = model.to(config.WHISPER_DEVICE)
            if hasattr(model, "eval"):
                model.eval()
            _model = model
        else:
            cached = _configure_model_cache(config.WHISPER_MODEL_SIZE)
            with timed("import_faster_whisper"):
                from faster_whisper import WhisperModel

            kwargs = {
                "device": config.WHISPER_DEVICE,
                "compute_type": config.WHISPER_COMPUTE_TYPE,
                "download_root": config.MODEL_CACHE_DIR,
            }
            if cached:
                kwargs["local_files_only"] = True
            try:
                _model = WhisperModel(config.WHISPER_MODEL_SIZE, **kwargs)
            except TypeError:
                kwargs.pop("local_files_only", None)
                _model = WhisperModel(config.WHISPER_MODEL_SIZE, **kwargs)
    return _model


def warmup_model() -> None:
    global _warmed_up
    if _warmed_up:
        return
    model = load_model()
    if _is_parakeet_model() and not _PARAKEET_WARMUP_TRANSCRIBE:
        with timed("model_warmup"):
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.synchronize()
            except Exception:
                pass
        _warmed_up = True
        return

    silence = np.zeros(int(config.AUDIO_SAMPLE_RATE) // 4, dtype=np.float32)
    with timed("model_warmup"):
        if _is_parakeet_model():
            _transcribe_parakeet_audio(silence)
        else:
            segments, _info = model.transcribe(
                silence,
                language=config.WHISPER_LANGUAGE,
                beam_size=1,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 100},
            )
            for _ in segments:
                pass
    _warmed_up = True


def _audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    data = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(config.AUDIO_SAMPLE_RATE))
        wf.writeframes((data * 32767.0).astype("<i2").tobytes())
    return buf.getvalue()


def _audio_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    data = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
    return (data * 32767.0).astype("<i2").tobytes()


def _parakeet_text(result) -> str:
    item = result[0] if isinstance(result, (list, tuple)) and result else result
    if hasattr(item, "text"):
        return str(item.text or "")
    if isinstance(item, dict):
        return str(item.get("text") or item.get("pred_text") or "")
    return str(item or "")


def _transcribe_parakeet_audio(audio: np.ndarray) -> str:
    model = load_model()
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(_audio_to_wav_bytes(audio))
            tmp_path = tmp.name
        with timed("transcribe_parakeet"):
            try:
                result = model.transcribe([tmp_path], batch_size=1)
            except TypeError:
                result = model.transcribe([tmp_path])
        return _parakeet_text(result).strip()
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _multipart_audio_body(
    *,
    wav_bytes: bytes,
    fields: dict[str, str],
    boundary: str = "----WhispererFormBoundary",
) -> tuple[bytes, str]:
    chunks: list[bytes] = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8"),
        wav_bytes,
        b"\r\n",
    ]
    for name, value in fields.items():
        if value is None:
            continue
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def transcribe_openai(
    audio: np.ndarray,
    api_key: str,
    language: str = "en",
    prompt: str | None = None,
    model: str = "gpt-4o-mini-transcribe",
) -> str:
    fields = {"model": model}
    if language:
        fields["language"] = language
    if prompt:
        fields["prompt"] = prompt
    body, boundary = _multipart_audio_body(wav_bytes=_audio_to_wav_bytes(audio), fields=fields)
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")).get("text", "")


def _normalize_groq_model(model: str | None = None) -> str:
    value = (model or GROQ_WHISPER_TURBO_MODEL).strip().lower()
    if value not in GROQ_WHISPER_MODELS:
        raise ValueError(
            f"Groq STT only supports {', '.join(sorted(GROQ_WHISPER_MODELS))}; got {model!r}."
        )
    return value


def transcribe_groq(
    audio: np.ndarray,
    api_key: str,
    language: str = "en",
    prompt: str | None = None,
    model: str | None = None,
) -> str:
    fields = {"model": _normalize_groq_model(model)}
    if language:
        fields["language"] = language
    if prompt:
        fields["prompt"] = prompt
    body, boundary = _multipart_audio_body(wav_bytes=_audio_to_wav_bytes(audio), fields=fields)
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": f"Whisperer/{config.VERSION}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")).get("text", "")


def _clean_riva_text(text: str) -> str:
    text = re.sub(r"(?:<unk>\s*)+", " ", str(text or ""), flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"(?<=\d)([.,])\s+(?=\d)", r"\1", text)
    return text.strip()


def _riva_response_texts(response) -> list[tuple[str, bool]]:
    parts: list[tuple[str, bool]] = []
    for result in getattr(response, "results", []):
        alternatives = getattr(result, "alternatives", None)
        if alternatives:
            text = _clean_riva_text(alternatives[0].transcript)
            if text:
                parts.append((text, bool(getattr(result, "is_final", True))))
    return parts


def _merge_transcript(previous: str, addition: str) -> str:
    previous = (previous or "").strip()
    addition = (addition or "").strip()
    if not previous:
        return addition
    if not addition:
        return previous
    if addition.lower().startswith(previous.lower()):
        return addition
    if previous.lower().endswith(addition.lower()):
        return previous
    prev_words = previous.split()
    add_words = addition.split()
    prev_norm = [re.sub(r"\W+", "", word).lower() for word in prev_words]
    add_norm = [re.sub(r"\W+", "", word).lower() for word in add_words]
    for size in range(min(12, len(prev_norm), len(add_norm)), 0, -1):
        if prev_norm[-size:] == add_norm[:size]:
            return f"{previous} {' '.join(add_words[size:])}".strip()
    return f"{previous} {addition}".strip()


class NvidiaStreamingTranscriber:
    """Hosted Riva streaming session used as the low-latency Parakeet path."""

    def __init__(self, api_key: str, language: str = "en", model: str | None = None):
        self.api_key = api_key
        self.language = language
        self.model = model or NVIDIA_RIVA_STREAMING_MODEL
        self.streaming_model = nvidia_riva_streaming_model(self.model)
        self._audio_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=4096)
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._finished = threading.Event()
        self._error = ""
        self._final_text = ""
        self._latest_text = ""
        self._partial_text = ""
        self._final_result_count = 0
        self._last_text_timestamp = 0.0
        self._closed = False

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def latest_text(self) -> str:
        with self._lock:
            return self._latest_text or _merge_transcript(self._final_text, self._partial_text)

    @property
    def partial_text(self) -> str:
        with self._lock:
            return self._partial_text

    @property
    def final_result_count(self) -> int:
        with self._lock:
            return self._final_result_count

    @property
    def last_text_timestamp(self) -> float:
        with self._lock:
            return self._last_text_timestamp

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def start(self) -> bool:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return True

    def feed_audio(self, audio: np.ndarray) -> None:
        if self._closed or self._finished.is_set():
            return
        pcm = _audio_to_pcm16_bytes(audio)
        if not pcm:
            return
        try:
            self._audio_queue.put_nowait(pcm)
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(pcm)
            except Exception:
                pass

    def finish(self, timeout_s: float = 0.45) -> str:
        self._closed = True
        try:
            self._audio_queue.put(None, timeout=0.05)
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(None)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, float(timeout_s)))
        return self.latest_text

    def adaptive_finalize_timeout(
        self,
        *,
        adaptive_enabled: bool = True,
        finalize_wait_ms: int = 450,
        fast_wait_ms: int = 120,
    ) -> float:
        max_wait = max(0, int(finalize_wait_ms)) / 1000.0
        if not adaptive_enabled or self._finished.is_set():
            return 0.0 if self._finished.is_set() else max_wait
        with self._lock:
            if self._error:
                return 0.0
            latest = self._latest_text.strip()
            partial = self._partial_text.strip()
            final_count = self._final_result_count
            last_ts = self._last_text_timestamp
        fast_wait = max(0.0, int(fast_wait_ms) / 1000.0)
        tail_wait = min(max_wait, max(fast_wait, 0.22))
        if not latest:
            return min(max_wait, 0.35)
        if final_count > 0:
            return tail_wait
        if partial and last_ts and time.monotonic() - last_ts >= 0.08:
            return tail_wait
        return min(max_wait, max(tail_wait, 0.25))

    def _audio_iterator(self) -> Iterable[bytes]:
        while True:
            item = self._audio_queue.get()
            if item is None:
                return
            if item:
                yield item

    def _run(self) -> None:
        try:
            import riva.client

            auth = _riva_auth(riva.client, self.api_key, _nvidia_riva_function_id(self.streaming_model, streaming=True))
            asr_service = riva.client.ASRService(auth)
            cfg = _riva_recognition_config(riva.client, self.language, self.streaming_model)
            streaming_cfg = riva.client.StreamingRecognitionConfig(config=cfg, interim_results=True)
            for response in asr_service.streaming_response_generator(self._audio_iterator(), streaming_cfg):
                self._handle_response(response)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            self._finished.set()

    def _handle_response(self, response) -> None:
        for text, is_final in _riva_response_texts(response):
            with self._lock:
                if is_final:
                    self._final_text = _merge_transcript(self._final_text, text)
                    self._partial_text = ""
                    self._final_result_count += 1
                    self._latest_text = self._final_text
                else:
                    self._partial_text = text
                    self._latest_text = _merge_transcript(self._final_text, text)
                self._last_text_timestamp = time.monotonic()


def transcribe_nvidia_riva_streaming(
    audio: np.ndarray,
    api_key: str,
    language: str = "en",
    model: str | None = None,
    chunk_ms: int = 32,
) -> str:
    transcriber = NvidiaStreamingTranscriber(api_key, language=language, model=model)
    transcriber.start()
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    chunk_samples = max(1, int(config.AUDIO_SAMPLE_RATE * max(10, int(chunk_ms)) / 1000.0))
    for start in range(0, data.size, chunk_samples):
        transcriber.feed_audio(data[start : start + chunk_samples])
    timeout = min(20.0, max(1.5, data.size / float(config.AUDIO_SAMPLE_RATE or 16000) + 4.0))
    return transcriber.finish(timeout_s=timeout).strip()


def prewarm_nvidia_riva(api_key: str, models: list[str] | None = None) -> int:
    if not api_key:
        return 0
    try:
        import riva.client
    except Exception as exc:
        raise RuntimeError("NVIDIA Parakeet API requires nvidia-riva-client. Install it with: pip install nvidia-riva-client") from exc
    count = 0
    for model in models or [NVIDIA_RIVA_TDT_MODEL, NVIDIA_RIVA_CTC_MODEL, NVIDIA_RIVA_STREAMING_MODEL]:
        function_id = _nvidia_riva_function_id(model, streaming=("rnnt" in model.lower()))
        riva.client.ASRService(_riva_auth(riva.client, api_key, function_id))
        count += 1
    return count


def transcribe_nvidia_parakeet(
    audio: np.ndarray,
    api_key: str,
    language: str = "en",
    prompt: str | None = None,
    model: str | None = None,
) -> str:
    del prompt
    try:
        import riva.client
    except Exception as exc:
        raise RuntimeError("NVIDIA Parakeet API requires nvidia-riva-client. Install it with: pip install nvidia-riva-client") from exc

    final_model = _normalize_nvidia_riva_model(model)
    auth = _riva_auth(riva.client, api_key, _nvidia_riva_function_id(final_model))
    asr_service = riva.client.ASRService(auth)
    recognition_config = _riva_recognition_config(riva.client, language, final_model)
    audio_data = np.asarray(audio, dtype=np.float32).reshape(-1)
    sample_rate = int(config.AUDIO_SAMPLE_RATE)
    chunk_samples = sample_rate * 25
    overlap_samples = sample_rate
    tail_pad = np.zeros(int(sample_rate * 1.2), dtype=np.float32)

    if audio_data.size <= chunk_samples:
        padded = np.concatenate([audio_data, tail_pad])
        response = asr_service.offline_recognize(_audio_to_pcm16_bytes(padded), recognition_config)
        return " ".join(text for text, _ in _riva_response_texts(response)).strip()

    transcript = ""
    start = 0
    while start < audio_data.size:
        end = min(audio_data.size, start + chunk_samples)
        chunk = audio_data[start:end]
        if end >= audio_data.size:
            chunk = np.concatenate([chunk, tail_pad])
        response = asr_service.offline_recognize(_audio_to_pcm16_bytes(chunk), recognition_config)
        transcript = _merge_transcript(transcript, " ".join(text for text, _ in _riva_response_texts(response)))
        if end >= audio_data.size:
            break
        start = max(0, end - overlap_samples)
    return transcript


def transcribe_deepgram(audio: np.ndarray, api_key: str, language: str = "en") -> str:
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?model=nova-2&language={language}&smart_format=true",
        data=_audio_to_wav_bytes(audio),
        headers={"Authorization": f"Token {api_key}", "Content-Type": "audio/wav"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result["results"]["channels"][0]["alternatives"][0].get("transcript", "")


def transcribe_cloud(
    audio: np.ndarray,
    provider: str,
    api_key: str,
    language: str = "en",
    prompt: str | None = None,
    model: str | None = None,
) -> str:
    if provider == "openai_whisper":
        return transcribe_openai(audio, api_key, language=language, prompt=prompt, model=model or "gpt-4o-mini-transcribe")
    if provider == "groq_whisper":
        return transcribe_groq(audio, api_key, language=language, prompt=prompt, model=model)
    if provider == "nvidia_parakeet":
        return transcribe_nvidia_parakeet(audio, api_key, language=language, prompt=prompt, model=model)
    if provider == "deepgram":
        return transcribe_deepgram(audio, api_key, language=language)
    raise ValueError(f"Unknown cloud STT provider: {provider}")


def transcribe(
    audio_ndarray,
    context_words: str = "",
    selected_text: str = "",
    clipboard_context: str = "",
    ui_automation_text: str = "",
) -> str:
    """Transcribe a float32 16 kHz mono array with the selected local model."""
    model = load_model()
    with timed("trim_silence"):
        audio = trim_silence(audio_ndarray) if _silence_trim_enabled() else np.asarray(audio_ndarray, dtype=np.float32)
    if _is_parakeet_model():
        return _transcribe_parakeet_audio(audio)

    prompt_parts: list[str] = []
    if context_words:
        prompt_parts.append(f"Screen context:\n{context_words}")
    if ui_automation_text:
        prompt_parts.append(f"Focused control:\n{ui_automation_text}")
    if clipboard_context:
        prompt_parts.append(f"Recent clipboard:\n{clipboard_context}")
    if selected_text:
        prompt_parts.append(f"Selected text:\n{selected_text}")
    initial_prompt = "\n\n".join(prompt_parts) if prompt_parts else None

    with timed("transcribe"):
        segments, _info = model.transcribe(
            audio,
            language=config.WHISPER_LANGUAGE,
            beam_size=config.WHISPER_BEAM_SIZE,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
        )
        return " ".join(segment.text.strip() for segment in segments)
