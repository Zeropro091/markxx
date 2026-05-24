"""
MARK-XX — Main PyQt6 UI
Glassmorphism dark theme, voice waveform, chat bubbles, file drop, settings panel.
"""

import sys
import os
import math
import time
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QScrollArea,
    QFrame, QSplitter, QSlider, QComboBox, QCheckBox, QTabWidget,
    QFileDialog, QMessageBox, QSizePolicy, QGraphicsOpacityEffect,
    QDialog, QFormLayout, QDialogButtonBox, QProgressBar, QSystemTrayIcon, QMenu,
    QSpinBox
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QSize, QPoint, QRect, QRectF, QPointF, pyqtProperty
)
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QLinearGradient, QRadialGradient,
    QFont, QFontDatabase, QPen, QBrush, QPixmap, QIcon, QAction,
    QDragEnterEvent, QDropEvent, QPalette, QTextCharFormat, QTextCursor
)

# ── Palette ────────────────────────────────────────────────────────────────────
C_BG            = QColor(10,  12,  20)
C_PANEL         = QColor(16,  20,  34,  200)
C_PANEL_LIGHT   = QColor(22,  28,  48,  220)
C_ACCENT        = QColor(64,  180, 255)
C_ACCENT2       = QColor(130, 90,  255)
C_GREEN         = QColor(50,  220, 130)
C_RED           = QColor(255, 80,  80)
C_TEXT          = QColor(220, 230, 255)
C_TEXT_DIM      = QColor(140, 155, 190)
C_BORDER        = QColor(64,  180, 255, 60)
C_USER_BUBBLE   = QColor(64,  180, 255, 35)
C_AI_BUBBLE     = QColor(130, 90,  255, 30)
C_TOOL_BUBBLE   = QColor(50,  220, 130, 25)

STYLE_GLOBAL = """
QWidget {
    background: transparent;
    color: #DCE6FF;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
QScrollBar:vertical {
    background: rgba(16,20,34,120);
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(64,180,255,140);
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { height: 0; }
QToolTip {
    background: rgba(16,20,34,240);
    color: #DCE6FF;
    border: 1px solid rgba(64,180,255,80);
    border-radius: 4px;
    padding: 4px 8px;
}
"""


# ══════════════════════════════════════════════════════════════════════════════
# Voice Waveform Widget
# ══════════════════════════════════════════════════════════════════════════════
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self._phase = 0.0
        self._active = False
        self._amplitude = 0.0
        self._target_amplitude = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    def set_active(self, active: bool):
        self._active = active
        self._target_amplitude = 1.0 if active else 0.0

    def _tick(self):
        self._phase += 0.12
        # Smooth amplitude transition
        diff = self._target_amplitude - self._amplitude
        self._amplitude += diff * 0.15
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        if self._amplitude < 0.01:
            # Draw idle dot
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(C_ACCENT.darker(150)))
            p.drawEllipse(QPointF(cx, cy), 3, 3)
            return

        # Draw animated waveform bars
        bar_count = 24
        bar_w = 3
        spacing = (w - bar_count * bar_w) / (bar_count + 1)

        grad_colors = [C_ACCENT, C_ACCENT2]

        for i in range(bar_count):
            x = spacing + i * (bar_w + spacing)
            # Wave height calculation
            wave = math.sin(self._phase + i * 0.45) * 0.5 + \
                   math.sin(self._phase * 1.3 + i * 0.3) * 0.3 + \
                   math.sin(self._phase * 0.7 + i * 0.6) * 0.2
            bar_h = max(4, (0.5 + wave * 0.5) * (h - 8) * self._amplitude)

            # Color gradient across bars
            t = i / max(bar_count - 1, 1)
            r = int(C_ACCENT.red()   * (1-t) + C_ACCENT2.red()   * t)
            g = int(C_ACCENT.green() * (1-t) + C_ACCENT2.green() * t)
            b = int(C_ACCENT.blue()  * (1-t) + C_ACCENT2.blue()  * t)
            color = QColor(r, g, b, int(200 * self._amplitude))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            rect = QRectF(x, cy - bar_h/2, bar_w, bar_h)
            p.drawRoundedRect(rect, 2, 2)


