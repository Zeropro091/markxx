"""
MARK — Sandbox Execution

Run shell commands in isolated environments to prevent damage.
Supports Docker and process-level isolation.

Inspired by gemini-cli's gVisor/Docker sandboxing.
"""

import os
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass

from core.logger import get_logger
log = get_logger("sandbox")


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    sandbox_type: str  # docker | process | none


class SandboxConfig:
    """Configuration for sandbox execution."""

    def __init__(self, mode: str = "auto"):
        """
        Args:
            mode: "docker" | "process" | "none" | "auto"
                  auto = use docker if available, else process isolation
        """
        self.mode = mode
        self._docker_available: Optional[bool] = None

    def has_docker(self) -> bool:
        """Check if Docker is available."""
        if self._docker_available is None:
            self._docker_available = shutil.which("docker") is not None
            if self._docker_available:
                try:
                    result = subprocess.run(
                        ["docker", "info"],
                        capture_output=True, text=True, timeout=5,
                    )
                    self._docker_available = result.returncode == 0
                except Exception:
                    self._docker_available = False
        return self._docker_available

    @property
    def effective_mode(self) -> str:
        if self.mode == "auto":
            return "docker" if self.has_docker() else "process"
        return self.mode


class Sandbox:
    """Execute commands in sandboxed environments."""

    def __init__(self, config: SandboxConfig = None, working_dir: str = "."):
        self.config = config or SandboxConfig()
        self.working_dir = os.path.abspath(working_dir)

    def execute(self, command: str, timeout: int = 30) -> SandboxResult:
        """Execute a command in the configured sandbox mode."""
        mode = self.config.effective_mode

        if mode == "docker":
            return self._docker_exec(command, timeout)
        elif mode == "process":
            return self._process_exec(command, timeout)
        else:
            return self._bare_exec(command, timeout)

    def _docker_exec(self, command: str, timeout: int) -> SandboxResult:
        """Run command in a Docker container with mounted workspace."""
        docker_cmd = [
            "docker", "run", "--rm",
            "--network=none",           # No network access
            "--memory=512m",            # Memory limit
            "--cpus=1",                 # CPU limit
            "-v", f"{self.working_dir}:/workspace:rw",
            "-w", "/workspace",
            "--user", f"{os.getuid()}:{os.getgid()}" if hasattr(os, 'getuid') else "",
            "python:3.12-slim",
            "sh", "-c", command,
        ]
        # Remove empty strings (Windows doesn't have getuid)
        docker_cmd = [x for x in docker_cmd if x]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True, text=True,
                timeout=timeout,
            )
            return SandboxResult(
                stdout=result.stdout[:10000],
                stderr=result.stderr[:5000],
                exit_code=result.returncode,
                sandbox_type="docker",
            )
        except subprocess.TimeoutExpired:
            return SandboxResult("", f"Command timed out after {timeout}s", -1, "docker")
        except Exception as e:
            log.error(f"Docker execution failed: {e}")
            # Fall back to process isolation
            return self._process_exec(command, timeout)

    def _process_exec(self, command: str, timeout: int) -> SandboxResult:
        """Run command with process-level isolation (restricted env)."""
        # Create a restricted environment
        env = os.environ.copy()
        # Remove potentially dangerous env vars
        for key in ["AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "API_KEY",
                     "DATABASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            env.pop(key, None)

        # Use a temp directory for TEMP/TMP to prevent pollution
        with tempfile.TemporaryDirectory() as tmpdir:
            env["TEMP"] = tmpdir
            env["TMP"] = tmpdir

            try:
                if os.name == "nt":
                    # Windows: use cmd /c
                    result = subprocess.run(
                        ["powershell", "-Command", command],
                        capture_output=True, text=True,
                        timeout=timeout, cwd=self.working_dir,
                        env=env,
                    )
                else:
                    result = subprocess.run(
                        ["sh", "-c", command],
                        capture_output=True, text=True,
                        timeout=timeout, cwd=self.working_dir,
                        env=env,
                    )
                return SandboxResult(
                    stdout=result.stdout[:10000],
                    stderr=result.stderr[:5000],
                    exit_code=result.returncode,
                    sandbox_type="process",
                )
            except subprocess.TimeoutExpired:
                return SandboxResult("", f"Command timed out after {timeout}s", -1, "process")
            except Exception as e:
                return SandboxResult("", str(e), -1, "process")

    def _bare_exec(self, command: str, timeout: int) -> SandboxResult:
        """Run command without sandboxing (fallback)."""
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["powershell", "-Command", command],
                    capture_output=True, text=True,
                    timeout=timeout, cwd=self.working_dir,
                )
            else:
                result = subprocess.run(
                    ["sh", "-c", command],
                    capture_output=True, text=True,
                    timeout=timeout, cwd=self.working_dir,
                )
            return SandboxResult(
                stdout=result.stdout[:10000],
                stderr=result.stderr[:5000],
                exit_code=result.returncode,
                sandbox_type="none",
            )
        except subprocess.TimeoutExpired:
            return SandboxResult("", f"Command timed out after {timeout}s", -1, "none")
        except Exception as e:
            return SandboxResult("", str(e), -1, "none")

    def check_status(self) -> dict:
        """Return sandbox capabilities."""
        return {
            "mode": self.config.effective_mode,
            "docker_available": self.config.has_docker(),
            "working_dir": self.working_dir,
        }
