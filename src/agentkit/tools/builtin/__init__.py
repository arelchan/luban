"""Built-in native tools that ship with AgentKit.

This package replaces the old single-file tools/builtin.py.
All tools are registered via the @tool decorator on import.
External code that imports from agentkit.tools.builtin continues to work unchanged.
"""

# ── Import all submodules to trigger @tool registration ──────────────────────
from agentkit.tools.builtin.context import (  # noqa: F401
    _runtime_context,
    _session_context,
    set_runtime_context,
    set_session_context,
)
from agentkit.tools.builtin.files import (  # noqa: F401
    read_file,
    write_file,
    edit_file,
    list_directory,
)
from agentkit.tools.builtin.shell import run_command  # noqa: F401
from agentkit.tools.builtin.search import glob_files, grep_files  # noqa: F401
from agentkit.tools.builtin.utility import get_current_time, calculate  # noqa: F401
from agentkit.tools.builtin.web import web_fetch, web_search  # noqa: F401
from agentkit.tools.builtin.tasks import (  # noqa: F401
    _task_store,
    _task_id_counter,
    _STATUS_ICON,
    _VALID_STATUSES,
    task_create,
    task_update,
    task_get,
    task_list,
)
from agentkit.tools.builtin.session import (  # noqa: F401
    rename_session,
    introspect_info,
    introspect_source,
)
from agentkit.tools.builtin.memory import (  # noqa: F401
    memory_get_profile,
    memory_keyword,
    memory_search,
)
from agentkit.tools.builtin.agents import spawn_agent, resume_agent  # noqa: F401