# ══════════════════════════════════════════════════════════════════════════════
# Chat Bubble
# ══════════════════════════════════════════════════════════════════════════════
class ChatBubble(QFrame):
    def __init__(self, text: str, role: str = "assistant", parent=None):
        super().__init__(parent)
        self.role = role
        self._setup(text)

    def _setup(self, text: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # Role label
        role_labels = {
            "user":      ("YOU",       C_ACCENT),
            "assistant": ("MARK",      C_ACCENT2),
            "tool":      ("SYSTEM",    C_GREEN),
            "error":     ("ERROR",     C_RED),
        }
        label_text, label_color = role_labels.get(self.role, ("MARK", C_ACCENT2))

        header = QLabel(label_text)
        header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        header.setStyleSheet(f"color: rgba({label_color.red()},{label_color.green()},{label_color.blue()},200);")
        layout.addWidget(header)

        # Message text
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.setStyleSheet("color: #DCE6FF; font-size: 13px; line-height: 1.5;")
        msg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(msg)

        self.setMinimumHeight(50)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg_colors = {
            "user":      C_USER_BUBBLE,
            "assistant": C_AI_BUBBLE,
            "tool":      C_TOOL_BUBBLE,
            "error":     QColor(255, 80, 80, 25),
        }
        border_colors = {
            "user":      C_ACCENT,
            "assistant": C_ACCENT2,
            "tool":      C_GREEN,
            "error":     C_RED,
        }
        bg = bg_colors.get(self.role, C_AI_BUBBLE)
        border = border_colors.get(self.role, C_ACCENT2)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(path, QBrush(bg))

        pen = QPen(QColor(border.red(), border.green(), border.blue(), 80), 1)
        p.setPen(pen)
        p.drawPath(path)


# ══════════════════════════════════════════════════════════════════════════════
# Settings Dialog
# ══════════════════════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    settings_saved = pyqtSignal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("MARK — Settings")
        self.setMinimumWidth(580)
        self.setMinimumHeight(580)
        self.setModal(True)
        self._build()

    # ── Slider factory ────────────────────────────────────────────────────────
    def _make_slider(self, lo, hi, val, fmt, scale):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi); s.setValue(int(val * scale))
        s.setStyleSheet("""
            QSlider::groove:horizontal{background:rgba(64,180,255,30);height:6px;border-radius:3px;}
            QSlider::handle:horizontal{background:#40B4FF;width:16px;height:16px;margin:-5px 0;border-radius:8px;}
            QSlider::sub-page:horizontal{background:#40B4FF;border-radius:3px;}""")
        lbl = QLabel(fmt.format(val / 1 if scale == 1 else val))
        lbl.setFixedWidth(52); lbl.setStyleSheet("color:#40B4FF;font-size:11px;")
        s.valueChanged.connect(lambda v: lbl.setText(fmt.format(v / scale)))
        row = QWidget(); rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
        rl.addWidget(s); rl.addWidget(lbl)
        return row, s

    def _hint(self, t):
        l = QLabel(f"<span style='font-size:10px;color:#506070;'>{t}</span>")
        l.setWordWrap(True); return l

    def _section(self, t):
        return QLabel(f"<b style='color:#40B4FF;font-size:12px;'>{t}</b>")

    def _build(self):
        self.setStyleSheet("""
            QDialog{background:rgb(12,15,26);border:1px solid rgba(64,180,255,80);border-radius:12px;}
            QLabel{color:#A0B0D0;}
            QLineEdit,QComboBox,QSpinBox{background:rgba(255,255,255,8);color:#DCE6FF;
                border:1px solid rgba(64,180,255,60);border-radius:6px;padding:6px 10px;}
            QLineEdit:focus,QSpinBox:focus{border-color:rgba(64,180,255,180);}
            QCheckBox{color:#A0B0D0;spacing:8px;}
            QCheckBox::indicator{width:16px;height:16px;border-radius:4px;
                border:1px solid rgba(64,180,255,80);background:rgba(255,255,255,6);}
            QCheckBox::indicator:checked{background:#40B4FF;border-color:#40B4FF;}
            QPushButton{background:rgba(64,180,255,30);color:#40B4FF;
                border:1px solid rgba(64,180,255,100);border-radius:6px;padding:7px 20px;font-weight:bold;}
            QPushButton:hover{background:rgba(64,180,255,60);}
            QTabWidget::pane{border:1px solid rgba(64,180,255,40);border-radius:8px;}
            QTabBar::tab{color:#8090B0;padding:8px 14px;}
            QTabBar::tab:selected{color:#40B4FF;border-bottom:2px solid #40B4FF;}
            QScrollArea{border:none;background:transparent;}
        """)

        root = QVBoxLayout(self)
        root.setSpacing(12); root.setContentsMargins(20,20,20,20)
        hdr = QLabel("⚙️  Settings")
        hdr.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        hdr.setStyleSheet("color:#40B4FF;margin-bottom:8px;")
        root.addWidget(hdr)

        tabs = QTabWidget()
        root.addWidget(tabs)

        def wrap(w):
            sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(w)
            sa.setStyleSheet("background:transparent;"); return sa

        # ═══════════════════════════════════════════════════════════ TAB 1: AI
        ai = QWidget(); f = QFormLayout(ai); f.setSpacing(10)

        self.api_key_input = QLineEdit(self.settings.gemini_api_key)
        self.api_key_input.setPlaceholderText("AIza... (primary key)")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        f.addRow("API Key 1:", self.api_key_input)
        f.addRow(self._hint("🔄 Extra keys — one per line. Auto-rotates on quota exceeded."))
        self.extra_keys_input = QTextEdit()
        self.extra_keys_input.setPlaceholderText("AIzaSy...  ← key 2\nAIzaSy...  ← key 3\n...")
        self.extra_keys_input.setPlainText("\n".join(self.settings.gemini_api_keys))
        self.extra_keys_input.setMinimumHeight(120); self.extra_keys_input.setMaximumHeight(200)
        self.extra_keys_input.setStyleSheet(
            "QTextEdit{background:rgba(255,255,255,6);color:#DCE6FF;"
            "border:1px solid rgba(64,180,255,60);border-radius:6px;"
            "padding:6px 10px;font-size:12px;font-family:'Consolas',monospace;}"
            "QTextEdit:focus{border-color:rgba(64,180,255,180);}")
        f.addRow("Extra Keys:", self.extra_keys_input)
        self._key_status_lbl = QLabel("")
        self._key_status_lbl.setStyleSheet("color:rgba(50,220,130,200);font-size:11px;")
        f.addRow(self._key_status_lbl); self._update_key_status()

        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "gemini-3.1-flash-lite","gemini-2.5-flash-lite","gemini-2.5-flash",
            "gemini-3-flash","gemini-3.5-flash",
            "gemini-2.5-flash-preview-05-20","gemini-1.5-flash","gemini-1.5-pro",
        ])
        idx = self.model_combo.findText(self.settings.gemini_model)
        if idx >= 0: self.model_combo.setCurrentIndex(idx)
        f.addRow("Model:", self.model_combo)

        temp_row, self.temp_slider = self._make_slider(0,100,self.settings.llm_temperature,"{:.2f}",100)
        f.addRow("Temperature:", temp_row)
        f.addRow(self._hint("0 = focused/deterministic   1 = creative/random"))

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(256,8192); self.max_tokens_spin.setSingleStep(256)
        self.max_tokens_spin.setValue(self.settings.llm_max_tokens)
        f.addRow("Max Tokens:", self.max_tokens_spin)

        tabs.addTab(wrap(ai), "🧠 AI")

        # ════════════════════════════════════════════════════════ TAB 2: Voice
        vo = QWidget(); f = QFormLayout(vo); f.setSpacing(10)
        f.addRow(self._section("Text-to-Speech"))
        self.voice_combo = QComboBox()
        self.voice_combo.addItems([
            "en-US-AriaNeural","en-US-GuyNeural","en-US-JennyNeural",
            "en-US-DavisNeural","en-US-TonyNeural",
            "en-GB-SoniaNeural","en-GB-RyanNeural",
            "en-AU-NatashaNeural","en-IN-NeerjaNeural",
        ])
        idx = self.voice_combo.findText(self.settings.voice_name)
        if idx >= 0: self.voice_combo.setCurrentIndex(idx)
        f.addRow("Voice:", self.voice_combo)
        rate_row, self.rate_slider = self._make_slider(50,200,self.settings.tts_rate,"{:.1f}x",100)
        f.addRow("Speed:", rate_row)
        vol_row,  self.vol_slider  = self._make_slider(0,100,self.settings.tts_volume,"{:.0f}%",100)
        f.addRow("Volume:", vol_row)
        self.speak_cb = QCheckBox("Speak responses automatically")
        self.speak_cb.setChecked(self.settings.speak_responses)
        f.addRow("", self.speak_cb)

        f.addRow(QLabel("")); f.addRow(self._section("Speech Recognition (STT)"))
        self.stt_model_combo = QComboBox()
        self.stt_model_combo.addItems(["tiny","base","small","medium","large"])
        idx = self.stt_model_combo.findText(self.settings.stt_model_size)
        if idx >= 0: self.stt_model_combo.setCurrentIndex(idx)
        f.addRow("Whisper Model:", self.stt_model_combo)
        f.addRow(self._hint("tiny = fast/less accurate   large = slow/most accurate"))
        self.stt_lang_combo = QComboBox()
        self.stt_lang_combo.addItems(["en","id","auto","es","fr","de","ja","zh","ko","pt"])
        idx = self.stt_lang_combo.findText(self.settings.stt_language)
        if idx >= 0: self.stt_lang_combo.setCurrentIndex(idx)
        f.addRow("Language:", self.stt_lang_combo)
        sens_row, self.sens_slider = self._make_slider(1,50,self.settings.mic_sensitivity*1000,"{:.0f}",1000)
        f.addRow("Mic Sensitivity:", sens_row)
        f.addRow(self._hint("Low = picks up more (noisy room).  High = needs a louder voice."))
        gate_row, self.gate_slider = self._make_slider(5,50,self.settings.silence_gate_sec,"{:.1f}s",10)
        f.addRow("Silence Gate:", gate_row)
        f.addRow(self._hint("Seconds of silence before MARK processes your speech."))
        self.wake_word_input = QLineEdit(self.settings.wake_word)
        f.addRow("Wake Word:", self.wake_word_input)
        tabs.addTab(wrap(vo), "🎙️ Voice")

        # ══════════════════════════════════════════════════ TAB 3: Interface
        ui = QWidget(); f = QFormLayout(ui); f.setSpacing(10)
        op_row, self.opacity_slider = self._make_slider(40,100,self.settings.window_opacity,"{:.0f}%",100)
        f.addRow("Transparency:", op_row)
        fn_row, self.font_slider    = self._make_slider(10,20,self.settings.font_size,"{:.0f}px",1)
        f.addRow("Font Size:", fn_row)
        self.win_size_combo = QComboBox()
        self.win_size_combo.addItems(["Compact (380×580)","Normal (480×720)","Wide (600×800)","Large (700×900)"])
        _szs = [(380,580),(480,720),(600,800),(700,900)]
        _best = min(range(4), key=lambda i: abs(_szs[i][0]-self.settings.window_width))
        self.win_size_combo.setCurrentIndex(_best)
        f.addRow("Window Size:", self.win_size_combo)
        self.always_on_top_cb = QCheckBox("Always on top")
        self.always_on_top_cb.setChecked(self.settings.always_on_top)
        f.addRow("", self.always_on_top_cb)
        tabs.addTab(wrap(ui), "🎨 Interface")

        # ══════════════════════════════════════════════════ TAB 4: Behaviour
        beh = QWidget(); f = QFormLayout(beh); f.setSpacing(10)
        self.user_name_input = QLineEdit(self.settings.user_name)
        f.addRow("Your Name:", self.user_name_input)
        self.assistant_name_input = QLineEdit(self.settings.assistant_name)
        f.addRow("Assistant Name:", self.assistant_name_input)
        self.max_turns_spin = QSpinBox()
        self.max_turns_spin.setRange(5,200); self.max_turns_spin.setValue(self.settings.max_history_turns)
        f.addRow("History Turns:", self.max_turns_spin)
        f.addRow(self._hint("How many previous messages MARK keeps in context."))
        self.auto_ss_cb = QCheckBox("Auto-capture screenshot when asked about screen")
        self.auto_ss_cb.setChecked(self.settings.auto_screenshot_on_request)
        f.addRow("", self.auto_ss_cb)
        tabs.addTab(wrap(beh), "⚙️ Behaviour")

        # ── Save / Cancel ─────────────────────────────────────────────────────
        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet("color:#8090B0;border-color:rgba(255,255,255,30);")
        cancel.clicked.connect(self.reject)
        save = QPushButton("  Save  ")
        save.clicked.connect(self._save)
        btns.addWidget(cancel); btns.addWidget(save)
        root.addLayout(btns)

    def _update_key_status(self):
        primary = self.api_key_input.text().strip()
        extras  = [k.strip() for k in self.extra_keys_input.toPlainText().splitlines() if k.strip()]
        total   = len([k for k in ([primary]+extras) if k])
        self._key_status_lbl.setText(f"🔑 {total} key{'s' if total!=1 else ''} in rotation pool")

    def _save(self):
        s = self.settings
        s.gemini_api_key   = self.api_key_input.text().strip()
        s.gemini_api_keys  = [k.strip() for k in self.extra_keys_input.toPlainText().splitlines()
                               if k.strip() and k.strip() != s.gemini_api_key]
        s.gemini_model     = self.model_combo.currentText()
        s.llm_temperature  = self.temp_slider.value() / 100.0
        s.llm_max_tokens   = self.max_tokens_spin.value()
        s.voice_name       = self.voice_combo.currentText()
        s.tts_rate         = self.rate_slider.value() / 100.0
        s.tts_volume       = self.vol_slider.value() / 100.0
        s.speak_responses  = self.speak_cb.isChecked()
        s.stt_model_size   = self.stt_model_combo.currentText()
        s.stt_language     = self.stt_lang_combo.currentText()
        s.mic_sensitivity  = self.sens_slider.value() / 1000.0
        s.silence_gate_sec = self.gate_slider.value() / 10.0
        s.silence_hysteresis = s.mic_sensitivity * 0.6
        s.wake_word        = self.wake_word_input.text().strip().lower()
        s.window_opacity   = self.opacity_slider.value() / 100.0
        s.font_size        = self.font_slider.value()
        _szs = [(380,580),(480,720),(600,800),(700,900)]
        s.window_width, s.window_height = _szs[self.win_size_combo.currentIndex()]
        s.always_on_top    = self.always_on_top_cb.isChecked()
        s.user_name        = self.user_name_input.text().strip() or "User"
        s.assistant_name   = self.assistant_name_input.text().strip() or "MARK"
        s.max_history_turns = self.max_turns_spin.value()
        s.auto_screenshot_on_request = self.auto_ss_cb.isChecked()
        self.settings_saved.emit(s)
        self.accept()

