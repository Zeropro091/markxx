"""
MARK — Context Compaction Engine

Manages conversation context to prevent token overflow.
Keeps "inception" messages (system prompt, project rules) intact
while compacting older turns into summaries.

Inspired by OpenCode's sliding window + inception pattern.
"""

import time
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from core.logger import get_logger
log = get_logger("context")


@dataclass
class ContextMessage:
    """A single message in the conversation."""
    role: str            # "user" | "model" | "tool_call" | "tool_result"
    content: str
    timestamp: float = 0.0
    is_inception: bool = False  # Never compacted
    token_estimate: int = 0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if self.token_estimate == 0:
            # Rough estimate: 1 token ≈ 4 chars
            self.token_estimate = len(self.content) // 4


class ContextCompactor:
    """Manages conversation context with sliding window + inception preservation.

    Architecture:
    ┌─────────────────────────────┐
    │  Inception messages         │ ← Never removed (system prompt, project rules)
    ├─────────────────────────────┤
    │  Compacted summary          │ ← Summary of old turns (regenerated on compact)
    ├─────────────────────────────┤
    │  Recent window (N turns)    │ ← Full fidelity recent messages
    └─────────────────────────────┘
    """

    def __init__(self, max_tokens: int = 100_000, window_size: int = 20):
        """
        Args:
            max_tokens: Maximum total estimated tokens before compacting
            window_size: Number of recent turns to keep at full fidelity
        """
        self.max_tokens = max_tokens
        self.window_size = window_size
        self.inception: List[ContextMessage] = []
        self.history: List[ContextMessage] = []
        self.compacted_summary: Optional[str] = None
        self._total_tokens = 0

    def add_inception(self, content: str, role: str = "system"):
        """Add an inception message that will never be compacted."""
        msg = ContextMessage(role=role, content=content, is_inception=True)
        self.inception.append(msg)

    def add(self, role: str, content: str):
        """Add a message to the conversation history."""
        msg = ContextMessage(role=role, content=content)
        self.history.append(msg)
        self._total_tokens += msg.token_estimate

    def should_compact(self) -> bool:
        """Check if compaction is needed."""
        return (
            self._total_tokens > self.max_tokens * 0.8
            or len(self.history) > self.window_size * 2
        )

    def compact(self) -> str:
        """Compact old messages into a summary, keeping recent window.

        Returns the compacted summary text.
        Note: This generates the summary text but does NOT call the LLM.
        The caller should use this to update the conversation.
        """
        if len(self.history) <= self.window_size:
            return ""  # Nothing to compact

        # Split: old messages to summarize, recent to keep
        split_point = len(self.history) - self.window_size
        old_messages = self.history[:split_point]
        recent_messages = self.history[split_point:]

        # Build summary of old messages
        summary_parts = []
        for msg in old_messages:
            prefix = {"user": "User", "model": "Assistant", "tool_call": "Tool",
                      "tool_result": "Result"}.get(msg.role, msg.role)
            # Truncate long messages for summary
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            summary_parts.append(f"[{prefix}]: {content}")

        self.compacted_summary = (
            "## Conversation Summary (compacted)\n"
            + "\n".join(summary_parts)
        )

        # Replace history with just the recent window
        self.history = recent_messages
        self._total_tokens = sum(m.token_estimate for m in self.history)

        log.info(
            f"Compacted {len(old_messages)} old messages. "
            f"Kept {len(recent_messages)} recent. "
            f"Tokens: ~{self._total_tokens}"
        )
        return self.compacted_summary

    def get_context_for_llm(self) -> List[Dict]:
        """Build the full context to send to the LLM.

        Returns list of message dicts in the format expected by the LLM.
        """
        messages = []

        # 1. Inception messages (always included)
        for msg in self.inception:
            messages.append({"role": msg.role, "content": msg.content})

        # 2. Compacted summary (if any)
        if self.compacted_summary:
            messages.append({
                "role": "system",
                "content": self.compacted_summary,
            })

        # 3. Recent history (full fidelity)
        for msg in self.history:
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    @property
    def total_tokens(self) -> int:
        """Estimated total tokens in context."""
        inception_tokens = sum(m.token_estimate for m in self.inception)
        summary_tokens = len(self.compacted_summary) // 4 if self.compacted_summary else 0
        return inception_tokens + summary_tokens + self._total_tokens

    @property
    def message_count(self) -> int:
        """Total messages in history (excluding inception)."""
        return len(self.history)

    def clear(self):
        """Clear all non-inception messages."""
        self.history.clear()
        self.compacted_summary = None
        self._total_tokens = 0

    def stats(self) -> dict:
        """Return context statistics."""
        return {
            "inception_messages": len(self.inception),
            "history_messages": len(self.history),
            "compacted": self.compacted_summary is not None,
            "total_tokens": self.total_tokens,
            "window_size": self.window_size,
            "max_tokens": self.max_tokens,
        }
