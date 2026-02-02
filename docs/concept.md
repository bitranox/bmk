we want to provode following cli commands :

t / test       --> test.sh  ---> pass the actual directory.
ti / testi / testintegration  --> test_integration_???_<commment>.sh

c / commit  --> commit.sh



bump bmp b --> ma/major m/minor p/patch


p / push --> push.sh
r / run --> run.sh
 
d / deps / dependencies --update
du / dup
cln / clean 
rel / release
bld / build
h/help/hlp / --help
m / mnu / menue


--> linux .sh
--> windows .ps1


implement the cli command t and test, which calls  a shellscript in src/bmk/scripts/test.sh - or, if it exists fom current directory/bmk_scripts/test.sh
for windows call test.ps1 after the same logic. as first parameter the current dir is always passed as first parameter to the script.
all other parameters given to t or test whould also be passed to the script.
create an empty (with shebang) src/bmk/scripts/test.sh and src/bmk/scripts/test.ps1








# Implementation Plan: CLI `test` / `t` Command

## Overview

Add a new CLI command `test` (alias `t`) that executes an external shell script, with local override support.

## Requirements

1. **Command names**: `test` (primary) and `t` (alias)
2. **Script selection by OS**:
   - Linux/macOS: `test.sh`
   - Windows: `test.ps1`
3. **Script lookup order** (first match wins):
   1. `<cwd>/bmk_makescripts/test.sh` (or `.ps1`) — local project override
   2. `<package>/makescripts/test.sh` (or `.ps1`) — bundled default
4. **Arguments**:
   - First arg: current working directory (always passed)
   - Remaining args: all CLI arguments passed through
5. **Placeholder scripts**: Create empty scripts with proper shebangs

---

## Files to Create

### 1. `src/bmk/makescripts/test.sh`
```bash
#!/usr/bin/env bash
# Default test script - override by placing bmk_makescripts/test.sh in your project
```

### 2. `src/bmk/makescripts/test.ps1`
```powershell
# Default test script - override by placing bmk_makescripts/test.ps1 in your project
```

### 3. `src/bmk/adapters/cli/commands/test_cmd.py`

> Note: Named `test_cmd.py` (not `test.py`) to avoid pytest collection conflicts.

New command module with:
- `cli_test` command (name: `test`)
- `cli_t` alias command (name: `t`) — same implementation, different Click name
- Helper functions:
  - `_get_script_name()` — return `test.sh` or `test.ps1` based on OS
  - `_resolve_script_path()` — find script using lookup order
  - `_run_test()` — shared implementation for both commands

**Command structure:**
```python
@click.command("test", context_settings=CLICK_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_test(args: tuple[str, ...]) -> None:
    """Run the project test script."""
    _run_test(args)

@click.command("t", context_settings=CLICK_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_t(args: tuple[str, ...]) -> None:
    """Run the project test script (alias for 'test')."""
    _run_test(args)
```

---

## Files to Modify

### 1. `src/bmk/adapters/cli/commands/__init__.py`
Add exports:
```python
from .test_cmd import cli_t, cli_test
# Add to __all__: "cli_t", "cli_test"
```

### 2. `src/bmk/adapters/cli/root.py`
Register commands in `_register_commands()`:
```python
from .commands import cli_t, cli_test
# Add to the for loop: cli_t, cli_test
```

---

## Implementation Details

### Script Resolution Logic

```python
def _get_script_name() -> str:
    """Return OS-appropriate script name."""
    return "test.ps1" if sys.platform == "win32" else "test.sh"

def _resolve_script_path(script_name: str, cwd: Path) -> Path | None:
    """Find script in local override or bundled location."""
    # 1. Local override: <cwd>/bmk_makescripts/<script>
    local_script = cwd / "bmk_makescripts" / script_name
    if local_script.is_file():
        return local_script

    # 2. Bundled: <package>/makescripts/<script>
    bundled_script = Path(__file__).parent.parent.parent / "makescripts" / script_name
    if bundled_script.is_file():
        return bundled_script

    return None
```

### Script Execution

```python
def _execute_script(script_path: Path, cwd: Path, extra_args: tuple[str, ...]) -> int:
    """Execute script with cwd as first argument."""
    if script_path.suffix == ".ps1":
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File",
               str(script_path), str(cwd), *extra_args]
    else:
        cmd = [str(script_path), str(cwd), *extra_args]

    result = subprocess.run(cmd, check=False)
    return result.returncode
```

### Exit Codes

- `0`: Script executed successfully (or script returned 0)
- `2` (`ExitCode.FILE_NOT_FOUND`): Script not found
- Other: Pass through script's exit code

---

## Files to Create for Tests

### `tests/test_cli_test_cmd.py`

Tests covering:
- `_get_script_name()` returns correct name per OS
- `_resolve_script_path()` prefers local override (`bmk_makescripts/`) over bundled
- `_resolve_script_path()` falls back to bundled when no local override
- `_resolve_script_path()` returns None when neither exists
- CLI integration: `cli_test` and `cli_t` invoke correctly
- Arguments are passed through correctly (cwd first, then extra args)
- Exit code 2 when script not found

---

## Verification

### Automated Tests
```bash
python -m pytest tests/test_cli_test_cmd.py -v
```

### Manual Verification
```bash
# Test bundled script (will just exit since scripts are empty)
bmk test
bmk t

# Test with args
bmk test --verbose --coverage

# Test local override
mkdir -p bmk_makescripts
echo '#!/bin/bash
echo "CWD: $1"
echo "Args: ${@:2}"' > bmk_makescripts/test.sh
chmod +x bmk_makescripts/test.sh
bmk test arg1 arg2
# Expected output:
# CWD: /path/to/current/dir
# Args: arg1 arg2
```

---

## Directory Structure After Implementation

```
src/bmk/
├── makescripts/                # NEW: Bundled scripts directory
│   ├── test.sh                 # NEW: Default test script (bash)
│   └── test.ps1                # NEW: Default test script (PowerShell)
├── adapters/
│   └── cli/
│       └── commands/
│           ├── __init__.py     # MODIFY: Add exports
│           └── test_cmd.py     # NEW: Test command implementation
tests/
└── test_cli_test_cmd.py        # NEW: Tests for the command
```

