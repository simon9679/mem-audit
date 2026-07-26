"""mem-audit: external consistency auditor for Mem0-based memory stores."""
from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    try:
        __version__ = _pkg_version("mem-audit")
    except PackageNotFoundError:
        # Running from a source checkout that was never pip-installed (e.g. CI /
        # the offline demo run via PYTHONPATH). No dist metadata to read.
        __version__ = "0+unknown"
except ImportError:  # importlib.metadata missing (shouldn't happen on 3.10+)
    __version__ = "0+unknown"
