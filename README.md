# ⬡ MARK-XX — Personal AI Assistant

> A fully local, Jarvis-style AI assistant powered by **Google Gemini** for intelligence, with local voice recognition, text-to-speech, computer control, screen vision, and persistent memory. No subscription beyond your Gemini API key.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🧠 **AI Brain** | Google Gemini (2.0 Flash, 1.5 Pro, etc.) |
| 🎙️ **Voice Input** | faster-whisper (local, offline, accurate) |
| 🔊 **Voice Output** | edge-tts neural voices (Aria, Guy, Jenny…) |
| 🖥️ **Screen Vision** | Takes screenshots, describes what's on screen |
| 📷 **Webcam** | Captures and analyzes webcam feed |
| 🚀 **App Launcher** | Open apps, launch programs by name |
| ⚡ **Run Commands** | Execute shell commands, get output |
| 📂 **File Manager** | Create, move, delete, list files |
| 📎 **File Analysis** | PDF, images, Word, Excel, code, CSV |
| 🧠 **Memory** | SQLite-backed persistent preferences & history |
| 🎨 **Glassmorphism UI** | Resizable, draggable, transparency control |
| 🪟 **Cross-Platform** | Windows, macOS, Linux |

---

## 🚀 Quick Start

### 1. Get a Gemini API Key
Free at: **https://aistudio.google.com/app/apikey**

### 2. Setup (Windows)
```bat
setup.bat
```
This creates a virtual environment and installs everything automatically.

### 3. Run
```bat
run.bat
```
Or manually:
```bat
venv\Scripts\activate
python main.py
```

### 4. Enter Your API Key
Click the **⚙️ Settings** button in the top-right and paste your Gemini API key.

---

## 🎙️ Voice Commands Examples

| Say... | Action |
|---|---|
| "Open Notepad" | Launches Notepad |
| "Take a screenshot and describe it" | Captures and analyzes screen |
| "Run dir in PowerShell" | Executes shell command |
| "Create a file called notes.txt with Hello World" | Creates file |
| "What files are in my Desktop?" | Lists directory |
| "Search the web for Python tutorials" | Opens browser search |
| "Remember my project is called MarkXX" | Saves to memory |

---

## ⚙️ Settings

| Setting | Description |
|---|---|
| Gemini API Key | Your Google AI Studio key |
| Model | gemini-2.0-flash (recommended) / 1.5-pro / 2.5-pro |
| TTS Voice | 7 neural voice options |
| STT Model | tiny/base/small/medium (speed vs accuracy) |
| Wake Word | Trigger word for auto-listen mode |
| Transparency | Window opacity 40%–100% |
| Always on Top | Float above other windows |

---

## 📁 Project Structure

```
markxx/
├── main.py              # Entry point
├── ui.py                # PyQt6 glassmorphism UI
├── core/
│   ├── llm.py           # Gemini API wrapper
│   ├── stt.py           # faster-whisper voice input
│   ├── tts.py           # edge-tts voice output
│   └── memory.py        # SQLite memory
├── actions/
│   ├── computer.py      # App/file/command control
│   ├── screen.py        # Screenshot + webcam
│   └── file_handler.py  # PDF/image/doc analysis
├── agent/
│   └── planner.py       # Agent orchestration
├── config/
│   └── settings.py      # User settings
├── memory/
│   └── markxx.db        # Auto-created SQLite DB
├── setup.bat            # One-click setup
└── run.bat              # Quick launch
```

---

## 🔧 Manual Install

```bash
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Mac/Linux

pip install PyQt6 google-generativeai faster-whisper edge-tts pyttsx3 \
            sounddevice numpy mss opencv-python Pillow pyautogui PyMuPDF \
            scipy pygame

python main.py
```

---

## 📋 Requirements

- Python 3.10+
- Google Gemini API key (free tier available)
- Microphone (for voice input)
- ~2GB disk space (for STT model download on first use)

---

## 💡 Tips

- **Voice input**: Press the 🎙️ mic button or press **Ctrl+M**
- **File analysis**: Drag & drop any file onto the window
- **Screenshot**: Click 📸 in the top bar, or say "describe my screen"
- **Always visible**: Enable "Always on Top" in Settings for a floating assistant
- The STT model downloads automatically on first mic use (~150MB for `base`)
