"""
Transparent overlay window with a real-time audio waveform and custom dictionary stats.
Uses PyQt6 with a frameless, always-on-top, translucent window.
"""

import os
import numpy as np
import time

from PyQt6.QtCore import (
    Qt,
    QTimer,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QEasingCurve,
    QAbstractAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QLinearGradient, QPen, QBrush, QImage, QPixmap, QFont
from PyQt6.QtWidgets import QApplication, QWidget, QGraphicsOpacityEffect
try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QUrl = None
    QWebEngineSettings = None
    QWebEngineView = None
from PIL import Image, ImageFilter

import config
from core.settings import load_settings, save_settings

NUM_BARS = 88
NOISE_FLOOR = 0.004
VISUAL_GAIN = 20.0
VISUAL_MIN_GAIN = 6.0
VISUAL_MAX_GAIN = 80.0
VISUAL_NOISE_FLOOR = 0.0012
VISUAL_GATE_FLOOR = 0.0018
VISUAL_TARGET_LEVEL = 0.24
VISUAL_GAIN_UP_SMOOTHING = 0.10
VISUAL_GAIN_DOWN_SMOOTHING = 0.22
VISUAL_GAIN_RESET_SMOOTHING = 0.025
VISUAL_RESPONSE_CURVE = 0.54
SPEAKING_THRESHOLD = 0.02
WAVE_CENTER_THRESHOLD = 0.014
SMOOTHING = 0.46
COLLAPSED_PILL_WIDTH = 72
EXPANDED_PILL_WIDTH = 240
COLLAPSED_PILL_HEIGHT = 30
EXPANDED_PILL_HEIGHT = 54
LOADING_CIRCLE_SIZE = COLLAPSED_PILL_HEIGHT
LOADING_ORBIT_DOTS = COLLAPSED_VISIBLE_BARS = 9
LOADING_ORBIT_RADIUS = 8.8
LOADING_DOT_SIZE = 2.55
LOADING_SPIN_SPEED = 0.010
LOADING_MORPH_EASE = 0.075
LOADING_HOVER_ICON_DISTANCE = 45.0
LOCK_DILATE_WIDTH = 12
LOCK_DILATE_HEIGHT = 6
HOVER_DILATE_WIDTH = 74
HOVER_DILATE_HEIGHT = 10
HOVER_CONTROL_SPACE = 36
HOVER_EASE_IN = 0.18
HOVER_EASE_OUT = 0.12
HOVER_ICON_EASE_IN = 0.26
HOVER_ICON_EASE_OUT = 0.48
DRAG_HANDLE_WIDTH = 34.0
DRAG_HANDLE_HEIGHT = 3.5
DRAG_HANDLE_GAP = 11.0
DRAG_HANDLE_ALPHA = 128
SNAP_MARGIN = 18
EDGE_SNAP_DISTANCE = 64
CENTER_MAGNET_ZONE_WIDTH = 500
CENTER_MAGNET_ZONE_HEIGHT = 500
CENTER_MAGNET_BELOW_SLOP = 80
CENTER_MAGNET_DIRECTION_SLOP = 8
CENTER_MAGNET_HOLD_MS = 200
SNAP_DURATION_MS = 260
REPAINT_INTERVAL_MS = 16
EXPANSION_SMOOTHING = 0.18
MIN_VISIBLE_BARS = 9
EXPANDED_VISIBLE_BARS = 34
EDGE_TAPER_FACTORS = (0.48, 0.62, 0.78, 0.92)
BAR_GAP = 3.5
BAR_WIDTH = 2.7
DOT_SIZE = 3.2
PROCESSING_DOT_COUNT = 9
PROCESSING_WAVE_SPEED = 0.28
PROCESSING_WAVE_HEIGHT = 3.4
MINI_IDLE_WAVE_SPEED = PROCESSING_WAVE_SPEED * 0.21
IDLE_WAVE_HEIGHT = 2.4
SILENCE_WAVE_DELAY_S = 0.5
WAVE_BLEND_EASE_IN = 0.032
WAVE_BLEND_EASE_OUT = 0.14
WAVE_OFFSET_EASE_TO_SINE = 0.095
WAVE_OFFSET_EASE_TO_CENTER = 0.20
BLUR_CACHE_TTL_S = 30.0
FADE_OUT_MS = 150
WAVEFORM_COLOR = QColor(228, 229, 235, 230)
MODEL_LOADING_LABEL_GAP = 6.0
MODEL_LOADING_LABEL_HEIGHT = 18.0
NO_AUDIO_INPUT_RMS = 0.00012
NO_AUDIO_INPUT_DELAY_S = 1.2
WAVE_LIGHTS_ENV = "WHISPERER_EXPERIMENT_WAVE_LIGHTS"
WAVE_LIGHTS_ASSET = os.path.join(config.PROJECT_ROOT, "assets", "overlay_wave_lights.html")
WAVE_LIGHTS_WIDTH = 392.0
WAVE_LIGHTS_HEIGHT = 86.0
WAVE_LIGHTS_CONTROL_GUTTER = 48.0
WAVE_LIGHTS_BANDS = 24
OVERLAY_STYLE_WAVEFORM = "waveform"
OVERLAY_STYLE_LIGHT_WAVE = "light_wave"


class WaveformOverlay(QWidget):
    open_ui_requested = pyqtSignal()
    force_stop_requested = pyqtSignal()

    """
    A pill-shaped transparent overlay that sits near the bottom-center of the
    screen and draws a live audio waveform and scrolling transcribed text.
    Hidden by default — shown on hotkey press, hidden after paste.
    """

    def __init__(self):
        super().__init__()
        self._audio_chunk: np.ndarray | None = None
        self._active = False
        self._status_text = "Listening..."
        self._bar_heights = np.zeros(NUM_BARS, dtype=np.float64)
        self._bar_targets = np.zeros(NUM_BARS, dtype=np.float64)
        self._visual_gain = VISUAL_GAIN
        self._expansion = 0.0
        self._transcribed_words = ""
        self._word_positions = []
        self._scroll_offset = 0.0
        self._word_timer = QTimer(self)
        self._word_timer.timeout.connect(self._update_scroll)
        self._drag_handle_rect = QRectF()
        self._dragging = False
        self._drag_offset = QPoint()
        self._drag_started_near_default = False
        self._center_magnet_armed = False
        self._last_default_distance: float | None = None
        self._drag_available_geometry: QRect | None = None
        self._drag_default_position: QPoint | None = None
        self._lock_glow = 0.0
        self._hover_progress = 0.0
        self._save_after_position_anim = False
        self._model_loading = False
        self._loading_ready_preview = False
        self._loading_morph = 1.0
        self._loading_morph_target = 1.0
        self._loading_spin_phase = 0.0
        self._no_audio_since: float | None = None
        self._no_audio_warning = False
        self._wave_lights_view = None
        self._wave_lights_loaded = False
        self._wave_lights_last_level = -1.0
        self._wave_lights_bands = np.zeros(WAVE_LIGHTS_BANDS, dtype=np.float64)
        self._wave_lights_last_bands_ts = 0.0
        self._wave_lights_available = QWebEngineView is not None and os.path.exists(WAVE_LIGHTS_ASSET)
        self._wave_lights_failed = False
        self._wave_lights_enabled = self._wave_lights_available and self._selected_overlay_style() == OVERLAY_STYLE_LIGHT_WAVE
        self._init_window()
        if self._wave_lights_enabled:
            self._init_wave_lights_view()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(90)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._position_anim = QPropertyAnimation(self, b"pos")
        self._position_anim.setDuration(SNAP_DURATION_MS)
        self._position_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._position_anim.finished.connect(self._on_position_animation_finished)

        self._magnet_timer = QTimer(self)
        self._magnet_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._magnet_timer.setSingleShot(True)
        self._magnet_timer.timeout.connect(self._snap_to_default_if_still_near)

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._repaint_timer.timeout.connect(self.update)
        self._blur_cache = None
        self._blur_cache_pixmap = QPixmap()
        self._blur_cache_ts = 0.0
        self._blur_cache_key = None
        self._blur_request_id = 0
        self._blur_refresh_pending = False
        self._last_blur_refresh_request_ts = 0.0

        self._mode_name = ""
        self._state = "normal"
        self._locked = False
        self._lock_glow = 0.0
        self._processing = False
        self._processing_phase = 0.0
        self._idle_phase = 0.0
        self._wave_offsets = np.zeros(EXPANDED_VISIBLE_BARS, dtype=np.float64)
        self._speech_latched = False
        self._last_voice_time = 0.0
        self._wave_blend = 1.0
        self._wave_centered_by_audio = False
        self._idle_wave_allowed = True
        self._fading_out = False
        self._hover_target = 0.0
        self._hover_progress = 0.0
        self._hover_icon_progress = 0.0
        self._model_loading = False
        self._loading_ready_preview = False
        self._loading_morph = 1.0
        self._loading_morph_target = 1.0
        self._loading_spin_phase = 0.0
        self._gear_hit_rect = QRectF()
        self._stop_hit_rect = QRectF()
        self._no_audio_since = None
        self._no_audio_warning = False

    def _selected_overlay_style(self) -> str:
        try:
            overlay_settings = load_settings().get("overlay", {})
            style = overlay_settings.get("visualizer_style")
        except Exception:
            style = None
        if style in (OVERLAY_STYLE_WAVEFORM, OVERLAY_STYLE_LIGHT_WAVE):
            return str(style)
        if os.environ.get(WAVE_LIGHTS_ENV) == "1":
            return OVERLAY_STYLE_LIGHT_WAVE
        return OVERLAY_STYLE_WAVEFORM

    def _refresh_wave_lights_selection(self):
        enabled = (
            self._wave_lights_available
            and not self._wave_lights_failed
            and self._selected_overlay_style() == OVERLAY_STYLE_LIGHT_WAVE
        )
        self._wave_lights_enabled = enabled
        if enabled and self._wave_lights_view is None:
            self._init_wave_lights_view()
        elif not enabled and self._wave_lights_view is not None:
            self._wave_lights_view.hide()
            if self._wave_lights_loaded:
                self._wave_lights_view.page().runJavaScript(
                    "window.setOverlayActive && window.setOverlayActive(false);"
                )
        self._sync_wave_lights_visibility()

    def _init_wave_lights_view(self):
        try:
            view = QWebEngineView(self)
            view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            view.setAutoFillBackground(False)
            if QWebEngineSettings is not None:
                settings = view.settings()
                settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
                if hasattr(QWebEngineSettings.WebAttribute, "WebGLEnabled"):
                    settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
            view.page().setBackgroundColor(QColor(0, 0, 0, 0))
            view.loadFinished.connect(self._on_wave_lights_loaded)
            view.load(QUrl.fromLocalFile(os.path.abspath(WAVE_LIGHTS_ASSET)))
            view.hide()
            self._wave_lights_view = view
        except Exception as exc:
            print(f"Wave Lights experiment unavailable: {exc}", flush=True)
            self._wave_lights_failed = True
            self._wave_lights_enabled = False
            self._wave_lights_view = None

    def _on_wave_lights_loaded(self, ok: bool):
        self._wave_lights_loaded = bool(ok)
        if not ok:
            self._wave_lights_failed = True
            self._wave_lights_enabled = False
            if self._wave_lights_view is not None:
                self._wave_lights_view.hide()
            return
        self._sync_wave_lights_visibility()

    def _wave_lights_should_show(self) -> bool:
        return (
            self._wave_lights_enabled
            and self._wave_lights_view is not None
            and self._wave_lights_loaded
            and self.isVisible()
            and not self._loading_visual_active()
            and not self._processing
            and self._state == "normal"
        )

    def _wave_lights_layout_active(self) -> bool:
        return (
            bool(getattr(self, "_wave_lights_enabled", False))
            and not self._loading_visual_active()
            and not getattr(self, "_processing", False)
            and getattr(self, "_state", "normal") == "normal"
        )

    def _sync_wave_lights_visibility(self):
        if self._wave_lights_view is None:
            return
        show = self._wave_lights_should_show()
        self._wave_lights_view.setVisible(show)
        if self._wave_lights_loaded:
            active = "true" if show and not self._fading_out else "false"
            self._wave_lights_view.page().runJavaScript(f"window.setOverlayActive && window.setOverlayActive({active});")

    def _update_wave_lights_geometry(self, panel: QRectF):
        if self._wave_lights_view is None:
            return
        rect = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        if rect.width() <= 8 or rect.height() <= 8:
            self._wave_lights_view.hide()
            return
        self._wave_lights_view.setGeometry(
            int(round(rect.left())),
            int(round(rect.top())),
            max(1, int(round(rect.width()))),
            max(1, int(round(rect.height()))),
        )
        self._sync_wave_lights_visibility()

    def _wave_lights_active(self) -> bool:
        return self._wave_lights_should_show()

    def _send_wave_lights_level(self, level: float):
        if self._wave_lights_view is None or not self._wave_lights_loaded:
            return
        level = max(0.0, min(1.0, float(level)))
        if abs(level - self._wave_lights_last_level) < 0.045:
            return
        self._wave_lights_last_level = level
        self._wave_lights_view.page().runJavaScript(f"window.setMicLevel && window.setMicLevel({level:.4f});")

    def _compute_wave_lights_bands(self, chunk: np.ndarray | None) -> list[float]:
        if chunk is None or len(chunk) < 32:
            self._wave_lights_bands *= 0.90
            return self._wave_lights_bands.tolist()
        try:
            data = chunk.astype(np.float32, copy=False)
            data = data[-min(len(data), 4096):]
            data = data - float(np.mean(data))
            rms = float(np.sqrt(np.mean(data * data))) if len(data) else 0.0
            voice_weight = max(0.0, min(1.0, (rms - 0.0025) * 55.0))
            if voice_weight <= 0.015:
                self._wave_lights_bands *= 0.82
                return self._wave_lights_bands.tolist()
            window = np.hanning(len(data)).astype(np.float32)
            spectrum = np.abs(np.fft.rfft(data * window))
            freqs = np.fft.rfftfreq(len(data), 1.0 / float(config.AUDIO_SAMPLE_RATE))
            edges = np.geomspace(80.0, 5200.0, WAVE_LIGHTS_BANDS + 1)
            bands = np.zeros(WAVE_LIGHTS_BANDS, dtype=np.float64)
            for i in range(WAVE_LIGHTS_BANDS):
                mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
                if np.any(mask):
                    bands[i] = float(np.mean(spectrum[mask]))
            bands = np.log1p(bands * 85.0)
            bands = np.clip((bands / 2.15) ** 0.70, 0.0, 1.0)
            bands *= voice_weight
            rising = bands > self._wave_lights_bands
            ease = np.where(rising, 0.72, 0.10)
            self._wave_lights_bands += (bands - self._wave_lights_bands) * ease
        except Exception:
            self._wave_lights_bands *= 0.90
        return self._wave_lights_bands.tolist()

    def _send_wave_lights_bands(self, bands: list[float]):
        if self._wave_lights_view is None or not self._wave_lights_loaded:
            return
        now = time.monotonic()
        if now - self._wave_lights_last_bands_ts < 0.025:
            return
        self._wave_lights_last_bands_ts = now
        payload = ",".join(f"{max(0.0, min(1.0, float(value))):.3f}" for value in bands)
        self._wave_lights_view.page().runJavaScript(f"window.setSpectrum && window.setSpectrum([{payload}]);")

    def _reset_visual_gain(self):
        self._visual_gain = VISUAL_GAIN

    def _init_window(self):
        self.setWindowTitle("Whisper Overlay")
        self.setFixedSize(config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._position_on_screen()

    def _desktop_geometry(self) -> QRect:
        screens = QApplication.screens()
        if not screens:
            return QRect()
        desktop = QRect(screens[0].geometry())
        for screen in screens[1:]:
            desktop = desktop.united(screen.geometry())
        return desktop

    def _available_geometry_for_position(self, pos: QPoint | None = None) -> QRect:
        if self._dragging and self._drag_available_geometry is not None:
            return QRect(self._drag_available_geometry)
        panel = self._panel_global_rect(self.pos() if pos is None else pos)
        screen = QApplication.screenAt(panel.center().toPoint()) or self.screen() or QApplication.primaryScreen()
        if screen:
            return QRect(screen.availableGeometry())
        return self._desktop_geometry()

    def _panel_global_rect(self, pos: QPoint | None = None) -> QRectF:
        pos = self.pos() if pos is None else pos
        panel = self._panel_rect(self.width(), self.height())
        return QRectF(pos.x() + panel.left(), pos.y() + panel.top(), panel.width(), panel.height())

    def _clamp_to_desktop(self, pos: QPoint, margin: int = 0) -> QPoint:
        desktop = self._available_geometry_for_position(pos)
        if desktop.isNull():
            return pos
        panel = self._panel_rect(self.width(), self.height())
        min_x = desktop.left() + margin - panel.left()
        max_x = desktop.left() + desktop.width() - margin - panel.right()
        min_y = desktop.top() + margin - panel.top()
        max_y = desktop.top() + desktop.height() - margin - panel.bottom()
        if max_x < min_x:
            max_x = min_x
        if max_y < min_y:
            max_y = min_y
        x = min(max(pos.x(), round(min_x)), round(max_x))
        y = min(max(pos.y(), round(min_y)), round(max_y))
        return QPoint(x, y)

    def _clear_blur_cache(self):
        self._blur_cache = None
        self._blur_cache_pixmap = QPixmap()
        self._blur_cache_key = None

    def _refresh_blur_after_position_change(self, delay_ms: int = 80):
        self._clear_blur_cache()
        if self.isVisible() and not self._fading_out:
            self._request_blur_refresh(delay_ms, force=True)
            self._repaint_timer.start(REPAINT_INTERVAL_MS)

    def _request_blur_refresh(self, delay_ms: int = 120, *, force: bool = False):
        now = time.monotonic()
        if not force and (self._blur_refresh_pending or now - self._last_blur_refresh_request_ts < 0.30):
            return
        self._last_blur_refresh_request_ts = now
        self._blur_refresh_pending = True
        self._blur_request_id += 1
        blur_request_id = self._blur_request_id
        panel = self._panel_global_rect()
        screen = QApplication.screenAt(panel.center().toPoint()) or self.screen()
        if not screen:
            self._blur_refresh_pending = False
            self.update()
            return

        ratio = screen.devicePixelRatio()
        geo = self.geometry()
        scr_geo = screen.geometry()
        local_x = geo.x() - scr_geo.x()
        local_y = geo.y() - scr_geo.y()
        w, h = geo.width(), geo.height()
        px_w = int(w * ratio)
        px_h = int(h * ratio)
        if px_w <= 0 or px_h <= 0:
            self._blur_refresh_pending = False
            self.update()
            return
        px_x = int(local_x * ratio)
        px_y = int(local_y * ratio)

        QTimer.singleShot(
            max(0, int(delay_ms)),
            lambda: self._grab_blur_then_show(
                blur_request_id, screen, px_x, px_y, px_w, px_h, ratio, w, h
            ),
        )

    def _stop_position_animation(self):
        if self._position_anim.state() != QAbstractAnimation.State.Stopped:
            self._position_anim.stop()

    def _saved_position(self) -> QPoint | None:
        try:
            settings = load_settings()
            overlay = settings.get("overlay")
            if not isinstance(overlay, dict):
                return None
            pos = overlay.get("position")
            if not isinstance(pos, dict):
                return None
            x = int(pos.get("x"))
            y = int(pos.get("y"))
            return QPoint(x, y)
        except (TypeError, ValueError, OSError):
            return None

    def _save_position(self):
        try:
            settings = load_settings()
            overlay = settings.get("overlay")
            if not isinstance(overlay, dict):
                overlay = {}
                settings["overlay"] = overlay
            overlay["position"] = {"x": self.x(), "y": self.y()}
            save_settings(settings)
        except OSError:
            pass

    def _default_position(self) -> QPoint | None:
        screen = QApplication.primaryScreen()
        if not screen:
            return None
        geo = screen.geometry()
        available = screen.availableGeometry()
        x = round(geo.x() + (geo.width() - self.width()) / 2)
        target_panel_bottom = available.bottom() + 1 - config.OVERLAY_BOTTOM_MARGIN
        y = round(target_panel_bottom - (self.height() + EXPANDED_PILL_HEIGHT) / 2)
        return QPoint(x, y)

    def _position_on_screen(self):
        pos = self._saved_position() or self._default_position()
        if pos is not None:
            if hasattr(self, "_position_anim"):
                self._stop_position_animation()
            self.move(self._clamp_to_desktop(pos))

    def _default_position_metrics(self, pos: QPoint | None = None) -> tuple[float, float, float] | None:
        default = self._drag_default_position if self._dragging and self._drag_default_position is not None else self._default_position()
        if default is None:
            return None
        current_panel = self._panel_global_rect(self.pos() if pos is None else pos)
        default_panel = self._panel_global_rect(default)
        dx = abs(current_panel.center().x() - default_panel.center().x())
        bottom_offset = default_panel.bottom() - current_panel.bottom()
        bottom_delta = abs(bottom_offset)
        return dx, bottom_offset, bottom_delta

    def _default_position_distance(self, pos: QPoint | None = None) -> float | None:
        metrics = self._default_position_metrics(pos)
        if metrics is None:
            return None
        dx, _bottom_offset, bottom_delta = metrics
        return float((dx * dx + bottom_delta * bottom_delta) ** 0.5)

    def _is_near_default_position(self, pos: QPoint | None = None, *, release: bool = False) -> bool:
        metrics = self._default_position_metrics(pos)
        if metrics is None:
            return False
        dx, bottom_offset, _bottom_delta = metrics
        half_width = CENTER_MAGNET_ZONE_WIDTH / 2
        return (
            dx <= half_width
            and bottom_offset >= -CENTER_MAGNET_BELOW_SLOP
            and bottom_offset <= CENTER_MAGNET_ZONE_HEIGHT
        )

    def _has_left_default_magnet_zone(self, pos: QPoint | None = None) -> bool:
        return not self._is_near_default_position(pos, release=True)

    def _edge_snap_target(self, pos: QPoint | None = None) -> QPoint | None:
        pos = self.pos() if pos is None else pos
        geo = self._available_geometry_for_position(pos)
        if geo.isNull():
            return None
        panel = self._panel_rect(self.width(), self.height())
        global_panel = self._panel_global_rect(pos)
        target_x = pos.x()
        target_y = pos.y()
        snapped = False

        left_gap = global_panel.left() - geo.left()
        right_gap = geo.left() + geo.width() - global_panel.right()
        top_gap = global_panel.top() - geo.top()
        bottom_gap = geo.top() + geo.height() - global_panel.bottom()

        if left_gap <= EDGE_SNAP_DISTANCE:
            target_x = round(geo.left() + SNAP_MARGIN - panel.left())
            snapped = True
        elif right_gap <= EDGE_SNAP_DISTANCE:
            target_x = round(geo.left() + geo.width() - SNAP_MARGIN - panel.right())
            snapped = True

        if top_gap <= EDGE_SNAP_DISTANCE:
            target_y = round(geo.top() + SNAP_MARGIN - panel.top())
            snapped = True
        elif bottom_gap <= EDGE_SNAP_DISTANCE:
            target_y = round(geo.top() + geo.height() - SNAP_MARGIN - panel.bottom())
            snapped = True

        if not snapped:
            return None
        return self._clamp_to_desktop(QPoint(target_x, target_y), margin=SNAP_MARGIN)

    def _release_snap_target(self) -> QPoint | None:
        default = self._default_position()
        if default is not None and self._center_magnet_armed and self._is_near_default_position(release=True):
            return self._clamp_to_desktop(default)
        return self._edge_snap_target()

    def _animate_to_position(self, target: QPoint, *, save_when_done: bool):
        target = self._clamp_to_desktop(target)
        if target == self.pos():
            if save_when_done:
                self._save_position()
            self._refresh_blur_after_position_change()
            return
        self._save_after_position_anim = save_when_done
        self._stop_position_animation()
        self._position_anim.setStartValue(self.pos())
        self._position_anim.setEndValue(target)
        self._position_anim.start()

    def _on_position_animation_finished(self):
        if self._save_after_position_anim:
            self._save_position()
            self._save_after_position_anim = False
        self._refresh_blur_after_position_change()

    def _snap_to_default_if_still_near(self):
        if not self._dragging or not self._center_magnet_armed or not self._is_near_default_position():
            return
        target = self._drag_default_position or self._default_position()
        if target is None:
            return
        target = self._clamp_to_desktop(target)
        self._dragging = False
        self._drag_started_near_default = False
        self._center_magnet_armed = False
        self._last_default_distance = None
        self._drag_available_geometry = None
        self._drag_default_position = None
        self._clear_blur_cache()
        self._animate_to_position(target, save_when_done=True)

    def fade_in(self, *, keep_model_loading: bool = False):
        self._refresh_wave_lights_selection()
        self._position_on_screen()
        self._bar_heights[:] = 0.0
        self._reset_visual_gain()
        self._expansion = 0.0
        self._transcribed_words = ""
        self._word_positions = []
        self._scroll_offset = 0.0
        self._is_bright_background = False
        self._state = "normal"
        self._locked = False
        self._lock_glow = 0.0
        self._processing = False
        self._processing_phase = 0.0
        self._idle_phase = 0.0
        self._wave_offsets[:] = 0.0
        self._speech_latched = False
        self._last_voice_time = 0.0
        self._wave_blend = 1.0
        self._wave_centered_by_audio = False
        self._idle_wave_allowed = True
        self._fading_out = False
        self._hover_target = 0.0
        self._hover_progress = 0.0
        self._hover_icon_progress = 0.0
        if not keep_model_loading:
            self._model_loading = False
            self._loading_ready_preview = False
            self._loading_morph = 1.0
            self._loading_morph_target = 1.0
        self._no_audio_since = None
        self._no_audio_warning = False
        self._gear_hit_rect = QRectF()
        self._stop_hit_rect = QRectF()
        
        self._word_timer.start(50)
        self._repaint_timer.start(REPAINT_INTERVAL_MS)
        self._fade_anim.stop()
        try:
            self._fade_anim.finished.disconnect(self._on_fade_out_done)
        except TypeError:
            pass
        self._fade_anim.setDuration(90)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(1.0)

        self.show()
        self.raise_()
        self._fade_anim.start()
        self._request_blur_refresh(120)
        self._sync_wave_lights_visibility()

    def _grab_blur_then_show(self, request_id, screen, px_x, px_y, px_w, px_h, ratio, logic_w, logical_h):
        if request_id != self._blur_request_id:
            self._blur_refresh_pending = False
            return
        try:
            logical_ratio = max(1.0, float(ratio or 1.0))
            scr_geo = screen.geometry()
            logical_w = max(1, int(logic_w))
            logical_h = max(1, int(logical_h))
            logical_x = max(0, min(round(px_x / logical_ratio), max(0, scr_geo.width() - logical_w)))
            logical_y = max(0, min(round(px_y / logical_ratio), max(0, scr_geo.height() - logical_h)))

            pixmap = screen.grabWindow(0, logical_x, logical_y, logical_w, logical_h)
            if pixmap.isNull():
                full = screen.grabWindow(0)
                if not full.isNull():
                    px_x = max(0, min(px_x, full.width() - px_w))
                    px_y = max(0, min(px_y, full.height() - px_h))
                    if px_w > 0 and px_h > 0:
                        pixmap = full.copy(px_x, px_y, px_w, px_h)

            if not pixmap.isNull():
                    img = pixmap.toImage()
                    capture_w = img.width()
                    capture_h = img.height()
                    capture_ratio = pixmap.devicePixelRatio() or ratio
                    if capture_w <= 0 or capture_h <= 0:
                        return
                    
                    # Calculate luminance to determine dark/light background
                    scaled_img = img.scaled(1, 1)
                    if not scaled_img.isNull():
                        color = scaled_img.pixelColor(0, 0)
                        luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
                        self._is_bright_background = luminance > 140
                        
                    if not img.isNull():
                        # Extract raw pixels to Pillow for an ultra-fast box blur
                        ptr = img.bits()
                        ptr.setsize(img.sizeInBytes())
                        arr = np.frombuffer(ptr, np.uint8).reshape((capture_h, capture_w, 4))
                        
                        # Convert to PIL Image (BGRA -> RGBA)
                        pil_img = Image.fromarray(arr, 'RGBA')
                        b, g, r, a = pil_img.split()
                        pil_img = Image.merge("RGBA", (r, g, b, a))
                        
                        # Apply fast blur (scaled by ratio to keep effect consistent)
                        # We use a smaller radius (12 instead of 18) for a tighter blur
                        # BoxBlur is already the fastest high-quality blur available in Python/Pillow
                        # that gives a real frosted glass effect without tanking performance.
                        blurred_pil = pil_img.filter(ImageFilter.BoxBlur(12 * ratio))
                        
                        # Back to numpy, swap channels back to BGRA for Qt
                        arr_blur = np.array(blurred_pil)
                        r, g, b, a = arr_blur[:,:,0], arr_blur[:,:,1], arr_blur[:,:,2], arr_blur[:,:,3]
                        bgra = np.dstack([b, g, r, a])
                        
                        # Store in Qt cache with correct device pixel ratio
                        qimg = QImage(bgra.data, capture_w, capture_h, capture_w * 4, QImage.Format.Format_ARGB32)
                        qimg.setDevicePixelRatio(capture_ratio)
                        if request_id == self._blur_request_id:
                            self._blur_cache = qimg.copy()
                            self._blur_cache_pixmap = QPixmap.fromImage(self._blur_cache)
                            self._blur_cache_ts = time.monotonic()
                            self._blur_cache_key = (screen.name(), self.geometry().getRect())
                            self.update()
        except Exception as e:
            print(f"Blur failed: {e}")
            pass
        finally:
            if request_id == self._blur_request_id:
                self._blur_refresh_pending = False

    def fade_out(self):
        self._blur_request_id += 1
        self._blur_refresh_pending = False
        self._fading_out = True
        self._sync_wave_lights_visibility()
        self._repaint_timer.start(REPAINT_INTERVAL_MS)
        self._fade_anim.stop()
        self._fade_anim.setDuration(FADE_OUT_MS)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        try:
            self._fade_anim.finished.disconnect(self._on_fade_out_done)
        except TypeError:
            pass
        self._fade_anim.finished.connect(self._on_fade_out_done)
        self._fade_anim.start()

    def _on_fade_out_done(self):
        self._repaint_timer.stop()
        self._word_timer.stop()
        self._audio_chunk = None
        self._active = False
        self._locked = False
        self._lock_glow = 0.0
        self._processing = False
        self._processing_phase = 0.0
        self._idle_phase = 0.0
        self._wave_offsets[:] = 0.0
        self._speech_latched = False
        self._last_voice_time = 0.0
        self._wave_blend = 1.0
        self._wave_centered_by_audio = False
        self._idle_wave_allowed = True
        self._fading_out = False
        self._hover_target = 0.0
        self._hover_progress = 0.0
        self._hover_icon_progress = 0.0
        self._model_loading = False
        self._loading_ready_preview = False
        self._loading_morph = 1.0
        self._loading_morph_target = 1.0
        self._no_audio_since = None
        self._no_audio_warning = False
        self._gear_hit_rect = QRectF()
        self._stop_hit_rect = QRectF()
        self._bar_heights[:] = 0.0
        self._reset_visual_gain()
        self._expansion = 0.0
        self._sync_wave_lights_visibility()
        self.hide()
        try:
            self._fade_anim.finished.disconnect(self._on_fade_out_done)
        except TypeError:
            pass

    def _update_no_audio_warning(self, chunk: np.ndarray | None):
        if not self._active or self._processing or self._model_loading or self._fading_out:
            if self._no_audio_since is not None or self._no_audio_warning:
                self._no_audio_since = None
                self._no_audio_warning = False
                self.update()
            return

        no_input = chunk is None or len(chunk) == 0
        if not no_input:
            try:
                data = chunk.astype(np.float32, copy=False)
                rms = float(np.sqrt(np.mean(data * data)))
                peak = float(np.max(np.abs(data))) if len(data) else 0.0
                no_input = rms <= NO_AUDIO_INPUT_RMS and peak <= NO_AUDIO_INPUT_RMS * 4.0
            except Exception:
                no_input = True

        if no_input:
            now = time.monotonic()
            if self._no_audio_since is None:
                self._no_audio_since = now
            next_warning = now - self._no_audio_since >= NO_AUDIO_INPUT_DELAY_S
            if next_warning != self._no_audio_warning:
                self._no_audio_warning = next_warning
                self.update()
        elif self._no_audio_since is not None or self._no_audio_warning:
            self._no_audio_since = None
            self._no_audio_warning = False
            self.update()

    def set_audio_chunk(self, chunk: np.ndarray | None):
        self._audio_chunk = chunk
        self._update_no_audio_warning(chunk)
        if not self._wave_lights_enabled:
            return
        level = 0.0
        if self._active and chunk is not None and len(chunk) > 0:
            try:
                data = chunk.astype(np.float32, copy=False)
                rms = float(np.sqrt(np.mean(data * data)))
                level = max(0.0, min(1.0, (rms - VISUAL_NOISE_FLOOR) * 13.5))
                level = level ** 0.72
            except Exception:
                level = 0.0
        self._send_wave_lights_level(level)
        self._send_wave_lights_bands(self._compute_wave_lights_bands(chunk if self._active else None))

    def set_active(self, active: bool):
        if active:
            self._refresh_wave_lights_selection()
        self._active = active
        if active:
            self._model_loading = False
            self._loading_ready_preview = False
            self._loading_morph = 1.0
            self._loading_morph_target = 1.0
            self._processing = False
            self._status_text = "Listening..."
            self._no_audio_since = None
            self._no_audio_warning = False
        else:
            self._audio_chunk = None
            self._no_audio_since = None
            self._no_audio_warning = False
            self._locked = False
            if not self.isVisible() and not self._fading_out:
                self._speech_latched = False
                self._last_voice_time = 0.0
                self._wave_blend = 1.0
                self._wave_centered_by_audio = False
                self._idle_wave_allowed = True
                self._wave_offsets[:] = 0.0
        self._sync_wave_lights_visibility()

    def set_status(self, text: str):
        self._status_text = text

    def _loading_visual_active(self) -> bool:
        return self._model_loading or self._loading_ready_preview or self._loading_morph < 0.995

    def _smoothstep(self, value: float) -> float:
        value = min(1.0, max(0.0, value))
        return value * value * (3.0 - 2.0 * value)

    def set_model_loading(self, loading: bool):
        was_loading = self._model_loading
        self._model_loading = bool(loading)
        if loading:
            if not was_loading:
                self._loading_morph = 0.0
                self._loading_spin_phase = 0.0
            self._loading_morph_target = 0.0
            self._loading_ready_preview = False
            self._state = "normal"
            self._processing = False
            self._active = False
            self._locked = False
            self._audio_chunk = None
            self._transcribed_words = ""
            if not was_loading:
                self._bar_heights[:] = 0.0
                self._wave_offsets[:] = 0.0
                self._speech_latched = False
                self._last_voice_time = 0.0
                self._idle_wave_allowed = True
                self._wave_blend = 1.0
            self._repaint_timer.start(REPAINT_INTERVAL_MS)
        elif was_loading:
            self._loading_ready_preview = True
            self._loading_morph_target = 1.0
            self._active = False
            self._processing = False
            self._audio_chunk = None
            self._speech_latched = False
            self._transcribed_words = ""
            self._wave_blend = 1.0
            self._repaint_timer.start(REPAINT_INTERVAL_MS)
        self._sync_wave_lights_visibility()
        self.update()

    def finish_model_loading(self):
        self.set_model_loading(False)

    def show_model_loading(self):
        if self.isVisible() and self._model_loading and not self._fading_out:
            self._word_timer.start(50)
            self._repaint_timer.start(REPAINT_INTERVAL_MS)
            self.show()
            self.raise_()
            self._request_blur_refresh(90)
            self.update()
            return
        if self.isVisible() and (self._model_loading or self._fading_out):
            self.set_model_loading(True)
            self._fading_out = False
            self._word_timer.start(50)
            self._repaint_timer.start(REPAINT_INTERVAL_MS)
            self._fade_anim.stop()
            try:
                self._fade_anim.finished.disconnect(self._on_fade_out_done)
            except TypeError:
                pass
            self._fade_anim.setDuration(80)
            self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade_anim.setStartValue(self._opacity_effect.opacity())
            self._fade_anim.setEndValue(1.0)
            self.show()
            self.raise_()
            self._fade_anim.start()
            self._request_blur_refresh(80, force=True)
            self.update()
            return
        self.set_model_loading(True)
        self.fade_in(keep_model_loading=True)

    def is_interacting(self) -> bool:
        return self._dragging or self._position_anim.state() != QAbstractAnimation.State.Stopped

    def is_locked(self) -> bool:
        return self._locked

    def set_mode(self, name: str):
        self._mode_name = name

    def set_locked(self, locked: bool):
        self._locked = locked
        self.update()

    def set_processing(self, processing: bool):
        self._processing = processing
        if processing:
            self._fading_out = False
            self._active = False
            self._locked = False
            self._audio_chunk = None
            self._state = "normal"
            self._speech_latched = False
            self._last_voice_time = 0.0
            self._wave_blend = 1.0
            self._wave_centered_by_audio = False
            self._idle_wave_allowed = True
            self._wave_offsets[:] = 0.0
            self._bar_heights[:] = 0.0
            self._reset_visual_gain()
            self._processing_phase = 0.0
            self._repaint_timer.start(REPAINT_INTERVAL_MS)
        self._sync_wave_lights_visibility()
        self.update()

    def enterEvent(self, event):
        self._hover_target = 1.0
        self._repaint_timer.start(REPAINT_INTERVAL_MS)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._dragging:
            self._hover_target = 0.0
            self._repaint_timer.start(REPAINT_INTERVAL_MS)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._gear_hit_rect.contains(pos):
                self.open_ui_requested.emit()
                event.accept()
                return
            if self._stop_hit_rect.contains(pos):
                self.force_stop_requested.emit()
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            panel = self._panel_rect(self.width(), self.height())
            if panel.contains(pos) or self._drag_handle_rect.contains(pos):
                self._stop_position_animation()
                self._magnet_timer.stop()
                self._dragging = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._drag_available_geometry = self._available_geometry_for_position(self.pos())
                self._drag_default_position = self._default_position()
                self._drag_started_near_default = self._is_near_default_position(release=True)
                self._center_magnet_armed = not self._drag_started_near_default
                self._last_default_distance = self._default_position_distance()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._stop_position_animation()
            pos = event.globalPosition().toPoint() - self._drag_offset
            clamped = self._clamp_to_desktop(pos)
            self.move(clamped)
            distance = self._default_position_distance(clamped)
            if self._drag_started_near_default and not self._center_magnet_armed:
                if self._has_left_default_magnet_zone(clamped):
                    self._center_magnet_armed = True
                self._magnet_timer.stop()
            else:
                moving_toward_default = (
                    distance is not None
                    and (
                        self._last_default_distance is None
                        or distance < self._last_default_distance - CENTER_MAGNET_DIRECTION_SLOP
                    )
                )
                if self._center_magnet_armed and self._is_near_default_position(clamped) and moving_toward_default:
                    self._magnet_timer.start(CENTER_MAGNET_HOLD_MS)
                else:
                    self._magnet_timer.stop()
            self._last_default_distance = distance
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._magnet_timer.stop()
            target = self._release_snap_target()
            self._drag_started_near_default = False
            self._center_magnet_armed = False
            self._last_default_distance = None
            self._drag_available_geometry = None
            self._drag_default_position = None
            if target is not None:
                self._animate_to_position(target, save_when_done=True)
            else:
                self._save_position()
                self._refresh_blur_after_position_change()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def show_cancelled(self):
        self._state = "cancelled"
        self._status_text = "Cancelled"
        self._bar_heights[:] = 0.0
        self._reset_visual_gain()
        self._expansion = 0.0
        self._audio_chunk = None
        self._active = False
        self._locked = False
        self._lock_glow = 0.0
        self._processing = False
        self._speech_latched = False
        self._last_voice_time = 0.0
        self._wave_blend = 1.0
        self._wave_centered_by_audio = False
        self._idle_wave_allowed = True
        self._wave_offsets[:] = 0.0
        self._fading_out = False
        self.show()
        self.raise_()
        self._opacity_effect.setOpacity(1.0)
        self._repaint_timer.start(REPAINT_INTERVAL_MS)
        QTimer.singleShot(800, self.fade_out)

    def show_error(self, message: str):
        self._state = "error"
        self._status_text = message
        self._bar_heights[:] = 0.0
        self._reset_visual_gain()
        self._expansion = 0.0
        self._audio_chunk = None
        self._active = False
        self._locked = False
        self._lock_glow = 0.0
        self._processing = False
        self._speech_latched = False
        self._last_voice_time = 0.0
        self._wave_blend = 1.0
        self._wave_centered_by_audio = False
        self._idle_wave_allowed = True
        self._wave_offsets[:] = 0.0
        self._fading_out = False
        self.show()
        self.raise_()
        self._opacity_effect.setOpacity(1.0)
        self._repaint_timer.start(REPAINT_INTERVAL_MS)
        QTimer.singleShot(2000, self.fade_out)

    def append_transcribed_text(self, text: str):
        """Append transcribed words and trigger a repaint."""
        self._transcribed_words = text
        self._word_positions = []
        self.update()

    def _update_scroll(self):
        """Smoothly scroll text when it goes off-screen."""
        w = self.width()
        # Get the total width of all words (approximate)
        # If the text exceeds width, increment scroll offset
        font_metrics = self.fontMetrics()
        total_text = f"{self._status_text} • {self._word_count()} words {self._transcribed_words}"
        text_width = font_metrics.horizontalAdvance(total_text)
        
        if text_width > w and self._transcribed_words:
            self._scroll_offset = min(self._scroll_offset + 1.0, text_width - w)
        else:
            self._scroll_offset = 0.0
        
        self.update()

    def _word_count(self) -> int:
        """Get number of words in transcribed text."""
        return len(self._transcribed_words.split()) if self._transcribed_words else 0

    def _mini_idle_wave_should_run(self) -> bool:
        return (
            (self._active or self._model_loading or self._loading_ready_preview)
            and not self._processing
            and not self._fading_out
            and not self._speech_latched
            and not self._transcribed_words
            and self._expansion < 0.18
        )

    def _compute_bar_targets(self) -> np.ndarray:
        """
        Convert raw mic samples into visual-only bar energy. The adaptive gain
        below only changes drawing sensitivity; it never changes recorded audio.
        """
        targets = self._bar_targets
        targets.fill(0.0)

        if not self._active or self._audio_chunk is None or len(self._audio_chunk) == 0:
            self._visual_gain += (VISUAL_GAIN - self._visual_gain) * VISUAL_GAIN_RESET_SMOOTHING
            return targets

        data = self._audio_chunk.astype(np.float32, copy=False)
        overall_rms = float(np.sqrt(np.mean(data ** 2)))

        if overall_rms < VISUAL_GATE_FLOOR:
            self._visual_gain += (VISUAL_GAIN - self._visual_gain) * VISUAL_GAIN_RESET_SMOOTHING
            return targets

        speech_signal = max(0.0, overall_rms - VISUAL_NOISE_FLOOR)
        if speech_signal <= 0.0:
            return targets

        desired_gain = VISUAL_TARGET_LEVEL / max(speech_signal, 0.0007)
        desired_gain = max(VISUAL_MIN_GAIN, min(VISUAL_MAX_GAIN, desired_gain))
        gain_ease = VISUAL_GAIN_DOWN_SMOOTHING if desired_gain < self._visual_gain else VISUAL_GAIN_UP_SMOOTHING
        self._visual_gain += (desired_gain - self._visual_gain) * gain_ease

        chunk_size = max(1, len(data) // NUM_BARS)
        usable = min(len(data), NUM_BARS * chunk_size)
        if usable <= 0:
            return targets
        bars = usable // chunk_size
        reshaped = data[: bars * chunk_size].reshape(bars, chunk_size)
        rms = np.sqrt(np.mean(reshaped * reshaped, axis=1))
        boosted = np.maximum(0.0, rms - VISUAL_NOISE_FLOOR) * self._visual_gain
        targets[:bars] = np.minimum(1.0, boosted) ** VISUAL_RESPONSE_CURVE

        return targets

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
        painter.drawRect(0, 0, w, h)

        if self._fading_out:
            targets = self._bar_heights
        else:
            targets = self._compute_bar_targets()
            self._bar_heights += (targets - self._bar_heights) * SMOOTHING
        bar_peak = float(np.max(self._bar_heights))
        voice_detected = self._active and bar_peak > SPEAKING_THRESHOLD
        wave_centered_by_audio = self._active and bar_peak > WAVE_CENTER_THRESHOLD
        if not self._fading_out:
            self._wave_centered_by_audio = wave_centered_by_audio
        now = time.monotonic()
        if self._model_loading and not self._fading_out:
            self._loading_spin_phase = (self._loading_spin_phase + LOADING_SPIN_SPEED) % (np.pi * 2.0)
        if not self._fading_out:
            self._loading_morph += (self._loading_morph_target - self._loading_morph) * LOADING_MORPH_EASE
            if (
                self._loading_ready_preview
                and self._loading_morph > 0.992
                and not self._model_loading
                and not self._active
            ):
                self._loading_morph = 1.0
            if abs(self._loading_morph_target - self._loading_morph) > 0.002:
                self._repaint_timer.start(REPAINT_INTERVAL_MS)
        if voice_detected and not self._fading_out:
            self._speech_latched = True
        if self._processing and not self._fading_out:
            speaking = 0.0
            self._processing_phase = (self._processing_phase + PROCESSING_WAVE_SPEED) % PROCESSING_DOT_COUNT
        elif self._transcribed_words:
            speaking = 1.0
        else:
            speaking = 1.0 if (voice_detected or self._speech_latched) else 0.0
        if not self._fading_out:
            self._expansion += (speaking - self._expansion) * EXPANSION_SMOOTHING

        active_wave = (
            (self._active or self._model_loading or self._loading_ready_preview)
            and not self._processing
            and not self._fading_out
        )
        if active_wave:
            if wave_centered_by_audio:
                self._last_voice_time = now
            mini_idle_wave = self._mini_idle_wave_should_run()
            if mini_idle_wave:
                self._idle_phase = (self._idle_phase + MINI_IDLE_WAVE_SPEED) % 10000.0
                target_blend = 1.0
            else:
                target_blend = 0.0
                if self._expansion >= 0.18:
                    self._wave_offsets[:] = 0.0
            self._idle_wave_allowed = mini_idle_wave
            easing = WAVE_BLEND_EASE_IN if target_blend > self._wave_blend else WAVE_BLEND_EASE_OUT
            self._wave_blend += (target_blend - self._wave_blend) * easing
        elif not self._processing and not self._fading_out:
            self._wave_centered_by_audio = False
            self._idle_wave_allowed = False
            self._wave_blend = 0.0
            self._wave_offsets[:] = 0.0

        hover_ease = HOVER_EASE_IN if self._hover_target > self._hover_progress else HOVER_EASE_OUT
        self._hover_progress += (self._hover_target - self._hover_progress) * hover_ease
        icon_ease = HOVER_ICON_EASE_IN if self._hover_target > self._hover_icon_progress else HOVER_ICON_EASE_OUT
        self._hover_icon_progress += (self._hover_target - self._hover_icon_progress) * icon_ease
        if (
            abs(self._hover_target - self._hover_progress) > 0.003
            or abs(self._hover_target - self._hover_icon_progress) > 0.003
        ):
            self._repaint_timer.start(REPAINT_INTERVAL_MS)
        lock_target = 1.0 if self._locked else 0.0
        self._lock_glow += (lock_target - self._lock_glow) * 0.24
        panel = self._panel_rect(w, h)
        self._update_wave_lights_geometry(panel)

        self._draw_blurred_background(painter, panel)
        self._draw_drag_handle(painter, panel)
        if self._loading_visual_active():
            self._draw_loading_waveform(painter, panel)
        elif not self._wave_lights_active():
            self._draw_waveform(painter, panel)
        self._draw_hover_controls(painter, panel)
        self._draw_status_text(painter, panel)
        self._draw_no_audio_label(painter, panel)
        self._draw_model_loading_label(painter, panel)

        painter.end()

    def _panel_rect(self, w: int, h: int) -> QRectF:
        if self._loading_visual_active():
            morph = self._smoothstep(self._loading_morph)
            width = LOADING_CIRCLE_SIZE + (COLLAPSED_PILL_WIDTH - LOADING_CIRCLE_SIZE) * morph
            height = LOADING_CIRCLE_SIZE
            lock_dilate = LOCK_DILATE_WIDTH * self._lock_glow
            width += lock_dilate
            height += lock_dilate
            width += HOVER_DILATE_WIDTH * self._hover_progress * morph
            height += HOVER_DILATE_HEIGHT * self._hover_progress * morph
        elif self._wave_lights_layout_active():
            width = WAVE_LIGHTS_WIDTH
            height = WAVE_LIGHTS_HEIGHT
            width += LOCK_DILATE_WIDTH * self._lock_glow
            height += LOCK_DILATE_HEIGHT * self._lock_glow
        else:
            width = COLLAPSED_PILL_WIDTH + (EXPANDED_PILL_WIDTH - COLLAPSED_PILL_WIDTH) * self._expansion
            height = COLLAPSED_PILL_HEIGHT + (EXPANDED_PILL_HEIGHT - COLLAPSED_PILL_HEIGHT) * self._expansion
            width += LOCK_DILATE_WIDTH * self._lock_glow
            height += LOCK_DILATE_HEIGHT * self._lock_glow
            width += HOVER_DILATE_WIDTH * self._hover_progress
            height += HOVER_DILATE_HEIGHT * self._hover_progress
        x = (w - width) / 2
        y = (h - height) / 2
        return QRectF(x, y, width, height)

    def _draw_blurred_background(self, painter: QPainter, panel: QRectF):
        """Draw a SuperWhisper-like compact recording panel."""
        if self._wave_lights_active():
            return

        capsule = panel
        radius = panel.height() / 2
        path = QPainterPath()
        path.addRoundedRect(capsule, radius, radius)

        if self._blur_cache_pixmap and not self._blur_cache_pixmap.isNull() and not self._dragging:
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, self._blur_cache_pixmap)
            painter.restore()

        if self._state == "error":
            fill = QColor(60, 20, 20, 128)
        elif self._state == "cancelled":
            fill = QColor(28, 28, 31, 128)
        else:
            fill = QColor(28, 29, 32, 128)
            if self._lock_glow > 0.01:
                glow = self._lock_glow
                fill = QColor(
                    int(28 + 18 * glow),
                    int(29 + 18 * glow),
                    int(32 + 22 * glow),
                    int(128 + 22 * glow),
                )

        painter.fillPath(path, fill)

        if self._lock_glow > 0.01 and self._state not in ("error", "cancelled"):
            glow = self._lock_glow
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.setPen(QPen(QColor(120, 168, 255, int(24 * glow)), 2.1))
            painter.drawPath(path)
            painter.setPen(QPen(QColor(210, 226, 255, int(34 * glow)), 1.05))
            painter.drawPath(path)

        border = QLinearGradient(panel.left(), panel.top(), panel.right(), panel.bottom())
        if self._state == "error":
            border.setColorAt(0.0, QColor(255, 80, 80, 60))
            border.setColorAt(0.5, QColor(255, 60, 60, 30))
            border.setColorAt(1.0, QColor(255, 40, 40, 15))
        else:
            lock = self._lock_glow
            border.setColorAt(0.0, QColor(255, 255, 255, int(42 + 42 * lock)))
            border.setColorAt(0.45, QColor(220, 234, 255, int(20 + 58 * lock)))
            border.setColorAt(1.0, QColor(120, 168, 255, int(10 + 42 * lock)))
        painter.setPen(QPen(QBrush(border), 1.05 + 0.48 * self._lock_glow))
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawPath(path)

    def _draw_drag_handle(self, painter: QPainter, panel: QRectF):
        progress = max(self._hover_icon_progress, 1.0 if self._dragging else 0.0)
        alpha = int(DRAG_HANDLE_ALPHA * min(1.0, max(0.0, progress)))
        if alpha <= 3:
            self._drag_handle_rect = QRectF()
            return

        handle = QRectF(
            panel.center().x() - DRAG_HANDLE_WIDTH / 2,
            panel.top() - DRAG_HANDLE_GAP,
            DRAG_HANDLE_WIDTH,
            DRAG_HANDLE_HEIGHT,
        )
        self._drag_handle_rect = handle.adjusted(-8.0, -6.0, 8.0, 8.0)

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(238, 240, 246, alpha))
        painter.drawRoundedRect(handle, DRAG_HANDLE_HEIGHT / 2, DRAG_HANDLE_HEIGHT / 2)
        painter.restore()

    def _draw_loading_waveform(self, painter: QPainter, panel: QRectF):
        morph = self._smoothstep(self._loading_morph)
        center = panel.center()
        dot_count = LOADING_ORBIT_DOTS
        bar_width = BAR_WIDTH
        total_width = dot_count * bar_width + (dot_count - 1) * BAR_GAP
        line_start_x = center.x() - total_width / 2
        lock_dilate = self._lock_glow * (1.0 - morph)
        orbit_radius = min(LOADING_ORBIT_RADIUS, max(5.5, panel.height() * 0.30)) + 2.2 * lock_dilate

        clip_path = QPainterPath()
        clip_path.addRoundedRect(panel, panel.height() / 2, panel.height() / 2)
        painter.save()
        painter.setClipPath(clip_path)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(QColor(WAVEFORM_COLOR))

        for i in range(dot_count):
            circle_angle = self._loading_spin_phase + (i / dot_count) * np.pi * 2.0
            circle_x = center.x() + np.cos(circle_angle) * orbit_radius
            circle_y = center.y() + np.sin(circle_angle) * orbit_radius

            line_x = line_start_x + i * (bar_width + BAR_GAP) + bar_width / 2
            sine_angle = ((i - self._idle_phase) / COLLAPSED_VISIBLE_BARS) * np.pi * 2.0
            line_y = center.y() + float(np.sin(sine_angle)) * IDLE_WAVE_HEIGHT * self._wave_blend

            x = circle_x + (line_x - circle_x) * morph
            y = circle_y + (line_y - circle_y) * morph
            dot_size = LOADING_DOT_SIZE + (DOT_SIZE - LOADING_DOT_SIZE) * morph + 0.25 * lock_dilate
            painter.drawEllipse(QRectF(x - dot_size / 2, y - dot_size / 2, dot_size, dot_size))

        painter.restore()

    def _draw_waveform(self, painter: QPainter, panel: QRectF):
        edge_padding = 10 + (16 - 10) * self._expansion
        edge_padding += HOVER_CONTROL_SPACE * self._hover_progress
        waveform_w = panel.width() - edge_padding * 2
        if waveform_w <= 0:
            return

        center_y = panel.center().y()
        max_amp = panel.height() * 0.40

        bar_width = BAR_WIDTH
        visible_bars = min(NUM_BARS, EXPANDED_VISIBLE_BARS)
        total_width = visible_bars * bar_width + (visible_bars - 1) * BAR_GAP
        start_x = panel.center().x() - total_width / 2
        reveal_left = panel.left() + edge_padding
        reveal_right = panel.right() - edge_padding
        fade_width = min(30.0, max(10.0, waveform_w * 0.28))
        collapsed_reveal_left = panel.center().x() - (COLLAPSED_PILL_WIDTH - 20) / 2
        collapsed_reveal_right = panel.center().x() + (COLLAPSED_PILL_WIDTH - 20) / 2
        fade_out_progress = min(1.0, max(0.0, (self._expansion - 0.62) / 0.30))
        edge_fade_strength = 1.0 - (fade_out_progress * fade_out_progress * (3.0 - 2.0 * fade_out_progress))

        clip_path = QPainterPath()
        clip_path.addRoundedRect(panel, panel.height() / 2, panel.height() / 2)
        painter.save()
        painter.setClipPath(clip_path)

        visible_slot = 0
        for i in range(visible_bars):
            source_index = int(round(i * (NUM_BARS - 1) / max(1, visible_bars - 1)))
            amp = self._bar_heights[source_index]
            x = start_x + i * (bar_width + BAR_GAP)
            bar_center = x + bar_width / 2
            if bar_center < reveal_left or bar_center > reveal_right:
                continue

            edge_alpha = 1.0
            if bar_center < collapsed_reveal_left or bar_center > collapsed_reveal_right:
                left_fade = min(1.0, max(0.0, (bar_center - reveal_left) / fade_width))
                right_fade = min(1.0, max(0.0, (reveal_right - bar_center) / fade_width))
                reveal_fade = left_fade * right_fade
                edge_alpha = reveal_fade * edge_fade_strength + (1.0 - edge_fade_strength)
            if edge_alpha <= 0.01:
                continue

            wave_offset = 0.0
            if self._processing and not self._active:
                angle = ((visible_slot - self._processing_phase) / PROCESSING_DOT_COUNT) * np.pi * 2.0
                wave_offset = float(np.sin(angle)) * PROCESSING_WAVE_HEIGHT
            elif (self._active or self._model_loading) and not self._processing:
                slot = min(visible_slot, len(self._wave_offsets) - 1)
                if self._mini_idle_wave_should_run():
                    angle = ((visible_slot - self._idle_phase) / COLLAPSED_VISIBLE_BARS) * np.pi * 2.0
                    target_offset = float(np.sin(angle)) * IDLE_WAVE_HEIGHT * self._wave_blend
                    current_offset = self._wave_offsets[slot]
                    easing = (
                        WAVE_OFFSET_EASE_TO_CENTER
                        if abs(target_offset) < abs(current_offset)
                        else WAVE_OFFSET_EASE_TO_SINE
                    )
                    current_offset += (target_offset - current_offset) * easing
                    self._wave_offsets[slot] = current_offset
                    wave_offset = current_offset
                else:
                    self._wave_offsets[slot] = 0.0
                    wave_offset = 0.0
            elif self._fading_out and not self._processing:
                slot = min(visible_slot, len(self._wave_offsets) - 1)
                wave_offset = float(self._wave_offsets[slot])

            is_idle = amp <= 0.012
            display_amp = amp
            edge_distance = min(i, visible_bars - 1 - i)
            edge_taper = EDGE_TAPER_FACTORS[edge_distance] if edge_distance < len(EDGE_TAPER_FACTORS) else 1.0
            bar_h = max(DOT_SIZE / 2, display_amp * max_amp * edge_taper)

            painter.setPen(QPen(Qt.PenStyle.NoPen))
            if self._state == "error":
                color = QColor(255, 100, 100, int(230 * edge_alpha))
            elif self._state == "cancelled":
                color = QColor(160, 160, 170, int(230 * edge_alpha))
            else:
                color = QColor(WAVEFORM_COLOR)
                color.setAlpha(int(WAVEFORM_COLOR.alpha() * edge_alpha))
                if self._processing and not self._active:
                    color.setAlpha(int(WAVEFORM_COLOR.alpha() * edge_alpha * 0.92))
            painter.setBrush(color)

            if is_idle or (self._processing and not self._active):
                dot_size = DOT_SIZE
                dot_y = center_y
                if wave_offset:
                    dot_y = center_y + wave_offset
                dot_x = x + (bar_width - dot_size) / 2
                painter.drawEllipse(QRectF(dot_x, dot_y - dot_size / 2, dot_size, dot_size))
            else:
                radius = bar_width / 2
                bar_center_y = center_y + wave_offset
                painter.drawRoundedRect(QRectF(x, bar_center_y - bar_h, bar_width, bar_h * 2), radius, radius)
            visible_slot += 1
        painter.restore()

    def _draw_hover_controls(self, painter: QPainter, panel: QRectF):
        icon_progress = min(1.0, max(0.0, self._hover_icon_progress))
        alpha = int(210 * icon_progress)
        if alpha <= 3:
            self._gear_hit_rect = QRectF()
            self._stop_hit_rect = QRectF()
            return

        icon_size = 18.0
        hit_size = 34.0
        center_y = panel.center().y()
        if self._loading_visual_active() and self._loading_morph < 0.35:
            distance = LOADING_HOVER_ICON_DISTANCE + 6.0 * self._hover_progress
            left_center = QPointF(panel.center().x() - distance, center_y)
            right_center = QPointF(panel.center().x() + distance, center_y)
        else:
            left_center = QPointF(panel.left() + 22.0 + 6.0 * self._hover_progress, center_y)
            right_center = QPointF(panel.right() - 22.0 - 6.0 * self._hover_progress, center_y)
        self._gear_hit_rect = QRectF(left_center.x() - hit_size / 2, center_y - hit_size / 2, hit_size, hit_size)
        self._stop_hit_rect = QRectF(right_center.x() - hit_size / 2, center_y - hit_size / 2, hit_size, hit_size)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(236, 238, 244, alpha)

        stop_size = icon_size * 0.58
        gear_path = QPainterPath()
        gear_path.setFillRule(Qt.FillRule.OddEvenFill)
        outer_r = stop_size * 0.667
        root_r = outer_r * 0.78
        first = True
        for step in range(32):
            angle = -np.pi / 2 + step * (np.pi * 2.0 / 32.0)
            radius = outer_r if step % 4 in (0, 1) else root_r
            point = QPointF(
                left_center.x() + np.cos(angle) * radius,
                left_center.y() + np.sin(angle) * radius,
            )
            if first:
                gear_path.moveTo(point)
                first = False
            else:
                gear_path.lineTo(point)
        gear_path.closeSubpath()
        hole_r = outer_r * 0.43
        gear_path.addEllipse(left_center, hole_r, hole_r)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(gear_path)

        stop_rect = QRectF(
            right_center.x() - stop_size / 2,
            right_center.y() - stop_size / 2,
            stop_size,
            stop_size,
        )
        painter.drawRoundedRect(stop_rect, 1.8, 1.8)
        painter.restore()

    def _draw_mode_badge(self, painter: QPainter, panel: QRectF):
        if not self._mode_name:
            return
        font = painter.font()
        font.setPointSize(8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text = self._mode_name
        text_w = metrics.horizontalAdvance(text)
        pad_x = 8
        pad_y = 3
        badge_w = text_w + pad_x * 2
        badge_h = metrics.height() + pad_y * 2 - 4
        badge_x = panel.right() - badge_w - 10
        badge_y = panel.top() - badge_h - 6
        if badge_y < 0:
            badge_y = panel.top() + 6

        rect = QRectF(badge_x, badge_y, badge_w, badge_h)
        path = QPainterPath()
        path.addRoundedRect(rect, badge_h / 2, badge_h / 2)
        painter.setPen(QPen(QColor(100, 160, 255, 120), 1))
        painter.setBrush(QColor(20, 35, 55, 220))
        painter.drawPath(path)
        painter.setPen(QColor(140, 190, 255, 255))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_status_text(self, painter: QPainter, panel: QRectF):
        if self._state not in ("cancelled", "error"):
            return
        font = painter.font()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(240, 240, 240, 255))
        rect = QRectF(panel.left(), panel.top(), panel.width(), panel.height())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._status_text)

    def _draw_model_loading_label(self, painter: QPainter, panel: QRectF):
        if not self._model_loading and self._loading_morph >= 0.995:
            return

        alpha_scale = 1.0 - self._smoothstep(self._loading_morph if not self._model_loading else 0.0)
        if alpha_scale <= 0.02:
            return
        rect = QRectF(
            0,
            panel.bottom() + MODEL_LOADING_LABEL_GAP,
            self.width(),
            MODEL_LOADING_LABEL_HEIGHT,
        )
        font = QFont("Inter Tight")
        if not font.exactMatch():
            font = QFont("Segoe UI")
        font.setPointSizeF(9.0)
        font.setWeight(QFont.Weight.Normal)

        painter.save()
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0, int(90 * alpha_scale)))
        painter.drawText(rect.translated(0, 1), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Model Loading")
        painter.setPen(QColor(232, 234, 241, int(185 * alpha_scale)))
        painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Model Loading")
        painter.restore()

    def _draw_no_audio_label(self, painter: QPainter, panel: QRectF):
        if not self._no_audio_warning or self._loading_visual_active() or self._processing:
            return

        rect = QRectF(
            0,
            panel.top() - MODEL_LOADING_LABEL_GAP - MODEL_LOADING_LABEL_HEIGHT,
            self.width(),
            MODEL_LOADING_LABEL_HEIGHT,
        )
        font = QFont("Inter Tight")
        if not font.exactMatch():
            font = QFont("Segoe UI")
        font.setPointSizeF(9.0)
        font.setWeight(QFont.Weight.Normal)

        painter.save()
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0, 90))
        painter.drawText(rect.translated(0, 1), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "No audio input detected")
        painter.setPen(QColor(232, 234, 241, 185))
        painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "No audio input detected")
        painter.restore()
