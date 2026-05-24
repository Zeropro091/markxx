"""
MARK-XX — Speech-to-Text (STT)
Continuous stream-based VAD:
  - sounddevice InputStream feeds a ring buffer at all times
  - When RMS crosses threshold → speech started, keep recording
  - When RMS stays below threshold for 2 seconds → speech ended → transcribe
  - Emits silence_countdown(float) so the UI can show a live countdown
"""

import time
import threading
import collections
import numpy as np
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.logger import get_logger
log = get_logger("stt")


# ── Defaults (overridden per-instance from Settings) ────────────────────────
WHISPER_RATE       = 16000
CHANNELS           = 1
CHUNK_MS           = 30
PRE_ROLL_SEC       = 0.3
MAX_RECORD_SEC     = 30


class STTWorker(QThread):
    transcribed       = pyqtSignal(str)    # final transcription text
    listening_started = pyqtSignal()       # mic opened / speech detected
    listening_stopped = pyqtSignal()       # processing started
    silence_countdown = pyqtSignal(float)  # countdown seconds remaining
    error_occurred    = pyqtSignal(str)

    def __init__(self, model_size: str = "base", language: str = "en",
                 mic_sensitivity: float = 0.008,
                 silence_hysteresis: float = 0.005,
                 silence_gate_sec: float = 2.0,
                 parent=None):
        super().__init__(parent)
        self.model_size          = model_size
        self.language            = language
        self.speech_threshold    = mic_sensitivity
        self.silence_threshold   = silence_hysteresis
        self.silence_gate_sec    = silence_gate_sec

        self._running  = False
        self._paused   = False
        self._model    = None

        # Stream state (shared between callback thread and main thread)
        self._lock          = threading.Lock()
        self._native_rate   = 44100   # updated on stream open
        self._chunk_frames  = 0
        self._pre_roll      = collections.deque()  # ring buffer for pre-roll
        self._speech_frames = []                   # accumulated speech
        self._in_speech     = False
        self._silence_start = 0.0                  # when silence began
        self._speech_ready  = threading.Event()    # signals main thread to transcribe
        self._captured      = None                 # np array to transcribe
        self._stream        = None

    # ── Model loading ──────────────────────────────────────────────────────────
    def _load_model(self):
        log.info(f"Loading Whisper model '{self.model_size}'…")
        t0 = time.time()
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            log.info(f"Whisper loaded in {time.time()-t0:.1f}s")
        except Exception as e:
            log.error(f"STT model load error: {e}")
            self.error_occurred.emit(f"STT model load: {e}")
            self._model = None

    # ── Audio callback (called by sounddevice on its own thread) ───────────────
    def _audio_callback(self, indata, frames, time_info, status):
        if self._paused or not self._running:
            return

        chunk = indata[:, 0].copy()   # mono float32
        rms   = float(np.sqrt(np.mean(chunk ** 2)))

        with self._lock:
            # Always keep a pre-roll ring buffer
            self._pre_roll.append(chunk)
            # Limit pre-roll size
            max_pre = int(PRE_ROLL_SEC / CHUNK_MS * 1000)
            while len(self._pre_roll) > max_pre:
                self._pre_roll.popleft()

            if not self._in_speech:
                if rms >= self.speech_threshold:
                    # Speech started
                    self._in_speech = True
                    self._speech_frames = list(self._pre_roll) + [chunk]
                    self._silence_start = 0.0
                    log.debug(f"Speech started (RMS={rms:.4f})")
                    self.listening_started.emit()
            else:
                self._speech_frames.append(chunk)
                total_sec = len(self._speech_frames) * CHUNK_MS / 1000

                if rms < self.silence_threshold:
                    if self._silence_start == 0.0:
                        self._silence_start = time.monotonic()
                    silence_elapsed = time.monotonic() - self._silence_start
                    remaining = max(0.0, self.silence_gate_sec - silence_elapsed)
                    self.silence_countdown.emit(remaining)

                    if silence_elapsed >= self.silence_gate_sec or total_sec >= MAX_RECORD_SEC:
                        # Commit: copy audio for transcription
                        audio_np = np.concatenate(self._speech_frames)
                        self._captured = audio_np
                        self._in_speech = False
                        self._speech_frames = []
                        self._pre_roll.clear()
                        self._silence_start = 0.0
                        self._speech_ready.set()
                        self.listening_stopped.emit()
                        log.debug(f"Speech ended — {len(audio_np)/self._native_rate:.1f}s captured")
                else:
                    # Still speaking — reset silence timer
                    self._silence_start = 0.0
                    self.silence_countdown.emit(SILENCE_GATE_SEC)

    # ── Transcription ─────────────────────────────────────────────────────────
    def _transcribe(self, audio_native: np.ndarray) -> Optional[str]:
        if self._model is None:
            return None

        # Resample from native rate to 16 kHz if needed
        rate = self._native_rate
        if rate != WHISPER_RATE:
            try:
                from scipy.signal import resample_poly
                from math import gcd
                g = gcd(WHISPER_RATE, rate)
                audio_native = resample_poly(
                    audio_native, WHISPER_RATE // g, rate // g
                ).astype(np.float32)
            except Exception:
                pass  # try raw — whisper handles many rates

        t0 = time.time()
        try:
            segments, _ = self._model.transcribe(
                audio_native,
                language=self.language if self.language != "auto" else None,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
            )
            text = " ".join(s.text for s in segments).strip()
            if text:
                log.info(f"STT ({time.time()-t0:.2f}s): \"{text[:80]}\"")
            else:
                log.debug(f"STT: no text ({time.time()-t0:.2f}s)")
            return text or None
        except Exception as e:
            log.error(f"Transcription error: {e}")
            self.error_occurred.emit(f"Transcription error: {e}")
            return None

    # ── Main thread loop ───────────────────────────────────────────────────────
    def run(self):
        self._running = True
        self._load_model()
        if self._model is None:
            return

        try:
            import sounddevice as sd
        except ImportError:
            self.error_occurred.emit("sounddevice not installed")
            return

        # Detect native sample rate
        try:
            dev_info = sd.query_devices(kind="input")
            self._native_rate = int(dev_info["default_samplerate"])
        except Exception:
            self._native_rate = 44100
        self._chunk_frames = int(self._native_rate * CHUNK_MS / 1000)

        log.info(f"STT stream: {self._native_rate} Hz, chunk={self._chunk_frames} frames")

        with sd.InputStream(
            samplerate=self._native_rate,
            channels=CHANNELS,
            dtype="float32",
            blocksize=self._chunk_frames,
            callback=self._audio_callback,
        ) as self._stream:
            log.info("Microphone stream opened — listening continuously")
            while self._running:
                # Wait for the callback to signal a complete utterance
                fired = self._speech_ready.wait(timeout=0.5)
                if fired and self._running:
                    self._speech_ready.clear()
                    with self._lock:
                        audio = self._captured
                        self._captured = None
                    if audio is not None and len(audio) > 0:
                        text = self._transcribe(audio)
                        if text:
                            self.transcribed.emit(text)

        log.info("STT stream closed")

    # ── Control ───────────────────────────────────────────────────────────────
    def pause(self):
        with self._lock:
            self._paused = True
            self._in_speech = False
            self._speech_frames = []
            self._silence_start = 0.0
        log.debug("STT paused")

    def resume(self):
        with self._lock:
            self._paused = False
        log.debug("STT resumed")

    def stop(self):
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass
        self._speech_ready.set()   # unblock wait()
        self.wait(3000)
        log.info("STT stopped")
