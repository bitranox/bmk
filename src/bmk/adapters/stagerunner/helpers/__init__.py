"""In-process pipeline leaf helpers (migrated from the former makescripts dir).

Each helper is a normal package module: those called in-process expose a
keyword-only ``main(...) -> int``; the rest are invoked as subprocesses by
``stagerunner/tools.py``. Shared pyproject parsing lives in ``_toml_config``.
"""
