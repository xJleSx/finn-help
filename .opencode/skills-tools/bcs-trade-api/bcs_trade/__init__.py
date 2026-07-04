"""BCS Trade API skill — library package.

The CLI in `bcs.py` is a thin shim that delegates to modules in this
package. The agent never imports from this package directly; it shells
out to the CLI and parses JSON.
"""
from __future__ import annotations

__version__ = "0.1.0"
