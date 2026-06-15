import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from core.logger import get_logger
log = get_logger('mcp')

class MCPServer:
    """Connection to a single MCP server via stdio transport."""
    def __init__(self, name: str, command: List[str], env: dict = None):
        self.name = name
        self.command = command
        self.env = env
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._tools: List[dict] = []
        self._lock = threading.Lock()
    
    def start(self) -> bool:
        try:
            import os
            full_env = {**os.environ, **(self.env or {})}
            self._process = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=full_env, text=True,
                bufsize=1
            )
            # Send initialize
            self._send({'jsonrpc': '2.0', 'id': self._next_id(), 'method': 'initialize', 
                       'params': {'protocolVersion': '2024-11-05', 
                                  'capabilities': {},
                                  'clientInfo': {'name': 'mark-xx', 'version': '1.0'}}})
            resp = self._recv()
            if resp and 'result' in resp:
                # Send initialized notification
                self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                log.info(f'MCP server {self.name} initialized')
                return True
        except Exception as e:
            log.error(f'Failed to start MCP server {self.name}: {e}')
        return False
    
    def discover_tools(self) -> List[dict]:
        self._send({'jsonrpc': '2.0', 'id': self._next_id(), 'method': 'tools/list', 'params': {}})
        resp = self._recv()
        if resp and 'result' in resp:
            self._tools = resp['result'].get('tools', [])
            log.info(f'Discovered {len(self._tools)} tools from {self.name}')
        return self._tools
    
    def call_tool(self, tool_name: str, arguments: dict) -> str:
        self._send({'jsonrpc': '2.0', 'id': self._next_id(), 'method': 'tools/call',
                   'params': {'name': tool_name, 'arguments': arguments}})
        resp = self._recv()
        if resp and 'result' in resp:
            content = resp['result'].get('content', [])
            texts = [c.get('text', '') for c in content if c.get('type') == 'text']
            return '\n'.join(texts) if texts else json.dumps(resp['result'])
        if resp and 'error' in resp:
            return f"MCP Error: {resp['error'].get('message', 'Unknown error')}"
        return 'MCP: No response'
    
    def stop(self):
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except: pass
    
    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id
    
    def _send(self, msg: dict):
        with self._lock:
            data = json.dumps(msg)
            self._process.stdin.write(data + '\n')
            self._process.stdin.flush()
    
    def _recv(self, timeout: float = 10.0) -> Optional[dict]:
        import select, sys
        try:
            # On Windows, use a simple readline with timeout
            import time
            start = time.time()
            while time.time() - start < timeout:
                line = self._process.stdout.readline()
                if line:
                    line = line.strip()
                    if not line:
                        continue
                    return json.loads(line)
                time.sleep(0.05)
        except Exception as e:
            log.error(f'MCP recv error: {e}')
        return None


class MCPManager:
    """Manages multiple MCP server connections."""
    def __init__(self):
        self._servers: Dict[str, MCPServer] = {}
        self._tool_map: Dict[str, str] = {}  # tool_name -> server_name
    
    def load_config(self, working_dir: str):
        config_paths = [
            Path(working_dir) / '.mark' / 'mcp.json',
            Path(working_dir) / '.gemini' / 'settings.json',
            Path.home() / '.mark' / 'mcp.json',
        ]
        for cp in config_paths:
            if cp.exists():
                try:
                    data = json.loads(cp.read_text())
                    servers = data.get('mcpServers', data.get('servers', {}))
                    for name, config in servers.items():
                        cmd = config.get('command', [])
                        if isinstance(cmd, str):
                            cmd = cmd.split()
                        args = config.get('args', [])
                        env = config.get('env', {})
                        full_cmd = [cmd] + args if isinstance(cmd, str) else cmd + args
                        self.add_server(name, full_cmd, env)
                    log.info(f'Loaded MCP config from {cp}: {len(servers)} servers')
                except Exception as e:
                    log.error(f'Failed to load MCP config {cp}: {e}')
    
    def add_server(self, name: str, command: List[str], env: dict = None):
        self._servers[name] = MCPServer(name, command, env)
    
    def start_all(self) -> Dict[str, List[dict]]:
        all_tools = {}
        for name, server in self._servers.items():
            if server.start():
                tools = server.discover_tools()
                for t in tools:
                    fqn = f'mcp_{name}_{t["name"]}'
                    self._tool_map[fqn] = name
                all_tools[name] = tools
        return all_tools
    
    def call_tool(self, fqn: str, arguments: dict) -> str:
        server_name = self._tool_map.get(fqn)
        if not server_name:
            return f'Unknown MCP tool: {fqn}'
        server = self._servers.get(server_name)
        if not server:
            return f'MCP server not found: {server_name}'
        # Strip prefix to get original tool name
        tool_name = fqn[len(f'mcp_{server_name}_'):]
        return server.call_tool(tool_name, arguments)
    
    def get_tool_declarations(self) -> list:
        """Generate FunctionDeclaration-compatible dicts for all MCP tools."""
        decls = []
        for fqn, server_name in self._tool_map.items():
            server = self._servers[server_name]
            tool_name = fqn[len(f'mcp_{server_name}_'):]
            tool_info = next((t for t in server._tools if t['name'] == tool_name), None)
            if tool_info:
                decls.append({
                    'name': fqn,
                    'description': tool_info.get('description', ''),
                    'input_schema': tool_info.get('inputSchema', {}),
                })
        return decls
    
    def stop_all(self):
        for server in self._servers.values():
            server.stop()
    
    def list_servers(self) -> dict:
        return {name: {'tools': len(s._tools), 'running': s._process is not None and s._process.poll() is None}
                for name, s in self._servers.items()}

# Global singleton
mcp = MCPManager()
