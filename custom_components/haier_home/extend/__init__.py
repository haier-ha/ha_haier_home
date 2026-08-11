"""PID extension auto-discovery module.

Provides ``load_extensions()`` which imports all .py files in the extend/
directory, triggering @register decorators for PID-specific entity subclasses.

The discovery performs blocking filesystem (scandir) and import operations, so
it must be run in an executor thread rather than the event loop. See
``async_setup`` in the integration's ``__init__.py``.
"""

import importlib
from pathlib import Path

_current_dir = Path(__file__).parent
_loaded = False


def load_extensions() -> None:
    """Discover and import all extension modules (blocking; run in executor)."""
    global _loaded  # noqa: PLW0603
    if _loaded:
        return
    for _file in sorted(_current_dir.glob("*.py")):
        if _file.name != "__init__.py":
            importlib.import_module(f".{_file.stem}", package=__package__)
    _loaded = True