# ══════════════════════════════════════════════════════════════════════════════
# Main Window
# ══════════════════════════════════════════════════════════════════════════════
class MarkWindow(QMainWindow):
    def __init__(self, settings, llm_client, memory, planner, stt_worker, tts_worker):
        super().__init__()
        self.settings    = settings
        self.llm_client  = llm_client
        self.memory      = memory
        self.planner     = planner
        self.stt_worker  = stt_worker
        self.tts_worker  = tts_worker
        self._is_listening = False
        self._is_thinking  = False

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._apply_settings()
        self._show_welcome()

    # ── Window Setup ──────────────────────────────────────────────────────────
    def _setup_window(self):
        self.setWindowTitle("MARK-XX")
        self.setMinimumSize(380, 580)
        self.resize(self.settings.window_width, self.settings.window_height)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)

        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width() - self.settings.window_width - 40,
            (screen.height() - self.settings.window_height) // 2
        )

    # ── UI Construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setObjectName("centralWidget")

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Glass panel
        self._panel = QWidget()
        self._panel.setObjectName("glassPanel")
        self._panel.setStyleSheet("""
            #glassPanel {
                background: rgba(12,15,28,220);
                border-radius: 16px;
                border: 1px solid rgba(64,180,255,60);
            }
        """)
        outer.addWidget(self._panel)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # ── Title Bar ─────────────────────────────────────────────────────────
        self._title_bar = self._build_title_bar()
        panel_layout.addWidget(self._title_bar)

        # ── Status Bar ────────────────────────────────────────────────────────
        self._status_bar = self._build_status_bar()
        panel_layout.addWidget(self._status_bar)

        # ── Chat Area ─────────────────────────────────────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setStyleSheet("background: transparent;")
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._chat_container = QWidget()
        self._chat_container.setStyleSheet("background: transparent;")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(12, 12, 12, 12)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch()

        self._scroll_area.setWidget(self._chat_container)
        panel_layout.addWidget(self._scroll_area, 1)

        # ── Thinking Indicator ────────────────────────────────────────────────
        self._thinking_bar = QWidget()
        self._thinking_bar.setFixedHeight(3)
        self._thinking_bar.setStyleSheet("background: transparent;")
        self._thinking_bar.setVisible(False)
        panel_layout.addWidget(self._thinking_bar)

        # ── Waveform ──────────────────────────────────────────────────────────
        self._waveform = WaveformWidget()
        panel_layout.addWidget(self._waveform)

        # ── Input Area ────────────────────────────────────────────────────────
        input_widget = self._build_input_area()
        panel_layout.addWidget(input_widget)

        # Resize handle
        self._resize_grip = QLabel("⠿")
        self._resize_grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._resize_grip.setFixedHeight(14)
        self._resize_grip.setStyleSheet("color: rgba(64,180,255,40); font-size:12px;")
        self._resize_grip.setCursor(Qt.CursorShape.SizeFDiagCursor)
        panel_layout.addWidget(self._resize_grip)

        # Drag-to-resize state
        self._drag_pos = None
        self._resizing = False
        self._resize_start_pos = None
        self._resize_start_size = None

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        bar.setStyleSheet("""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 rgba(20,25,45,220), stop:1 rgba(12,15,28,220));
            border-radius: 16px 16px 0 0;
            border-bottom: 1px solid rgba(64,180,255,40);
        """)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)

        # Icon + Name
        icon_lbl = QLabel("⬡")
        icon_lbl.setFont(QFont("Segoe UI", 18))
        icon_lbl.setStyleSheet("color: #40B4FF;")
        layout.addWidget(icon_lbl)

        name_lbl = QLabel("MARK")
        name_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color: #DCE6FF; letter-spacing: 3px;")
        layout.addWidget(name_lbl)

        self._status_dot = QLabel("●")
        self._status_dot.setFont(QFont("Segoe UI", 8))
        self._status_dot.setStyleSheet("color: #32DC82; margin-top: 8px;")
        layout.addWidget(self._status_dot)

        layout.addStretch()

        # Window controls
        for icon, tooltip, action in [
            ("⚙", "Settings",    self._open_settings),
            ("—", "Minimize",    self.showMinimized),
            ("⬛", "Maximize",    self._toggle_max),
            ("✕", "Close",       self.close),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(32, 32)
            btn.setToolTip(tooltip)
            btn.clicked.connect(action)
            if icon == "✕":
                btn.setStyleSheet("""
                    QPushButton { background:transparent; color:#8090B0; border:none; font-size:14px; border-radius:6px; }
                    QPushButton:hover { background:rgba(255,80,80,120); color:white; }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton { background:transparent; color:#8090B0; border:none; font-size:14px; border-radius:6px; }
                    QPushButton:hover { background:rgba(64,180,255,30); color:#40B4FF; }
                """)
            layout.addWidget(btn)

        # Enable drag
        bar.mousePressEvent   = self._on_title_press
        bar.mouseMoveEvent    = self._on_title_move
        bar.mouseReleaseEvent = self._on_title_release
        return bar

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(28)
        bar.setStyleSheet("background: transparent; border-bottom: 1px solid rgba(64,180,255,20);")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("color: rgba(140,155,190,180); font-size: 11px;")
        layout.addWidget(self._status_label)

        layout.addStretch()

        # Screenshot button
        ss_btn = QPushButton("📸")
        ss_btn.setToolTip("Take Screenshot & Analyze")
        ss_btn.setFixedSize(24, 20)
        ss_btn.setStyleSheet("QPushButton{background:transparent;border:none;font-size:14px;} QPushButton:hover{color:#40B4FF;}")
        ss_btn.clicked.connect(self._trigger_screenshot)
        layout.addWidget(ss_btn)

        # Webcam button
        cam_btn = QPushButton("📷")
        cam_btn.setToolTip("Capture Webcam")
        cam_btn.setFixedSize(24, 20)
        cam_btn.setStyleSheet("QPushButton{background:transparent;border:none;font-size:14px;} QPushButton:hover{color:#40B4FF;}")
        cam_btn.clicked.connect(self._trigger_webcam)
        layout.addWidget(cam_btn)

        # Clear button
        clr_btn = QPushButton("🗑")
        clr_btn.setToolTip("Clear Chat")
        clr_btn.setFixedSize(24, 20)
        clr_btn.setStyleSheet("QPushButton{background:transparent;border:none;font-size:14px;} QPushButton:hover{color:#FF5050;}")
        clr_btn.clicked.connect(self._clear_chat)
        layout.addWidget(clr_btn)

        return bar

    def _build_input_area(self) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("""
            background: rgba(16,20,38,180);
            border-top: 1px solid rgba(64,180,255,40);
            border-radius: 0 0 16px 16px;
        """)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)

        # File drop label (hidden by default)
        self._drop_label = QLabel("📎 Drop files here to analyze (PDF, images, code, docs)")
        self._drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_label.setStyleSheet("""
            color: rgba(64,180,255,120);
            font-size: 11px;
            border: 1px dashed rgba(64,180,255,60);
            border-radius: 6px;
            padding: 6px;
        """)
        self._drop_label.setVisible(False)
        layout.addWidget(self._drop_label)

        # Input row
        row = QHBoxLayout()
        row.setSpacing(8)

        self._text_input = QTextEdit()
        self._text_input.setPlaceholderText("Message MARK... (Enter to send, Shift+Enter for newline)")
        self._text_input.setMaximumHeight(80)
        self._text_input.setMinimumHeight(44)
        self._text_input.setStyleSheet("""
            QTextEdit {
                background: rgba(255,255,255,6);
                color: #DCE6FF;
                border: 1px solid rgba(64,180,255,60);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QTextEdit:focus { border-color: rgba(64,180,255,160); }
        """)
        self._text_input.installEventFilter(self)
        row.addWidget(self._text_input, 1)

        # Buttons column
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        self._send_btn = QPushButton("▶")
        self._send_btn.setFixedSize(44, 44)
        self._send_btn.setToolTip("Send (Enter)")
        self._send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(64,180,255,180), stop:1 rgba(130,90,255,180));
                color: white; border: none; border-radius: 10px;
                font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 rgba(64,180,255,220), stop:1 rgba(130,90,255,220)); }
            QPushButton:pressed { background: rgba(64,180,255,100); }
        """)
        self._send_btn.clicked.connect(self._send_message)
        btn_col.addWidget(self._send_btn)

        self._mic_btn = QPushButton("🎙")
        self._mic_btn.setFixedSize(44, 32)
        self._mic_btn.setToolTip("Toggle Microphone (Ctrl+M)")
        self._mic_btn.setCheckable(True)
        self._mic_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,8); color: #8090B0;
                border: 1px solid rgba(255,255,255,20); border-radius: 8px; font-size: 14px;
            }
            QPushButton:hover { background: rgba(64,180,255,25); color:#40B4FF; border-color:rgba(64,180,255,80); }
            QPushButton:checked { background: rgba(50,220,130,30); color:#32DC82; border-color:rgba(50,220,130,120); }
        """)
        self._mic_btn.clicked.connect(self._toggle_mic)
        btn_col.addWidget(self._mic_btn)

        row.addLayout(btn_col)
        layout.addLayout(row)

        # File attach button
        attach_row = QHBoxLayout()
        attach_btn = QPushButton("📎  Attach File")
        attach_btn.setStyleSheet("""
            QPushButton { background:transparent; color:rgba(64,180,255,150);
                border:none; font-size:11px; text-align:left; }
            QPushButton:hover { color:#40B4FF; }
        """)
        attach_btn.clicked.connect(self._attach_file)
        attach_row.addWidget(attach_btn)
        attach_row.addStretch()

        self._tts_toggle = QCheckBox("🔊 Speak responses")
        self._tts_toggle.setChecked(True)
        self._tts_toggle.setStyleSheet("color: rgba(140,155,190,150); font-size:11px;")
        attach_row.addWidget(self._tts_toggle)
        layout.addLayout(attach_row)

        return widget

    # ── Signal Connections ────────────────────────────────────────────────────
    def _connect_signals(self):
        self.planner.response_ready.connect(self._on_response)
        self.planner.tool_executed.connect(self._on_tool_executed)
        self.planner.thinking.connect(self._on_thinking)
        self.planner.error_occurred.connect(self._on_error)
        # Agentic step updates (ReAct loop progress)
        if hasattr(self.planner, 'step_update'):
            self.planner.step_update.connect(
                lambda msg: self._set_status(msg) if msg else None
            )

        if self.stt_worker:
            self.stt_worker.transcribed.connect(self._on_transcribed)
            self.stt_worker.listening_started.connect(self._on_listening_started)
            self.stt_worker.listening_stopped.connect(self._on_listening_stopped)
            self.stt_worker.silence_countdown.connect(self._on_silence_countdown)
            self.stt_worker.error_occurred.connect(lambda e: self._set_status(f"STT: {e}", error=True))

        if self.tts_worker:
            self.tts_worker.started_speaking.connect(lambda: self._set_status("Speaking..."))
            self.tts_worker.finished_speaking.connect(lambda: self._set_status("Ready"))

        # Key rotation notification
        def _on_key_rotated(key, slot, total, reason):
            short = key[:8] + "…" if len(key) > 8 else key
            msg = f"🔄 Key rotated → slot {slot}/{total} ({short}) — {reason}"
            self._set_status(msg)
            self._add_bubble(msg, "tool")

        self.llm_client.on_key_rotated = _on_key_rotated

    # ── Apply Settings ────────────────────────────────────────────────────────
    def _apply_settings(self):
        self.setWindowOpacity(self.settings.window_opacity)
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if self.settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.show()
        QTimer.singleShot(200, self._register_hotkey)

    # ── Welcome Message ───────────────────────────────────────────────────────
    def _show_welcome(self):
        has_key = bool(self.settings.gemini_api_key)
        if has_key:
            msg = (f"Hello{' ' + self.settings.user_name if self.settings.user_name else ''}! "
                   "I'm MARK, your personal AI assistant. I'm online and ready.\n\n"
                   "I can open apps, manage files, analyze documents, see your screen, and more. "
                   "Just ask, or press the mic button to speak.")
        else:
            msg = ("Welcome to MARK! ⚠️ No Gemini API key found.\n\n"
                   "Please click ⚙️ Settings and enter your Gemini API key to get started. "
                   "Get a free key at: aistudio.google.com")
        self._add_bubble(msg, "assistant")

    # ── Chat Helpers ──────────────────────────────────────────────────────────
    def _add_bubble(self, text: str, role: str):
        bubble = ChatBubble(text, role)
        # Insert before stretch
        idx = self._chat_layout.count() - 1
        self._chat_layout.insertWidget(idx, bubble)
        # Scroll to bottom
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        self._scroll_area.verticalScrollBar().setValue(
            self._scroll_area.verticalScrollBar().maximum()
        )

    def _clear_chat(self):
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.memory.clear_history()
        self.llm_client.reset_chat()
        self._add_bubble("Chat cleared. How can I help you?", "assistant")

    # ── Send ──────────────────────────────────────────────────────────────────
    def _send_message(self):
        text = self._text_input.toPlainText().strip()
        if not text or self._is_thinking:
            return
        if not self.llm_client.is_configured:
            self._add_bubble("⚠️ Please set your Gemini API key in Settings (⚙️).", "error")
            return
        self._text_input.clear()
        self._add_bubble(text, "user")
        self.planner.submit(text)

    def _on_transcribed(self, text: str):
        if not text.strip():
            return
        self._text_input.setPlainText(text)
        self._send_message()

    # ── Planner Callbacks ─────────────────────────────────────────────────────
    def _on_response(self, text: str):
        self._add_bubble(text, "assistant")
        if self._tts_toggle.isChecked() and self.tts_worker:
            self.tts_worker.speak(text)

    def _on_tool_executed(self, tool_name: str, result: str):
        short = result[:200] + ("..." if len(result) > 200 else "")
        self._add_bubble(f"{tool_name}\n{short}", "tool")

    def _on_thinking(self, thinking: bool):
        self._is_thinking = thinking
        if thinking:
            self._set_status("Thinking...")
            self._status_dot.setStyleSheet("color: #F0A040; margin-top: 8px;")
        else:
            self._set_status("Ready")
            self._status_dot.setStyleSheet("color: #32DC82; margin-top: 8px;")

    def _on_error(self, error: str):
        self._add_bubble(f"Error: {error}", "error")

    # ── Status ────────────────────────────────────────────────────────────────
    def _set_status(self, msg: str, error: bool = False):
        self._status_label.setText(msg)
        if error:
            self._status_label.setStyleSheet("color: rgba(255,80,80,180); font-size: 11px;")
        else:
            self._status_label.setStyleSheet("color: rgba(140,155,190,180); font-size: 11px;")

    # ── Mic / STT ─────────────────────────────────────────────────────────────
    def _on_listening_started(self):
        """Speech detected — light up waveform."""
        self._waveform.set_active(True)
        self._set_status("🎤 Listening…")

    def _on_listening_stopped(self):
        """Silence gate closed — transcribing."""
        self._waveform.set_active(False)
        self._set_status("⏳ Transcribing…")

    def _on_silence_countdown(self, remaining: float):
        """Live countdown while trailing silence accumulates."""
        if remaining > 0.05:
            self._set_status(f"🔇 Processing in {remaining:.1f}s…")

    def _toggle_mic(self):
        if not self.stt_worker:
            self._add_bubble("STT not available. Install faster-whisper.", "error")
            return
        self._is_listening = self._mic_btn.isChecked()
        if self._is_listening:
            if not self.stt_worker.isRunning():
                self._set_status("⏳ Loading speech model…")
                self.stt_worker.start()
            else:
                self.stt_worker.resume()
            self._set_status("🎤 Mic active — speak anytime")
        else:
            self.stt_worker.pause()
            self._waveform.set_active(False)
            self._set_status("Ready")

    # ── Screenshot / Webcam ───────────────────────────────────────────────────
    def _trigger_screenshot(self):
        self._add_bubble("Taking a screenshot and analyzing it...", "user")
        self.planner.submit("Take a screenshot and describe what you see on my screen in detail.")

    def _trigger_webcam(self):
        self._add_bubble("Capturing webcam...", "user")
        self.planner.submit("Capture my webcam and describe what you see.")

    # ── File Handling ─────────────────────────────────────────────────────────
    def _attach_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach File", "",
            "All Supported Files (*.pdf *.txt *.md *.py *.js *.ts *.html *.json *.csv "
            "*.png *.jpg *.jpeg *.gif *.docx *.xlsx *.xml *.yaml *.yml);;"
            "All Files (*)"
        )
        if path:
            self._process_dropped_file(path)

    def _process_dropped_file(self, path: str):
        name = Path(path).name
        self._add_bubble(f"📎 Analyzing: {name}", "user")
        prompt = self._text_input.toPlainText().strip() or "Please analyze this file and give me a detailed summary."
        self._text_input.clear()
        # Process in planner thread
        QThread.currentThread()
        threading.Thread(target=self.planner.process_file, args=(path, prompt), daemon=True).start()

    # ── Settings ──────────────────────────────────────────────────────────────
    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self, new_settings):
        from config.settings import save_settings
        self.settings = new_settings
        save_settings(new_settings)
        all_keys = new_settings.get_all_keys()
        self.llm_client.configure(
            api_key=all_keys[0] if all_keys else "",
            model=new_settings.gemini_model,
            extra_keys=all_keys[1:] if len(all_keys) > 1 else [],
        )
        self._apply_settings()
        if self.tts_worker:
            self.tts_worker.voice  = new_settings.voice_name
            self.tts_worker.rate   = new_settings.tts_rate
            self.tts_worker.volume = new_settings.tts_volume
        key_count = len(all_keys)
        self._add_bubble(
            f"Settings saved ✓  —  {key_count} API key{'s' if key_count != 1 else ''} in rotation pool.", "tool"
        )

    # ── Window Controls ───────────────────────────────────────────────────────
    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # Drag to move (title bar)
    def _on_title_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _on_title_move(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def _on_title_release(self, event):
        self._drag_pos = None

    # Drag to resize (bottom-right grip)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            grip = self._resize_grip.geometry()
            if grip.contains(pos):
                self._resizing = True
                self._resize_start_pos  = event.globalPosition().toPoint()
                self._resize_start_size = self.size()

    def mouseMoveEvent(self, event):
        if self._resizing and self._resize_start_pos:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            new_w = max(380, self._resize_start_size.width()  + delta.x())
            new_h = max(500, self._resize_start_size.height() + delta.y())
            self.resize(new_w, new_h)

    def mouseReleaseEvent(self, event):
        self._resizing = False

    # ── Drag & Drop ───────────────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_label.setVisible(True)

    def dragLeaveEvent(self, event):
        self._drop_label.setVisible(False)

    def dropEvent(self, event: QDropEvent):
        self._drop_label.setVisible(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self._process_dropped_file(path)

    # ── Enter key in input ────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._text_input and event.type() == QEvent.Type.KeyPress:
            if (event.key() == Qt.Key.Key_Return and
                    not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    # ── Paint (glass background) ──────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Subtle glow behind panel
        glow = QRadialGradient(self.width() / 2, 0, self.width())
        glow.setColorAt(0, QColor(64, 180, 255, 15))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(glow))

    def _register_hotkey(self):
        if os.name == 'nt':
            try:
                import ctypes
                self.HOTKEY_ID = 99
                hwnd = int(self.winId())
                if not hwnd:
                    QTimer.singleShot(200, self._register_hotkey)
                    return
                # MOD_CONTROL = 0x0002, MOD_NOREPEAT = 0x4000
                # VK_PRIOR (PageUp) = 0x21
                ctypes.windll.user32.UnregisterHotKey(hwnd, self.HOTKEY_ID)
                success = ctypes.windll.user32.RegisterHotKey(hwnd, self.HOTKEY_ID, 0x0002 | 0x4000, 0x21)
                if success:
                    print("✅ Global hotkey Ctrl+PageUp registered successfully")
                else:
                    print("❌ Failed to register global hotkey Ctrl+PageUp")
            except Exception as e:
                print(f"Error registering global hotkey: {e}")

    def _toggle_window(self):
        if self.isMinimized() or not self.isVisible() or not self.isActiveWindow():
            self.show()
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            self.raise_()
            self.activateWindow()
        else:
            self.hide()

    def nativeEvent(self, eventType, message):
        if os.name == 'nt' and eventType == b'windows_generic_MSG':
            try:
                import ctypes
                from ctypes import wintypes
                ptr = int(message)
                if ptr != 0:
                    sz = ctypes.sizeof(wintypes.MSG)
                    data = ctypes.string_at(ptr, sz)
                    msg = wintypes.MSG.from_buffer_copy(data)
                    if msg.message == 0x0312:  # WM_HOTKEY
                        if msg.wParam == getattr(self, 'HOTKEY_ID', 99):
                            self._toggle_window()
                            return True, 0
            except Exception:
                pass
        return False, 0


    def closeEvent(self, event):
        # Save window size
        self.settings.window_width  = self.width()
        self.settings.window_height = self.height()
        from config.settings import save_settings
        save_settings(self.settings)

        # Unregister hotkey
        if os.name == 'nt':
            try:
                import ctypes
                hwnd = int(self.winId())
                ctypes.windll.user32.UnregisterHotKey(hwnd, getattr(self, 'HOTKEY_ID', 99))
            except Exception:
                pass

        # Stop threads
        if self.stt_worker and self.stt_worker.isRunning():
            self.stt_worker.stop()
        if self.tts_worker and self.tts_worker.isRunning():
            self.tts_worker.stop()
        if self.planner.isRunning():
            self.planner.stop()

        event.accept()
