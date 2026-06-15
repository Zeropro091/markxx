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


# ── Voice catalog ─────────────────────────────────────────────────────────────

VOICE_CATALOG = {
    "kokoro": {
        "af_heart": {"name": "Heart", "gender": "F", "accent": "US", "style": "warm, default"},
        "af_bella": {"name": "Bella", "gender": "F", "accent": "US", "style": "soft"},
        "af_nicole": {"name": "Nicole", "gender": "F", "accent": "US", "style": "professional"},
        "af_sarah": {"name": "Sarah", "gender": "F", "accent": "US", "style": "clear"},
        "af_sky": {"name": "Sky", "gender": "F", "accent": "US", "style": "bright"},
        "am_adam": {"name": "Adam", "gender": "M", "accent": "US", "style": "deep"},
        "am_michael": {"name": "Michael", "gender": "M", "accent": "US", "style": "neutral"},
        "bf_emma": {"name": "Emma", "gender": "F", "accent": "UK", "style": "formal"},
        "bf_isabella": {"name": "Isabella", "gender": "F", "accent": "UK", "style": "refined"},
        "bm_george": {"name": "George", "gender": "M", "accent": "UK", "style": "distinguished"},
        "bm_lewis": {"name": "Lewis", "gender": "M", "accent": "UK", "style": "friendly"},
    },
    "piper": {
        "en_US-lessac-medium": {"name": "Lessac", "gender": "M", "accent": "US", "style": "default"},
        "en_US-lessac-high": {"name": "Lessac HQ", "gender": "M", "accent": "US", "style": "high quality"},
        "en_US-ryan-medium": {"name": "Ryan", "gender": "M", "accent": "US", "style": "medium"},
        "en_US-ryan-high": {"name": "Ryan HQ", "gender": "M", "accent": "US", "style": "high quality"},
        "en_US-amy-medium": {"name": "Amy", "gender": "F", "accent": "US", "style": "medium"},
        "en_GB-alan-medium": {"name": "Alan", "gender": "M", "accent": "UK", "style": "medium"},
        "en_GB-alba-medium": {"name": "Alba", "gender": "F", "accent": "UK", "style": "medium"},
        "en_GB-cori-medium": {"name": "Cori", "gender": "F", "accent": "UK", "style": "medium"},
    },
    "orpheus": {
        "tara": {"name": "Tara", "gender": "F", "accent": "US", "style": "expressive, default"},
        "leah": {"name": "Leah", "gender": "F", "accent": "US", "style": "calm"},
        "jess": {"name": "Jess", "gender": "F", "accent": "US", "style": "energetic"},
        "leo": {"name": "Leo", "gender": "M", "accent": "US", "style": "confident"},
        "dan": {"name": "Dan", "gender": "M", "accent": "US", "style": "casual"},
        "mia": {"name": "Mia", "gender": "F", "accent": "US", "style": "warm"},
        "zac": {"name": "Zac", "gender": "M", "accent": "US", "style": "young"},
        "zoe": {"name": "Zoe", "gender": "F", "accent": "US", "style": "youthful"},
    },
    "edge": {
        # English US
        "en-US-AriaNeural": {"name": "Aria", "gender": "F", "accent": "US", "style": "conversational"},
        "en-US-GuyNeural": {"name": "Guy", "gender": "M", "accent": "US", "style": "news anchor"},
        "en-US-JennyNeural": {"name": "Jenny", "gender": "F", "accent": "US", "style": "friendly"},
        "en-US-DavisNeural": {"name": "Davis", "gender": "M", "accent": "US", "style": "casual"},
        "en-US-AmberNeural": {"name": "Amber", "gender": "F", "accent": "US", "style": "warm"},
        "en-US-AndrewNeural": {"name": "Andrew", "gender": "M", "accent": "US", "style": "professional"},
        "en-US-BrianNeural": {"name": "Brian", "gender": "M", "accent": "US", "style": "narrator"},
        "en-US-EmmaNeural": {"name": "Emma", "gender": "F", "accent": "US", "style": "professional"},
        "en-US-EricNeural": {"name": "Eric", "gender": "M", "accent": "US", "style": "calm"},
        "en-US-MichelleNeural": {"name": "Michelle", "gender": "F", "accent": "US", "style": "assistant"},
        "en-US-RogerNeural": {"name": "Roger", "gender": "M", "accent": "US", "style": "elderly wise"},
        "en-US-SteffanNeural": {"name": "Steffan", "gender": "M", "accent": "US", "style": "storyteller"},
        # English UK
        "en-GB-RyanNeural": {"name": "Ryan", "gender": "M", "accent": "UK", "style": "British, default"},
        "en-GB-SoniaNeural": {"name": "Sonia", "gender": "F", "accent": "UK", "style": "British female"},
        "en-GB-ThomasNeural": {"name": "Thomas", "gender": "M", "accent": "UK", "style": "British formal"},
        "en-GB-MaisieNeural": {"name": "Maisie", "gender": "F", "accent": "UK", "style": "British young"},
        # English AU
        "en-AU-NatashaNeural": {"name": "Natasha", "gender": "F", "accent": "AU", "style": "Australian"},
        "en-AU-WilliamNeural": {"name": "William", "gender": "M", "accent": "AU", "style": "Australian"},
        # Indonesian
        "id-ID-ArdiNeural": {"name": "Ardi", "gender": "M", "accent": "ID", "style": "Indonesian male"},
        "id-ID-GadisNeural": {"name": "Gadis", "gender": "F", "accent": "ID", "style": "Indonesian female"},
        # Japanese
        "ja-JP-NanamiNeural": {"name": "Nanami", "gender": "F", "accent": "JP", "style": "Japanese"},
        "ja-JP-KeitaNeural": {"name": "Keita", "gender": "M", "accent": "JP", "style": "Japanese"},
        # Korean
        "ko-KR-SunHiNeural": {"name": "SunHi", "gender": "F", "accent": "KR", "style": "Korean"},
        "ko-KR-InJoonNeural": {"name": "InJoon", "gender": "M", "accent": "KR", "style": "Korean"},
        # Chinese
        "zh-CN-XiaoxiaoNeural": {"name": "Xiaoxiao", "gender": "F", "accent": "CN", "style": "Chinese"},
        "zh-CN-YunxiNeural": {"name": "Yunxi", "gender": "M", "accent": "CN", "style": "Chinese"},
        # Spanish
        "es-ES-ElviraNeural": {"name": "Elvira", "gender": "F", "accent": "ES", "style": "Spanish"},
        "es-ES-AlvaroNeural": {"name": "Alvaro", "gender": "M", "accent": "ES", "style": "Spanish"},
        # French
        "fr-FR-DeniseNeural": {"name": "Denise", "gender": "F", "accent": "FR", "style": "French"},
        "fr-FR-HenriNeural": {"name": "Henri", "gender": "M", "accent": "FR", "style": "French"},
        # German
        "de-DE-KatjaNeural": {"name": "Katja", "gender": "F", "accent": "DE", "style": "German"},
        "de-DE-ConradNeural": {"name": "Conrad", "gender": "M", "accent": "DE", "style": "German"},
    },
}


