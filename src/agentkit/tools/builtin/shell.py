"""Shell tool: run_command."""

from __future__ import annotations

import os
import subprocess

from agentkit.tools.native import tool


@tool
def run_command(command: str, timeout: int = 120, background: bool = False) -> str:
    """Execute a shell command and return combined stdout+stderr output.

    WHEN TO USE: Only when NO dedicated tool exists — git, npm, pytest, curl, docker, make, etc.
    DO NOT USE FOR (use the dedicated tool instead):
    - Reading files → read_file
    - Searching file contents → grep_files
    - Finding files by name → glob_files
    - Listing directories → list_directory
    - Creating/writing files → write_file
    - Editing files → edit_file

    For destructive commands (rm -rf, git push --force, git reset --hard), always confirm with the user first.
    Commands run in the current working directory.

    Args:
        command: The shell command to execute. Supports pipes, redirects, && chaining.
        timeout: Maximum seconds to wait. Increase for tests/builds (default 120s). Max 600s.
        background: If True, start process in background and return PID immediately. Use for servers/watchers."""
    if background:
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=os.getcwd(),
            )
            return f"Started background process (PID {proc.pid}): {command}"
        except Exception as e:
            return f"Error starting background process: {e}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}" if output else result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
