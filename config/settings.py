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

    # ── Multimodal Live (WebSocket Audio Streaming) ─────────────────────────
    multimodal_live_mode: bool = False     # True → bypass Whisper/TTS, use Gemini Live WebSocket
    live_model: str = "models/gemini-2.5-flash-native-audio-preview-12-2025"
    live_voice: str = "Charon"

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
                return _apply_env_keys(s)
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
            # Sync API keys from user_settings.json if in CLI mode
            if os.getenv("MARK_CLI") == "1":
                user_path = Path(__file__).parent.parent / "config" / "user_settings.json"
                if user_path.exists():
                    try:
                        with open(user_path, "r") as f:
                            u_data = json.load(f)
                        if "gemini_api_key" in u_data:
                            s.gemini_api_key = u_data["gemini_api_key"]
                        if "gemini_api_keys" in u_data:
                            s.gemini_api_keys = u_data["gemini_api_keys"]
                    except Exception:
                        pass
            return _apply_env_keys(s)
        except Exception:
            pass
    return _apply_env_keys(Settings())


def _apply_env_keys(s: Settings) -> Settings:
    """Override API keys from environment variables if set.
    
    Supports:
        GEMINI_API_KEY   — single primary key
        GEMINI_API_KEYS  — comma-separated list of extra keys
    """
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if env_key:
        s.gemini_api_key = env_key

    env_keys = os.getenv("GEMINI_API_KEYS", "").strip()
    if env_keys:
        s.gemini_api_keys = [k.strip() for k in env_keys.split(",") if k.strip()]

    return s


def save_settings(settings: Settings) -> None:
    config_path = _get_config_path()
    print(f"DEBUG: Saving settings to {config_path}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(asdict(settings), f, indent=2)
    print(f"DEBUG: Settings saved successfully to {config_path}")

    # Sync API keys to the other settings file to keep them in sync
    try:
        user_path = Path(__file__).parent.parent / "config" / "user_settings.json"
        cli_path = Path(__file__).parent.parent / "config" / "cli_settings.json"
        if os.getenv("MARK_CLI") == "1":
            # Synced from CLI -> UI
            if user_path.exists():
                with open(user_path, "r") as f:
                    u_data = json.load(f)
                u_data["gemini_api_key"] = settings.gemini_api_key
                u_data["gemini_api_keys"] = settings.gemini_api_keys
                with open(user_path, "w") as f:
                    json.dump(u_data, f, indent=2)
        else:
            # Synced from UI -> CLI
            if cli_path.exists():
                with open(cli_path, "r") as f:
                    c_data = json.load(f)
                c_data["gemini_api_key"] = settings.gemini_api_key
                c_data["gemini_api_keys"] = settings.gemini_api_keys
                with open(cli_path, "w") as f:
                    json.dump(c_data, f, indent=2)
    except Exception:
        pass
