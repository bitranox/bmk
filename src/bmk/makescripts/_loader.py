"""Shared dynamic loader for _toml_config module.

Purpose
-------
Centralizes the ``importlib.util``-based loading of ``_toml_config.py`` that
makescripts need when run as standalone scripts outside the installed package.

Contents
--------
* ``load_toml_config_module`` -- dynamically import ``_toml_config`` from
  the same directory as the calling script.
* ``load_pyproject_config`` -- convenience wrapper that loads a
  ``PyprojectConfig`` from a ``pyproject.toml`` path.

System Role
-----------
Internal helper shared by ``_clean.py``, ``_run.py``, ``_bump_version.py``,
``_dependencies.py``, and ``_release.py``.  Each of those scripts previously
contained an identical copy of the dynamic loader.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    from _toml_config import PyprojectConfig

__all__ = ["load_toml_config_module", "load_pyproject_config"]


def load_toml_config_module() -> ModuleType:
    """Dynamically import _toml_config from the makescripts directory.

    Allows scripts to work both when run standalone from the makescripts
    directory and when imported for testing from elsewhere.

    The module is registered in ``sys.modules`` to ensure dataclasses can
    resolve type annotations correctly in Python 3.14+.

    Returns:
        The loaded ``_toml_config`` module.

    Raises:
        ImportError: If ``_toml_config.py`` cannot be found or loaded.
    """
    if "_toml_config" in sys.modules:
        return sys.modules["_toml_config"]

    script_dir = Path(__file__).parent
    toml_config_path = script_dir / "_toml_config.py"

    spec = importlib.util.spec_from_file_location("_toml_config", toml_config_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load _toml_config from {toml_config_path}"
        raise ImportError(msg)

    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec to allow dataclasses to work
    sys.modules["_toml_config"] = module
    spec.loader.exec_module(module)
    return module


def load_pyproject_config(path: Path) -> PyprojectConfig:
    """Load pyproject.toml configuration using the _toml_config module.

    Args:
        path: Path to the ``pyproject.toml`` file.

    Returns:
        Parsed ``PyprojectConfig`` instance.
    """
    module = load_toml_config_module()
    return module.load_pyproject_config(path)  # type: ignore[no-any-return]
