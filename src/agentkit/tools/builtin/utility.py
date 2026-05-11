"""Utility tools: get_current_time, calculate."""

from __future__ import annotations

from datetime import datetime, timezone

from agentkit.tools.native import tool


@tool
def get_current_time(timezone_name: str = "UTC") -> str:
    """Get the current date and time in a specific timezone.

    WHEN TO USE: User asks for current time, or you need timestamps for file naming, logging, etc.

    Args:
        timezone_name: IANA timezone name, e.g. 'Asia/Shanghai', 'America/New_York', 'UTC'. Defaults to UTC."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
        timezone_name = "UTC"
    now = datetime.now(tz)
    return now.strftime(f"%Y-%m-%d %H:%M:%S {timezone_name}")


@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely. Supports +, -, *, /, **, (), and scientific notation.

    WHEN TO USE: Arithmetic that must be exact — token cost estimates, unit conversions, date math.
    WHEN NOT TO USE: Trivial math you can do in your head (2+2, 10*3).

    Args:
        expression: Mathematical expression using digits, operators (+,-,*,/,**), and parentheses. E.g. '(1024*1024)/8'."""
    allowed = set("0123456789+-*/.() eE")
    if not all(c in allowed for c in expression):
        return "Error: expression contains invalid characters"
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"Error: {e}"
