"""Extract pip-audit ignore-vuln flags from pyproject.toml.

Usage: python _extract_pip_audit_ignores.py

Reads pyproject.toml in the current working directory and prints
one --ignore-vuln=<ID> flag per line to stdout.
Exits 0 always (missing file or missing section is not an error).
"""

import sys
from pathlib import Path

import rtoml


def main() -> None:
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        sys.exit(0)

    data = rtoml.load(pyproject.open("r", encoding="utf-8"))
    ignores = data.get("tool", {}).get("pip-audit", {}).get("ignore-vulns", [])

    for vuln_id in ignores:
        print(f"--ignore-vuln={vuln_id}")


if __name__ == "__main__":
    main()
