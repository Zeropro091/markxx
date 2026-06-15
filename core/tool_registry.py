"""
MARK-XX — ToolRegistry
Typed, extensible tool registry replacing the hardcoded TOOLS dict.
Supports categories, read-only annotations (plan-mode safe), and
backward-compatible dict access via the `tools` property.
"""

from typing import Callable, Dict, Optional, List
from dataclasses import dataclass, field


@dataclass
class ToolDef:
    name: str
    fn: Callable
    description: str = ""
    category: str = "general"
    read_only: bool = False  # True = safe for plan mode


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDef] = {}

    def register(self, name: str, fn: Callable, description: str = "",
                 category: str = "general", read_only: bool = False):
        self._tools[name] = ToolDef(name=name, fn=fn, description=description,
                                    category=category, read_only=read_only)

    def unregister(self, name: str):
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)

    def execute(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        return tool.fn(args)

    def get_read_only_tools(self) -> List[str]:
        return [name for name, t in self._tools.items() if t.read_only]

    def get_all_names(self) -> List[str]:
        return sorted(self._tools.keys())

    @property
    def tools(self) -> Dict[str, Callable]:
        """Legacy compatibility — returns dict of name -> fn."""
        return {name: t.fn for name, t in self._tools.items()}

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
