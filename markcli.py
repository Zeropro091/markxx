"""
MARK-XX CLI Agent
Interactive terminal-based AI agent with full safety, context management,
self-healing, and state persistence.

Usage:
    python markcli.py                          # Launch interactive Textual TUI
    python markcli.py --classic                # Launch in classic terminal REPL mode
    python markcli.py --model gemini-2.5-flash # Use a specific model
    python markcli.py --key YOUR_API_KEY       # Override API key
    python markcli.py --budget 0.50            # Set token budget ($0.50)
    python markcli.py --mode normal            # normal (ask for dangerous) | auto | strict
    python markcli.py --dry-run                # Preview mode (no execution)
    python markcli.py --resume                  # Resume last interrupted session
    python markcli.py /path/to/project         # Set working directory
"""

import sys
import os
from pathlib import Path

# Mark CLI mode to suppress INFO log spam to stdout
os.environ["MARK_CLI"] = "1"

# Enable ANSI escape sequence rendering on Windows Console/PowerShell
if os.name == 'nt':
    os.system('')

# Make sure project root is on sys.path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def main():
    # ── Parse args ─────────────────────────────────────────────────────────
    model = None
    api_key_override = None
    working_dir = "."
    mode = "auto"          # auto | normal | strict
    budget_usd = float('inf')  # Token budget in USD (unlimited by default)
    dry_run = False
    do_resume = False
    classic_mode = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--model", "-m") and i + 1 < len(args):
            model = args[i + 1]; i += 2
        elif arg in ("--key", "-k") and i + 1 < len(args):
            api_key_override = args[i + 1]; i += 2
        elif arg in ("--mode",) and i + 1 < len(args):
            mode = args[i + 1]
            if mode not in ("auto", "normal", "strict"):
                print(f"Invalid mode: {mode}. Use: auto, normal, strict")
                sys.exit(1)
            i += 2
        elif arg in ("--budget", "-b") and i + 1 < len(args):
            try:
                budget_usd = float(args[i + 1])
            except ValueError:
                print(f"Invalid budget: {args[i + 1]}")
                sys.exit(1)
            i += 2
        elif arg in ("--dry-run", "--dry", "-d"):
            dry_run = True; i += 1
        elif arg in ("--resume", "-r"):
            do_resume = True; i += 1
        elif arg in ("--classic", "--repl"):
            classic_mode = True; i += 1
        elif arg in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        elif not arg.startswith("-"):
            working_dir = arg; i += 1
        else:
            print(f"Unknown option: {arg}")
            sys.exit(1)

    # ── Init logging ──────────────────────────────────────────────────────────
    from core.logger import get_logger
    log = get_logger("cli")

    # ── ANSI helpers ──────────────────────────────────────────────────────────
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    MAGENTA = "\033[35m"
    RED     = "\033[31m"
    RESET   = "\033[0m"

    if os.getenv("NO_COLOR") or not sys.stdout.isatty():
        BOLD = DIM = CYAN = GREEN = YELLOW = MAGENTA = RED = RESET = ""

    # ── Load settings ─────────────────────────────────────────────────────────
    from config.settings import load_settings, save_settings
    settings = load_settings()
    settings.memory_db = str(ROOT / "memory" / "markxx.db")

    if model:
        settings.gemini_model = model
    if api_key_override:
        settings.gemini_api_key = api_key_override
        log.warning("API key passed via --key flag is visible in process list. "
                    "Prefer GEMINI_API_KEY env var for security.")

    # ── Check API key ─────────────────────────────────────────────────────────
    all_keys = settings.get_all_keys()
    if not all_keys or not all_keys[0].strip():
        print(f"\n{YELLOW}No Gemini API key configured.{RESET}")
        print(f"Set it via:  {BOLD}set GEMINI_API_KEY=YOUR_KEY{RESET}  (recommended)")
        print(f"         or: {BOLD}python markcli.py --key YOUR_KEY{RESET}")
        print(f"         or: configure it in the GUI Settings panel.")
        print()
        key = input(f"Enter primary API key (or press Enter to quit): ").strip()
        if not key:
            sys.exit(1)
        settings.gemini_api_key = key

        # Prompt for extra keys (same as UI's multi-key support)
        print(f"\n{DIM}Optionally, add extra API keys for automatic rotation on quota limits.{RESET}")
        print(f"{DIM}Enter one key per line. Press Enter on an empty line to finish.{RESET}\n")
        extra_keys = []
        while True:
            ek = input(f"  Extra key {len(extra_keys) + 1} (or blank to skip): ").strip()
            if not ek:
                break
            if ek != key:
                extra_keys.append(ek)
        if extra_keys:
            settings.gemini_api_keys = extra_keys

        save_settings(settings)
        all_keys = settings.get_all_keys()
        total = len(all_keys)
        print(f"{GREEN}{total} key{'s' if total != 1 else ''} saved to config.{RESET}")

    # ── Initialize components ─────────────────────────────────────────────────
    from core.llm import LLMClient
    from core.memory import Memory
    from agent.cli_planner import CLIPlanner

    memory = Memory(settings.memory_db)
    llm_client = LLMClient(
        api_key=all_keys[0] if all_keys else "",
        model=settings.gemini_model,
        system_prompt="",
        extra_keys=all_keys[1:] if len(all_keys) > 1 else [],
        temperature=settings.llm_temperature,
        max_tokens=None,  # None = model default max output (no explicit cap)
    )

    # Resolve working directory
    working_dir = str(Path(working_dir).resolve())
    os.chdir(working_dir)

    planner = CLIPlanner(
        llm_client, memory,
        working_dir=working_dir,
        mode=mode,
        budget_usd=budget_usd,
        dry_run=dry_run,
        settings=settings,
    )

    if not classic_mode:
        from tui import MarkTUI
        app = MarkTUI(planner, settings, working_dir)
        app.run()
        sys.exit(0)

    # Classic REPL: print rotation notices to the terminal
    def _on_key_rotated(key, slot, total, reason):
        display_key = key[:8] + "..." if key else "None"
        if reason == "single key — add more keys for rotation":
            print(f"\n  {YELLOW}{BOLD}⚠ Rate limit — only 1 API key. Add more in Settings for rotation.{RESET}\n")
        elif reason == "cooldown retry":
            print(f"\n  {YELLOW}{BOLD}⏳ All keys rate-limited. Retrying with key 1/{total} after cooldown…{RESET}\n")
        else:
            print(f"\n  {YELLOW}{BOLD}⚡ Rate limit hit. Rotated API key to slot {slot}/{total} ({display_key}){RESET}\n")

    llm_client.on_key_rotated = _on_key_rotated

    # ── Print banner ──────────────────────────────────────────────────────────
    mode_label = {"auto": "YOLO", "normal": "Normal", "strict": "Strict"}[mode]
    dry_label = f" {YELLOW}(DRY-RUN){RESET}" if dry_run else ""

    print()
    print(f"  {BOLD}{CYAN}MARK-XX CLI Agent{RESET}{dry_label}")
    print(f"  {DIM}Model: {settings.gemini_model}")
    print(f"  Working: {working_dir}")
    budget_label = "Unlimited" if budget_usd == float('inf') else f"${budget_usd:.2f}"
    print(f"  Mode: {mode_label} | Budget: {budget_label}")
    print(f"  Type a task, /help for commands, /quit to exit{RESET}")
    print()

    # ── Handle --resume ───────────────────────────────────────────────────────
    if do_resume:
        result = planner.resume()
        if result:
            planner._print_response(result)
        else:
            print(f"  {YELLOW}No previous session found to resume.{RESET}")
        # Continue into interactive mode

    # ── REPL loop ─────────────────────────────────────────────────────────────
    while True:
        try:
            prompt_str = f"  {BOLD}{MAGENTA}MARK>{RESET} "
            user_input = input(prompt_str)

        except (EOFError, KeyboardInterrupt):
            print(f"\n  {DIM}Bye!{RESET}")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # ── Built-in commands ─────────────────────────────────────────────
        if user_input.startswith("/"):
            cmd = user_input.lower().split()[0]

            if cmd in ("/quit", "/exit", "/q"):
                print(f"  {DIM}Bye!{RESET}")
                break

            elif cmd in ("/help", "/h", "/?"):
                print(f"""
  {BOLD}Commands:{RESET}
    /help             Show this help
    /quit             Exit MARK CLI
    /undo             Revert last MARK edit (git checkpoint rollback)
    /index            Index codebase for semantic search
    /plan             Enter plan mode (read-only exploration)
    /build            Exit plan mode (enable all tools)
    /compact          Compact conversation context (save tokens)
    /context          Show context stats
    /resume           Resume last interrupted session
    /model NAME       Switch to a different model
    /mode MODE        Change safety mode (auto/normal/strict)
    /budget $AMOUNT   Set token budget (e.g. /budget 0.50)
    /dry-run          Toggle dry-run mode (preview without execution)
    /clear            Clear conversation history
    /history          Show recent conversation history
    /status           Show current settings + budget usage
    /dir [PATH]       Change or show working directory
    /map              Show workspace import graph
    /ignore           Show .markignore rules
    /evolve PROMPT    Self-evolution rewrite (branch checkout & rollback safety)
    /schedule "task" every X / daily Y   Schedule automated runs
    /unschedule ID    Remove a scheduled job
    /jobs             List all scheduled jobs
""")
                continue

            elif cmd == "/model":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"  Current model: {BOLD}{settings.gemini_model}{RESET}")
                    print(f"  Usage: /model gemini-2.5-flash")
                else:
                    new_model = parts[1].strip()
                    settings.gemini_model = new_model
                    save_settings(settings)
                    fresh_keys = settings.get_all_keys()
                    if not fresh_keys:
                        print(f"  {RED}No API keys configured.{RESET}")
                        continue
                    llm_client.configure(
                        api_key=fresh_keys[0],
                        model=new_model,
                        extra_keys=fresh_keys[1:] if len(fresh_keys) > 1 else [],
                    )
                    print(f"  {GREEN}Switched to: {new_model}{RESET}")
                continue

            elif cmd == "/mode":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"  Current mode: {BOLD}{planner.interceptor.mode}{RESET}")
                    print(f"  Usage: /mode auto | normal | strict")
                else:
                    new_mode = parts[1].strip()
                    if new_mode in ("auto", "normal", "strict"):
                        planner.interceptor.mode = new_mode
                        planner.interceptor._auto_approved.clear()
                        label = {"auto": "YOLO", "normal": "Normal", "strict": "Strict"}[new_mode]
                        print(f"  {GREEN}Mode: {label}{RESET}")
                    else:
                        print(f"  {YELLOW}Invalid mode. Use: auto, normal, strict{RESET}")
                continue

            elif cmd == "/budget":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"  {BOLD}{planner.budget.usage_summary}{RESET}")
                else:
                    try:
                        new_budget = float(parts[1].strip().replace("$", ""))
                        planner.budget.max_budget_usd = new_budget
                        planner.budget._cut_off = False
                        print(f"  {GREEN}Budget set: ${new_budget:.2f}{RESET}")
                    except ValueError:
                        print(f"  {YELLOW}Invalid amount. Usage: /budget 0.50{RESET}")
                continue

            elif cmd == "/dry-run":
                planner.dry_runner.active = not planner.dry_runner.active
                state = "ON" if planner.dry_runner.active else "OFF"
                if planner.dry_runner.active:
                    planner.dry_runner.planned_actions = []
                print(f"  Dry-run mode: {BOLD}{state}{RESET}")
                if planner.dry_runner.active:
                    print(f"  {DIM}Agent will plan but not execute. Use /dry-run again to disable.{RESET}")
                continue

            elif cmd == "/resume":
                result = planner.resume()
                if result:
                    planner._print_response(result)
                else:
                    print(f"  {YELLOW}No previous session found to resume.{RESET}")
                continue

            elif cmd == "/clear":
                memory.clear_history()
                llm_client.reset_chat()
                planner.state.clear()
                print(f"  {GREEN}History cleared.{RESET}")
                continue

            elif cmd == "/history":
                history = memory.get_history(limit=10)
                if not history:
                    print(f"  {DIM}(no history){RESET}")
                for msg in history:
                    role = msg.get("role", "?")
                    content = msg.get("parts", [""])[0][:80]
                    color = CYAN if role == "user" else MAGENTA
                    print(f"  {color}{role}:{RESET} {content}")
                continue

            elif cmd == "/status":
                print(f"""
  {BOLD}Status:{RESET}
    Model:     {settings.gemini_model}
    Keys:      {len(all_keys)} configured
    Memory:    {settings.memory_db}
    Working:   {working_dir}
    Temp:      {settings.llm_temperature}
    Tokens:    {settings.llm_max_tokens}
    Mode:      {planner.interceptor.mode}
    Dry-run:   {"ON" if planner.dry_runner.active else "OFF"}
    Budget:    {planner.budget.usage_summary}
""")
                continue

            elif cmd == "/map":
                try:
                    summary = planner.mapper.summary()
                    print(f"  {BOLD}Workspace Map:{RESET}")
                    for line in summary.split("\n"):
                        print(f"  {line}")
                except Exception as e:
                    print(f"  {YELLOW}Error mapping workspace: {e}{RESET}")
                continue

            elif cmd == "/ignore":
                print(f"  {BOLD}Active ignore patterns:{RESET}")
                for p in planner.ignore.patterns[:20]:
                    print(f"  {DIM}  {p}{RESET}")
                if len(planner.ignore.patterns) > 20:
                    print(f"  {DIM}  ... and {len(planner.ignore.patterns) - 20} more{RESET}")
                # Check if .markignore exists
                markignore = Path(working_dir) / ".markignore"
                if markignore.exists():
                    print(f"  {GREEN}  (.markignore file loaded){RESET}")
                else:
                    print(f"  {YELLOW}  (no .markignore file -- using defaults){RESET}")
                continue

            elif cmd == "/evolve":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"  {YELLOW}Usage: /evolve <prompt>{RESET}")
                else:
                    prompt = parts[1].strip()
                    print(f"\n  🧬 Starting self-evolution: {prompt}...")
                    from agent.evolution import SelfEvolver
                    evolver = SelfEvolver(planner, working_dir)
                    result = evolver.run_evolution(prompt)
                    print(f"\n  🧬 {BOLD}EVOLUTION RESULT:{RESET}")
                    print(result)
                continue

            elif cmd == "/schedule":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"  {YELLOW}Usage: /schedule \"task prompt\" every <minutes> OR /schedule \"task prompt\" daily <HH:MM>{RESET}")
                else:
                    import re
                    m = re.match(r'^"(.*?)"\s+(every|daily)\s+(.*)$', parts[1].strip(), re.IGNORECASE)
                    if not m:
                        print(f"  {YELLOW}Usage: /schedule \"task prompt\" every <minutes> OR /schedule \"task prompt\" daily <HH:MM>{RESET}")
                    else:
                        prompt, s_type, s_val = m.groups()
                        s_type = "interval" if s_type.lower() == "every" else "daily"
                        s_val = s_val.replace("minutes", "").replace("minute", "").strip()
                        from core.scheduler import JobScheduler
                        sched = JobScheduler()
                        job = sched.add_job(prompt, s_type, s_val)
                        print(f"  {GREEN}Job scheduled successfully! ID: {job['id']} | Next Run: {job['next_run']}{RESET}")
                continue

            elif cmd == "/unschedule":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"  {YELLOW}Usage: /unschedule <job_id>{RESET}")
                else:
                    from core.scheduler import JobScheduler
                    sched = JobScheduler()
                    if sched.remove_job(parts[1].strip()):
                        print(f"  {GREEN}Job {parts[1].strip()} removed.{RESET}")
                    else:
                        print(f"  {RED}Job ID {parts[1].strip()} not found.{RESET}")
                continue

            elif cmd == "/jobs":
                from core.scheduler import JobScheduler
                sched = JobScheduler()
                if not sched.jobs:
                    print(f"  {DIM}No scheduled jobs active.{RESET}")
                else:
                    print(f"\n  {BOLD}Active Scheduled Jobs:{RESET}")
                    for j in sched.jobs:
                        sched_desc = f"every {j['value']}m" if j["schedule_type"] == "interval" else f"daily at {j['value']}"
                        print(f"    ID: {j['id']} | \"{j['task_prompt']}\" ({sched_desc}) | Next: {j['next_run']}")
                continue

            elif cmd == "/dir":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"  Working directory: {BOLD}{working_dir}{RESET}")
                else:
                    new_dir = parts[1].strip()
                    new_path = Path(new_dir).resolve()
                    if new_path.exists() and new_path.is_dir():
                        working_dir = str(new_path)
                        os.chdir(working_dir)
                        planner.working_dir = working_dir
                        planner.jail = __import__("core.safety", fromlist=["PathJail"]).PathJail(working_dir)
                        planner.ignore = __import__("core.safety", fromlist=["MarkIgnore"]).MarkIgnore(working_dir)
                        planner.mapper = __import__("core.safety", fromlist=["WorkspaceMapper"]).WorkspaceMapper(working_dir, planner.ignore)
                        planner.state = __import__("agent.cli_planner", fromlist=["SessionState"]).SessionState(working_dir)
                        print(f"  {GREEN}Working directory: {working_dir}{RESET}")
                    else:
                        print(f"  {YELLOW}Directory not found: {new_dir}{RESET}")
                continue

            elif cmd == "/undo":
                try:
                    from core.git_checkpoint import undo_last_edit
                    result = undo_last_edit(working_dir)
                    print(f"  {result}")
                except Exception as e:
                    print(f"  {RED}Undo failed: {e}{RESET}")
                continue

            elif cmd == "/index":
                try:
                    from core.indexer import CodebaseIndexer
                    print(f"  {DIM}Indexing codebase for semantic search...{RESET}")
                    indexer = CodebaseIndexer(
                        api_key=all_keys[0] if all_keys else "",
                        db_path=str(Path(working_dir) / ".mark" / "index.db"),
                    )
                    stats = indexer.index(working_dir, force=True)
                    print(f"  {GREEN}Indexed {stats.get('indexed', 0)} chunks in {stats.get('time', '?')}s | Skipped: {stats.get('skipped', 0)}{RESET}")
                except ImportError:
                    print(f"  {YELLOW}Indexer not yet built. Coming soon.{RESET}")
                except Exception as e:
                    print(f"  {RED}Indexing failed: {e}{RESET}")
                continue

            elif cmd == "/plan":
                planner.plan_mode = True
                print(f"  {GREEN}📋 Plan mode activated — read-only exploration. Use /build to exit.{RESET}")
                continue

            elif cmd == "/build":
                planner.plan_mode = False
                print(f"  {GREEN}🔨 Build mode activated — all tools enabled.{RESET}")
                continue

            elif cmd == "/compact":
                if planner.context.should_compact():
                    summary = planner.context.compact()
                    print(f"  {GREEN}Compacted. Context: ~{planner.context.total_tokens} tokens{RESET}")
                else:
                    print(f"  {DIM}No compaction needed yet (~{planner.context.total_tokens} tokens){RESET}")
                continue

            elif cmd == "/context":
                stats = planner.context.stats()
                print(f"  Context: {stats['history_messages']} messages, ~{stats['total_tokens']} tokens")
                print(f"  Window: {stats['window_size']} | Max: {stats['max_tokens']} | Compacted: {stats['compacted']}")
                if planner.plan_mode:
                    print(f"  {YELLOW}📋 Plan mode active (read-only){RESET}")
                continue

            else:
                print(f"  {YELLOW}Unknown command: {cmd}. Type /help for commands.{RESET}")
                continue

        # ── Process user input through the agent ─────────────────────────
        print()
        response = planner.process(user_input, working_dir)
        planner._print_response(response)


if __name__ == "__main__":
    main()
