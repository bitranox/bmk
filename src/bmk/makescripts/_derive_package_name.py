"""Derive the importable package name from pyproject.toml.

Usage: python _derive_package_name.py <path-to-pyproject.toml>

Prints the package name to stdout and exits 0 on success, 1 on failure.
"""

import sys
from pathlib import Path

import rtoml


def main() -> None:
    pyproject_path = Path(sys.argv[1])
    with pyproject_path.open("r", encoding="utf-8") as f:
        data = rtoml.load(f)

    # Try to derive import package from hatch wheel packages
    tool = data.get("tool", {})
    hatch = tool.get("hatch", {})
    build = hatch.get("build", {})
    targets = build.get("targets", {})
    wheel = targets.get("wheel", {})
    packages = wheel.get("packages", [])

    if packages:
        print(Path(packages[0]).name)
        sys.exit(0)

    # Try to derive from project.scripts entry points
    project = data.get("project", {})
    scripts = project.get("scripts", {})

    for spec in scripts.values():
        if ":" in spec:
            module = spec.split(":", 1)[0]
            print(module.split(".", 1)[0])
            sys.exit(0)

    # Fallback to project name with hyphens replaced by underscores
    name = project.get("name", "")
    if name:
        print(name.replace("-", "_"))
        sys.exit(0)

    sys.exit(1)


if __name__ == "__main__":
    main()
