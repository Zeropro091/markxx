"""
MARK-XX — Text-to-Speech (TTS)
Primary: edge-tts (neural, excellent quality) → playsound3
Fallback: pyttsx3 (fully offline, robotic but reliable)
"""

import asyncio
import re
import threading
import os
import tempfile
import time
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.logger import get_logger
log = get_logger("tts")


def clean_for_tts(text: str) -> str:
    """Strip markdown formatting and code so TTS reads clean, natural text aloud.

    Removes code blocks entirely (nobody wants code read word-by-word),
    strips markdown syntax, and cleans up punctuation for speech.
    """
    # 1) Remove fenced code blocks completely (including content)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'```.+', '', text)
    # 2) Remove inline code — keep only if it's a short plain word
    #    e.g. `python` → python, `fetch('https://api...')` → (removed)
    def _inline_code(m):
        code = m.group(1).strip()
        if re.match(r'^[a-zA-Z0-9_\-]+$', code) and len(code) <= 30:
            return code
        return ''
    text = re.sub(r'`([^`]+)`', _inline_code, text)
    # 3) Remove bold/italic markers — keep the text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # 4) Remove heading markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 5) Remove links — keep display text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # 6) Remove images — keep alt text
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
    # 7) Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # 8) Remove list markers
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    # 9) Remove blockquote markers
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    # 10) Remove emojis (TTS can't pronounce them)
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    # 11) Remove URLs that survived link stripping
    text = re.sub(r'https?://\S+', '', text)
    # 12) Remove abbreviations in parentheses like (Software Development Kit)
    #     TTS stumbles over these — the expansion before it already explains it
    text = re.sub(r'\s*\([A-Z][a-zA-Z\s]{2,40}\)', '', text)
    # 13) Remove common symbol markers
    text = re.sub(r'[❌✅✓✔✗✘⚠→←↑↓⇒⇐]', '', text)
    # 14) Clean up leftover artifacts
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    # 15) Remove lines that are now empty after stripping
    lines = [l for l in text.split('\n') if l.strip()]
    text = '\n'.join(lines)
    return text.strip()


class TTSWorker(QThread):
    started_speaking  = pyqtSignal()
    finished_speaking = pyqtSignal()
    error_occurred    = pyqtSignal(str)

    def __init__(self, voice: str = "en-US-AriaNeural",
                 rate: float = 1.1, volume: float = 0.9, parent=None):
        super().__init__(parent)
        self.voice   = voice
        self.rate    = rate
        self.volume  = volume
        self._queue: list[str] = []
        self._lock   = threading.Lock()
        self._running = False

    def speak(self, text: str):
        cleaned = clean_for_tts(text)
        with self._lock:
            self._queue.append(cleaned)

    def stop_speaking(self):
        with self._lock:
            self._queue.clear()

    def run(self):
        self._running = True
        while self._running:
            text = None
            with self._lock:
                if self._queue:
                    text = self._queue.pop(0)
            if text:
                self._speak_now(text)
            else:
                self.msleep(50)

    def _speak_now(self, text: str):
        preview = text[:60].replace("\n", " ")
        log.info(f"TTS >> \"{preview}{'...' if len(text) > 60 else ''}\"")
        t0 = time.time()
        self.started_speaking.emit()
        try:
            ok = self._speak_edge_tts(text)
            if not ok:
                log.warning("edge-tts failed, falling back to pyttsx3")
                self._speak_pyttsx3(text)
            log.debug(f"TTS done in {time.time()-t0:.2f}s")
        except Exception as e:
            log.error(f"TTS error: {e}")
            self.error_occurred.emit(f"TTS error: {e}")
            try:
                self._speak_pyttsx3(text)
            except Exception:
                pass
        finally:
            self.finished_speaking.emit()

    # ── edge-tts → playsound3 (primary) ───────────────────────────────────────
    def _speak_edge_tts(self, text: str) -> bool:
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

            # Save MP3 (edge-tts is async)
            asyncio.run(communicate.save(tmp.name))

            if not os.path.exists(tmp.name) or os.path.getsize(tmp.name) < 100:
                return False

            # Play — playsound3 blocks until done
            playsound(tmp.name)

            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return True

        except ImportError as e:
            self.error_occurred.emit(f"TTS import missing: {e}")
            return False
        except Exception as e:
            self.error_occurred.emit(f"edge-tts error: {e}")
            return False

    # ── pyttsx3 (offline fallback) ────────────────────────────────────────────
    def _speak_pyttsx3(self, text: str):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", int(180 * self.rate))
            engine.setProperty("volume", self.volume)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            self.error_occurred.emit(f"pyttsx3 error: {e}")

    def stop(self):
        self._running = False
        self.stop_speaking()
        self.wait(2000)
