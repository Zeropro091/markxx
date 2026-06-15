"""
MARK-XX — Main Entry Point
Initialises all components and launches the PyQt6 UI.
"""

import sys
import os
from pathlib import Path

# ── Make sure project root is on sys.path ─────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Init logging FIRST (before any other import logs) ────────────────────────
from core.logger import get_logger, get_log_path
log = get_logger("main")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from config.settings import load_settings, save_settings
from core.llm import LLMClient
from core.memory import Memory
from core.tts import TTSWorker
from agent.planner import PlannerWorker


def main():
    log.info(f"Log file: {get_log_path()}")

    # ── High-DPI support ──────────────────────────────────────────────────────
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("MARK-XX")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("MARK")
    app.setStyleSheet("""
        QToolTip {
            background: rgba(12,15,28,240);
            color: #DCE6FF;
            border: 1px solid rgba(64,180,255,80);
            border-radius: 4px;
            padding: 4px 8px;
        }
    """)

    # ── Load settings ─────────────────────────────────────────────────────────
    settings = load_settings()
    settings.memory_db = str(ROOT / "memory" / "markxx.db")
    log.info(f"Settings loaded — model={settings.gemini_model}, keys={len(settings.get_all_keys())}")

    # ── Initialise memory ─────────────────────────────────────────────────────
    memory = Memory(settings.memory_db)
    log.info(f"Memory DB: {settings.memory_db}")

    # Restore user name from memory if not set
    if not settings.user_name or settings.user_name == "User":
        stored_name = memory.get_pref("user_name")
        if stored_name:
            settings.user_name = stored_name

    # ── Initialise LLM (system prompt built by planner from .gemini) ──────────────
    all_keys = settings.get_all_keys()
    log.info(f"LLM: model={settings.gemini_model}, key_pool={len(all_keys)}")
    llm_client = LLMClient(
        api_key=all_keys[0] if all_keys else "",
        model=settings.gemini_model,
        system_prompt="",   # planner rebuilds this on every request
        extra_keys=all_keys[1:] if len(all_keys) > 1 else [],
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )

    # ── Initialise TTS ───────────────────────────────────────────────────────
    tts_worker = None
    if not getattr(settings, "multimodal_live_mode", False):
        tts_worker = TTSWorker(
            voice=settings.voice_name,
            rate=settings.tts_rate,
            volume=settings.tts_volume,
        )
        tts_worker.start()
        log.info(f"TTS started — voice={settings.voice_name}")

    # ── Initialise STT (optional — requires faster-whisper) ──────────────────
    stt_worker = None
    if not getattr(settings, "multimodal_live_mode", False):
        try:
            from core.stt import STTWorker
            stt_worker = STTWorker(
                model_size=settings.stt_model_size,
                language=settings.stt_language,
                mic_sensitivity=settings.mic_sensitivity,
                silence_hysteresis=settings.silence_hysteresis,
                silence_gate_sec=settings.silence_gate_sec,
            )
            log.info(f"STT ready — model={settings.stt_model_size}, lang={settings.stt_language}")
            # Don't start yet — user must press mic button
        except ImportError:
            log.warning("faster-whisper not installed — voice input disabled.")

    # ── Initialise Planner ───────────────────────────────────────────────────
    planner = None
    if not getattr(settings, "multimodal_live_mode", False):
        planner = PlannerWorker(llm_client, memory)
        planner.start()
        log.info("Planner started")

    # ── Launch UI ────────────────────────────────────────────────────────────
    from ui import MarkWindow
    window = MarkWindow(
        settings=settings,
        llm_client=llm_client,
        memory=memory,
        planner=planner,
        stt_worker=stt_worker,
        tts_worker=tts_worker,
    )
    window.show()
    log.info("UI launched — entering event loop")

    # ── Log session start to Nemesi memory ───────────────────────────────────────
    try:
        import datetime
        from agent.tools import MEMORY_DIR
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        session_log = MEMORY_DIR / "MARK-sessions.md"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- **{timestamp}** — MARK started (model={settings.gemini_model}, keys={len(all_keys)})\n"
        with open(session_log, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass

    ret = app.exec()

    # ── Cleanup ──────────────────────────────────────────────────────────────
    log.info("Shutting down…")
    if stt_worker and stt_worker.isRunning():
        stt_worker.stop()
    if tts_worker and tts_worker.isRunning():
        tts_worker.stop()
    if planner and planner.isRunning():
        planner.stop()

    save_settings(settings)
    log.info("Shutdown complete")
    sys.exit(ret)


if __name__ == "__main__":
    main()
