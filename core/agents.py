import threading
import queue
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from core.logger import get_logger
log = get_logger('agents')

class AgentRole(Enum):
    BUILD = 'build'       # Full access - can read, write, execute
    PLAN = 'plan'         # Read-only - can only read files, search, browse
    EXPLORE = 'explore'   # Fast codebase navigation - read + search only
    RESEARCH = 'research' # Web + docs research - web_search, fetch_url only

# Which tools each role can access
ROLE_TOOLS = {
    AgentRole.BUILD: None,  # None = all tools
    AgentRole.PLAN: {
        'read_file', 'list_files', 'search_files', 'glob_files',
        'web_search', 'fetch_url', 'semantic_search', 'recall_notes',
        'read_many_files', 'git_diff',
        'note_list', 'note_read', 'note_search',
    },
    AgentRole.EXPLORE: {
        'read_file', 'list_files', 'search_files', 'glob_files',
        'semantic_search', 'read_many_files',
    },
    AgentRole.RESEARCH: {
        'web_search', 'fetch_url', 'recall_notes',
    },
}

@dataclass
class AgentTask:
    id: str
    role: AgentRole
    prompt: str
    status: str = 'pending'  # pending | running | done | failed
    result: Optional[str] = None
    error: Optional[str] = None

class SubAgent:
    """A sub-agent that runs a task with restricted tool access."""
    def __init__(self, agent_id: str, role: AgentRole, llm_factory: Callable):
        self.id = agent_id
        self.role = role
        self.allowed_tools = ROLE_TOOLS.get(role)
        self._llm = llm_factory()
        self._inbox: queue.Queue = queue.Queue()
    
    def can_use_tool(self, tool_name: str) -> bool:
        if self.allowed_tools is None:
            return True
        return tool_name in self.allowed_tools

class AgentTeam:
    """Manages a team of sub-agents with different roles."""
    def __init__(self):
        self._agents: Dict[str, SubAgent] = {}
        self._tasks: Dict[str, AgentTask] = {}
        self._task_counter = 0
    
    def create_task(self, role: AgentRole, prompt: str) -> str:
        self._task_counter += 1
        task_id = f'task-{self._task_counter}'
        task = AgentTask(id=task_id, role=role, prompt=prompt)
        self._tasks[task_id] = task
        log.info(f'Created {role.value} task: {task_id}')
        return task_id
    
    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self._tasks.get(task_id)
    
    def update_task(self, task_id: str, status: str, result: str = None, error: str = None):
        task = self._tasks.get(task_id)
        if task:
            task.status = status
            if result:
                task.result = result
            if error:
                task.error = error
    
    def list_tasks(self, status: str = None) -> List[AgentTask]:
        if status:
            return [t for t in self._tasks.values() if t.status == status]
        return list(self._tasks.values())
    
    def get_tool_filter(self, role: AgentRole) -> Optional[set]:
        return ROLE_TOOLS.get(role)
    
    def stats(self) -> dict:
        by_status = {}
        for t in self._tasks.values():
            by_status[t.status] = by_status.get(t.status, 0) + 1
        return {'total_tasks': len(self._tasks), 'by_status': by_status}

# Global singleton
team = AgentTeam()
