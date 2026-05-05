"""
Microphone capture using sounddevice.
Provides a simple start/stop recording interface that accumulates audio
into a numpy buffer at 16 kHz mono (what Whisper expects).

Also maintains a rolling window of recent samples for smooth waveform
visualisation.
"""

import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd

import config
from core.dictation_backup import (
    finalize_last_dictation_wav,
    float32_to_pcm16_bytes,
    reset_last_dictation_backup,
)
from core.settings import load_settings

VISUAL_WINDOW = 4096
AUTO_CHANNEL_PROBE_SECONDS = 0.18
AUTO_CHANNEL_SCAN_LIMIT = 8
AUTO_CHANNEL_CAPTURE_LIMIT = 2
AUTO_CHANNEL_MIN_RMS = 0.00008
AUTO_CHANNEL_DOMINANCE = 1.6


class AudioRecorder:
    """
    Thread-safe microphone recorder.

    Usage
    -----
    recorder = AudioRecorder()
    recorder.start()          # begins capturing
    ...                       # user speaks
    audio = recorder.stop()   # returns np.ndarray float32 @ 16 kHz
    """

    def __init__(self, live_recognizer=None):
        self._buffer: list[np.ndarray] = []
        self._visual_buffer = np.zeros(VISUAL_WINDOW, dtype=np.float32)
        self._visual_len = 0
        self._visual_pos = 0
        self._stream: sd.InputStream | None = None
        self._stream_samplerate = config.AUDIO_SAMPLE_RATE
        self._device_index: int | None = None
        self._input_channel = 0
        self._channels = config.AUDIO_CHANNELS
        self._warm_stream = True
        self._streaming_audio_chunk_ms = 32
        self._stream_blocksize = config.AUDIO_BLOCKSIZE
        self._target_chunk_samples = max(1, int(config.AUDIO_SAMPLE_RATE * 0.032))
        self._auto_input_channel = True
        self._input_device_name = ""
        self._max_input_channels = config.AUDIO_CHANNELS
        self._last_probe_key = None
        self._lock = threading.Lock()
        self._consumer_lock = threading.Lock()
        self._audio_consumers: list[Callable[[np.ndarray], None]] = []
        self._backup_lock = threading.Lock()
        self._backup_file = None
        self._backup_bytes_written = 0
        self._recording = False
        self.live_recognizer = live_recognizer
        self.refresh_settings(load_settings())

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def live_chunk(self) -> np.ndarray | None:
        """Return the last VISUAL_WINDOW samples as a 1-D float32 array."""
        with self._lock:
            if self._visual_len <= 0:
                return None
            if self._visual_len < VISUAL_WINDOW:
                return self._visual_buffer[: self._visual_len].copy()
            return np.concatenate((
                self._visual_buffer[self._visual_pos :],
                self._visual_buffer[: self._visual_pos],
            ))
        return None

    def _append_visual_samples(self, samples: np.ndarray):
        samples = samples.astype(np.float32, copy=False)
        count = len(samples)
        if count <= 0:
            return
        if count >= VISUAL_WINDOW:
            self._visual_buffer[:] = samples[-VISUAL_WINDOW:]
            self._visual_len = VISUAL_WINDOW
            self._visual_pos = 0
            return

        end = self._visual_pos + count
        if end <= VISUAL_WINDOW:
            self._visual_buffer[self._visual_pos:end] = samples
        else:
            first = VISUAL_WINDOW - self._visual_pos
            self._visual_buffer[self._visual_pos:] = samples[:first]
            self._visual_buffer[: end % VISUAL_WINDOW] = samples[first:]
        self._visual_pos = end % VISUAL_WINDOW
        self._visual_len = min(VISUAL_WINDOW, self._visual_len + count)

    def _select_active_channel(self, indata: np.ndarray) -> np.ndarray:
        if indata.ndim <= 1 or indata.shape[1] == 1:
            return indata.flatten()

        if self._auto_input_channel:
            try:
                data = indata.astype(np.float32, copy=False)
                rms = np.sqrt(np.mean(data * data, axis=0))
                best_channel = int(np.argmax(rms))
                current_channel = max(0, min(int(self._input_channel), indata.shape[1] - 1))
                best_rms = float(rms[best_channel])
                current_rms = float(rms[current_channel])
                if (
                    best_channel != current_channel
                    and best_rms >= AUTO_CHANNEL_MIN_RMS
                    and best_rms >= max(AUTO_CHANNEL_MIN_RMS, current_rms * AUTO_CHANNEL_DOMINANCE)
                ):
                    self._input_channel = best_channel
            except Exception:
                pass

        channel = max(0, min(int(self._input_channel), indata.shape[1] - 1))
        return indata[:, channel]

    def _resample_to_target_rate(self, audio: np.ndarray) -> np.ndarray:
        source_rate = int(round(self._stream_samplerate))
        target_rate = int(config.AUDIO_SAMPLE_RATE)
        if source_rate == target_rate or len(audio) == 0:
            return audio.astype(np.float32, copy=False)

        target_len = max(1, int(round(len(audio) * target_rate / source_rate)))
        source_x = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        target_x = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
        return np.interp(target_x, source_x, audio).astype(np.float32)

    def _split_target_chunks(self, audio: np.ndarray) -> list[np.ndarray]:
        audio = audio.astype(np.float32, copy=False)
        if len(audio) <= 0:
            return []
        chunk_samples = max(1, int(self._target_chunk_samples))
        if len(audio) <= chunk_samples:
            return [audio]
        return [audio[start : start + chunk_samples] for start in range(0, len(audio), chunk_samples)]

    def add_audio_consumer(self, callback: Callable[[np.ndarray], None]):
        with self._consumer_lock:
            if callback not in self._audio_consumers:
                self._audio_consumers.append(callback)

    def remove_audio_consumer(self, callback: Callable[[np.ndarray], None]):
        with self._consumer_lock:
            self._audio_consumers = [consumer for consumer in self._audio_consumers if consumer != callback]

    def _feed_audio_consumers(self, samples: np.ndarray):
        if self.live_recognizer:
            try:
                self.live_recognizer.feed_audio(samples)
            except Exception:
                pass
        with self._consumer_lock:
            consumers = list(self._audio_consumers)
        for consumer in consumers:
            try:
                consumer(samples)
            except Exception:
                pass

    def _callback(self, indata: np.ndarray, frames, time_info, status):
        if not self._recording:
            return
        flat = self._select_active_channel(indata)
        flat = self._resample_to_target_rate(flat)
        for chunk in self._split_target_chunks(flat):
            with self._lock:
                self._buffer.append(chunk.copy())
                self._append_visual_samples(chunk)
            self._write_backup_samples(chunk)
            self._feed_audio_consumers(chunk)

    def _start_backup_cache(self):
        raw_path = reset_last_dictation_backup()
        with self._backup_lock:
            self._close_backup_file_locked()
            self._backup_bytes_written = 0
            try:
                self._backup_file = open(raw_path, "ab", buffering=0)
            except Exception:
                self._backup_file = None

    def _close_backup_file_locked(self):
        if self._backup_file is None:
            return
        try:
            self._backup_file.close()
        except Exception:
            pass
        self._backup_file = None

    def _write_backup_samples(self, samples: np.ndarray):
        pcm = float32_to_pcm16_bytes(samples)
        if not pcm:
            return
        with self._backup_lock:
            if self._backup_file is None:
                return
            try:
                self._backup_file.write(pcm)
                self._backup_bytes_written += len(pcm)
            except Exception:
                self._close_backup_file_locked()

    def _finish_backup_cache(self):
        should_finalize = False
        with self._backup_lock:
            should_finalize = self._backup_bytes_written > 0
            self._close_backup_file_locked()
        if should_finalize:
            finalize_last_dictation_wav()

    def refresh_settings(self, settings: dict | None = None):
        settings = settings or load_settings()
        previous = (
            self._device_index,
            self._input_channel,
            self._channels,
            self._stream_samplerate,
            self._warm_stream,
            self._streaming_audio_chunk_ms,
            self._auto_input_channel,
            self._max_input_channels,
        )
        self._warm_stream = bool(settings.get("performance", {}).get("warm_microphone_stream", True))
        try:
            self._streaming_audio_chunk_ms = max(16, min(250, int(settings.get("performance", {}).get("streaming_audio_chunk_ms", 32))))
        except (TypeError, ValueError):
            self._streaming_audio_chunk_ms = 32
        self._target_chunk_samples = max(
            1,
            int(round(config.AUDIO_SAMPLE_RATE * self._streaming_audio_chunk_ms / 1000.0)),
        )
        audio_settings = settings.get("audio", {})
        device_index = audio_settings.get("input_device")
        device_name = audio_settings.get("input_device_name")
        self._auto_input_channel = bool(audio_settings.get("input_channel_auto", True))
        requested_channel = audio_settings.get("input_channel", 0)
        try:
            requested_channel = max(0, int(requested_channel))
        except (TypeError, ValueError):
            requested_channel = 0

        try:
            devices = sd.query_devices()
        except Exception:
            self._device_index = None
            self._channels = config.AUDIO_CHANNELS
            return

        selected_index = None
        if isinstance(device_index, int) and 0 <= device_index < len(devices):
            device = devices[device_index]
            if int(device.get("max_input_channels", 0)) > 0:
                selected_index = device_index

        if selected_index is None and device_name:
            for index, device in enumerate(devices):
                if (
                    int(device.get("max_input_channels", 0)) > 0
                    and str(device.get("name", "")).strip() == device_name
                ):
                    selected_index = index
                    break

        try:
            device_info = (
                sd.query_devices(selected_index, "input")
                if selected_index is not None
                else sd.query_devices(kind="input")
            )
        except Exception:
            selected_index = None
            device_info = {}

        self._device_index = selected_index
        self._stream_samplerate = int(round(device_info.get("default_samplerate") or config.AUDIO_SAMPLE_RATE))
        max_channels = max(1, int(device_info.get("max_input_channels", config.AUDIO_CHANNELS)))
        self._max_input_channels = max_channels
        self._input_channel = min(requested_channel, max_channels - 1)
        self._input_device_name = str(device_info.get("name", "") or device_name or "System default microphone")
        # Open only the channels needed to reach the selected input. Auto mode
        # keeps a tiny stereo pair open so driver channel swaps after restart can
        # be corrected while still avoiding broad loopback capture.
        self._channels = max(1, min(max_channels, self._input_channel + 1))
        if self._auto_input_channel and max_channels > 1:
            self._channels = max(self._channels, min(max_channels, AUTO_CHANNEL_CAPTURE_LIMIT))
        configured_blocksize = int(config.AUDIO_BLOCKSIZE or 0)
        chunk_blocksize = max(1, int(round(self._stream_samplerate * self._streaming_audio_chunk_ms / 1000.0)))
        if configured_blocksize > 0:
            self._stream_blocksize = max(1, min(configured_blocksize, chunk_blocksize))
        else:
            self._stream_blocksize = chunk_blocksize

        current = (
            self._device_index,
            self._input_channel,
            self._channels,
            self._stream_samplerate,
            self._warm_stream,
            self._streaming_audio_chunk_ms,
            self._auto_input_channel,
            self._max_input_channels,
        )
        if self._stream is not None and not self._recording and current != previous:
            self.close()
            if self._warm_stream:
                self.prepare()

    def _probe_active_input_channel(self):
        if not self._auto_input_channel or self._recording or self._stream is not None:
            return

        try:
            device_info = (
                sd.query_devices(self._device_index, "input")
                if self._device_index is not None
                else sd.query_devices(kind="input")
            )
        except Exception:
            return

        max_channels = max(1, int(device_info.get("max_input_channels", self._channels)))
        if max_channels <= 1:
            return

        samplerate = int(round(device_info.get("default_samplerate") or self._stream_samplerate))
        probe_key = (self._device_index, samplerate, max_channels)
        if probe_key == self._last_probe_key:
            return
        self._last_probe_key = probe_key

        scan_channels = min(max_channels, AUTO_CHANNEL_SCAN_LIMIT)
        while scan_channels > 1:
            try:
                frames = max(1, int(samplerate * AUTO_CHANNEL_PROBE_SECONDS))
                audio = sd.rec(
                    frames,
                    samplerate=samplerate,
                    channels=scan_channels,
                    dtype=config.AUDIO_DTYPE,
                    device=self._device_index,
                )
                sd.wait()
                data = np.asarray(audio, dtype=np.float32)
                if data.ndim == 1:
                    data = data.reshape(-1, 1)
                rms = np.sqrt(np.mean(data * data, axis=0))
                best_channel = int(np.argmax(rms))
                best_rms = float(rms[best_channel])
                current_channel = min(self._input_channel, len(rms) - 1)
                current_rms = float(rms[current_channel])
                if (
                    best_channel != self._input_channel
                    and best_rms >= AUTO_CHANNEL_MIN_RMS
                    and best_rms >= max(AUTO_CHANNEL_MIN_RMS, current_rms * AUTO_CHANNEL_DOMINANCE)
                ):
                    print(
                        "Mic auto-selected input channel "
                        f"{best_channel + 1} on {self._input_device_name} "
                        f"(rms {best_rms:.6f} vs {current_rms:.6f})",
                        flush=True,
                    )
                    self._input_channel = best_channel
                    self._channels = max(1, min(max_channels, self._input_channel + 1))
                    if self._auto_input_channel and max_channels > 1:
                        self._channels = max(self._channels, min(max_channels, AUTO_CHANNEL_CAPTURE_LIMIT))
                return
            except Exception:
                scan_channels = min(scan_channels - 1, max(1, scan_channels // 2))

    def _open_stream(self):
        if self._stream is not None:
            return

        self._probe_active_input_channel()
        stream = sd.InputStream(
            samplerate=self._stream_samplerate,
            channels=self._channels,
            dtype=config.AUDIO_DTYPE,
            blocksize=self._stream_blocksize,
            device=self._device_index,
            callback=self._callback,
        )
        stream.start()
        self._stream = stream

    def prepare(self):
        """Warm the input stream so the next dictation can start instantly."""
        if not self._warm_stream:
            return
        self._open_stream()

    def start(self):
        """Open the mic stream and begin recording."""
        with self._lock:
            self._buffer.clear()
            self._visual_buffer[:] = 0.0
            self._visual_len = 0
            self._visual_pos = 0
        self._start_backup_cache()
        self._recording = True
        try:
            if self._stream is None:
                self._open_stream()
        except Exception:
            self._recording = False
            self._finish_backup_cache()
            raise

    def stop(self) -> np.ndarray:
        """Stop recording and return the full audio as a 1-D float32 array."""
        self._recording = False
        if self._stream is not None and not self._warm_stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._finish_backup_cache()
        with self._lock:
            if self._buffer:
                return np.concatenate(self._buffer, axis=0).flatten().astype(np.float32, copy=False)
            return np.zeros(0, dtype=np.float32)

    def close(self):
        self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._finish_backup_cache()
