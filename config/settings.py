"""
MARK-XX Configuration Settings
All tunable parameters live here — nothing hardcoded in modules.
"""

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List

CONFIG_PATH = Path(__file__).parent.parent / "config" / "user_settings.json"


@dataclass
class Settings:
    # ── API Keys ──────────────────────────────────────────────────────────────
    gemini_api_key:  str       = ""
    gemini_api_keys: List[str] = field(default_factory=list)

    # ── LLM ───────────────────────────────────────────────────────────────────
    gemini_model:     str   = "gemini-3.1-flash-lite"
    llm_temperature:  float = 0.7
    llm_max_tokens:   int   = 2048

    # ── TTS ───────────────────────────────────────────────────────────────────
    voice_name:   str   = "en-US-AriaNeural"
    tts_rate:     float = 1.1
    tts_volume:   float = 0.9

    # ── STT ───────────────────────────────────────────────────────────────────
    stt_language:      str   = "en"
    stt_model_size:    str   = "base"
    wake_word:         str   = "mark"
    auto_listen:       bool  = True
    mic_sensitivity:   float = 0.008   # RMS threshold to detect speech start
    silence_hysteresis:float = 0.005   # RMS must drop below this to count as silence
    silence_gate_sec:  float = 2.0     # seconds of silence before processing

    # ── UI ────────────────────────────────────────────────────────────────────
    window_opacity:  float = 0.92
    always_on_top:   bool  = False
    theme:           str   = "dark"
    font_size:       int   = 13
    window_width:    int   = 480
    window_height:   int   = 720

    # ── Behaviour ─────────────────────────────────────────────────────────────
    assistant_name:             str  = "MARK"
    user_name:                  str  = "User"
    max_history_turns:          int  = 20
    auto_screenshot_on_request: bool = True
    speak_responses:            bool = True

    # ── Paths ─────────────────────────────────────────────────────────────────
    memory_db: str = ""

    def get_all_keys(self) -> List[str]:
        seen, keys = set(), []
        for k in ([self.gemini_api_key] + self.gemini_api_keys):
            k = k.strip()
            if k and k not in seen:
                seen.add(k); keys.append(k)
        return keys


def load_settings() -> Settings:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            s = Settings()
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
            return s
        except Exception:
            pass
    return Settings()


def save_settings(settings: Settings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(asdict(settings), f, indent=2)
