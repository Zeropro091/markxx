"""
MARK-XX — Multi-Engine TTS (Text-to-Speech)

Supports 4 engines, switchable at runtime:
  1. kokoro   — Best quality, 82M params, CPU-friendly (default)
  2. piper    — Fastest, ultra-lightweight
  3. orpheus  — Most expressive (emotions), LLaMA-based, needs GPU
  4. edge     — Cloud-based Microsoft Edge neural voices (original)

Usage:
    tts = MultiTTS(engine="kokoro")
    tts.speak("Hello world")
    tts.set_engine("piper")  # switch at runtime
"""

import asyncio
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from core.logger import get_logger
log = get_logger("tts")


# ── Markdown cleaner (shared) ────────────────────────────────────────────────

def clean_for_tts(text: str) -> str:
    """Strip markdown/code so TTS reads clean natural text."""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'```.+', '', text)
    def _inline(m):
        c = m.group(1).strip()
        return c if re.match(r'^[a-zA-Z0-9_\-]+$', c) and len(c) <= 30 else ''
    text = re.sub(r'`([^`]+)`', _inline, text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    lines = [l for l in text.split('\n') if l.strip()]
    return '\n'.join(lines).strip()


# ── Engine: Kokoro TTS ────────────────────────────────────────────────────────

class KokoroEngine:
    """Kokoro TTS — 82M param model, best quality on CPU."""

    def __init__(self, voice: str = "af_heart", speed: float = 1.0):
        self.voice = voice
        self.speed = speed
        self._pipeline = None

    def _ensure_loaded(self):
        if self._pipeline is not None:
            return True
        try:
            from kokoro import KPipeline
            self._pipeline = KPipeline(lang_code=self.voice[:1])
            log.info(f"Kokoro TTS loaded (voice={self.voice})")
            return True
        except ImportError:
            log.error("Kokoro not installed. Run: pip install kokoro soundfile")
            return False
        except Exception as e:
            log.error(f"Kokoro init failed: {e}")
            return False

    def speak(self, text: str) -> bool:
        if not self._ensure_loaded():
            return False
        try:
            import soundfile as sf

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()

            generator = self._pipeline(text, voice=self.voice, speed=self.speed)
            # Kokoro yields (graphemes, phonemes, audio) tuples
            audio_segments = []
            for _, _, audio in generator:
                audio_segments.append(audio)

            if not audio_segments:
                return False

            import numpy as np
            full_audio = np.concatenate(audio_segments)
            sf.write(tmp.name, full_audio, 24000)

            self._play_file(tmp.name)
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return True
        except Exception as e:
            log.error(f"Kokoro speak failed: {e}")
            return False

    def _play_file(self, path: str):
        """Play audio file cross-platform."""
        try:
            from playsound3 import playsound
            playsound(path)
        except ImportError:
            # Fallback: use system player
            if os.name == "nt":
                os.startfile(path)
                time.sleep(2)
            else:
                subprocess.run(["aplay", path], capture_output=True)

    @staticmethod
    def available_voices():
        return [
            "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
            "am_adam", "am_michael",
            "bf_emma", "bf_isabella",
            "bm_george", "bm_lewis",
        ]


# ── Engine: Piper TTS ────────────────────────────────────────────────────────

class PiperEngine:
    """Piper TTS — fastest, ultra-lightweight ONNX-based."""

    def __init__(self, model: str = "en_US-lessac-medium", speed: float = 1.0):
        self.model = model
        self.speed = speed

    def speak(self, text: str) -> bool:
        try:
            from piper import PiperVoice

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()

            voice = PiperVoice.load(self.model)
            with open(tmp.name, "wb") as f:
                voice.synthesize(text, f, length_scale=1.0 / self.speed)

            self._play_file(tmp.name)
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return True
        except ImportError:
            log.error("Piper not installed. Run: pip install piper-tts")
            return False
        except Exception as e:
            log.error(f"Piper speak failed: {e}")
            return False

    def _play_file(self, path: str):
        try:
            from playsound3 import playsound
            playsound(path)
        except ImportError:
            if os.name == "nt":
                os.startfile(path)
                time.sleep(2)
            else:
                subprocess.run(["aplay", path], capture_output=True)


# ── Engine: Orpheus TTS ───────────────────────────────────────────────────────

class OrpheusEngine:
    """Orpheus TTS — LLaMA-based, most expressive, needs GPU."""

    def __init__(self, voice: str = "tara", speed: float = 1.0):
        self.voice = voice
        self.speed = speed
        self._model = None

    def speak(self, text: str) -> bool:
        try:
            from orpheus_tts import OrpheusModel

            if self._model is None:
                self._model = OrpheusModel(model_name="canopylabs/orpheus-tts-0.1-finetune-prod")
                log.info(f"Orpheus TTS loaded (voice={self.voice})")

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()

            audio = self._model.generate_speech(
                prompt=text,
                voice=self.voice,
            )
            with open(tmp.name, "wb") as f:
                f.write(audio)

            self._play_file(tmp.name)
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return True
        except ImportError:
            log.error("Orpheus not installed. Run: pip install orpheus-tts")
            return False
        except Exception as e:
            log.error(f"Orpheus speak failed: {e}")
            return False

    def _play_file(self, path: str):
        try:
            from playsound3 import playsound
            playsound(path)
        except ImportError:
            if os.name == "nt":
                os.startfile(path)
                time.sleep(2)
            else:
                subprocess.run(["aplay", path], capture_output=True)

    @staticmethod
    def available_voices():
        return ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"]


# ── Engine: Edge TTS (original, cloud-based) ──────────────────────────────────

class EdgeEngine:
    """Microsoft Edge TTS — cloud neural voices, no API key needed."""

    def __init__(self, voice: str = "en-GB-RyanNeural",
                 rate: float = 1.1, volume: float = 0.9):
        self.voice = voice
        self.rate = rate
        self.volume = volume

    def speak(self, text: str) -> bool:
        try:
            import edge_tts
            from playsound3 import playsound

            rate_str = (
                f"+{int((self.rate - 1.0) * 100)}%"
                if self.rate >= 1.0
                else f"-{int((1.0 - self.rate) * 100)}%"
            )
            communicate = edge_tts.Communicate(text, self.voice, rate=rate_str)

            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()

            asyncio.run(communicate.save(tmp.name))

            if not os.path.exists(tmp.name) or os.path.getsize(tmp.name) < 100:
                return False

            playsound(tmp.name)
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return True
        except ImportError:
            log.error("edge-tts not installed. Run: pip install edge-tts playsound3")
            return False
        except Exception as e:
            log.error(f"Edge TTS failed: {e}")
            return False


# ── Multi-engine TTS controller ───────────────────────────────────────────────

ENGINES = {
    "kokoro": KokoroEngine,
    "piper": PiperEngine,
    "orpheus": OrpheusEngine,
    "edge": EdgeEngine,
}

class MultiTTS:
    """Switchable TTS engine with fallback chain.

    Usage:
        tts = MultiTTS(engine="kokoro")
        tts.speak("Hello")
        tts.set_engine("piper")   # switch at runtime
        tts.speak("Now using Piper")
    """

    def __init__(self, engine: str = "kokoro", **kwargs):
        self._engine_name = engine
        self._kwargs = kwargs
        self._engine = self._create_engine(engine, **kwargs)
        self._lock = threading.Lock()
        self._enabled = True

    def _create_engine(self, name: str, **kwargs):
        cls = ENGINES.get(name)
        if cls is None:
            log.warning(f"Unknown TTS engine '{name}', falling back to edge")
            cls = EdgeEngine
        try:
            return cls(**kwargs)
        except TypeError:
            return cls()

    def set_engine(self, name: str, **kwargs):
        """Switch TTS engine at runtime."""
        with self._lock:
            self._engine_name = name
            self._kwargs = kwargs
            self._engine = self._create_engine(name, **kwargs)
            log.info(f"TTS engine switched to: {name}")

    @property
    def engine_name(self) -> str:
        return self._engine_name

    def speak(self, text: str):
        """Speak text using the current engine (with fallback)."""
        if not self._enabled or not text.strip():
            return

        cleaned = clean_for_tts(text)
        if not cleaned:
            return

        with self._lock:
            ok = self._engine.speak(cleaned)
            if not ok and self._engine_name != "edge":
                log.warning(f"{self._engine_name} failed, falling back to edge")
                fallback = EdgeEngine()
                fallback.speak(cleaned)

    def speak_async(self, text: str):
        """Speak in background thread (non-blocking)."""
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()

    def toggle(self) -> bool:
        """Toggle TTS on/off. Returns new state."""
        self._enabled = not self._enabled
        return self._enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val

    def status(self) -> dict:
        return {
            "engine": self._engine_name,
            "enabled": self._enabled,
            "available_engines": list(ENGINES.keys()),
        }
