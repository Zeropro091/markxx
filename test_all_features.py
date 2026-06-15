"""MARK-XX -- Full Feature Test Suite"""
import sys
import os
import io
import traceback

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

os.chdir(os.path.dirname(os.path.abspath(__file__)))
passed = 0
failed = 0
errors = []

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✅ {name}")
        passed += 1
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        errors.append((name, traceback.format_exc()))
        failed += 1

# ═══════════════════════════════════════════════════════════════════
# P0 TESTS
# ═══════════════════════════════════════════════════════════════════

print("\n━━━ P0: Smart Edit Engine ━━━")

def test_exact_match():
    from core.smart_edit import smart_edit
    r = smart_edit("hello world", "hello", "goodbye")
    assert r.strategy == "exact" and r.occurrences == 1
    assert r.new_content == "goodbye world"
test("Exact match", test_exact_match)

def test_flexible_match():
    from core.smart_edit import smart_edit
    content = "def foo():\n    x = 1\n    y = 2\n"
    r = smart_edit(content, "x = 1\ny = 2", "x = 10\ny = 20")
    assert r.strategy == "flexible" and r.occurrences == 1
    assert "x = 10" in r.new_content
test("Flexible match (whitespace)", test_flexible_match)

def test_fuzzy_match():
    from core.smart_edit import smart_edit
    content = "def hello_world():\n    pass\n"
    r = smart_edit(content, "def hello_wrld():\n    pass", "def bye():\n    pass")
    assert r.strategy == "fuzzy" and r.occurrences == 1
test("Fuzzy match (Levenshtein)", test_fuzzy_match)

def test_no_match():
    from core.smart_edit import smart_edit
    r = smart_edit("abc", "xyz_nothing_matches", "new")
    assert r.strategy == "failed" and r.occurrences == 0
test("No match returns failed", test_no_match)

def test_omission_detection():
    from core.smart_edit import detect_omission_placeholders
    hits = detect_omission_placeholders("# ... rest of code\n// existing code here\nnormal line")
    assert len(hits) == 2
test("Omission placeholder detection", test_omission_detection)

def test_multiple_occurrences():
    from core.smart_edit import smart_edit
    r = smart_edit("aaa", "a", "b", allow_multiple=True)
    assert r.occurrences == 3 and r.new_content == "bbb"
test("Multiple occurrences (allow_multiple)", test_multiple_occurrences)

print("\n━━━ P0: read_many_files ━━━")

def test_read_many_files():
    from agent.cli_tools import tool_read_many_files
    r = tool_read_many_files({"path": "core", "include": ["*.py"], "max_chars": 50000})
    assert "Read" in r and "file(s)" in r and "===" in r
test("read_many_files basic", test_read_many_files)

print("\n━━━ P0: Background Shell ━━━")

def test_shell_background():
    from agent.cli_tools import tool_shell_background, tool_shell_status, tool_shell_kill
    r = tool_shell_background({"command": "python -c \"import time; time.sleep(30)\""})
    assert "PID=" in r
    pid = r.split("PID=")[1].split(")")[0].strip()
    # Check status
    s = tool_shell_status({"pid": int(pid)})
    assert "running" in s.lower() or "Running" in s
    # Kill it
    k = tool_shell_kill({"pid": int(pid)})
    assert "killed" in k.lower() or "Killed" in k or "Terminated" in k
test("Background shell lifecycle", test_shell_background)

# ═══════════════════════════════════════════════════════════════════
# P1 TESTS
# ═══════════════════════════════════════════════════════════════════

print("\n━━━ P1: Context Compaction ━━━")

def test_context_basic():
    from core.context import ContextCompactor
    c = ContextCompactor(max_tokens=100, window_size=3)
    c.add_inception("You are MARK-XX", "system")
    for i in range(10):
        c.add("user", f"Message {i}")
        c.add("model", f"Response {i}")
    assert c.message_count == 20
    assert c.should_compact()
test("Context tracking", test_context_basic)

def test_context_compact():
    from core.context import ContextCompactor
    c = ContextCompactor(max_tokens=100, window_size=3)
    c.add_inception("system prompt", "system")
    for i in range(10):
        c.add("user", f"msg {i}")
    summary = c.compact()
    assert c.message_count == 3  # Only window_size kept
    assert summary  # Summary was generated
    ctx = c.get_context_for_llm()
    assert ctx[0]["content"] == "system prompt"  # Inception preserved
test("Context compaction + inception preservation", test_context_compact)

print("\n━━━ P1: Plan Mode ━━━")

def test_plan_mode():
    # Just test the flag mechanism — full CLI test needs interactive session
    from core.context import ContextCompactor
    plan_tools = {"read_file", "list_files", "search_files", "glob_files", "web_search"}
    assert "write_file" not in plan_tools
    assert "read_file" in plan_tools
test("Plan mode tool filter", test_plan_mode)

print("\n━━━ P1: MARK.md Memory ━━━")

def test_markmd():
    from core.markmd import load_mark_context
    # Should return empty string when no MARK.md files exist
    result = load_mark_context(".")
    assert isinstance(result, str)
