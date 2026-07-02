"""Cross-OS Python stage runner.

Replaces the bash/PowerShell staged command runner: discovers pipeline stages
from an in-code registry, runs order-groups sequentially with within-group
parallelism, captures output shown only on failure in JSON mode, and forwards to
tools via argv-list subprocess calls.
"""
