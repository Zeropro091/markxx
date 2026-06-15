# live_session.py
import asyncio
import re
import os
import sys
import threading
import traceback
from pathlib import Path
from datetime import datetime

import sounddevice as sd
from google import genai
from google.genai import types

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    class LiveSignals(QObject):
        add_bubble = pyqtSignal(str, str)
        set_status = pyqtSignal(str, bool)
        set_thinking = pyqtSignal(bool)
except ImportError:
    class LiveSignals:
        pass


# Safe print helper to prevent UnicodeEncodeError on Windows
try:
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, "reconfigure"): sys.stderr.reconfigure(encoding='utf-8')
except Exception: pass

def _print(msg: str):
    try: print(msg)
    except UnicodeEncodeError:
        try:
            enc = sys.stdout.encoding or 'utf-8'
            print(msg.encode(enc, errors='replace').decode(enc))
        except Exception:
            print(msg.encode('ascii', errors='replace').decode('ascii'))

# Live streaming settings
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "browser_control",
        "description": "Automates Chrome/Edge/Firefox via Playwright: navigate, search, click, type, scroll, take screenshot.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "go_to | click | type | press | scroll | wait | screenshot | close_page | check | select_option | go_back | go_forward | reload"},
                "url": {"type": "STRING", "description": "URL to navigate to"},
                "selector": {"type": "STRING", "description": "CSS selector to click/type"},
                "text": {"type": "STRING", "description": "Text to type or select"},
                "key": {"type": "STRING", "description": "Key to press"},
                "x": {"type": "INTEGER", "description": "Scroll delta x"},
                "y": {"type": "INTEGER", "description": "Scroll delta y"},
                "path": {"type": "STRING", "description": "Screenshot save path"},
                "value": {"type": "STRING", "description": "Option value to select"},
                "checked": {"type": "BOOLEAN", "description": "Check state (default: true)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "computer_settings",
        "description": "Modify computer settings: volume, brightness, dark mode, wifi, window positioning, or screen locks.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "volume_up|volume_down|mute|volume_set|brightness_up|brightness_down|close_app|close_window|full_screen|minimize|maximize|snap_left|snap_right|switch_window|show_desktop|task_manager|dark_mode|toggle_wifi|restart|shutdown"},
                "value":     {"type": "STRING",  "description": "Value for setting (e.g. integer 0-100 for volume_set)"},
                "description": {"type": "STRING", "description": "Description of intent to automatically detect settings action"},
                "confirmed": {"type": "STRING", "description": "yes|no to confirm dangerous actions like restart/shutdown"}
            },
            "required": []
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "file_processor",
        "description": "Processes any file: images, PDFs, Word docs, CSV/Excel, JSON, code, audio, video, archives, PPTX. Summarize, fix, format, convert, trim, transcribe, etc.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Full path to the file"},
                "action": {"type": "STRING", "description": "describe|ocr|resize|convert|compress|summarize|extract_text|to_word|stats|analyze|validate|format|run|transcribe|trim|list|extract"},
                "instruction": {"type": "STRING", "description": "Custom processing instruction"},
                "format": {"type": "STRING", "description": "Target extension for convert"},
                "width": {"type": "INTEGER"},
                "height": {"type": "INTEGER"},
                "scale": {"type": "NUMBER"},
                "quality": {"type": "INTEGER"},
                "start": {"type": "STRING"},
                "end": {"type": "STRING"},
                "timestamp": {"type": "STRING"},
                "column": {"type": "STRING"},
                "value": {"type": "STRING"},
                "condition": {"type": "STRING"},
                "ascending": {"type": "BOOLEAN"},
                "save": {"type": "BOOLEAN"},
                "destination": {"type": "STRING"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "open_app",
        "description": "Opens any application on the computer (e.g. WhatsApp, Chrome, Spotify).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING", "description": "Exact name of the application"}
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query"},
                "mode": {"type": "STRING", "description": "search or compare"},
                "items": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": "Controls YouTube: play videos, summarize video, get video info, or trending videos.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": "Captures and analyzes the screen or webcam image. Addresses what you see/analyze.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' or 'camera'. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file"},
                "code":        {"type": "STRING", "description": "Raw code string"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": "THE ONLY tool for ANY Steam or Epic Games request: install, update, list, download status.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": "Shuts down the assistant completely when the user says goodbye or wants to stop.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "save_memory",
        "description": "Save an important personal fact about the user silently to long-term memory.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "identity | preferences | projects | relationships | wishes | notes"},
                "key":   {"type": "STRING", "description": "Short snake_case key"},
                "value": {"type": "STRING", "description": "Concise value in English"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    }
]

