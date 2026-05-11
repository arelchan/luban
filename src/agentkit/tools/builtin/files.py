"""File operation tools: read_file, write_file, edit_file, list_directory."""

from __future__ import annotations

from pathlib import Path

from agentkit.tools.native import tool


@tool
def read_file(file_path: str, offset: int = 0, limit: int = 0) -> str:
    """Read a file and return its contents with line numbers.

    IMPORTANT: You MUST read a file before editing it. Never modify a file you haven't read in this conversation.
    For large files, use offset and limit to read in chunks instead of loading everything.
    Always prefer this tool over run_command with cat/head/tail — those are forbidden.
    You can read multiple files in parallel if they are independent.

    Args:
        file_path: Absolute or relative path to the file to read.
        offset: 0-based line index to start reading from. Only provide for large files.
        limit: Maximum number of lines to return. 0 means read entire file."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"Error: File not found: {path}"
    if not path.is_file():
        return f"Error: Not a file: {path}"
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if offset > 0:
            lines = lines[offset:]
        if limit > 0:
            lines = lines[:limit]
        start = offset + 1
        numbered = []
        for i, line in enumerate(lines):
            numbered.append(f"{start + i:>5}│ {line.rstrip()}")
        return "\n".join(numbered)
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def write_file(file_path: str, content: str) -> str:
    """Create a new file or completely overwrite an existing file. Creates parent directories automatically.

    WHEN TO USE: Creating new files, or complete rewrites where edit_file would be impractical.
    WHEN NOT TO USE: For targeted edits to existing files — use edit_file instead (it only sends the diff, much cheaper).
    NEVER use run_command with echo/heredoc to create files — always use this tool.
    IMPORTANT: If overwriting an existing file, you MUST read_file first.

    Args:
        file_path: Absolute or relative path. Parent directories are created if needed.
        content: The complete file content to write."""
    path = Path(file_path).expanduser().resolve()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def edit_file(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Edit a file by performing exact string replacement. Preferred over write_file for modifying existing files.

    IMPORTANT: You MUST call read_file first — never edit a file you haven't read in this conversation.
    The edit will FAIL if old_string is not found or is not unique (unless replace_all=True).
    If old_string appears multiple times, either add more surrounding context to make it unique, or set replace_all=True.
    When editing text from read_file output, preserve exact indentation as shown in the file content.

    Args:
        file_path: Path to the file to modify. Must exist.
        old_string: The exact text to find and replace. Must match file content exactly including whitespace.
        new_string: The replacement text. Must differ from old_string.
        replace_all: If True, replace ALL occurrences. Use for renaming variables/identifiers across the file."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"Error: File not found: {path}"
    try:
        text = path.read_text(encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            return "Error: old_string not found in file."
        if not replace_all and count > 1:
            return f"Error: old_string found {count} times. Use replace_all=True to replace all, or provide more context to make it unique."
        new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        path.write_text(new_text, encoding="utf-8")
        replaced = count if replace_all else 1
        return f"Successfully edited {path} ({replaced} replacement{'s' if replaced > 1 else ''})"
    except Exception as e:
        return f"Error editing file: {e}"


@tool
def list_directory(path: str = ".") -> str:
    """List a directory's contents showing file types and sizes.

    Use for getting an overview of a directory structure.
    For finding files by name pattern across directories, use glob_files instead.
    For reading file content, use read_file (NOT this tool).

    Args:
        path: Directory path to list. Defaults to current working directory."""
    dir_path = Path(path).expanduser().resolve()
    if not dir_path.exists():
        return f"Error: Path not found: {dir_path}"
    if not dir_path.is_dir():
        return f"Error: Not a directory: {dir_path}"
    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for entry in entries:
            if entry.is_dir():
                lines.append(f"  {entry.name}/")
            else:
                size = entry.stat().st_size
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size // 1024}K"
                else:
                    size_str = f"{size // (1024 * 1024)}M"
                lines.append(f"  {entry.name}  ({size_str})")
        return f"{dir_path}/\n" + "\n".join(lines) if lines else f"{dir_path}/ (empty)"
    except Exception as e:
        return f"Error: {e}"
