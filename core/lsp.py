"""
MARK — LSP Integration (Language Server Protocol)

Provides IDE-level code intelligence to the agent:
- goToDefinition — jump to function/class definition
- findReferences — find all usages of a symbol
- hover — get type info / docs for a symbol
- diagnostics — get compiler errors after edits

Supports Python (pyright/pylsp) and TypeScript (tsserver) out of the box.
Inspired by OpenCode's LSP integration.
"""

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from core.logger import get_logger
log = get_logger("lsp")


# ── LSP Language Detection ────────────────────────────────────────────────────

LANGUAGE_SERVERS = {
    ".py": {
        "name": "pyright",
        "command": ["pyright-langserver", "--stdio"],
        "fallback": ["pylsp"],
    },
    ".ts": {
        "name": "typescript",
        "command": ["typescript-language-server", "--stdio"],
    },
    ".tsx": {
        "name": "typescript",
        "command": ["typescript-language-server", "--stdio"],
    },
    ".js": {
        "name": "typescript",
        "command": ["typescript-language-server", "--stdio"],
    },
    ".go": {
        "name": "gopls",
        "command": ["gopls", "serve"],
    },
}


@dataclass
class LSPPosition:
    file: str
    line: int       # 0-indexed
    character: int  # 0-indexed


@dataclass
class LSPResult:
    operation: str
    success: bool
    data: Any = None
    error: str = ""


class LSPClient:
    """JSON-RPC 2.0 client for a Language Server."""

    def __init__(self, name: str, command: List[str], workspace: str):
        self.name = name
        self.command = command
        self.workspace = workspace
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._initialized = False

    def start(self) -> bool:
        """Start the language server process."""
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # We'll handle encoding manually for Content-Length
            )
            # Initialize
            init_result = self._request("initialize", {
                "processId": None,
                "rootUri": Path(self.workspace).as_uri(),
                "capabilities": {
                    "textDocument": {
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "hover": {"contentFormat": ["plaintext"]},
                        "publishDiagnostics": {"relatedInformation": True},
                    },
                },
            })
            if init_result is not None:
                self._notify("initialized", {})
                self._initialized = True
                log.info(f"LSP server '{self.name}' started")
                return True
        except FileNotFoundError:
            log.warning(f"LSP server not found: {' '.join(self.command)}")
        except Exception as e:
            log.error(f"LSP start failed: {e}")
        return False

    def stop(self):
        """Shutdown the language server."""
        if self._process:
            try:
                self._request("shutdown", None)
                self._notify("exit", None)
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                if self._process:
                    self._process.kill()
            self._process = None
            self._initialized = False

    # ── LSP Operations ─────────────────────────────────────────────────────

    def definition(self, pos: LSPPosition) -> LSPResult:
        """Go to definition."""
        result = self._text_document_request("textDocument/definition", pos)
        return LSPResult("goToDefinition", result is not None, result)

    def references(self, pos: LSPPosition) -> LSPResult:
        """Find all references."""
        params = self._make_position_params(pos)
        params["context"] = {"includeDeclaration": True}
        result = self._request("textDocument/references", params)
        return LSPResult("findReferences", result is not None, result)

    def hover(self, pos: LSPPosition) -> LSPResult:
        """Get hover info (type, docs)."""
        result = self._text_document_request("textDocument/hover", pos)
        if result and isinstance(result, dict):
            contents = result.get("contents", "")
            if isinstance(contents, dict):
                contents = contents.get("value", str(contents))
            return LSPResult("hover", True, contents)
        return LSPResult("hover", False)

    def document_symbols(self, file_path: str) -> LSPResult:
        """List all symbols in a file."""
        uri = Path(file_path).as_uri()
        result = self._request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        return LSPResult("documentSymbol", result is not None, result)

    def diagnostics(self, file_path: str) -> LSPResult:
        """Get diagnostics (errors/warnings) for a file.

        Note: Diagnostics are typically pushed via notifications.
        This opens the file to trigger diagnostics.
        """
        self._open_file(file_path)
        # Give the server a moment to compute diagnostics
        time.sleep(0.5)
        return LSPResult("diagnostics", True, "(diagnostics are async — check server output)")

    # ── Internal helpers ───────────────────────────────────────────────────

    def _open_file(self, file_path: str):
        """Notify server that a file was opened."""
        uri = Path(file_path).as_uri()
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": self._detect_language(file_path),
                "version": 1,
                "text": content,
            },
        })

    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension."""
        ext = Path(file_path).suffix.lower()
        return {
            ".py": "python", ".ts": "typescript", ".tsx": "typescriptreact",
            ".js": "javascript", ".go": "go", ".rs": "rust",
            ".java": "java", ".c": "c", ".cpp": "cpp",
        }.get(ext, "plaintext")

    def _text_document_request(self, method: str, pos: LSPPosition):
        """Make a textDocument position request."""
        self._open_file(pos.file)
        return self._request(method, self._make_position_params(pos))

    def _make_position_params(self, pos: LSPPosition) -> dict:
        uri = Path(pos.file).as_uri()
        return {
            "textDocument": {"uri": uri},
            "position": {"line": pos.line, "character": pos.character},
        }

    def _request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and wait for response."""
        with self._lock:
            self._request_id += 1
            msg = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
            }
            if params is not None:
                msg["params"] = params

            self._send(msg)
            return self._recv(self._request_id)

    def _notify(self, method: str, params: Any):
        """Send a JSON-RPC notification (no response expected)."""
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def _send(self, msg: dict):
        """Send a JSON-RPC message with Content-Length header."""
        if not self._process or not self._process.stdin:
            return
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        self._process.stdin.write(header + body)
        self._process.stdin.flush()

    def _recv(self, expected_id: int, timeout: float = 10.0) -> Any:
        """Read a JSON-RPC response."""
        if not self._process or not self._process.stdout:
            return None
        start = time.time()
        while time.time() - start < timeout:
            try:
                # Read Content-Length header
                header = b""
                while True:
                    byte = self._process.stdout.read(1)
                    if not byte:
                        return None
                    header += byte
                    if header.endswith(b"\r\n\r\n"):
                        break

                # Parse content length
                length = 0
                for line in header.decode("utf-8").strip().split("\r\n"):
                    if line.startswith("Content-Length:"):
                        length = int(line.split(":")[1].strip())

                if length == 0:
                    continue

                # Read body
                body = self._process.stdout.read(length)
                response = json.loads(body.decode("utf-8"))

                if response.get("id") == expected_id:
                    return response.get("result")

                # Skip notifications (no id)
            except Exception as e:
                log.debug(f"LSP recv error: {e}")
                break
        return None


