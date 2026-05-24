#!/usr/bin/env python3
"""
MARK-XX CLI Agent
Interactive terminal-based AI agent with full safety, context management,
self-healing, and state persistence.

Usage:
    python markcli.py                          # Launch in current directory
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

# Make sure project root is on sys.path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def main():
    # ── Parse args ─────────────────────────────────────────────────────────
    model = None
    api_key_override = None
    working_dir = "."
    mode = "auto"          # auto | normal | strict
    budget_usd = 1.0       # Token budget in USD
    dry_run = False
    do_resume = False

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
    from config.settings import load_settings
    settings = load_settings()
    settings.memory_db = str(ROOT / "memory" / "markxx.db")

    if model:
        settings.gemini_model = model
    if api_key_override:
        settings.gemini_api_key = api_key_override

    # ── Check API key ─────────────────────────────────────────────────────────
    all_keys = settings.get_all_keys()
    if not all_keys or not all_keys[0].strip():
        print(f"\n{YELLOW}No Gemini API key configured.{RESET}")
        print(f"Set it via: {BOLD}python markcli.py --key YOUR_KEY{RESET}")
        print(f"Or configure it in the GUI Settings panel first.")
        print()
        key = input(f"Enter API key (or press Enter to quit): ").strip()
        if not key:
            sys.exit(1)
        settings.gemini_api_key = key
        all_keys = [key]

    # ── Initialize components ─────────────────────────────────────────────────
    from core.llm import LLMClient
    from core.memory import Memory
    from agent.cli_planner import CLIPlanner

    memory = Memory(settings.memory_db)
    llm_client = LLMClient(
        api_key=all_keys[0],
        model=settings.gemini_model,
        system_prompt="",
        extra_keys=all_keys[1:] if len(all_keys) > 1 else [],
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
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
    )

    # ── Print banner ──────────────────────────────────────────────────────────
    mode_label = {"auto": "YOLO", "normal": "Normal", "strict": "Strict"}[mode]
    dry_label = f" {YELLOW}(DRY-RUN){RESET}" if dry_run else ""

    print()
    print(f"  {BOLD}{CYAN}MARK-XX CLI Agent{RESET}{dry_label}")
    print(f"  {DIM}Model: {settings.gemini_model}")
    print(f"  Working: {working_dir}")
    print(f"  Mode: {mode_label} | Budget: ${budget_usd:.2f}")
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
                    llm_client.configure(
                        api_key=all_keys[0],
                        model=new_model,
                        extra_keys=all_keys[1:] if len(all_keys) > 1 else [],
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

            else:
                print(f"  {YELLOW}Unknown command: {cmd}. Type /help for commands.{RESET}")
                continue

        # ── Process user input through the agent ─────────────────────────
        print()
        response = planner.process(user_input, working_dir)
        planner._print_response(response)


if __name__ == "__main__":
    main()
