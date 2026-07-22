"""Plugin loader with safety guards.

WARNING: Plugins are loaded dynamically and can execute arbitrary code.
Only load plugins from trusted sources.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PLUGIN_DIR.parent.parent.resolve()

if not str(_PLUGIN_DIR.resolve()).startswith(str(_PROJECT_ROOT)):
    raise RuntimeError(
        f"Plugin directory {_PLUGIN_DIR} is outside project root {_PROJECT_ROOT}"
    )


class PluginSecurityError(Exception):
    """Raised when a plugin is loaded from an unsafe or unexpected path."""


def _warn_if_writable() -> None:
    import stat
    try:
        mode = os.stat(_PLUGIN_DIR).st_mode
        if mode & stat.S_IWOTH:
            logger.warning(
                "Plugin directory %s is world-writable — possible security risk",
                _PLUGIN_DIR,
            )
    except OSError:
        pass


_warn_if_writable()
