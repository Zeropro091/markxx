import sys
import os
from pathlib import Path

# Enable ANSI escape sequences on Windows
if os.name == 'nt':
    os.system('')

from textual import work, on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Input, RichLog, Static, Button, Label, Select, Checkbox, TextArea
from textual.reactive import reactive
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from rich.markdown import Markdown

from config.settings import load_settings
from core.llm import LLMClient
from core.memory import Memory
from agent.cli_planner import CLIPlanner
from core.scheduler import JobScheduler

def get_clipboard_text() -> str:
    """Read text from clipboard. Uses PowerShell for reliability in alt-screen terminals."""
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        return result.stdout.rstrip("\r\n") if result.returncode == 0 else ""
    except Exception:
        return ""


def set_clipboard_text(text: str) -> bool:
    """Copy text to clipboard. Uses PowerShell for reliability in alt-screen terminals."""
    if not text:
        return False
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Set-Clipboard", "-Value", text],
            capture_output=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        return True
    except Exception:
        return False


class ClipboardMixin:
    """Mixin that adds Ctrl+V paste and Ctrl+C copy to any Screen or App.

    Screens using this mixin should declare bindings with priority=True:
        Binding("ctrl+v", "paste_clipboard", "Paste", show=False, priority=True),
        Binding("ctrl+c", "copy_clipboard", "Copy", show=False, priority=True),
    """

    def action_paste_clipboard(self) -> None:
        focused = self.focused
        if isinstance(focused, (Input, TextArea)):
            text = get_clipboard_text()
            if text:
                if isinstance(focused, Input):
                    val = focused.value
                    cursor = focused.cursor_position
                    focused.value = val[:cursor] + text + val[cursor:]
                    focused.cursor_position = cursor + len(text)
                elif isinstance(focused, TextArea):
                    focused.insert(text)

    def action_copy_clipboard(self) -> None:
        focused = self.focused
        if isinstance(focused, Input):
            text = focused.value
            if text:
                set_clipboard_text(text)
        elif isinstance(focused, TextArea):
            text = focused.selected_text if hasattr(focused, 'selected_text') else ""
            if text:
                set_clipboard_text(text)


class SidebarInfo(Static):
    """Sidebar showing current configuration, session details, and tool status."""

    status_text = reactive("Ready")
    budget_text = reactive("Budget: $0.00 / $1.00")

    def __init__(self, settings, working_dir, mode, budget, **kwargs):
        super().__init__(**kwargs)
        self.settings = settings
        self.working_dir = working_dir
        self.mode = mode
        self.budget = budget

    def render(self) -> Text:
        result = Text()
        parts = [
            ("⚙️ SYSTEM STATUS\n", "bold magenta"),
            (f"Model: {self.settings.gemini_model}\n", "cyan"),
            (f"API keys: {len(self.settings.get_all_keys())} (rotation pool)\n", "dim"),
            (f"Mode: {self.mode}\n", "green" if self.mode == "YOLO" else "yellow"),
            (f"Dir: {self.working_dir}\n", "dim"),
            ("\n", ""),
            ("📊 TOKEN BUDGET\n", "bold magenta"),
            (f"{self.budget_text}\n", "yellow"),
            ("\n", ""),
            ("🤖 AGENT STATUS\n", "bold magenta"),
            (self.status_text, "bold green" if "Ready" in self.status_text else "bold orange1"),
        ]
        for text, style in parts:
            result.append(text, style=style)
        return result


TIER_MODELS = {
    "high": [
        ("Gemini 3.1 Pro (Preview) [0 RPM, 0 RPD]", "gemini-3.1-pro-preview"),
        ("Gemini 2.5 Pro [0 RPM, 0 RPD]", "gemini-2.5-pro"),
        ("Gemini 1.5 Pro [0 RPM, 0 RPD]", "gemini-1.5-pro"),
    ],
    "medium": [
        ("Gemini 3.5 Flash [5 RPM, 20 RPD]", "gemini-3.5-flash"),
        ("Gemini 3 Flash [5 RPM, 20 RPD]", "gemini-3-flash"),
        ("Gemini 2.5 Flash [5 RPM, 20 RPD]", "gemini-2.5-flash"),
        ("Gemini 1.5 Flash [15 RPM, 15 RPD]", "gemini-1.5-flash"),
    ],
    "low": [
        ("Gemini 3.1 Flash-Lite [15 RPM, 500 RPD]", "gemini-3.1-flash-lite"),
        ("Gemini 2.5 Flash-Lite [10 RPM, 20 RPD]", "gemini-2.5-flash-lite"),
    ]
}