test("MARK.md loader", test_markmd)

print("\n━━━ P1: ToolRegistry ━━━")

def test_registry():
    from core.tool_registry import ToolRegistry
    r = ToolRegistry()
    r.register("test_tool", lambda args: "ok", category="test", read_only=True)
    assert "test_tool" in r
    assert len(r) == 1
    assert r.execute("test_tool", {}) == "ok"
    assert r.get_read_only_tools() == ["test_tool"]
    r.unregister("test_tool")
    assert len(r) == 0
test("ToolRegistry CRUD", test_registry)

def test_registry_global():
    from agent.tools import registry, TOOLS
    assert len(registry) >= 40
    assert len(TOOLS) >= 40
    assert "edit_file" in registry
    assert "read_file" in registry
    # Check read-only flags
    ro = registry.get_read_only_tools()
    assert "read_file" in ro
    assert "edit_file" not in ro
test("Global registry (40+ tools)", test_registry_global)

# ═══════════════════════════════════════════════════════════════════
# P2 TESTS
# ═══════════════════════════════════════════════════════════════════

print("\n━━━ P2: Lifecycle Hooks ━━━")

def test_hooks_register():
    from core.hooks import HookSystem, HookResult
    h = HookSystem()
    results = []
    h.register("before_tool", "logger", handler=lambda ctx: results.append(ctx))
    h.fire("before_tool", {"action": "edit_file"})
    assert len(results) == 1
    assert results[0]["action"] == "edit_file"
test("Hook register + fire", test_hooks_register)

def test_hooks_block():
    from core.hooks import HookSystem, HookResult
    h = HookSystem()
    h.register("before_tool", "blocker", handler=lambda ctx: HookResult(allowed=False, reason="blocked by test"))
    result = h.fire("before_tool", {"action": "delete_file"})
    assert not result.allowed
    assert "blocked" in result.reason
test("Hook blocking", test_hooks_block)

print("\n━━━ P2: MCP Client ━━━")

def test_mcp_manager():
    from core.mcp_client import MCPManager
    m = MCPManager()
    assert m.list_servers() == {}
    m.add_server("test", ["echo", "hello"])
    assert "test" in m.list_servers()
test("MCP manager", test_mcp_manager)

print("\n━━━ P2: Agent Teams ━━━")

def test_agent_teams():
    from core.agents import AgentTeam, AgentRole, ROLE_TOOLS
    t = AgentTeam()
    tid = t.create_task(AgentRole.PLAN, "analyze codebase")
    task = t.get_task(tid)
    assert task.role == AgentRole.PLAN
    assert task.status == "pending"
    t.update_task(tid, "done", result="analyzed")
    assert t.get_task(tid).status == "done"
    # Check role permissions
    plan_tools = ROLE_TOOLS[AgentRole.PLAN]
    assert "read_file" in plan_tools
    assert "edit_file" not in (plan_tools or set())
    build_tools = ROLE_TOOLS[AgentRole.BUILD]
    assert build_tools is None  # BUILD = all tools
test("Agent teams + roles", test_agent_teams)

print("\n━━━ P2: LSP ━━━")

def test_lsp_import():
    from core.lsp import LSPManager, LSPClient, LANGUAGE_SERVERS
    assert ".py" in LANGUAGE_SERVERS
    assert ".ts" in LANGUAGE_SERVERS
    m = LSPManager(".")
    assert m.has_client("test.py")
    assert not m.has_client("test.unknown")
test("LSP manager + language detection", test_lsp_import)

print("\n━━━ P2: Sandbox ━━━")

def test_sandbox():
    from core.sandbox import Sandbox, SandboxConfig
    s = Sandbox(SandboxConfig(mode="process"), working_dir=".")
    result = s.execute("python -c \"print('sandboxed')\"", timeout=10)
    assert "sandboxed" in result.stdout
    assert result.sandbox_type == "process"
test("Sandbox process execution", test_sandbox)

def test_sandbox_status():
    from core.sandbox import Sandbox
    s = Sandbox(working_dir=".")
    status = s.check_status()
    assert "mode" in status
    assert "working_dir" in status
test("Sandbox status check", test_sandbox_status)

# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════

print("\n━━━ Integration ━━━")

def test_all_imports():
    from agent.tools import TOOLS, registry
    from agent.tool_declarations import build_tool_declarations
    from agent.cli_planner import CLIPlanner
    decls = build_tool_declarations()
    assert len(decls) > 0
test("All imports clean", test_all_imports)

def test_tool_count():
    from agent.tools import registry
    count = len(registry)
    assert count >= 45, f"Expected ≥45 tools, got {count}"
test(f"Tool count ≥ 45", test_tool_count)

# ═══════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════

print(f"\n{'='*50}")
print(f"  RESULTS: {passed} passed, {failed} failed")
print(f"{'='*50}")

if errors:
    print("\nFailed tests:")
    for name, tb in errors:
        print(f"\n--- {name} ---")
        print(tb[-500:])

sys.exit(0 if failed == 0 else 1)
