"""Web tools: web_fetch, web_search (Brave API + Bing fallback)."""

from __future__ import annotations

import re as _re
from urllib.parse import quote_plus

import httpx

from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context


@tool
def web_fetch(url: str, max_length: int = 10000) -> str:
    """Fetch a URL and return its content as plain text. HTML is automatically converted.

    Use for reading web pages, documentation, API responses, or any URL content.
    Results are truncated to max_length to avoid overwhelming context.

    Args:
        url: The full URL to fetch (must include https://).
        max_length: Maximum characters to return. Default 10000. Increase for long pages."""
    try:
        from agentkit import APP_NAME as _app_name
        with httpx.Client(timeout=15.0, follow_redirects=True, trust_env=True) as client:
            resp = client.get(url, headers={"User-Agent": f"{_app_name}/1.0"})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = resp.text
            if "html" in content_type:
                text = _html_to_text(text)
            if len(text) > max_length:
                text = text[:max_length] + f"\n\n... (truncated, total {len(resp.text)} chars)"
            return text or "(empty response)"
    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} for {url}"
    except Exception as e:
        return f"Error fetching URL: {e}"


def _html_to_text(html: str) -> str:
    """Simple HTML to text conversion without external dependencies."""
    text = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r"<br\s*/?>", "\n", text, flags=_re.IGNORECASE)
    text = _re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", text, flags=_re.IGNORECASE)
    text = _re.sub(r"<li[^>]*>", "- ", text, flags=_re.IGNORECASE)
    text = _re.sub(r"<[^>]+>", "", text)
    for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(entity, char)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


@tool
def web_search(query: str, num_results: int = 5) -> str:
    """Search the web and return results with titles, URLs, and snippets.

    Use for finding up-to-date information, documentation, or answers beyond your training data.
    Returns structured results (title, URL, snippet) that you can then fetch with web_fetch if needed.

    Args:
        query: The search query. Be specific for better results.
        num_results: Number of results to return. Default 5."""
    cfg = _runtime_context.get("config")
    ws_cfg = cfg.tools.web_search if cfg else None
    brave_key = ws_cfg.brave_api_key if ws_cfg else ""
    engine = ws_cfg.engine if ws_cfg else "auto"

    if brave_key and engine in ("auto", "brave"):
        result = _search_brave(query, num_results, brave_key)
        if not result.startswith("Error:"):
            return result

    return _search_bing(query, num_results)


def _search_brave(query: str, num_results: int, api_key: str) -> str:
    try:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": num_results, "text_decorations": 0},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            timeout=10.0,
            trust_env=True,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("web", {}).get("results", [])
        if not items:
            return "No results found."
        results = []
        for item in items[:num_results]:
            results.append(f"[{item.get('title','')}]\n{item.get('url','')}\n{item.get('description','')}")
        return "\n\n".join(results)
    except Exception as e:
        return f"Error: Brave search failed: {e}"


def _search_bing(query: str, num_results: int) -> str:
    try:
        url = f"https://www.bing.com/search?q={quote_plus(query)}&count={num_results}"
        resp = httpx.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=15.0,
            follow_redirects=True,
            trust_env=True,
        )
        resp.raise_for_status()
        return _parse_bing_results(resp.text, num_results)
    except Exception as e:
        return f"Error: Bing search failed: {e}"


def _parse_bing_results(html: str, max_results: int) -> str:
    results = []
    blocks = _re.findall(r'<li class="b_algo".*?</li>', html, _re.DOTALL)
    for block in blocks[:max_results]:
        title_match = _re.search(r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, _re.DOTALL)
        snippet_match = _re.search(r'<p[^>]*>(.*?)</p>', block, _re.DOTALL)
        if not title_match:
            continue
        url = title_match.group(1)
        title = _re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
        snippet = ""
        if snippet_match:
            snippet = _re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
            snippet = _re.sub(r"\s+", " ", snippet)
        if url and title:
            results.append(f"[{title}]\n{url}\n{snippet}")
    return "\n\n".join(results) if results else "No results found."
