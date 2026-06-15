"""
MARK — Lifecycle Hooks System
Inspired by gemini-cli's hook system. Allows registering Python callables
or external scripts to fire at key lifecycle events (session, tool, model, error).
Hooks can block actions, modify arguments, or just observe.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

from core.logger import get_logger

log = get_logger('hooks')

HOOK_EVENTS = [
    'session_start',    # When CLI session begins
    'session_end',      # When CLI session ends
    'before_tool',      # Before any tool execution
    'after_tool',       # After any tool execution
    'before_model',     # Before LLM call
    'after_model',      # After LLM response
    'on_error',         # On any error
]


@dataclass
class HookResult:
    allowed: bool = True
    reason: str = ''
    modified_args: Optional[dict] = None


@dataclass
class Hook:
    event: str
    name: str
    handler: Optional[Callable] = None  # Python callable
    script: Optional[str] = None        # External script path
    priority: int = 100                  # Lower = runs first


class HookSystem:
    def __init__(self):
        self._hooks: Dict[str, List[Hook]] = {e: [] for e in HOOK_EVENTS}

    def register(self, event: str, name: str, handler: Callable = None,
                 script: str = None, priority: int = 100) -> bool:
        if event not in HOOK_EVENTS:
            log.warning(f'Unknown hook event: {event}')
            return False
        hook = Hook(event=event, name=name, handler=handler, script=script, priority=priority)
        self._hooks[event].append(hook)
        self._hooks[event].sort(key=lambda h: h.priority)
        log.info(f'Registered hook: {name} on {event}')
        return True

    def unregister(self, event: str, name: str):
        self._hooks[event] = [h for h in self._hooks[event] if h.name != name]

    def fire(self, event: str, context: dict = None) -> HookResult:
        if event not in HOOK_EVENTS:
            return HookResult()
        context = context or {}
        for hook in self._hooks[event]:
            try:
                if hook.handler:
                    result = hook.handler(context)
                    if isinstance(result, HookResult):
                        if not result.allowed:
                            log.info(f'Hook {hook.name} blocked: {result.reason}')
                            return result
                elif hook.script:
                    result = self._run_script(hook, context)
                    if not result.allowed:
                        return result
            except Exception as e:
                log.error(f'Hook {hook.name} failed: {e}')
        return HookResult()

    def _run_script(self, hook: Hook, context: dict) -> HookResult:
        try:
            proc = subprocess.run(
                ['python', hook.script],
                input=json.dumps(context),
                capture_output=True, text=True, timeout=10
            )
            if proc.returncode == 2:  # Emergency brake
                return HookResult(allowed=False, reason=f'Emergency stop: {proc.stderr}')
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                if data.get('decision') == 'deny':
                    return HookResult(allowed=False, reason=data.get('reason', 'Denied by hook'))
                if data.get('modified_args'):
                    return HookResult(allowed=True, modified_args=data['modified_args'])
        except subprocess.TimeoutExpired:
            log.warning(f'Hook script timed out: {hook.script}')
        except Exception as e:
            log.error(f'Hook script error: {e}')
        return HookResult()

    def load_from_config(self, config_dir: str):
        hooks_dir = Path(config_dir) / '.mark' / 'hooks'
        if not hooks_dir.exists():
            return
        for event_dir in hooks_dir.iterdir():
            if event_dir.is_dir() and event_dir.name in HOOK_EVENTS:
                for script in sorted(event_dir.glob('*.py')):
                    self.register(event_dir.name, script.stem, script=str(script))

    def list_hooks(self) -> dict:
        return {e: [h.name for h in hooks] for e, hooks in self._hooks.items() if hooks}


# Global singleton
hooks = HookSystem()
