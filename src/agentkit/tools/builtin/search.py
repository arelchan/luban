"""Search tools: glob_files, grep_files."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from agentkit.tools.native import tool


@tool
def glob_files(pattern: str, path: str = ".") -> str:
    """Find files by name/path pattern. Returns matching file paths sorted alphabetically.

    WHEN TO USE: You know the filename pattern but not the exact location.
    WHEN NOT TO USE: To search file *contents* → use grep_files instead.
    Never use run_command with `find` or `ls` — always use this tool.
    You can call this in parallel with other searches for independent queries.

    Args:
        pattern: Glob pattern. Examples: '**/*.py', 'src/**/*.ts', '**/test_*.py', '*.md'.
        path: Base directory to search from. Defaults to current working directory."""
    base = Path(path).expanduser().resolve()
    if not base.exists():
        return f"Error: Path not found: {base}"
    try:
        matches = sorted(base.glob(pattern))
        files = [str(m.relative_to(base)) for m in matches if m.is_file()]
        if not files:
            return "No files matched the pattern."
        if len(files) > 100:
            return "\n".join(files[:100]) + f"\n... and {len(files) - 100} more files"
        return "\n".join(files)
    except Exception as e:
        return f"Error: {e}"


@tool
def grep_files(pattern: str, path: str = ".", include: str = "", context: int = 0, max_results: int = 100) -> str:
    """Search file contents using a regex pattern. Returns file:line:match format.

    WHEN TO USE: Finding where a function/class/variable is defined or used, searching for patterns across files.
    WHEN NOT TO USE: Finding files by name → use glob_files. Reading a known file → use read_file.
    Never use run_command with `grep` or `rg` — always use this tool.
    Typical workflow: glob_files → grep_files → read_file (narrow down progressively).

    Args:
        pattern: Regular expression to search for (e.g. 'class Foo', 'def bar', 'import.*os').
        path: Directory to search in recursively. Defaults to current working directory.
        include: Filter filenames by glob pattern, e.g. '*.py', '*.ts'. Empty means all files.
        context: Number of lines to show before and after each match (like grep -C). Useful for understanding code.
        max_results: Maximum number of matches to return. Default 100."""
    base = Path(path).expanduser().resolve()
    if not base.exists():
        return f"Error: Path not found: {base}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex: {e}"

    results = []
    match_count = 0

    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]

        for fname in sorted(files):
            if include and not fnmatch.fnmatch(fname, include):
                continue
            fpath = Path(root) / fname
            try:
                lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
                rel = fpath.relative_to(base)
                for i, line in enumerate(lines):
                    if regex.search(line):
                        if context > 0:
                            if results:
                                results.append("--")
                            start = max(0, i - context)
                            for j in range(start, i):
                                results.append(f"{rel}:{j+1}- {lines[j].rstrip()}")
                            results.append(f"{rel}:{i+1}: {line.rstrip()}")
                            end = min(len(lines), i + context + 1)
                            for j in range(i + 1, end):
                                results.append(f"{rel}:{j+1}- {lines[j].rstrip()}")
                        else:
                            results.append(f"{rel}:{i+1}: {line.rstrip()}")
                        match_count += 1
                        if match_count >= max_results:
                            results.append(f"... (truncated at {max_results} matches)")
                            return "\n".join(results)
            except (OSError, UnicodeDecodeError):
                continue

    if not results:
        return "No matches found."
    return "\n".join(results)