class MarkLive:
    def __init__(self, settings, signals=None, window=None):
        self.settings       = settings
        self.signals        = signals
        self.window         = window
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._turn_done_event: asyncio.Event | None = None
        self._active        = True

    def log_bubble(self, text: str, role: str):
        if self.signals:
            self.signals.add_bubble.emit(text, role)
        else:
            _print(f"[{role.upper()}] {text}")

    def set_status(self, msg: str, error: bool = False):
        if self.signals:
            self.signals.set_status.emit(msg, error)
        else:
            _print(f"[STATUS] {msg}")

    def set_thinking(self, thinking: bool):
        if self.signals:
            self.signals.set_thinking.emit(thinking)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.set_status("Speaking...")
        else:
            # Check mic state
            if self.window and not self.window._mic_btn.isChecked():
                self.set_status("Muted")
            else:
                self.set_status("Listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.log_bubble(f"ERR: {tool_name} - {short}", "error")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y - %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        sys_prompt = (
            "You are MARK-XX, a advanced agentic AI coding and desktop assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results -- always call the appropriate tool."
        )

        parts = [time_ctx, sys_prompt]

        voice_name = getattr(self.settings, "live_voice", "Charon")

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        _print(f"[MARK-XX] Tool: {name} with args: {args}")
        self.set_thinking(True)

        loop = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "browser_control":
                from actions.browser_control import browser_control
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args))
                result = r or "Done."

            elif name == "computer_control":
                from actions.computer_control import computer_control
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args))
                result = r or "Done."

            elif name == "computer_settings":
                from actions.computer_settings import computer_settings
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args))
                result = r or "Done."

            elif name == "dev_agent":
                from actions.dev_agent import dev_agent
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, speak=self.speak))
                result = r or "Done."

            elif name == "file_processor":
                from actions.file_processor import file_processor
                r = await loop.run_in_executor(None, lambda: file_processor(parameters=args, speak=self.speak))
                result = r or "Done."

            elif name == "open_app":
                from actions.open_app import open_app
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "web_search":
                from actions.web_search import web_search
                r = await loop.run_in_executor(None, lambda: web_search(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "weather_report":
                from actions.weather_report import weather_action
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "send_message":
                from actions.send_message import send_message
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "reminder":
                from actions.reminder import reminder
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "youtube_video":
                from actions.youtube_video import youtube_video
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "screen_process":
                from actions.screen_processor import screen_process
                r = await loop.run_in_executor(None, lambda: screen_process(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "desktop_control":
                from actions.desktop import desktop_control
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "code_helper":
                from actions.code_helper import code_helper
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.window, speak=self.speak))
                result = r or "Done."

            elif name == "game_updater":
                from actions.game_updater import game_updater
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.window, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                from actions.flight_finder import flight_finder
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.window))
                result = r or "Done."

            elif name == "shutdown_jarvis":
                self.log_bubble("Shutdown requested.", "system")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()
                result = "Goodbye."

            elif name == "save_memory":
                category = args.get("category", "notes")
                key      = args.get("key", "")
                value    = args.get("value", "")
                if key and value:
                    if self.window and hasattr(self.window, "memory") and self.window.memory:
                        self.window.memory.set_pref(f"{category}:{key}", value)
                    _print(f"[Memory] save_memory: {category}/{key} = {value}")
                result = "ok"

            elif name == "file_controller":
                from actions.file_controller import file_controller
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.window))
                result = r or "Done."

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        self.set_thinking(False)
        if self.window and not self.window._mic_btn.isChecked():
            self.set_status("Muted")
        else:
            self.set_status("Listening...")

        _print(f"[MARK-XX] Tool result: {name} -> {str(result)[:100]}")
        self.log_bubble(f"{name}\n{str(result)[:200]}...", "tool")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while self._active:
            try:
                msg = await self.out_queue.get()
                await self.session.send_realtime_input(media=msg)
            except Exception:
                break

    async def _listen_audio(self):
        _print("[MARK-XX] Microphone started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            muted = False
            if self.window:
                muted = not self.window._mic_btn.isChecked()
            if not jarvis_speaking and self._active and not muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                _print("[MARK-XX] Microphone stream open")
                while self._active:
                    await asyncio.sleep(0.1)
        except Exception as e:
            _print(f"[MARK-XX] Microphone error: {e}")
            raise


    async def _receive_audio(self):
        _print("[MARK-XX] Receiver loop started")
        out_buf, in_buf = [], []

        try:
            while self._active:
                async for response in self.session.receive():
                    if not self._active:
                        break

                    if response.data:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.log_bubble(full_in, "user")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.log_bubble(full_out, "assistant")
                            out_buf = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            _print(f"[MARK-XX] Tool call: {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            _print(f"[MARK-XX] Receiver error: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        _print("[MARK-XX] Speaker output started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while self._active:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            _print(f"[MARK-XX] Speaker error: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        api_key = self.settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"}
        )

        model_name = getattr(self.settings, "live_model", LIVE_MODEL)

        while self._active:
            try:
                _print("[MARK-XX] Connecting to Gemini Live API...")
                self.set_status("Connecting...")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=model_name, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._turn_done_event = asyncio.Event()

                    _print("[MARK-XX] Connected successfully.")
                    self.set_status("Listening...")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                _print(f"[MARK-XX] Connection warning: {e}")
                traceback.print_exc()
            self.set_speaking(False)
            self.set_status("Reconnecting...")
            _print("[MARK-XX] Reconnecting in 3s...")
            await asyncio.sleep(3)

    def stop(self):
        self._active = False

def run_live(settings, signals=None, window=None):
    _print("[LiveSession] Starting background live session loop...")
    live = MarkLive(settings, signals, window)
    if window:
        window.live_session = live
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(live.run())
    except KeyboardInterrupt:
        pass
    finally:
        live.stop()
        loop.close()