ENGINES = {
    "kokoro": KokoroEngine,
    "piper": PiperEngine,
    "orpheus": OrpheusEngine,
    "edge": EdgeEngine,
}

class MultiTTS:
    """Switchable TTS engine with fallback chain and voice catalog.

    Usage:
        tts = MultiTTS(engine="kokoro")
        tts.speak("Hello")
        tts.set_engine("piper")
        tts.set_voice("af_bella")
        tts.set_engine("edge", voice="en-US-AriaNeural")
    """

    def __init__(self, engine: str = "kokoro", voice: str = None, **kwargs):
        self._engine_name = engine
        self._voice_id = voice
        self._kwargs = kwargs
        self._engine = self._create_engine(engine, voice=voice, **kwargs)
        self._lock = threading.Lock()
        self._enabled = True

    def _create_engine(self, name: str, voice: str = None, **kwargs):
        cls = ENGINES.get(name)
        if cls is None:
            log.warning(f"Unknown TTS engine '{name}', falling back to edge")
            cls = EdgeEngine
            name = "edge"

        if voice:
            if name == "piper":
                kwargs["model"] = voice
            else:
                kwargs["voice"] = voice

        try:
            return cls(**kwargs)
        except TypeError:
            return cls()

    def set_engine(self, name: str, voice: str = None, **kwargs):
        """Switch TTS engine at runtime."""
        with self._lock:
            self._engine_name = name
            self._voice_id = voice
            self._kwargs = kwargs
            self._engine = self._create_engine(name, voice=voice, **kwargs)
            log.info(f"TTS engine: {name}" + (f" voice={voice}" if voice else ""))

    def set_voice(self, voice_id: str):
        """Switch voice within the current engine."""
        self._voice_id = voice_id
        self.set_engine(self._engine_name, voice=voice_id, **self._kwargs)

    @property
    def engine_name(self) -> str:
        return self._engine_name

    @property
    def voice_id(self) -> str:
        return self._voice_id

    def speak(self, text: str):
        if not self._enabled or not text.strip():
            return
        cleaned = clean_for_tts(text)
        if not cleaned:
            return
        with self._lock:
            ok = self._engine.speak(cleaned)
            if not ok and self._engine_name != "edge":
                log.warning(f"{self._engine_name} failed, falling back to edge")
                EdgeEngine().speak(cleaned)

    def speak_async(self, text: str):
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()

    def toggle(self) -> bool:
        self._enabled = not self._enabled
        return self._enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val

    def list_voices(self, engine: str = None) -> dict:
        return VOICE_CATALOG.get(engine or self._engine_name, {})

    def list_voices_formatted(self, engine: str = None) -> str:
        eng = engine or self._engine_name
        voices = VOICE_CATALOG.get(eng, {})
        if not voices:
            return f"No voice catalog for '{eng}'"
        lines = [f"Voices for {eng} ({len(voices)} available):"]
        for vid, info in voices.items():
            g = info.get("gender", "?")
            a = info.get("accent", "?")
            s = info.get("style", "")
            n = info.get("name", vid)
            lines.append(f"  {vid:30s}  {n:12s}  {g}  {a:4s}  {s}")
        return "\n".join(lines)

    def status(self) -> dict:
        return {
            "engine": self._engine_name,
            "voice": self._voice_id,
            "enabled": self._enabled,
            "available_engines": list(ENGINES.keys()),
            "voice_count": {e: len(v) for e, v in VOICE_CATALOG.items()},
        }