class LSPManager:
    """Manages LSP clients for different languages."""

    def __init__(self, workspace: str):
        self.workspace = workspace
        self._clients: Dict[str, LSPClient] = {}

    def get_client(self, file_path: str) -> Optional[LSPClient]:
        """Get or create an LSP client for the given file type."""
        ext = Path(file_path).suffix.lower()
        config = LANGUAGE_SERVERS.get(ext)
        if not config:
            return None

        name = config["name"]
        if name not in self._clients:
            client = LSPClient(name, config["command"], self.workspace)
            if client.start():
                self._clients[name] = client
            else:
                # Try fallback
                for fb in config.get("fallback", []):
                    client = LSPClient(name, [fb], self.workspace)
                    if client.start():
                        self._clients[name] = client
                        break
                else:
                    return None

        return self._clients.get(name)

    def has_client(self, file_path: str) -> bool:
        """Check if an LSP server is available for this file type."""
        ext = Path(file_path).suffix.lower()
        return ext in LANGUAGE_SERVERS

    def stop_all(self):
        """Stop all LSP servers."""
        for client in self._clients.values():
            client.stop()
        self._clients.clear()


# ── Tool function for the agent ───────────────────────────────────────────────

def tool_lsp(args: dict) -> str:
    """LSP tool callable by the agent.

    Args:
        operation: goToDefinition | findReferences | hover | documentSymbol
        file: absolute path to file
        line: 1-based line number
        character: 1-based character offset
    """
    _manager = getattr(tool_lsp, "_manager", None)
    if _manager is None:
        return "Error: LSP not initialized. Set working directory first."

    operation = args.get("operation", "")
    file_path = args.get("file", "")
    line = int(args.get("line", 1)) - 1       # Convert to 0-indexed
    character = int(args.get("character", 1)) - 1

    if not file_path:
        return "Error: 'file' is required"

    client = _manager.get_client(file_path)
    if not client:
        ext = Path(file_path).suffix
        return f"Error: No LSP server available for {ext} files. Install one of: {list(LANGUAGE_SERVERS.keys())}"

    pos = LSPPosition(file=file_path, line=line, character=character)

    if operation == "goToDefinition":
        result = client.definition(pos)
    elif operation == "findReferences":
        result = client.references(pos)
    elif operation == "hover":
        result = client.hover(pos)
    elif operation == "documentSymbol":
        result = client.document_symbols(file_path)
    else:
        return f"Error: Unknown operation '{operation}'. Use: goToDefinition, findReferences, hover, documentSymbol"

    if result.success and result.data:
        return json.dumps(result.data, indent=2, default=str)[:5000]
    return f"No results for {operation} at {Path(file_path).name}:{line+1}:{character+1}"


def init_lsp(workspace: str):
    """Initialize the LSP manager for a workspace."""
    tool_lsp._manager = LSPManager(workspace)
    log.info(f"LSP manager initialized for {workspace}")
