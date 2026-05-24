import sys
import traceback
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
print("app created", flush=True)

from ui import MarkWindow
from config.settings import load_settings
from core.llm import LLMClient
from core.memory import Memory
from core.tts import TTSWorker
from agent.planner import PlannerWorker

settings = load_settings()
settings.memory_db = 'memory/markxx.db'
memory = Memory(settings.memory_db)
llm_client = LLMClient(api_key='', model=settings.gemini_model)
tts_worker = TTSWorker()
planner = PlannerWorker(llm_client, memory)

print("Instantiating full MarkWindow...", flush=True)
try:
    window = MarkWindow(settings, llm_client, memory, planner, None, tts_worker)
    print("Window instantiated, calling show()...", flush=True)
    window.show()
    print("Window show() completed successfully!", flush=True)
except Exception as e:
    print(f"Caught exception in main: {e}", flush=True)
    traceback.print_exc()
