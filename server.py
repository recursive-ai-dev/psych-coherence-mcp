"""Backward-compatible launcher for the packaged MCP server.

New integrations should run ``python -m psych_coherence_mcp`` or the
``psych-coherence-mcp`` console command. Public imports should come from the
``psych_coherence_mcp`` package.
"""

from psych_coherence_mcp import *  # noqa: F403
from psych_coherence_mcp import __all__ as __all__
from psych_coherence_mcp.server import main

if __name__ == "__main__":
    main()