class SettingsScreen(ClipboardMixin, Screen):
    """Screen for modifying CLI and LLM settings."""

    BINDINGS = [
        Binding("escape", "dismiss", "Go Back", show=True),
        Binding("ctrl+v", "paste_clipboard", "Paste", show=False, priority=True),
        Binding("ctrl+c", "copy_clipboard", "Copy", show=False, priority=True),
    ]

    def __init__(self, settings, **kwargs):
        super().__init__(**kwargs)
        self.settings = settings

        # Find matching initial tier for active model
        self.initial_tier = "medium"
        for tier, models in TIER_MODELS.items():
            if any(m[1] == self.settings.gemini_model for m in models):
                self.initial_tier = tier
                break

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="settings-form"):
            yield Static("⚙️ TECHNICAL CLI SETTINGS", classes="settings-title")

            yield Label("Gemini API Keys (one per line, first = primary):")
            yield TextArea("\n".join([self.settings.gemini_api_key] + self.settings.gemini_api_keys), id="setting-api-keys", language=None)
            # Button to add a single API key dynamically
            yield Button("+ Add API Key", variant="primary", id="btn-add-key")

            yield Label("Model Tier:")
            yield Select(
                options=[
                    ("High Tier (Pro/Complex)", "high"),
                    ("Medium Tier (Flash/Balanced)", "medium"),
                    ("Low Tier (Lite/Speed)", "low")
                ],
                value=self.initial_tier,
                id="setting-tier"
            )

            yield Label("Model:")
            yield Select(
                options=TIER_MODELS[self.initial_tier],
                value=self.settings.gemini_model,
                id="setting-model"
            )

            yield Label("Max Steps per Task:")
            yield Input(value=str(self.settings.cli_max_steps), id="setting-steps")

            yield Label("Max Result Length:")
            yield Input(value=str(self.settings.cli_max_result_len), id="setting-result-len")

            yield Label("Max Heal Retries:")
            yield Input(value=str(self.settings.cli_max_heal_retries), id="setting-heal-retries")

            yield Label("LLM Temperature:")
            yield Input(value=str(self.settings.llm_temperature), id="setting-temp")

            yield Label("Self-Evolution:")
            yield Checkbox("Enable agent self-evolution capability", value=self.settings.cli_enable_self_evolution, id="setting-self-evolve")

            with Horizontal(classes="buttons-row"):
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", variant="error", id="btn-cancel")
        yield Footer()

    @on(Select.Changed, "#setting-tier")
    def tier_changed(self, event: Select.Changed) -> None:
        tier = event.value
        if tier:
            model_select = self.query_one("#setting-model", Select)
            model_select.set_options(TIER_MODELS[tier])
            model_select.value = TIER_MODELS[tier][0][1]

    def action_dismiss(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-cancel")
    def cancel_pressed(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-add-key")
    def add_key_pressed(self) -> None:
        def after_add(new_key):
            if new_key:
                # Update the API keys textarea to reflect added key
                ta = self.query_one("#setting-api-keys", TextArea)
                keys = [self.settings.gemini_api_key] + self.settings.gemini_api_keys
                ta.load_text("\n".join(keys))
        self.push_screen(AddApiKeyScreen(self.settings), after_add)

    @on(Button.Pressed, "#btn-save")
    def save_pressed(self) -> None:
        try:
            # Retrieve multiline API keys from TextArea
            raw_keys = self.query_one("#setting-api-keys", TextArea).text.strip()
            # Split by newlines and commas, allowing both formats
            keys = [k.strip() for line in raw_keys.split('\n') for k in line.split(',') if k.strip()]
            # Validate keys (simple check for length)
            for k in keys:
                if len(k) < 10:
                    raise ValueError(f"API key too short: {k[:12]}...")
            # Update settings: primary key is first if exists, else empty string
            self.settings.gemini_api_key = keys[0] if keys else ""
            self.settings.gemini_api_keys = keys[1:] if len(keys) > 1 else []
            self.settings.gemini_model = self.query_one("#setting-model", Select).value
            self.settings.cli_max_steps = int(self.query_one("#setting-steps", Input).value.strip())
            self.settings.cli_max_result_len = int(self.query_one("#setting-result-len", Input).value.strip())
            self.settings.cli_max_heal_retries = int(self.query_one("#setting-heal-retries", Input).value.strip())
            self.settings.llm_temperature = float(self.query_one("#setting-temp", Input).value.strip())
            self.settings.cli_enable_self_evolution = self.query_one("#setting-self-evolve", Checkbox).value

            from config.settings import save_settings
            save_settings(self.settings)

            self.dismiss(self.settings)
        except Exception as e:
            # Show error in chat log and keep screen open for correction
            self.app.chat.write(Text(f"❌ Error saving settings: {e}", style="bold red"))

    class AddApiKeyScreen(ClipboardMixin, Screen):
        """Screen to add a single API key."""
        BINDINGS = [
            Binding("escape", "dismiss", "Cancel", show=True),
            Binding("ctrl+v", "paste_clipboard", "Paste", show=False, priority=True),
            Binding("ctrl+c", "copy_clipboard", "Copy", show=False, priority=True),
        ]

        def __init__(self, settings, **kwargs):
            super().__init__(**kwargs)
            self.settings = settings

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("Add Gemini API Key", classes="settings-title")
            yield Input(placeholder="Enter new API key", id="new-api-key")
            with Horizontal(classes="buttons-row"):
                yield Button("Save", variant="primary", id="add-key-save")
                yield Button("Cancel", variant="error", id="add-key-cancel")
            yield Footer()

        @on(Button.Pressed, "#add-key-cancel")
        def cancel(self) -> None:
            self.dismiss(None)

        @on(Button.Pressed, "#add-key-save")
        def save(self) -> None:
            new_key = self.query_one("#new-api-key", Input).value.strip()
            # Simple validation for API key format
            if new_key and len(new_key) < 10:
                # Show error message in the main chat
                self.app.chat.write(Text(f"❌ API key too short: {new_key}", style="bold red"))
                self.dismiss(None)
                return
            if new_key:
                try:
                    existing = self.settings.get_all_keys()
                    if new_key in existing:
                        self.app.chat.write(Text("⚠ That API key is already in the pool.", style="bold yellow"))
                        self.dismiss(None)
                        return
                    self.settings.gemini_api_keys.append(new_key)
                    from config.settings import save_settings
                    save_settings(self.settings)
                    self.dismiss(new_key)
                except Exception as e:
                    self.app.chat.write(Text(f"❌ Error adding API key: {e}", style="bold red"))
                    self.dismiss(None)
            else:
                self.dismiss(None)

class SchedulerScreen(ClipboardMixin, Screen):
    """Screen for managing scheduled automation jobs."""

    BINDINGS = [
        Binding("escape", "dismiss", "Go Back", show=True),
        Binding("ctrl+v", "paste_clipboard", "Paste", show=False, priority=True),
        Binding("ctrl+c", "copy_clipboard", "Copy", show=False, priority=True),
    ]

    def __init__(self, settings, **kwargs):
        super().__init__(**kwargs)
        self.settings = settings
        self.scheduler = JobScheduler()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="scheduler-form"):
            yield Static("📅 AUTOMATION SCHEDULER", classes="settings-title")

            yield Static("Active Jobs:", classes="section-label")
            yield Static("No active scheduled jobs.", id="active-jobs-list")

            yield Label("Delete Job:")
            yield Select(options=[], id="job-to-delete-select")
            yield Button("Delete Selected Job", variant="error", id="btn-delete-job")

            yield Static("───────────────────────────────────────", classes="separator")

            yield Static("Add New Job:", classes="section-label")

            yield Label("Task Prompt:")
            yield Input(placeholder="e.g. check git status and run tests", id="job-prompt")

            yield Label("Schedule Type:")
            yield Select(
                options=[
                    ("Every X Minutes (Interval)", "interval"),
                    ("Daily at HH:MM (Daily)", "daily")
                ],
                value="interval",
                id="job-type"
            )

            yield Label("Schedule Value (minutes or HH:MM):")
            yield Input(placeholder="e.g. 60 or 14:30", id="job-value")

            with Horizontal(classes="buttons-row"):
                yield Button("Add Scheduled Job", variant="success", id="btn-add-job")
                yield Button("Close", variant="primary", id="btn-close")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_jobs_ui()

    def refresh_jobs_ui(self) -> None:
        self.scheduler.jobs = self.scheduler.load_jobs()
        
        list_static = self.query_one("#active-jobs-list", Static)
        if not self.scheduler.jobs:
            list_static.update("No active scheduled jobs.")
        else:
            text = ""
            for j in self.scheduler.jobs:
                desc = "every " + str(j["value"]) + "m" if j["schedule_type"] == "interval" else "daily at " + str(j["value"])
                text += f"• [ID: {j['id']}] \"{j['task_prompt']}\"\n  Schedule: {desc} | Next Run: {j['next_run']}\n\n"
            list_static.update(text.strip())

        delete_select = self.query_one("#job-to-delete-select", Select)
        options = [(f"[{j['id']}] {j['task_prompt'][:40]}...", j["id"]) for j in self.scheduler.jobs]
        delete_select.set_options(options)
        if options:
            delete_select.value = options[0][1]
        else:
            delete_select.value = Select.NULL

    @on(Button.Pressed, "#btn-add-job")
    def add_job_pressed(self) -> None:
        prompt_input = self.query_one("#job-prompt", Input)
        type_select = self.query_one("#job-type", Select)
        value_input = self.query_one("#job-value", Input)

        prompt = prompt_input.value.strip()
        s_type = type_select.value
        s_val = value_input.value.strip()

        if not prompt or not s_val:
            return

        self.scheduler.add_job(prompt, s_type, s_val)
        prompt_input.value = ""
        value_input.value = ""
        self.refresh_jobs_ui()

    @on(Button.Pressed, "#btn-delete-job")
    def delete_job_pressed(self) -> None:
        delete_select = self.query_one("#job-to-delete-select", Select)
        job_id = delete_select.value
        if job_id and job_id != Select.NULL:
            self.scheduler.remove_job(job_id)
            self.refresh_jobs_ui()

    @on(Button.Pressed, "#btn-close")
    def close_pressed(self) -> None:
        self.dismiss(None)

    def action_dismiss(self) -> None:
        self.dismiss(None)


class MarkTUI(ClipboardMixin, App):
    """MARK-XX Interactive Chat TUI."""

    TITLE = "MARK-XX CLI Agent"

    CSS = """
    Screen {
        background: #121214;
    }

    #main-container {
        height: 1fr;
        width: 100%;
    }

    #chat-pane {
        width: 3fr;
        height: 1fr;
        border: tall #26262b;
        background: #18181b;
        padding: 1;
    }

    #sidebar-pane {
        width: 1fr;
        height: 1fr;
        border: tall #26262b;
        background: #141416;
        padding: 1;
    }

    #input-container {
        height: auto;
        dock: bottom;
        padding: 0 1;
    }

    #user-input {
        background: #18181b;
        border: tall #26262b;
        color: #e4e4e7;
    }

    #user-input:focus {
        border: tall #7c3aed;
    }

    #settings-form, #scheduler-form {
        padding: 1 4;
        background: #18181b;
        border: tall #26262b;
        margin: 1 10;
        height: auto;
    }

    #active-jobs-list {
        background: #141416;
        border: solid #26262b;
        padding: 1;
        margin-top: 1;
        margin-bottom: 1;
        height: 6;
        color: #a1a1aa;
    }

    .section-label {
        color: #e4e4e7;
        text-style: bold;
        margin-top: 1;
    }

    .separator {
        color: #26262b;
        margin-top: 1;
        margin-bottom: 1;
        text-align: center;
    }

    .settings-title {
        text-style: bold;
        color: #7c3aed;
        margin-bottom: 1;
        text-align: center;
    }

    Label {
        color: #a1a1aa;
        margin-top: 1;
        margin-bottom: 0;
    }

    .buttons-row {
        margin-top: 2;
        height: auto;
        align: center middle;
    }

    .buttons-row Button {
        margin: 0 2;
    }

    #setting-api-keys {
        height: 6;
        border: tall #26262b;
        background: #141416;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("ctrl+r", "resume_session", "Resume", show=True),
        Binding("ctrl+s", "show_settings", "Settings", show=True),
        Binding("ctrl+j", "show_scheduler", "Scheduler", show=True),
        Binding("ctrl+v", "paste_clipboard", "Paste", show=False, priority=True),
        Binding("ctrl+c", "interrupt_or_copy", "Stop/Copy", show=True, priority=True),
    ]

    def __init__(self, planner: CLIPlanner, settings, working_dir: str):
        super().__init__()
        self.planner = planner
        self.settings = settings
        self.working_dir = working_dir
        self.mode_label = {"auto": "YOLO", "normal": "Normal", "strict": "Strict"}[planner.interceptor.mode]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-container"):
            yield RichLog(id="chat-pane", wrap=True, highlight=True, markup=False)
            yield SidebarInfo(
                self.settings, self.working_dir, self.mode_label, self.planner.budget,
                id="sidebar-pane",
            )
        with Container(id="input-container"):
            yield Input(placeholder="Type a task and press Enter...", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        self.chat = self.query_one("#chat-pane", RichLog)
        self.sidebar = self.query_one("#sidebar-pane", SidebarInfo)
        self.input_box = self.query_one("#user-input", Input)

        self.chat.write(Text("⚡ MARK-XX CLI Agent online.", style="bold magenta"))
        self.chat.write(Text("Type your request below and press Enter.\n", style="dim"))

        self.update_sidebar()
        self.input_box.focus()

        def _on_key_rotated(key, slot, total, reason):
            short = (key[:8] + "…") if key else "?"
            if reason == "single key — add more keys for rotation":
                msg = "\n⚠ Rate limit — only 1 API key. Add more in Settings for rotation.\n"
            elif reason == "cooldown retry":
                msg = f"\n⏳ All keys rate-limited. Retrying with key 1/{total} after cooldown…\n"
            else:
                msg = f"\n⚡ Rate limit — switched to API key {slot}/{total} ({short})\n"
            self.call_from_thread(self.chat.write, Text(msg, style="bold yellow"))

        self.planner.llm.on_key_rotated = _on_key_rotated

        # Check for scheduled jobs every 30 seconds
        self.set_interval(30, self.check_scheduled_jobs)

    def update_sidebar(self):
        self.sidebar.budget_text = self.planner.budget.usage_summary
        self.sidebar.refresh()

    # ── Handle user input submission ─────────────────────────────────────────
    @on(Input.Submitted, "#user-input")
    async def handle_submit(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text:
            return

        self.input_box.value = ""
        self.chat.write(Text(f"\n▶ {user_text}", style="bold cyan"))
        
        if user_text.startswith("/"):
            self.handle_slash_command(user_text)
            return

        self.run_agent_loop(user_text)

    # ── Agent loop (runs in background thread) ───────────────────────────────
    @work(exclusive=True, thread=True)
    def run_agent_loop(self, user_text: str) -> None:
        self.sidebar.status_text = "Thinking..."
        self.call_from_thread(self.sidebar.refresh)

        # Redirect stdout so planner print() calls go to the chat log
        original_stdout = sys.stdout

        class _TuiWriter:
            def __init__(self, chat):
                self._chat = chat
            def write(self, s):
                if s and s.strip():
                    self._chat.write(Text.from_ansi(s))
            def flush(self):
                pass

        sys.stdout = _TuiWriter(self.chat)

        try:
            response = self.planner.process(user_text, self.working_dir)
            self.call_from_thread(self.chat.write, Text("\n── MARK ──", style="bold magenta"))
            self.call_from_thread(self.chat.write, Markdown(response))
        except Exception as e:
            self.call_from_thread(self.chat.write, Text(f"\nError: {e}", style="bold red"))
        finally:
            sys.stdout = original_stdout
            self.sidebar.status_text = "Ready"
            self.call_from_thread(self.update_sidebar)
            self.call_from_thread(self.input_box.focus)

    # ── Actions ──────────────────────────────────────────────────────────────
    def action_interrupt_or_copy(self) -> None:
        """Ctrl+C: copy from focused input, or interrupt running agent."""
        focused = self.focused
        if isinstance(focused, Input):
            text = focused.value
            if text:
                set_clipboard_text(text)
                self.chat.write(Text("📋 Copied to clipboard.", style="dim"))
            return
        if isinstance(focused, TextArea):
            text = focused.selected_text if hasattr(focused, 'selected_text') else ""
            if text:
                set_clipboard_text(text)
                self.chat.write(Text("📋 Copied to clipboard.", style="dim"))
            return
        # Nothing focused → interrupt running agent
        workers = self.workers
        cancelled = False
        for worker in workers:
            if not worker.is_finished:
                worker.cancel()
                cancelled = True
        if cancelled:
            self.chat.write(Text("\n⛔ Agent interrupted.", style="bold yellow"))
            self.sidebar.status_text = "Ready"
            self.sidebar.refresh()

    def on_mouse_up(self, event) -> None:
        if event.button == 3:  # Right-click
            try:
                widget = self.get_widget_at(event.screen_x, event.screen_y)[0]
            except Exception:
                widget = None
            target = widget if isinstance(widget, (Input, TextArea)) else self.focused
            if isinstance(target, (Input, TextArea)):
                text = get_clipboard_text()
                if text:
                    if isinstance(target, Input):
                        val = target.value
                        cursor = target.cursor_position
                        target.value = val[:cursor] + text + val[cursor:]
                        target.cursor_position = cursor + len(text)
                        target.focus()
                    elif isinstance(target, TextArea):
                        target.insert(text)
                        target.focus()

    def action_clear_chat(self) -> None:
        self.chat.clear()
        self.chat.write(Text("⚡ Chat cleared.", style="dim"))

    def action_resume_session(self) -> None:
        self.chat.write(Text("\nResuming last session...", style="bold yellow"))
        self._run_resume()

    @work(exclusive=True, thread=True)
    def _run_resume(self) -> None:
        self.sidebar.status_text = "Resuming..."
        self.call_from_thread(self.sidebar.refresh)

        original_stdout = sys.stdout

        class _TuiWriter:
            def __init__(self, chat):
                self._chat = chat
            def write(self, s):
                if s and s.strip():
                    self._chat.write(Text.from_ansi(s))
            def flush(self):
                pass

        sys.stdout = _TuiWriter(self.chat)

        try:
            result = self.planner.resume()
            if result:
                self.call_from_thread(self.chat.write, Text("\n── MARK ──", style="bold magenta"))
                self.call_from_thread(self.chat.write, Markdown(result))
            else:
                self.call_from_thread(self.chat.write, Text("\nNo previous session to resume.", style="bold yellow"))
        except Exception as e:
            self.call_from_thread(self.chat.write, Text(f"\nError: {e}", style="bold red"))
        finally:
            sys.stdout = original_stdout
            self.sidebar.status_text = "Ready"
            self.call_from_thread(self.update_sidebar)
            self.call_from_thread(self.input_box.focus)

    def action_show_settings(self) -> None:
        def update_after_settings(new_settings) -> None:
            if new_settings:
                self.settings = new_settings
                self.planner.llm.model_name = self.settings.gemini_model
                self.planner.llm.temperature = self.settings.llm_temperature
                self.planner.max_steps = self.settings.cli_max_steps
                self.planner.max_result_len = self.settings.cli_max_result_len
                self.planner.max_heal_retries = self.settings.cli_max_heal_retries
                self.planner.jail.forbidden_patterns = self.settings.cli_forbidden_patterns
                self.planner.interceptor.dangerous_tools = set(self.settings.cli_dangerous_tools)
                self.planner.settings.cli_enable_self_evolution = self.settings.cli_enable_self_evolution

                # Reconfigure LLM client with updated key pool
                all_keys = self.settings.get_all_keys()
                if all_keys:
                    self.planner.llm.configure(
                        api_key=all_keys[0],
                        model=self.settings.gemini_model,
                        extra_keys=all_keys[1:] if len(all_keys) > 1 else [],
                    )
                    n = len(all_keys)
                    self.chat.write(
                        Text(
                            f"\n⚙️ Settings saved — {n} API key{'s' if n != 1 else ''} in rotation pool.",
                            style="bold green",
                        )
                    )
                else:
                    self.chat.write(Text("\n⚙️ Settings saved (no API keys — add at least one).", style="bold yellow"))

                self.update_sidebar()
            self.input_box.focus()

        self.push_screen(SettingsScreen(self.settings), update_after_settings)

    def action_show_scheduler(self) -> None:
        def update_after_scheduler(result) -> None:
            self.input_box.focus()

        self.push_screen(SchedulerScreen(self.settings), update_after_scheduler)

    def handle_slash_command(self, cmd_text: str) -> None:
        parts = cmd_text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            self.exit()

        elif cmd == "/clear":
            self.action_clear_chat()

        elif cmd == "/resume":
            self.action_resume_session()

        elif cmd == "/evolve":
            if not args:
                self.chat.write(Text("❌ Error: Usage: /evolve <prompt>", style="bold red"))
                return
            self.chat.write(Text(f"\n🧬 Starting self-evolution: {args}...", style="bold magenta"))
            self.run_evolution_loop(args)

        elif cmd == "/schedule":
            import re
            m = re.match(r'^"(.*?)"\s+(every|daily)\s+(.*)$', args, re.IGNORECASE)
            if not m:
                self.chat.write(Text("❌ Usage: /schedule \"task prompt\" every <minutes> OR /schedule \"task prompt\" daily <HH:MM>", style="bold red"))
                return
            prompt, s_type, s_val = m.groups()
            s_type = "interval" if s_type.lower() == "every" else "daily"
            s_val = s_val.replace("minutes", "").replace("minute", "").strip()
            
            from core.scheduler import JobScheduler
            sched = JobScheduler()
            job = sched.add_job(prompt, s_type, s_val)
            self.chat.write(Text(f"📅 Job scheduled successfully! ID: {job['id']} | Next Run: {job['next_run']}", style="bold green"))

        elif cmd == "/unschedule":
            if not args:
                self.chat.write(Text("❌ Error: Usage: /unschedule <job_id>", style="bold red"))
                return
            from core.scheduler import JobScheduler
            sched = JobScheduler()
            if sched.remove_job(args):
                self.chat.write(Text(f"🗑️ Job {args} removed.", style="bold green"))
            else:
                self.chat.write(Text(f"❌ Job ID {args} not found.", style="bold red"))

        elif cmd == "/jobs":
            from core.scheduler import JobScheduler
            sched = JobScheduler()
            if not sched.jobs:
                self.chat.write(Text("📅 No scheduled jobs active.", style="dim"))
                return
            self.chat.write(Text("\n📅 Active Scheduled Jobs:", style="bold magenta"))
            for j in sched.jobs:
                status = "Active" if j["active"] else "Inactive"
                sched_desc = f"every {j['value']}m" if j["schedule_type"] == "interval" else f"daily at {j['value']}"
                self.chat.write(Text(f"  ID: {j['id']} | \"{j['task_prompt']}\" ({sched_desc}) | Next: {j['next_run']}", style="cyan"))

        else:
            self.chat.write(Text(f"❓ Unknown slash command: {cmd}", style="bold yellow"))

    @work(exclusive=True, thread=True)
    def run_evolution_loop(self, evolution_prompt: str) -> None:
        self.sidebar.status_text = "Evolving..."
        self.call_from_thread(self.sidebar.refresh)

        try:
            from agent.evolution import SelfEvolver
            evolver = SelfEvolver(self.planner, self.working_dir)
            result = evolver.run_evolution(evolution_prompt)
            self.call_from_thread(self.chat.write, Text("\n── EVOLUTION RESULT ──", style="bold magenta"))
            self.call_from_thread(self.chat.write, Markdown(result))
        except Exception as e:
            self.call_from_thread(self.chat.write, Text(f"\nEvolution Error: {e}", style="bold red"))
        finally:
            self.sidebar.status_text = "Ready"
            self.call_from_thread(self.update_sidebar)
            self.call_from_thread(self.input_box.focus)

    def check_scheduled_jobs(self) -> None:
        from core.scheduler import JobScheduler
        from datetime import datetime
        
        sched = JobScheduler()
        now = datetime.now()
        
        for job in sched.jobs:
            if not job.get("active", True):
                continue
            
            next_run_dt = datetime.fromisoformat(job["next_run"])
            if next_run_dt <= now:
                job["last_run"] = now.isoformat()
                next_run_dt = sched.calculate_next_run(job["schedule_type"], job["value"], now)
                job["next_run"] = next_run_dt.isoformat()
                sched.save_jobs()
                
                self.chat.write(Text(f"\n⏰ [SCHEDULER] Triggering job {job['id']}: \"{job['task_prompt']}\"", style="bold yellow"))
                self.run_scheduled_job_worker(job["task_prompt"], job["id"])

    @work(thread=True)
    def run_scheduled_job_worker(self, prompt: str, job_id: str) -> None:
        self.sidebar.status_text = f"Running Job {job_id}"
        self.call_from_thread(self.sidebar.refresh)
        
        try:
            response = self.planner.process(prompt, self.working_dir)
            self.call_from_thread(self.chat.write, Text(f"\n⏰ [SCHEDULER] Job {job_id} Completed:", style="bold green"))
            self.call_from_thread(self.chat.write, Markdown(response))
        except Exception as e:
            self.call_from_thread(self.chat.write, Text(f"\n⏰ [SCHEDULER] Job {job_id} Failed: {e}", style="bold red"))
        finally:
            self.sidebar.status_text = "Ready"
            self.call_from_thread(self.update_sidebar)
