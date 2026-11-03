# ADR-0020: Installer and launcher pin Python to exactly 3.12

**Status**: Accepted  
**Date**: 2026-11-02  
**Author**: B6b Docs Build Session  
**Decision level**: D1  
**Primary lane**: Lane A (Release Critical)  
**Roadmap drift**: None  
**Spec**: `docs/design/SPEC-2026-10-29-PYTHON-312-PIN-01.md` (local, untracked)

## Context

The installers previously selected the newest available Python (3.13/3.14) or accepted
any version `>= 3.12`. Newer Python releases require C++ build tools to compile some
libraries, which breaks otherwise-valid installs. Documentation variously said 3.12+
or 3.14. The owner wants a single, exact interpreter version across launchers and
installers. The governing spec is
`docs/design/SPEC-2026-10-29-PYTHON-312-PIN-01.md` (local, untracked).

## Decision

1. **Exact probe everywhere:** require `sys.version_info[:2] == (3, 12)` in
   `launcher.py`, `start.ps1`, `start.sh`, and `scripts/bootstrap`; never fall back to
   3.11, 3.13, or 3.14.
2. **Install 3.12 when missing:**
   - Windows: winget `Python.Python.3.12` as primary, python.org 3.12.8 as fallback;
     per-user install first, then system-wide; re-probe the absolute path after install.
   - Linux/macOS `start.sh`: order uv > apt > dnf > Homebrew, versioned packages only
     (`python3.12`, `python3.12-venv`), never an unversioned `python3` or pacman
     `python`. If no route yields 3.12, STOP with instructions and exit 1.
   - `start.sh` does not bootstrap uv.
3. **Stale venv handling:** only `launcher.py` deletes and recreates a stale
   `backend/.venv`, and only behind the safe-delete guard (symlink/junction refusal,
   canonical-path check, no-op when absent). `start.ps1`, `start.sh`, and
   `scripts/bootstrap` never delete or modify a venv: they fall through (start scripts)
   or refuse with a pointer to `launcher.py`/`start.sh` (`scripts/bootstrap`, including
   a dangling-symlink venv).
4. **`backend/pyproject.toml`:** `requires-python = ">=3.12"` is unchanged for now; the
   owner is undecided about tightening to `<3.13`.
5. **No embedded-version check:** `onx.exe`/PyInstaller was removed in B0.

## Implementation

- B0 `58d6132` (separate)
- B1a/B1b/B2 `668a3c0`
- test fix `7ab2499`
- B3 `5e718a5` (`start.ps1`)
- B4 `b46947c` (`start.sh`)
- B5a `70f1e35` (`scripts/bootstrap` + `start.sh` tidy)
- B5b docs wording `315d5c0`
- B6a tests `671a0ce`
- B6b ADR + decisions index `7bd86f5`

CI on 7bd86f5: Backend Tests (ubuntu-latest, push) run 41439915100 passed. windows-ci (workflow_dispatch) run 41500641374 failed with 23 failed / 3381 passed / 69 skipped; the same 23 tests failed in the scheduled windows-ci run 41416383328 on 5e718a5 (before B4-B6), so these failures predate B4-B6a; none is in backend/tests/test_start_sh_python_pin.py. One of the 23 is backend/tests/test_launcher_python_pin.py::test_check_python_accepts_312 (a Windows path-separator assertion in a pin test from B1); five are in backend/tests/test_launcher_dynamic_port.py.

## Consequences

- Arch/CachyOS without a `python3.12` package ends at STOP; uv is the recommended route.
- Direct `pip`/`ruff` use can still run on 3.13/3.14 because `requires-python` is
  unchanged.
- `launcher.py`'s POSIX install order (uv > Homebrew > apt > dnf,
  `install_python_posix`) differs from `start.sh`'s (uv > apt > dnf > Homebrew).
- Windows was verified by the owner on a VM clone on 2026-10-31 (`start.bat` recreated
  the venv with 3.12.8).
- The Linux `start.sh` path is verified by static and hermetic tests only; no real
  package-manager install was run.

## Rejected alternatives

- Installing the newest Python.
- Accepting any version `>=3.12`.
- Deleting the venv inside the start scripts.
- Auto-installing uv from `start.sh`.
- Unversioned pacman/apt/dnf `python`.
- Using the python.org installer as the primary Windows path.

## Follow-ups

- Unify the POSIX install order between `launcher.py` and `start.sh`.
- Add `timeout 10` to the `scripts/bootstrap` probe (`start.sh` already has it).
- Decide whether to tighten `requires-python` to `<3.13`.
- Run the Windows matrix after the Dynamic Port changes.
- Fix the Windows-only failures: the pin test test_check_python_accepts_312 first (path separator), then the 5 dynamic-port tests (CRLF and mocking); the remaining Windows failures (docker dood path normalization, btrfs/zfs, provider conformance signal.SIGKILL, server command local_windows) are unrelated to the pin.
- CI first run pending.
