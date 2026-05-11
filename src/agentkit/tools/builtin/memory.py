"""Long-term memory retrieval tools: memory_get_profile, memory_keyword, memory_search."""

from __future__ import annotations

from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context


@tool
def memory_get_profile() -> str:
    """Return all user profile memories (preferences, technical background, work habits).

    WHEN TO USE: Starting a new complex task where user context matters.
    WHEN NOT TO USE: Every turn, or for simple questions. Only call when profile info would change your approach."""
    mm = _runtime_context.get("memory_manager")
    if not mm or not mm.long_term:
        return "Long-term memory is not enabled."
    entries = mm.long_term.store.get_all("profile")
    if not entries:
        return "No profile memories yet."
    lines = []
    for e in entries:
        lines.append(f"[{e.get('category','')}] {e.get('content','')}")
    return "\n".join(lines)


@tool
def memory_keyword(keyword: str, memory_type: str = "") -> str:
    """Search long-term memory by exact keyword/substring match.

    WHEN TO USE: You know a specific term — project name, tool name, config key, person name.
    For fuzzy/semantic search, use memory_search instead.

    Args:
        keyword: The exact term to search for (case-insensitive substring match).
        memory_type: Filter by 'profile', 'fact', or 'lesson'. Empty searches all types."""
    mm = _runtime_context.get("memory_manager")
    if not mm or not mm.long_term:
        return "Long-term memory is not enabled."
    mtype = memory_type if memory_type in ("profile", "fact", "lesson") else None
    results = mm.long_term.store.keyword_search(keyword, memory_type=mtype)
    if not results:
        return f"No memories found matching '{keyword}'."
    lines = []
    for e in results:
        t = e.get("type", "")
        if t == "profile":
            lines.append(f"[profile/{e.get('category','')}] {e.get('content','')}")
        elif t == "fact":
            lines.append(f"[fact/{e.get('scope','')}] {e.get('content','')}")
        elif t == "lesson":
            lines.append(f"[lesson] {e.get('title','')}: {e.get('content','')}")
    return "\n".join(lines)


@tool
async def memory_search(query: str, memory_type: str = "", top_k: int = 5) -> str:
    """Search long-term memory by semantic similarity. Falls back to keyword search if embedding is not configured.

    WHEN TO USE: You need relevant past experience but don't know the exact keyword to search for.
    For exact keyword lookup, use memory_keyword (faster and more precise).

    Args:
        query: Natural language description of what you're looking for.
        memory_type: Filter by 'profile', 'fact', or 'lesson'. Empty searches all types.
        top_k: Number of results to return. Default 5."""
    mm = _runtime_context.get("memory_manager")
    if not mm or not mm.long_term:
        return "Long-term memory is not enabled."

    store = mm.long_term.store
    mtype = memory_type if memory_type in ("profile", "fact", "lesson") else None

    embedder = _runtime_context.get("embedder")
    if embedder and embedder.enabled:
        vec = await embedder.embed(query)
        if vec:
            results = store.vector_search(vec, memory_type=mtype, top_k=top_k, min_score=0.3)
            if results:
                lines = []
                for e, score in results:
                    t = e.get("type", "")
                    if t == "profile":
                        lines.append(f"[profile/{e.get('category','')}] {e.get('content','')} (score: {score:.2f})")
                    elif t == "fact":
                        lines.append(f"[fact/{e.get('scope','')}] {e.get('content','')} (score: {score:.2f})")
                    elif t == "lesson":
                        lines.append(f"[lesson] {e.get('title','')}: {e.get('content','')} (score: {score:.2f})")
                return "\n".join(lines)

    results_kw = store.keyword_search(query, memory_type=mtype, max_results=top_k)
    if not results_kw:
        return f"No memories found for '{query}'."
    lines = []
    for e in results_kw:
        t = e.get("type", "")
        if t == "profile":
            lines.append(f"[profile/{e.get('category','')}] {e.get('content','')}")
        elif t == "fact":
            lines.append(f"[fact/{e.get('scope','')}] {e.get('content','')}")
        elif t == "lesson":
            lines.append(f"[lesson] {e.get('title','')}: {e.get('content','')}")
    return "\n".join(lines)
