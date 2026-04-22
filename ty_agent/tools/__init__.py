"""ty-agent tools package.

Provides a lightweight tool registry and core tool implementations
(read_file, write_file, patch, search_files, terminal, execute_code,
browser_navigate, browser_snapshot, browser_click, browser_type,
browser_scroll, browser_back, browser_press, browser_get_images,
browser_vision, browser_console).
"""

from ty_agent.tools.registry import registry, tool_error, tool_result

# Import core tools to trigger self-registration
import ty_agent.tools.core  # noqa: F401
import ty_agent.tools.browser_tools  # noqa: F401

__all__ = ["registry", "tool_error", "tool_result"]
