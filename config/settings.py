"""
MARK-XX Configuration Settings
All tunable parameters live here — nothing hardcoded in modules.
"""

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List

def _get_config_path() -> Path:
    if os.getenv("MARK_CLI") == "1":
        return Path(__file__).parent.parent / "config" / "cli_settings.json"
    return Path(__file__).parent.parent / "config" / "user_settings.json"



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
    wake_word_enabled: bool  = True     # When True, mic passively listens for wake word
    wake_word_timeout: float = 8.0      # Seconds to wait for follow-up after bare wake word
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

    # ── CLI Power User Configs ────────────────────────────────────────────────
    cli_max_steps:              int       = 15
    cli_max_result_len:         int       = 4000
    cli_max_heal_retries:       int       = 3
    cli_dangerous_tools:        List[str] = field(default_factory=lambda: ["run_command", "write_file", "edit_file", "delete_file", "move_file"])
    cli_forbidden_patterns:     List[str] = field(default_factory=lambda: [".env", ".env.local", ".env.production", "credentials", "secrets", "id_rsa", "id_ed25519", ".ssh", ".gnupg"])
    cli_system_prompt:          str       = ""
    cli_enable_self_evolution:  bool      = True



    def get_all_keys(self) -> List[str]:
        seen, keys = set(), []
        for k in ([self.gemini_api_key] + self.gemini_api_keys):
            k = k.strip()
            if k and k not in seen:
                seen.add(k); keys.append(k)
        return keys


def load_settings() -> Settings:
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # CLI mode inheritance fallback: if cli_settings.json doesn't exist, inherit from user_settings.json
    if os.getenv("MARK_CLI") == "1" and not config_path.exists():
        user_path = Path(__file__).parent.parent / "config" / "user_settings.json"
        if user_path.exists():
            try:
                with open(user_path, "r") as f:
                    data = json.load(f)
                s = Settings()
                # Populate everything from user_settings.json as initial default
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                
                # Write to cli_settings.json so it is saved separately
                save_settings(s)
                return s
            except Exception:
                pass

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
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
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(asdict(settings), f, indent=2)
