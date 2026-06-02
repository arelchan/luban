"""File operation tools: read_file, write_file, edit_file, list_directory."""

from __future__ import annotations

import base64
from pathlib import Path

from agentkit.tools.native import tool

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
_PDF_EXTENSIONS = {".pdf"}


_DEFAULT_READ_LIMIT = 2000  # Max lines returned by default (like CC)


@tool
def read_file(file_path: str, offset: int = 0, limit: int = 0, pages: str = "") -> str:
    """Read a file and return its contents with line numbers.

    IMPORTANT: You MUST read a file before editing it. Never modify a file you haven't read in this conversation.
    By default reads up to 2000 lines. For large files, use offset and limit to read specific ranges.
    Supports PDF files (use pages param, e.g. '1-5') and image files (returns base64 for vision models).
    Always prefer this tool over run_command with cat/head/tail — those are forbidden.
    You can read multiple files in parallel if they are independent.

    Args:
        file_path: Absolute or relative path to the file to read.
        offset: 0-based line index to start reading from. Only provide for large files.
        limit: Maximum number of lines to return. 0 means use default limit (2000 lines).
        pages: For PDF files only. Page range e.g. '1-5', '3', '10-20'. Max 20 pages per request."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"Error: File not found: {path}"
    if not path.is_file():
        return f"Error: Not a file: {path}"

    suffix = path.suffix.lower()

    # ── Image files: return base64 ──
    if suffix in _IMAGE_EXTENSIONS:
        return _read_image(path)

    # ── PDF files: extract text by page ──
    if suffix in _PDF_EXTENSIONS:
        return _read_pdf(path, pages)

    # ── Text files: standard read with line numbers ──
    try:
        all_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        total = len(all_lines)
        lines = all_lines
        if offset > 0:
            lines = lines[offset:]
        effective_limit = limit if limit > 0 else _DEFAULT_READ_LIMIT
        truncated = len(lines) > effective_limit
        lines = lines[:effective_limit]
        start = offset + 1
        numbered = []
        for i, line in enumerate(lines):
            numbered.append(f"{start + i:>5}│ {line.rstrip()}")
        result = "\n".join(numbered)
        if truncated:
            shown = len(lines)
            result += f"\n\n[Truncated: showing {shown}/{total} lines. Use offset={offset + shown} to read more.]"
        return result
    except UnicodeDecodeError:
        return f"Error: Binary file cannot be read as text: {path}"
    except Exception as e:
        return f"Error reading file: {e}"


def _read_image(path: Path) -> str:
    """Read an image file and return base64 encoded content."""
    try:
        size = path.stat().st_size
        if size > 20 * 1024 * 1024:  # 20MB limit
            return f"Error: Image too large ({size // (1024*1024)}MB). Max 20MB."
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        suffix = path.suffix.lower().lstrip(".")
        media_type = f"image/{suffix}" if suffix != "jpg" else "image/jpeg"
        return f"[IMAGE: {path.name} ({size // 1024}KB)]\ndata:{media_type};base64,{b64}"
    except Exception as e:
        return f"Error reading image: {e}"


def _read_pdf(path: Path, pages: str = "") -> str:
    """Read a PDF file and extract text content."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        try:
            import pdfplumber
            return _read_pdf_pdfplumber(path, pages)
        except ImportError:
            return (
                "Error: PDF reading requires PyMuPDF or pdfplumber. "
                "Install with: pip install pymupdf  or  pip install pdfplumber"
            )

    try:
        doc = fitz.open(str(path))
        total_pages = len(doc)

        # Parse page range
        page_range = _parse_page_range(pages, total_pages)
        if len(page_range) == 1:  # Error message
            doc.close()
            return page_range[0]
        start_page, end_page = page_range

        # Limit to 20 pages per request
        if end_page - start_page > 20:
            end_page = start_page + 20

        result_lines = [f"[PDF: {path.name} | Pages {start_page+1}-{end_page}/{total_pages}]", ""]
        for i in range(start_page, end_page):
            page = doc[i]
            text = page.get_text()
            result_lines.append(f"── Page {i+1} ──")
            result_lines.append(text.strip() if text else "(empty page)")
            result_lines.append("")

        doc.close()

        if end_page < total_pages:
            result_lines.append(f"[Use pages='{end_page+1}-{min(end_page+20, total_pages)}' to read more]")

        return "\n".join(result_lines)
    except Exception as e:
        return f"Error reading PDF: {e}"


def _read_pdf_pdfplumber(path: Path, pages: str = "") -> str:
    """Fallback PDF reader using pdfplumber."""
    import pdfplumber

    try:
        with pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)
            page_range = _parse_page_range(pages, total_pages)
            if len(page_range) == 1:
                return page_range[0]
            start_page, end_page = page_range

            if end_page - start_page > 20:
                end_page = start_page + 20

            result_lines = [f"[PDF: {path.name} | Pages {start_page+1}-{end_page}/{total_pages}]", ""]
            for i in range(start_page, end_page):
                page = pdf.pages[i]
                text = page.extract_text()
                result_lines.append(f"── Page {i+1} ──")
                result_lines.append(text.strip() if text else "(empty page)")
                result_lines.append("")

            if end_page < total_pages:
                result_lines.append(f"[Use pages='{end_page+1}-{min(end_page+20, total_pages)}' to read more]")

            return "\n".join(result_lines)
    except Exception as e:
        return f"Error reading PDF: {e}"


def _parse_page_range(pages: str, total: int):
    """Parse page range string. Returns (start, end) 0-indexed, or error string as first element."""
    if not pages:
        if total > 20:
            return (f"Error: PDF has {total} pages. Use pages='1-20' to read a specific range (max 20 per request).",)
        return 0, total

    pages = pages.strip()
    try:
        if "-" in pages:
            parts = pages.split("-", 1)
            start = int(parts[0]) - 1  # Convert to 0-indexed
            end = int(parts[1])
        else:
            start = int(pages) - 1
            end = start + 1

        start = max(0, min(start, total - 1))
        end = max(start + 1, min(end, total))
        return start, end
    except ValueError:
        return (f"Error: Invalid page range '{pages}'. Use format like '1-5' or '3'.",)


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
