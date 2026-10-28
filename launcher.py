#!/usr/bin/env python3
"""
onx-manager — Development Environment Launcher
=============================================
Enterprise-grade launcher that prepares and starts the entire
development environment with a single command.

Usage:
    python launcher.py              Start backend + frontend + open browser
    python launcher.py --stop       Gracefully shut down
    python launcher.py --restart    Restart everything
    python launcher.py --status     Show running processes and ports
    python launcher.py --status --watch   Live monitoring (1s refresh)
    python launcher.py --logs       Show service logs
    python launcher.py --self-test  Verify all prerequisites
    python launcher.py --code       Also open VS Code in project root
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from threading import Lock, Thread
from typing import Any

if os.name == "posix":
    try:
        import fcntl
        for _fd_str in os.listdir("/proc/self/fd"):
            try:
                _fd = int(_fd_str)
                if _fd > 2:
                    _flags = fcntl.fcntl(_fd, fcntl.F_GETFD)
                    fcntl.fcntl(_fd, fcntl.F_SETFD, _flags | fcntl.FD_CLOEXEC)
            except (ValueError, OSError):
                pass
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════
# Platform & Stream Initialization (UTF-8 encoding / Windows console)
# ═══════════════════════════════════════════════════════════════════════

if os.name == "nt":
    # Enable UTF-8 code page (65001) for Windows console
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        os.system("color")
    except Exception:
        pass

# Reconfigure stdout and stderr streams to UTF-8 with safe error replacement
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

PROJECT_NAME = "onx-manager"
PROJECT_VERSION = "0.1.0"
ONX_DIR_NAME = ".onx"
MCS_DIR_NAME = ONX_DIR_NAME  # alias for backward compat
BACKEND_PORT = 8000
FRONTEND_PORT = 5173
PORT_SCAN_SPAN = 100
MAX_PORT_ATTEMPTS = 3


def backend_health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/health"


BACKEND_HEALTH_URL = backend_health_url(BACKEND_PORT)
SWAGGER_URL = f"http://localhost:{BACKEND_PORT}/docs"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"
POLL_INTERVAL = 0.5
STARTUP_TIMEOUT = 120
MAX_LOG_LINES = 1000
WATCH_REFRESH = 1.0


COLORS: dict[str, str] = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "italic": "\033[3m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
    "white": "\033[97m",
    "bg_red": "\033[101m",
    "bg_green": "\033[102m",
    "bg_yellow": "\033[103m",
    "bg_blue": "\033[104m",
    "bg_magenta": "\033[105m",
    "bg_cyan": "\033[106m",
}


def c(code: str, text: str) -> str:
    return f"{COLORS.get(code, '')}{text}{COLORS['reset']}"


# ═══════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class SystemResources:
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float


@dataclass
class ServiceInfo:
    name: str
    pid: int | None = None
    running: bool = False
    port_open: bool = False
    port: int = 0
    uptime: float | None = None
    resources: SystemResources | None = None


@dataclass
class SelfTestResult:
    check: str
    status: bool
    detail: str = ""

    def colored_status(self) -> str:
        return c("green", "✓") if self.status else c("red", "✖")


class PortState(Enum):
    FREE = auto()
    OWN_HEALTHY = auto()
    OWN_UNHEALTHY = auto()
    HEALTHY_UNVERIFIED = auto()
    FOREIGN = auto()
    UNKNOWN = auto()


class ProvenanceStatus(Enum):
    VERIFIED = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class PortDecision:
    port: int
    reuse: bool
    source: str  # "known-active" | "preferred" | "scan"


@dataclass
class LauncherConfig:
    backend_port: int = BACKEND_PORT
    frontend_port: int = FRONTEND_PORT
    open_browser: bool = True
    open_swagger: bool = False
    open_vscode: bool = False
    auto_install_deps: bool = True
    startup_timeout: int = STARTUP_TIMEOUT
    active_backend_port: int | None = None
    configured_backend_port: int = BACKEND_PORT


# ═══════════════════════════════════════════════════════════════════════
# Paths
# ═══════════════════════════════════════════════════════════════════════


def detect_project_root() -> Path:
    candidates = [
        Path(sys.argv[0]).resolve().parent,
        Path.cwd().resolve(),
    ]
    visited: set[Path] = set()
    for start in candidates:
        current = start
        while current != current.parent:
            if current in visited:
                break
            visited.add(current)
            if (current / ".git").is_dir():
                return current
            if (current / "backend" / "pyproject.toml").is_file():
                return current
            if (current / "frontend" / "package.json").is_file():
                return current
            current = current.parent
    return Path.cwd().resolve()


PROJECT_ROOT = detect_project_root()
ONX_DIR = PROJECT_ROOT / ONX_DIR_NAME
MCS_DIR = ONX_DIR  # alias for backward compat
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
VENV_DIR = BACKEND_DIR / ".venv"
LOGS_DIR = ONX_DIR / "logs"
BACKEND_LOG = LOGS_DIR / "backend.log"
FRONTEND_LOG = LOGS_DIR / "frontend.log"


# ═══════════════════════════════════════════════════════════════════════
# Terminal output utilities & Unicode resilience
# ═══════════════════════════════════════════════════════════════════════

_ansi_enabled = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False


def ansi(text: str) -> str:
    return text if _ansi_enabled else ""


def detect_unicode_support() -> bool:
    """Detect whether stdout console reliably renders Unicode box and symbol glyphs."""
    # 1. Explicit user override
    if os.environ.get("ONX_FORCE_ASCII", "").lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("ONX_FORCE_UNICODE", "").lower() in ("1", "true", "yes"):
        return True

    # 2. Modern terminal emulators (Windows Terminal, VS Code, JetBrains, ConEmu, Mintty, WezTerm)
    if any(k in os.environ for k in ("WT_SESSION", "TERM_PROGRAM", "ConEmuPID", "WEZTERM_PANE")):
        return True

    # 3. Unix / POSIX terminal
    if os.name != "nt":
        encoding = getattr(sys.stdout, "encoding", "") or ""
        return "utf" in encoding.lower()

    # 4. Windows: check UTF-8 code page (65001) AND Virtual Terminal Processing support
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        cp = kernel32.GetConsoleOutputCP()
        if cp != 65001:
            return False

        h_out = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_out, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            return bool(mode.value & 0x0004)
    except Exception:
        pass

    return False


_unicode_enabled = detect_unicode_support()

SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if _unicode_enabled else "|/-\\"

_GLYPH_FALLBACKS: dict[str, str] = {
    "✔": "[OK]",
    "✓": "[OK]",
    "✖": "[X]",
    "⚠": "[!]",
    "ℹ": "[i]",
    "▸": ">",
    "—": "-",
    "–": "-",
    "━": "=",
    "─": "-",
    "═": "=",
    "●": "*",
    "○": "o",
    "█": "#",
    "╗": "+",
    "╔": "+",
    "╝": "+",
    "╚": "+",
    "║": "|",
    "⠋": "*",
    "⠙": "*",
    "⠹": "*",
    "⠸": "*",
    "⠼": "*",
    "⠴": "*",
    "⠦": "*",
    "⠧": "*",
    "⠇": "*",
    "⠏": "*",
}

_GLYPH_TRANS_TABLE = str.maketrans(_GLYPH_FALLBACKS)
_builtin_print = print


def _format_for_terminal(text: str) -> str:
    """If Unicode rendering is not reliably supported, transliterate to clean ASCII."""
    if not _unicode_enabled:
        text = text.translate(_GLYPH_TRANS_TABLE)
    return text


def _safe_encode_text(text: str, encoding: str) -> str:
    """Attempt direct encoding; on failure, transliterate known unicode symbols to ASCII and encode."""
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        transliterated = text.translate(_GLYPH_TRANS_TABLE)
        try:
            return transliterated.encode(encoding, errors="replace").decode(
                encoding, errors="replace"
            )
        except Exception:
            return transliterated.encode("ascii", errors="replace").decode("ascii")


def safe_print(*args: Any, **kwargs: Any) -> None:
    """Resilient print function that applies ASCII fallback and handles encoding errors."""
    processed_args = []
    for arg in args:
        s = str(arg) if not isinstance(arg, str) else arg
        s = _format_for_terminal(s)
        processed_args.append(s)

    try:
        _builtin_print(*processed_args, **kwargs)
    except UnicodeEncodeError:
        file = kwargs.get("file") or sys.stdout
        encoding = getattr(file, "encoding", None) or "ascii"
        safe_args = [_safe_encode_text(a, encoding) for a in processed_args]
        try:
            _builtin_print(*safe_args, **kwargs)
        except Exception:
            try:
                ascii_args = [
                    a.translate(_GLYPH_TRANS_TABLE).encode("ascii", errors="replace").decode("ascii")
                    for a in processed_args
                ]
                _builtin_print(*ascii_args, **kwargs)
            except Exception:
                pass


def safe_write(stream: Any, text: str) -> None:
    """Safe stream write that applies ASCII fallback and handles encoding errors."""
    text = _format_for_terminal(text)
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        try:
            safe_text = _safe_encode_text(text, encoding)
            stream.write(safe_text)
        except Exception:
            try:
                ascii_text = (
                    str(text)
                    .translate(_GLYPH_TRANS_TABLE)
                    .encode("ascii", errors="replace")
                    .decode("ascii")
                )
                stream.write(ascii_text)
            except Exception:
                pass
    except Exception:
        pass


# Globally guard print across launcher module
print = safe_print


class Spinner:
    def __init__(self, message: str = "") -> None:
        self._message = message
        self._running = False
        self._thread: Thread | None = None

    def start(self) -> None:
        if not _ansi_enabled:
            safe_print(f"{self._message}...")
            return
        self._running = True
        self._thread = Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        i = 0
        while self._running:
            char = SPINNER_CHARS[i % len(SPINNER_CHARS)]
            safe_write(sys.stdout, f"\r{c('cyan', char)} {self._message}...")
            try:
                sys.stdout.flush()
            except Exception:
                pass
            time.sleep(0.1)
            i += 1
        safe_write(sys.stdout, "\r" + " " * 80 + "\r")
        try:
            sys.stdout.flush()
        except Exception:
            pass

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  {c('dim', ts)} {msg}")


def log_ok(msg: str) -> None:
    log(f"{c('green', '✔')} {msg}")


def log_info(msg: str) -> None:
    log(f"{c('blue', 'ℹ')} {msg}")


def log_warn(msg: str) -> None:
    log(f"{c('yellow', '⚠')} {msg}")


def log_error(msg: str) -> None:
    log(f"{c('red', '✖')} {msg}")


def log_step(step: str, msg: str) -> None:
    log(f"  {c('bold', '▸')} {c('cyan', step)} {c('dim', '—')} {msg}")


def log_bold(msg: str) -> None:
    print(f"  {c('bold', msg)}")


def ask_yes_no(question: str, default: bool = False) -> bool:
    suffix = c("dim", "[Y/n]") if default else c("dim", "[y/N]")
    while True:
        try:
            answer = input(f"  {c('yellow', '?')} {question} {suffix} ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            if answer == "":
                return default
        except (EOFError, KeyboardInterrupt):
            return False


# ═══════════════════════════════════════════════════════════════════════
# Render utilities
# ═══════════════════════════════════════════════════════════════════════


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


def render_line(char: str = "═", width: int = 52) -> str:
    if not _unicode_enabled:
        if char == "═":
            char = "="
        elif char == "─":
            char = "-"
    return char * width


def print_banner() -> None:
    if _unicode_enabled:
        banner = r"""
 ██████╗ ███╗   ██╗██╗  ██╗
██╔═══██╗████╗  ██║╚██╗██╔╝
██║   ██║██╔██╗ ██║ ╚███╔╝ 
██║   ██║██║╚██╗██║ ██╔██╗ 
╚██████╔╝██║ ╚████║██╔╝ ██╗
 ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝
"""
    else:
        banner = r"""
   ____  _   ___  __
  / __ \/ | / / |/ /
 / / / /  |/ /|   / 
/ /_/ / /|  //   |  
\____/_/ |_//_/|_|  
"""
    if _ansi_enabled:
        banner = c("cyan", banner)
    print()
    print(banner)
    print(f"  {c('bold', f'{PROJECT_NAME} v{PROJECT_VERSION}')}")
    print(f"  {c('dim', 'Development Environment Launcher')}")
    print()


def print_usage() -> None:
    print(f"  {c('bold', f'{PROJECT_NAME} — Development Launcher')}")
    print()
    print(f"  {c('cyan', 'Usage')}:")
    print(f"    python launcher.py              {c('dim', 'Start dev environment')}")
    print(f"    python launcher.py --stop       {c('dim', 'Stop all processes')}")
    print(f"    python launcher.py --restart    {c('dim', 'Restart everything')}")
    print(f"    python launcher.py --status     {c('dim', 'Show status')}")
    print(f"    python launcher.py --status --watch{c('dim', '  Live monitoring')}")
    print(f"    python launcher.py --logs       {c('dim', 'Show service logs')}")
    print(f"    python launcher.py --self-test  {c('dim', 'Verify prerequisites')}")
    print(f"    python launcher.py --install-node{c('dim', ' Install Node.js 20 LTS (Win)')}")
    print(f"    python launcher.py --install-cpp{c('dim', '  Install C++ Build Tools (Win)')}")
    print(f"    python launcher.py --code       {c('dim', 'Also open VS Code')}")
    print(f"    python launcher.py --swagger    {c('dim', 'Also open Swagger API docs')}")
    print(f"    python launcher.py --help       {c('dim', 'Show this help')}")
    print()


# ═══════════════════════════════════════════════════════════════════════
# ConfigManager
# ═══════════════════════════════════════════════════════════════════════


def _parse_preferred_port(raw_val: Any) -> int | None:
    if isinstance(raw_val, bool) or not isinstance(raw_val, (int, str)):
        return None
    if isinstance(raw_val, str):
        cleaned = raw_val.strip()
        if not cleaned or not re.fullmatch(r"[+-]?[0-9]+", cleaned):
            return None
    try:
        val = int(raw_val)
    except (ValueError, TypeError):
        return None
    if 1024 <= val <= 65535:
        return val
    return None


def _validate_preferred_port(source: str, raw_val: Any) -> int | None:
    port = _parse_preferred_port(raw_val)
    if port is None:
        log_warn(f"Invalid {source}={raw_val!r}; must be an integer between 1024 and 65535.")
        return None
    return port


def _get_active_env_override() -> tuple[str, int] | None:
    if "ONX_BACKEND_PORT" in os.environ:
        p = _parse_preferred_port(os.environ["ONX_BACKEND_PORT"])
        if p is not None:
            return ("ONX_BACKEND_PORT", p)
    if "MCS_BACKEND_PORT" in os.environ:
        p = _parse_preferred_port(os.environ["MCS_BACKEND_PORT"])
        if p is not None:
            return ("MCS_BACKEND_PORT", p)
    return None


class ConfigManager:
    _instance: ConfigManager | None = None

    def __init__(self) -> None:
        self._config: LauncherConfig | None = None

    @classmethod
    def instance(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # The effective port is snapshotted at first load (memoized in _config)
    # and does not track later os.environ changes.
    def load(self) -> LauncherConfig:
        if self._config is not None:
            return self._config
        cfg_path = MCS_DIR / "config.json"
        raw: dict[str, Any] = {}
        if cfg_path.is_file():
            try:
                raw = json.loads(cfg_path.read_text())
            except Exception:
                raw = {}

        if "backend_port" in raw:
            validated = _validate_preferred_port("config backend_port", raw["backend_port"])
            configured_port = validated if validated is not None else BACKEND_PORT
        else:
            configured_port = BACKEND_PORT

        effective_port: int | None = None
        if "ONX_BACKEND_PORT" in os.environ:
            effective_port = _validate_preferred_port(
                "ONX_BACKEND_PORT", os.environ["ONX_BACKEND_PORT"]
            )
        if effective_port is None and "MCS_BACKEND_PORT" in os.environ:
            effective_port = _validate_preferred_port(
                "MCS_BACKEND_PORT", os.environ["MCS_BACKEND_PORT"]
            )
        if effective_port is None:
            effective_port = configured_port

        self._config = LauncherConfig(
            backend_port=effective_port,
            frontend_port=raw.get("frontend_port", FRONTEND_PORT),
            open_browser=raw.get("open_browser", True),
            open_swagger=raw.get("open_swagger", False),
            open_vscode=raw.get("open_vscode", False),
            auto_install_deps=raw.get("auto_install_deps", True),
            startup_timeout=raw.get("startup_timeout", STARTUP_TIMEOUT),
            configured_backend_port=configured_port,
        )
        return self._config

    def save(self) -> None:
        cfg = self.load()
        MCS_DIR.mkdir(parents=True, exist_ok=True)
        (MCS_DIR / "config.json").write_text(json.dumps({
            "backend_port": cfg.configured_backend_port,
            "frontend_port": cfg.frontend_port,
            "open_browser": cfg.open_browser,
            "open_swagger": cfg.open_swagger,
            "open_vscode": cfg.open_vscode,
            "auto_install_deps": cfg.auto_install_deps,
            "startup_timeout": cfg.startup_timeout,
        }, indent=2))

    def update(self, **kwargs: Any) -> None:
        cfg = self.load()
        env_override = _get_active_env_override()
        for key, value in kwargs.items():
            if key == "backend_port":
                cfg.configured_backend_port = value
                if env_override is not None:
                    env_var, env_port = env_override
                    log_warn(
                        f"Active environment override {env_var}={env_port} takes precedence over {key}={value}; "
                        f"configured_backend_port updated, effective backend_port unchanged."
                    )
                else:
                    cfg.backend_port = value
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
        self._config = cfg


# ═══════════════════════════════════════════════════════════════════════
# PIDManager
# ═══════════════════════════════════════════════════════════════════════


class PIDManager:
    @staticmethod
    def mcs_path(name: str) -> Path:
        return MCS_DIR / name

    @staticmethod
    def write(name: str, pid: int) -> None:
        MCS_DIR.mkdir(parents=True, exist_ok=True)
        PIDManager.mcs_path(f"{name}.pid").write_text(str(pid))

    @staticmethod
    def read(name: str) -> int | None:
        path = PIDManager.mcs_path(f"{name}.pid")
        if not path.is_file():
            return None
        try:
            return int(path.read_text().strip())
        except (ValueError, OSError):
            return None

    @staticmethod
    def clear(name: str) -> None:
        path = PIDManager.mcs_path(f"{name}.pid")
        if path.is_file():
            path.unlink()

    @staticmethod
    def write_active_port(port: int) -> None:
        MCS_DIR.mkdir(parents=True, exist_ok=True)
        (MCS_DIR / "backend.port").write_text(f"{port}\n")

    @staticmethod
    def read_active_port() -> int | None:
        candidates = [
            MCS_DIR / "backend.port",
            PROJECT_ROOT / ".mcs" / "backend.port",
        ]
        for path in candidates:
            if path.is_file():
                try:
                    val = int(path.read_text().strip())
                    if 1 <= val <= 65535:
                        return val
                except (ValueError, OSError):
                    continue
        return None

    @staticmethod
    def clear_active_port() -> None:
        for path in (MCS_DIR / "backend.port", PROJECT_ROOT / ".mcs" / "backend.port"):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass

    @staticmethod
    def is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes

                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    return False
                try:
                    exit_code = wintypes.DWORD()
                    if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return False
                    return exit_code.value == 259  # STILL_ACTIVE
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
            else:
                os.kill(pid, 0)
                return True
        except (OSError, ImportError, Exception):
            return False

    @staticmethod
    def cleanup_stale() -> None:
        if not MCS_DIR.is_dir():
            return
        for f in MCS_DIR.glob("*.pid"):
            try:
                pid = int(f.read_text().strip())
                if not PIDManager.is_alive(pid):
                    f.unlink()
                    log(f"Cleaned stale PID file: {f.name}")
            except (ValueError, OSError):
                f.unlink()

    @staticmethod
    def _get_descendants(pid: int) -> list[int]:
        """Recursively collect all descendant PIDs via psutil with fallback to /proc."""
        try:
            import psutil

            proc = psutil.Process(pid)
            return [child.pid for child in proc.children(recursive=True)]
        except Exception:
            pass

        descendants: list[int] = []
        try:
            task_dir = Path(f"/proc/{pid}/task")
            if not task_dir.is_dir():
                return descendants
            for tid_entry in task_dir.iterdir():
                children_path = task_dir / tid_entry.name / "children"
                if children_path.is_file():
                    raw = children_path.read_text().strip()
                    if raw:
                        for child_pid_str in raw.split():
                            try:
                                child_pid = int(child_pid_str)
                                descendants.append(child_pid)
                                descendants.extend(PIDManager._get_descendants(child_pid))
                            except ValueError:
                                continue
        except (OSError, PermissionError):
            pass
        return descendants

    @staticmethod
    def kill_tree(pid: int) -> None:
        try:
            if os.name == "nt":
                # Residual risk: taskkill /F /T cannot mirror "no SIGKILL escalation" (D-10)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
            else:
                children = PIDManager._get_descendants(pid)
                for child_pid in reversed(children):
                    subprocess.run(
                        ["kill", "-TERM", str(child_pid)],
                        capture_output=True, timeout=5,
                    )
                subprocess.run(
                    ["kill", "-TERM", str(pid)],
                    capture_output=True, timeout=5,
                )
                time.sleep(1)
                if PIDManager.is_alive(pid):
                    subprocess.run(
                        ["kill", "-KILL", str(pid)],
                        capture_output=True, timeout=5,
                    )
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def save_started_at() -> None:
        MCS_DIR.mkdir(parents=True, exist_ok=True)
        PIDManager.mcs_path("started_at").write_text(str(time.time()))

    @staticmethod
    def get_started_at() -> float | None:
        path = PIDManager.mcs_path("started_at")
        if path.is_file():
            try:
                return float(path.read_text().strip())
            except (ValueError, OSError):
                return None
        return None

    @staticmethod
    def clear_started_at() -> None:
        path = PIDManager.mcs_path("started_at")
        if path.is_file():
            path.unlink()


def _clear_backend_pid_if(expected_pid: int | None) -> None:
    """Clear backend.pid only if its stored PID matches expected_pid.
    No-op if expected_pid is None.
    """
    if expected_pid is None:
        return
    current_pid = PIDManager.read("backend")
    if current_pid == expected_pid:
        PIDManager.clear("backend")


def _capture_process_create_time(pid: int) -> float | None:
    """Capture process create_time via psutil. Returns None on failure or if pid is invalid."""
    if pid <= 0:
        return None
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:
        return None


def _verify_process_identity(pid: int, expected_create_time: float | None) -> bool:
    """Verify target process create_time matches expected_create_time within 0.5s tolerance.

    Refuses (returns False) when expected_create_time is None (no proof, no kill; O-8).
    """
    if expected_create_time is None or pid <= 0:
        return False
    try:
        import psutil

        proc = psutil.Process(pid)
        current = proc.create_time()
        if abs(current - expected_create_time) > 0.5:
            log_warn(
                f"Process create_time mismatch for pid={pid} "
                f"(expected {expected_create_time}, got {current}) — skipping kill"
            )
            return False
        return True
    except Exception as exc:
        log_warn(f"Could not verify process identity for pid={pid}: {exc} — skipping kill")
        return False


# ═══════════════════════════════════════════════════════════════════════
# PortManager
# ═══════════════════════════════════════════════════════════════════════


class PortManager:
    @staticmethod
    def is_open(port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
        if host == "127.0.0.1":
            try:
                with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    return s.connect_ex(("::1", port)) == 0
            except OSError:
                pass
        return False

    @staticmethod
    def can_bind(port: int, host: str = "0.0.0.0") -> bool:
        if not (1 <= port <= 65535):
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if os.name == "posix":
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return True
        except (OSError, ValueError, OverflowError):
            return False

    @staticmethod
    def find_free(start: int = 8000, end: int = 9000) -> int:
        for port in range(start, end):
            if not PortManager.is_open(port):
                return port
        return start + 1000

    @staticmethod
    def get_pid_by_port(port: int) -> int | None:
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["netstat", "-ano", "-p", "TCP"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 5 and f":{port}" in parts[1]:
                        pid_str = parts[4]
                        if pid_str.isdigit():
                            return int(pid_str)
            else:
                result = subprocess.run(
                    ["ss", "-tlnp"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if f":{port}" in line and "pid=" in line:
                        match = re.search(r"pid=(\d+)", line)
                        if match:
                            return int(match.group(1))
                result = subprocess.run(
                    ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip():
                    pid_str = result.stdout.strip().splitlines()[0]
                    if pid_str.isdigit():
                        return int(pid_str)
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

    @staticmethod
    def belongs_to_project(pid: int) -> bool:
        if pid <= 0:
            return False

        cmdline = ""
        cwd = ""
        exe = ""

        try:
            import psutil
            p = psutil.Process(pid)
            try:
                cmdline = " ".join(p.cmdline())
            except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                cmdline = ""
            try:
                cwd = p.cwd()
            except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                cwd = ""
            try:
                exe = p.exe()
            except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                exe = ""
        except Exception:
            pass

        if not cmdline and Path(f"/proc/{pid}/cmdline").is_file():
            try:
                raw = Path(f"/proc/{pid}/cmdline").read_bytes()
                cmdline = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
            except (OSError, PermissionError):
                pass

        if not cwd and Path(f"/proc/{pid}/cwd").is_symlink():
            try:
                cwd = str(Path(f"/proc/{pid}/cwd").resolve())
            except (OSError, PermissionError):
                pass

        if os.name == "nt" and not cmdline:
            try:
                ps_script = (
                    f"Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" | "
                    "Select-Object CommandLine, ExecutablePath | "
                    "ConvertTo-Json -Compress"
                )
                res = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    capture_output=True, text=True, timeout=5,
                )
                if res.stdout.strip():
                    data = json.loads(res.stdout.strip())
                    if isinstance(data, dict):
                        cmdline = str(data.get("CommandLine") or "")
                        exe = str(data.get("ExecutablePath") or "")
            except Exception:
                pass

        cmdline_lower = cmdline.lower()
        exe_lower = exe.lower()
        cwd_lower = cwd.lower()

        # 1. Daemon / exclusions first
        daemon_keywords = ("playit", "cloudflared", "tmux", "java")
        for kw in daemon_keywords:
            if kw in cmdline_lower or kw in exe_lower:
                return False

        # Exclusions for Minecraft server data directories
        server_data_str = str(PROJECT_ROOT / "backend" / "data" / "servers").lower()
        if server_data_str:
            if server_data_str in cwd_lower:
                return False
            if server_data_str in exe_lower:
                return False
            if server_data_str in cmdline_lower:
                return False

        # 2. Project root path in cwd, exe, or cmdline
        project_root_str = str(PROJECT_ROOT).lower()
        if project_root_str:
            if cwd_lower.startswith(project_root_str):
                return True
            if project_root_str in exe_lower:
                return True
            if project_root_str in cmdline_lower:
                return True

        # 3. Unique project identifiers
        project_markers = ("onx-frontend", "mcs-frontend", "onx-manager", "mcs-manager", "app.main:app")
        for marker in project_markers:
            if marker in cmdline_lower:
                return True

        return False

    @staticmethod
    def classify_backend_port(port: int, health_timeout: float = 2.0) -> PortState:
        if PortManager.can_bind(port):
            return PortState.FREE

        listener_pid = PortManager.get_pid_by_port(port)
        is_healthy = check_backend_health(port, timeout=health_timeout)

        if listener_pid is not None:
            if PortManager.belongs_to_project(listener_pid):
                return PortState.OWN_HEALTHY if is_healthy else PortState.OWN_UNHEALTHY
            else:
                return PortState.FOREIGN
        else:
            return PortState.HEALTHY_UNVERIFIED if is_healthy else PortState.UNKNOWN

    @staticmethod
    def resolve_startup_port(
        preferred: int,
        known_active: int | None,
        on_own_unhealthy: Callable[[int], bool],
        exclude_ports: set[int] | None = None,
    ) -> PortDecision | None:
        excluded = exclude_ports or set()

        # 0. Known active port
        if known_active is not None and known_active not in excluded:
            active_state = PortManager.classify_backend_port(known_active, health_timeout=2.0)
            if active_state in (PortState.OWN_HEALTHY, PortState.HEALTHY_UNVERIFIED):
                return PortDecision(port=known_active, reuse=True, source="known-active")
            elif active_state == PortState.OWN_UNHEALTHY:
                freed = on_own_unhealthy(known_active)
                if freed:
                    PIDManager.clear_active_port()
                else:
                    return None
            else:
                PIDManager.clear_active_port()

        # 1. Preferred port
        if preferred in excluded:
            pref_state = None
        else:
            pref_state = PortManager.classify_backend_port(preferred, health_timeout=2.0)
        if pref_state == PortState.FREE:
            return PortDecision(port=preferred, reuse=False, source="preferred")
        elif pref_state in (PortState.OWN_HEALTHY, PortState.HEALTHY_UNVERIFIED):
            return PortDecision(port=preferred, reuse=True, source="preferred")
        elif pref_state == PortState.OWN_UNHEALTHY:
            freed = on_own_unhealthy(preferred)
            if not freed:
                return None
            post_state = PortManager.classify_backend_port(preferred, health_timeout=2.0)
            if post_state == PortState.FREE:
                return PortDecision(port=preferred, reuse=False, source="preferred")
            return None

        # 2. Fallback scan
        for candidate in range(preferred + 1, preferred + PORT_SCAN_SPAN):
            if not (1024 <= candidate <= 65535) or candidate in excluded:
                continue
            cand_state = PortManager.classify_backend_port(candidate, health_timeout=1.0)
            if cand_state == PortState.FREE:
                return PortDecision(port=candidate, reuse=False, source="scan")
            elif cand_state in (PortState.OWN_HEALTHY, PortState.HEALTHY_UNVERIFIED):
                return PortDecision(port=candidate, reuse=True, source="scan")
            elif cand_state == PortState.OWN_UNHEALTHY:
                freed = on_own_unhealthy(candidate)
                if not freed:
                    return None
                post_state = PortManager.classify_backend_port(candidate, health_timeout=1.0)
                if post_state == PortState.FREE:
                    return PortDecision(port=candidate, reuse=False, source="scan")
                return None
            elif cand_state in (PortState.FOREIGN, PortState.UNKNOWN):
                continue

        # 3. Exhaustion
        PIDManager.clear_active_port()
        return None

    @staticmethod
    def kill_on_port(
        port: int,
        expected_pid: int | None = None,
        expected_create_time: float | None = None,
    ) -> bool:
        """Kill process on given port. Caller should have already prompted."""
        pid = PortManager.get_pid_by_port(port)
        if expected_pid is not None:
            if pid != expected_pid:
                log_warn(
                    f"Listener on port {port} (PID {pid}) does not match "
                    f"expected PID {expected_pid} — skipping kill"
                )
                return False
        if expected_create_time is not None:
            target_pid = expected_pid if expected_pid is not None else pid
            if not target_pid or not _verify_process_identity(target_pid, expected_create_time):
                log_warn(
                    f"Process identity verification failed for PID {target_pid} "
                    f"on port {port} — skipping kill"
                )
                return False
        if pid and PIDManager.is_alive(pid):
            PIDManager.kill_tree(pid)
            time.sleep(1)
            if PortManager.is_open(port):
                log_error(f"Failed to free port {port}")
                return False
            log_ok(f"Freed port {port}")
            return True
        return True


# ═══════════════════════════════════════════════════════════════════════
# Git helpers
# ═══════════════════════════════════════════════════════════════════════


def get_git_branch() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT),
        )
        branch = result.stdout.strip()
        return branch if branch and branch != "HEAD" else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def get_git_commit_short() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT),
        )
        commit = result.stdout.strip()
        return commit if commit else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# SystemMonitor
# ═══════════════════════════════════════════════════════════════════════


class SystemMonitor:
    """Collects system resource usage (CPU, RAM) for live monitoring."""

    @staticmethod
    def collect() -> SystemResources | None:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.3)
            mem = psutil.virtual_memory()
            return SystemResources(
                cpu_percent=cpu,
                memory_percent=mem.percent,
                memory_used_mb=mem.used / (1024 * 1024),
                memory_total_mb=mem.total / (1024 * 1024),
            )
        except ImportError:
            try:
                cpu = SystemMonitor._cpu_from_proc()
                mem = SystemMonitor._mem_from_proc()
                if mem is not None:
                    return SystemResources(
                        cpu_percent=cpu,
                        memory_percent=mem.percent,
                        memory_used_mb=mem.used,
                        memory_total_mb=mem.total,
                    )
            except Exception:
                pass
        return None

    @staticmethod
    def _cpu_from_proc() -> float:
        try:
            proc_stat = Path("/proc/stat")
            if not proc_stat.is_file():
                return 0.0
            with proc_stat.open() as f:
                line = f.readline()
            parts = line.split()
            if not parts or parts[0] != "cpu":
                return 0.0
            values = [int(v) for v in parts[1:]]
            total = sum(values)
            idle = values[3]
            return 100.0 * (1.0 - idle / total) if total > 0 else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _mem_from_proc() -> object | None:
        try:
            meminfo = Path("/proc/meminfo")
            if not meminfo.is_file():
                return None
            total = 0
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
            if total > 0:
                used_kb = total - available
                from types import SimpleNamespace
                return SimpleNamespace(
                    percent=100.0 * used_kb / total,
                    used=used_kb / 1024,
                    total=total / 1024,
                )
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════════════
# TerminalOpener
# ═══════════════════════════════════════════════════════════════════════


class WindowGeometry:
    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


# Each monitor half at 1920×1080: 960×540 per terminal
WINDOW_BACKEND = WindowGeometry(0, 0, 960, 540)
WINDOW_FRONTEND = WindowGeometry(960, 0, 960, 540)


class TerminalOpener:
    """Opens a service in its own terminal window with log capture."""

    TERMINAL_PREFERENCE: list[tuple[str, list[str]]] = [
        ("gnome-terminal", ["--", "bash", "-c"]),
        ("konsole", ["--separate", "--hold", "-e", "bash", "-c"]),
        ("xfce4-terminal", ["-e", "bash", "-c"]),
        ("xterm", ["-e", "bash", "-c"]),
    ]

    @staticmethod
    def _wrap_command(cmd_str: str, log_file: Path) -> str:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            return cmd_str
        return f"{cmd_str} 2>&1 | tee -a '{log_file}'; exec bash"

    @staticmethod
    def _find_terminal() -> tuple[str, list[str]] | None:
        for term, args in TerminalOpener.TERMINAL_PREFERENCE:
            if shutil.which(term) is not None:
                return (term, args)
        return None

    @staticmethod
    def _find_kdotool() -> Path | None:
        candidates = [
            Path.home() / ".local" / "bin" / "kdotool",
            Path("/usr") / "bin" / "kdotool",
            Path("/usr") / "local" / "bin" / "kdotool",
            Path(MCS_DIR) / "bin" / "kdotool",
        ]
        for c in candidates:
            if c.is_file() and os.access(c, os.X_OK):
                return c
        return None

    @staticmethod
    def _list_konsole_windows(kdotool: Path) -> set[str]:
        try:
            result = subprocess.run(
                [str(kdotool), "search", "--classname", "--limit", "20", "konsole"],
                capture_output=True, text=True, timeout=5,
            )
            ids = set()
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and "{" in line:
                    ids.add(line)
            return ids
        except subprocess.TimeoutExpired:
            return set()

    @staticmethod
    def _position_new_window(
        kdotool: Path, before: set[str], geo: WindowGeometry,
    ) -> bool:
        time.sleep(2)
        after = TerminalOpener._list_konsole_windows(kdotool)
        new_windows = after - before
        if len(new_windows) != 1:
            return False
        win_id = next(iter(new_windows))
        try:
            subprocess.run(
                [str(kdotool), "windowmove", win_id, str(geo.x), str(geo.y)],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                [str(kdotool), "windowsize", win_id, str(geo.width), str(geo.height)],
                capture_output=True, timeout=5,
            )
            return True
        except subprocess.TimeoutExpired:
            return False

    @staticmethod
    def _build_cmd(service_title: str, wrapped: str, geo: WindowGeometry | None) -> list[str]:
        terminal = TerminalOpener._find_terminal()
        if terminal is None:
            return []
        term_exe, term_args = terminal
        return [term_exe] + term_args + [wrapped]

    @staticmethod
    def escape_cmd_path(path: str | Path) -> str:
        """Escape and sanitize a filesystem path for insertion inside double quotes in a Windows cmd.exe command."""
        # 1. Remove any double quotes to prevent quote-injection or quote breakout
        s = str(path).replace('"', "")
        # 2. Strip trailing backslashes to avoid escaping the closing quote in C/C++ argv parsers (CommandLineToArgvW)
        return s.rstrip("\\")

    @staticmethod
    def open_backend(
        python: Path,
        port: int,
        env: dict[str, str] | None = None,
    ) -> int | None:
        if os.name == "nt":
            esc_backend = TerminalOpener.escape_cmd_path(BACKEND_DIR)
            esc_python = TerminalOpener.escape_cmd_path(python)
            cmd_str = (
                f'cd /d "{esc_backend}" && "{esc_python}" -m uvicorn app.main:app '
                f"--host 0.0.0.0 --port {port} --reload --reload-dir app"
            )
        else:
            cmd_str = (
                f"cd '{BACKEND_DIR}' && "
                f"PYTHONPATH='{BACKEND_DIR}' "
                f"{python} -m uvicorn app.main:app "
                f"--host 0.0.0.0 --port {port} --reload --reload-dir app"
            )
        return TerminalOpener._open("Backend", cmd_str, BACKEND_LOG, env, WINDOW_BACKEND)

    @staticmethod
    def open_frontend(backend_port: int) -> int | None:
        if os.name == "nt":
            esc_frontend = TerminalOpener.escape_cmd_path(FRONTEND_DIR)
            cmd_str = f'cd /d "{esc_frontend}" && npm run dev'
        else:
            cmd_str = f"cd '{FRONTEND_DIR}' && npm run dev"
        return TerminalOpener._open(
            "Frontend",
            cmd_str,
            FRONTEND_LOG,
            {"ONX_BACKEND_PORT": str(backend_port)},
            WINDOW_FRONTEND,
        )

    @staticmethod
    def _open(
        service_title: str,
        cmd_str: str,
        log_file: Path,
        extra_env: dict[str, str] | None = None,
        geometry: WindowGeometry | None = None,
    ) -> int | None:
        wrapped = TerminalOpener._wrap_command(cmd_str, log_file)
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        full_cmd = TerminalOpener._build_cmd(service_title, wrapped, geometry)
        if full_cmd:
            try:
                proc = subprocess.Popen(
                    full_cmd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                if geometry:
                    kd_path = TerminalOpener._find_kdotool()
                    if kd_path:
                        before_wins = TerminalOpener._list_konsole_windows(kd_path)
                        threading.Thread(
                            target=TerminalOpener._position_new_window,
                            args=(kd_path, before_wins, geometry),
                            daemon=True,
                        ).start()
                return proc.pid
            except OSError:
                pass

        try:
            log_fh = os.open(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            popen_kwargs: dict[str, Any] = {
                "env": env,
                "stdout": log_fh,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
                "close_fds": True,
            }
            if os.name != "nt":
                popen_kwargs["pass_fds"] = (log_fh,)
                popen_cmd: list[str] | str = ["bash", "-c", cmd_str]
            else:
                popen_cmd = f'cmd.exe /s /c "{cmd_str}"'

            proc = subprocess.Popen(
                popen_cmd,
                **popen_kwargs,
            )
            os.close(log_fh)
            return proc.pid
        except OSError:
            return None


# ═══════════════════════════════════════════════════════════════════════
# LogManager
# ═══════════════════════════════════════════════════════════════════════


class LogManager:
    """Manages log file I/O for service logs."""

    @staticmethod
    def tail(path: Path, n: int = 50) -> list[str]:
        if not path.is_file():
            return []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.rstrip("\n").split("\n")
            return lines[-n:]
        except OSError:
            return []

    @staticmethod
    def follow(path: Path, stop_event: threading.Event | None = None) -> None:
        """Tail -f style log following."""
        if not path.is_file():
            log_error(f"Log file not found: {path}")
            return
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                while stop_event is None or not stop_event.is_set():
                    line = f.readline()
                    if line:
                        ts = datetime.now().strftime("%H:%M:%S")
                        print(f"  {c('dim', ts)} {line.rstrip()}")
                    else:
                        time.sleep(0.2)
        except KeyboardInterrupt:
            pass



# ═══════════════════════════════════════════════════════════════════════
# Background ProcessManager (kept for backward compat and fallback)
# ═══════════════════════════════════════════════════════════════════════


class LogCollector(Thread):
    def __init__(self, name: str, stream) -> None:
        super().__init__(daemon=True)
        self.name = name
        self._stream = stream
        self.buffer: list[str] = []
        self._lock = Lock()
        self.start()

    def run(self) -> None:
        for raw in iter(self._stream.readline, b""):
            decoded = raw.decode("utf-8", errors="replace").rstrip()
            with self._lock:
                self.buffer.append(decoded)
                if len(self.buffer) > MAX_LOG_LINES:
                    self.buffer = self.buffer[-MAX_LOG_LINES:]

    def drain(self) -> list[str]:
        with self._lock:
            lines = list(self.buffer)
            self.buffer.clear()
        return lines


class ProcessManager:
    def __init__(
        self, name: str, cmd: list[str], cwd: str | Path,
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.cmd = cmd
        self.cwd = str(cwd)
        self.env = env
        self.process: subprocess.Popen | None = None
        self._log_collector: LogCollector | None = None

    def start(self) -> None:
        env = os.environ.copy()
        if self.env:
            env.update(self.env)
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.process = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
        )
        PIDManager.write(self.name, self.process.pid)
        if self.process.stdout:
            self._log_collector = LogCollector(self.name, self.process.stdout)

    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def terminate(self) -> None:
        if self.process and self.is_running():
            PIDManager.kill_tree(self.process.pid)
            self.process.wait(timeout=10)
        PIDManager.clear(self.name)

    def drain_logs(self) -> list[str]:
        if self._log_collector is None:
            return []
        return self._log_collector.drain()

    def print_logs(self, prefix: str = "") -> None:
        for line in self.drain_logs():
            ts = datetime.now().strftime("%H:%M:%S")
            tag = prefix if prefix else c("dim", f"[{self.name}]")
            print(f"  {c('dim', ts)} {tag} {line}")


# ═══════════════════════════════════════════════════════════════════════
# Validator
# ═══════════════════════════════════════════════════════════════════════


class ValidationError(Exception):
    def __init__(self, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.fix = fix


def find_or_activate_node() -> None:
    """Ensure local portable or standard Node.js directory is in PATH."""
    node_candidates = [
        ONX_DIR / "node",
        ONX_DIR / "node" / "node-v20.18.0-win-x64",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs",
        Path("C:/Program Files/nodejs"),
        Path("C:/Program Files (x86)/nodejs"),
    ]
    for nd in node_candidates:
        if nd.is_dir() and ((nd / "node.exe").is_file() or (nd / "node").is_file()):
            nd_str = str(nd.resolve())
            current_path = os.environ.get("PATH", "")
            if nd_str not in current_path.split(os.pathsep):
                os.environ["PATH"] = f"{nd_str}{os.pathsep}{current_path}"


class Validator:
    """Validates the project environment is ready to run."""

    @staticmethod
    def check_python() -> tuple[str, str]:
        ver = platform.python_version()
        try:
            major, minor = (int(x) for x in ver.split(".")[:2])
            if major < 3 or (major == 3 and minor < 12):
                raise ValidationError(
                    f"Python {ver} is too old (need 3.12+)",
                    "Install Python 3.12+ from https://python.org",
                )
        except ValidationError:
            raise
        except Exception:
            pass
        python_path = find_backend_venv()
        if python_path is None:
            python_path = Path("python3" if os.name != "nt" else "python")
        return ver, str(python_path)

    @staticmethod
    def check_node(timeout_sec: float | None = None) -> str:
        find_or_activate_node()
        if timeout_sec is None:
            timeout_sec = 15.0 if os.name == "nt" else 10.0

        node_cmd = "node"
        if os.name == "nt":
            local_node = ONX_DIR / "node" / "node.exe"
            if local_node.is_file():
                node_cmd = str(local_node)
            else:
                which_node = shutil.which("node")
                if which_node:
                    node_cmd = which_node

        try:
            result = subprocess.run(
                [node_cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if result.returncode != 0:
                err_msg = (result.stderr or result.stdout or "").strip()
                raise ValidationError(
                    f"Node.js check failed (exit code {result.returncode}): {err_msg}",
                    "Install Node.js 18+ from https://nodejs.org",
                )
            ver = result.stdout.strip()
            try:
                v = int(ver.lstrip("v").split(".")[0])
                if v < 18:
                    raise ValidationError(
                        f"Node.js {ver} is too old (need 18+)",
                        "Install Node.js 18+ from https://nodejs.org",
                    )
            except (ValueError, IndexError):
                pass
            return ver
        except FileNotFoundError:
            raise ValidationError(
                "Node.js is not installed",
                "Install Node.js 18+ from https://nodejs.org",
            ) from None
        except subprocess.TimeoutExpired as exc:
            raise ValidationError(
                f"Node.js version probe timed out after {int(timeout_sec)} seconds",
                "Ensure Node.js is responsive on your system PATH",
            ) from exc
        except Exception as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(
                f"Failed to execute Node.js: {exc}",
                "Install Node.js 18+ from https://nodejs.org",
            ) from exc

    @staticmethod
    def check_npm(timeout_sec: float | None = None) -> str:
        find_or_activate_node()
        if timeout_sec is None:
            timeout_sec = 20.0 if os.name == "nt" else 10.0

        # Attempt to locate npm executable or cli script directly
        npm_cmd = "npm"
        if os.name == "nt":
            local_node = ONX_DIR / "node"
            local_npm = local_node / "npm.cmd"
            if local_npm.is_file():
                npm_cmd = str(local_npm)
            else:
                which_npm = shutil.which("npm")
                if which_npm:
                    npm_cmd = which_npm

        attempts = 2 if os.name == "nt" else 1
        last_timeout_exc: subprocess.TimeoutExpired | None = None

        for attempt in range(1, attempts + 1):
            try:
                result = subprocess.run(
                    [npm_cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    shell=(os.name == "nt" and npm_cmd == "npm"),
                )
                if result.returncode != 0:
                    err_msg = (result.stderr or result.stdout or "").strip()
                    raise ValidationError(
                        f"npm execution failed (exit code {result.returncode}): {err_msg}",
                        "npm should come with Node.js — verify your Node.js and npm installation",
                    )
                ver = result.stdout.strip()
                if not ver:
                    raise ValidationError(
                        "npm returned empty version string",
                        "npm installation may be corrupted — reinstall Node.js",
                    )
                return ver
            except FileNotFoundError:
                raise ValidationError(
                    "npm is not installed",
                    "npm should come with Node.js — reinstall Node.js or install npm",
                ) from None
            except subprocess.TimeoutExpired as exc:
                last_timeout_exc = exc
                if attempt < attempts:
                    time.sleep(0.5)
                    continue
            except PermissionError as exc:
                raise ValidationError(
                    f"Permission denied while executing npm: {exc}",
                    "Ensure you have permission to execute npm binary",
                ) from None
            except OSError as exc:
                raise ValidationError(
                    f"Failed to execute npm: {exc}",
                    "Check your system PATH and Node.js installation",
                ) from None

        raise ValidationError(
            f"npm version probe timed out after {int(timeout_sec)} seconds",
            (
                "npm may be slow due to cold disk cache or antivirus scan. "
                "Run 'npm --version' in terminal to test responsiveness"
            ),
        ) from last_timeout_exc

    @staticmethod
    def check_project_structure() -> None:
        if not BACKEND_DIR.is_dir():
            raise ValidationError(f"Backend directory not found: {BACKEND_DIR}")
        if not FRONTEND_DIR.is_dir():
            raise ValidationError(f"Frontend directory not found: {FRONTEND_DIR}")
        if not (BACKEND_DIR / "pyproject.toml").is_file():
            raise ValidationError(
                "Backend pyproject.toml not found",
                "Ensure the backend project is initialized",
            )
        if not (FRONTEND_DIR / "package.json").is_file():
            raise ValidationError(
                "Frontend package.json not found",
                "Ensure the frontend project is initialized",
            )
        if not (BACKEND_DIR / "app" / "main.py").is_file():
            raise ValidationError(
                f"Backend entry point not found: {BACKEND_DIR / 'app' / 'main.py'}",
            )

    @staticmethod
    def check_venv() -> Path:
        venv = find_backend_venv()
        if venv is None:
            raise ValidationError(
                "Virtual environment not found",
                f"Run: cd {BACKEND_DIR} && python3 -m venv .venv "
                f"&& .venv/bin/pip install -r requirements.txt",
            )
        return venv

    @staticmethod
    def check_git() -> str | None:
        branch = get_git_branch()
        if branch is None:
            raise ValidationError(
                "Not a git repository or no commits yet",
                "Run: git init && git add . && git commit -m 'initial'",
            )
        return branch

    @staticmethod
    def check_backend_deps(python: Path) -> bool:
        try:
            result = subprocess.run(
                [str(python), "-c", "import fastapi, uvicorn, sqlalchemy, pydantic"],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    @staticmethod
    def check_frontend_deps() -> bool:
        return (FRONTEND_DIR / "node_modules").is_dir()

    @staticmethod
    def check_ports(backend_port: int, frontend_port: int) -> list[str]:
        issues: list[str] = []
        if PortManager.is_open(backend_port):
            pid = PortManager.get_pid_by_port(backend_port)
            issues.append(f"Port {backend_port} in use by PID {pid or '?'}")
        if PortManager.is_open(frontend_port):
            pid = PortManager.get_pid_by_port(frontend_port)
            issues.append(f"Port {frontend_port} in use by PID {pid or '?'}")
        return issues


# ═══════════════════════════════════════════════════════════════════════
# SelfTester
# ═══════════════════════════════════════════════════════════════════════


class SelfTester:
    """Runs comprehensive self-test and prints a report."""

    @staticmethod
    def _check_backend_health(port: int) -> SelfTestResult:
        if _backend_is_serving(port):
            return SelfTestResult("Backend health", True, f"Running on {port}")
        return SelfTestResult("Backend health", False, "Not running")

    @staticmethod
    def run() -> list[SelfTestResult]:
        results: list[SelfTestResult] = []

        # Python
        try:
            ver, path = Validator.check_python()
            results.append(SelfTestResult("Python", True, f"{ver} ({path})"))
        except ValidationError as e:
            results.append(SelfTestResult("Python", False, str(e)))

        # Node
        try:
            ver = Validator.check_node()
            results.append(SelfTestResult("Node.js", True, ver))
        except ValidationError as e:
            results.append(SelfTestResult("Node.js", False, str(e)))

        # npm
        try:
            ver = Validator.check_npm()
            results.append(SelfTestResult("npm", True, ver))
        except ValidationError as e:
            results.append(SelfTestResult("npm", False, str(e)))

        # Project structure
        try:
            Validator.check_project_structure()
            results.append(SelfTestResult("Project structure", True))
        except ValidationError as e:
            results.append(SelfTestResult("Project structure", False, str(e)))

        # Git
        try:
            branch = Validator.check_git()
            results.append(SelfTestResult("Git repository", True, branch or "detached"))
        except ValidationError as e:
            results.append(SelfTestResult("Git repository", False, str(e)))

        # venv
        try:
            venv = Validator.check_venv()
            results.append(SelfTestResult("Virtual environment", True, str(venv)))
        except ValidationError as e:
            results.append(SelfTestResult("Virtual environment", False, str(e)))

        # Backend deps
        try:
            venv_path = find_backend_venv()
            if venv_path and Validator.check_backend_deps(venv_path):
                results.append(SelfTestResult("Backend dependencies", True))
            else:
                results.append(SelfTestResult("Backend dependencies", False, "Missing packages"))
        except Exception as e:
            results.append(SelfTestResult("Backend dependencies", False, str(e)))

        # Database schema
        try:
            venv_path = find_backend_venv()
            if venv_path:
                env = os.environ.copy()
                env["PYTHONPATH"] = str(BACKEND_DIR)
                proc = subprocess.run(
                    [str(venv_path), "-m", "app.core.persistence.reconciler", "--check-only", "--json"],
                    cwd=str(BACKEND_DIR),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                stdout = proc.stdout.strip()
                res = json.loads(stdout) if stdout else {}
                status = res.get("status", "FAILED")
                if status in ("READY", "RECONCILED"):
                    results.append(SelfTestResult("Database schema", True, f"Revision {res.get('target_revision', 'head')}"))
                elif status == "BLOCKED_UNSAFE":
                    results.append(SelfTestResult("Database schema", False, f"Blocked: {res.get('message', '')}"))
                else:
                    results.append(SelfTestResult("Database schema", False, res.get("message", "Needs migration")))
            else:
                results.append(SelfTestResult("Database schema", False, "Virtual environment not found"))
        except Exception as e:
            results.append(SelfTestResult("Database schema", False, str(e)))

        # Frontend deps
        if Validator.check_frontend_deps():
            results.append(SelfTestResult("Frontend dependencies", True))
        else:
            results.append(SelfTestResult("Frontend dependencies", False, "node_modules missing"))

        # Ports
        cfg = ConfigManager.instance().load()
        effective_backend_port = get_effective_backend_port(cfg.backend_port)
        port_issues = Validator.check_ports(effective_backend_port, cfg.frontend_port)
        if not port_issues:
            port_str = f"{effective_backend_port}, {cfg.frontend_port}"
            results.append(SelfTestResult("Ports available", True, port_str))
        else:
            results.append(SelfTestResult("Ports available", False, "; ".join(port_issues)))

        # Try to detect running services
        fe_pid = PIDManager.read("frontend")
        fe_alive = fe_pid is not None and PIDManager.is_alive(fe_pid)
        pa = PortManager.is_open

        results.append(SelfTester._check_backend_health(effective_backend_port))

        if fe_alive or pa(cfg.frontend_port):
            results.append(SelfTestResult("Frontend availability", True, "Running"))
        else:
            results.append(SelfTestResult("Frontend availability", False, "Not running"))

        # Terminal support
        if os.name == "nt":
            results.append(SelfTestResult("Terminal support", True, "cmd.exe"))
        else:
            term = TerminalOpener._find_terminal()
            if term:
                results.append(SelfTestResult("Terminal support", True, term[0]))
            else:
                err = "No terminal emulator found — will use background processes"
                results.append(SelfTestResult("Terminal support", False, err))

        # Browser
        results.append(SelfTestResult("Browser access", True, "webbrowser module available"))

        return results

    @staticmethod
    def print_report(results: list[SelfTestResult]) -> None:
        print()
        print(f"  {c('bold', '━━━ Self-Test Report ━━━')}")
        print()
        passed = sum(1 for r in results if r.status)
        total = len(results)
        for r in results:
            icon = r.colored_status()
            status_txt = c("green", "PASS") if r.status else c("red", "FAIL")
            detail = f"  {c('dim', r.detail)}" if r.detail else ""
            print(f"  {icon} {c('bold', r.check):30} {status_txt}{detail}")
        print()
        if passed == total:
            print(f"  {c('green', '✔')} {c('bold', f'All {total} checks passed')}")
        else:
            print(f"  {c('yellow', '⚠')} {c('bold', f'{passed}/{total} checks passed')}")
        print()


# ═══════════════════════════════════════════════════════════════════════
# LogViewer
# ═══════════════════════════════════════════════════════════════════════


class LogViewer:
    """Displays service logs with timestamps."""

    @staticmethod
    def show() -> None:
        print()
        print(f"  {c('bold', '━━━ Service Logs ━━━')}")
        print()

        for label, path in [("Backend", BACKEND_LOG), ("Frontend", FRONTEND_LOG)]:
            print(f"  {c('bold', f'── {label} ──')}")
            lines = LogManager.tail(path, n=50)
            if not lines:
                print(f"  {c('dim', '(no log entries)')}")
            else:
                for line in lines:
                    if line.strip():
                        ts = c("dim", datetime.now().strftime("%H:%M:%S"))
                        print(f"  {ts} {line}")
            print()


# ═══════════════════════════════════════════════════════════════════════
# StatusDisplay
# ═══════════════════════════════════════════════════════════════════════


class StatusDisplay:
    """Renders the status screen, optionally in live watch mode."""

    @staticmethod
    def _collect_service(name: str, port: int, *, verify_backend: bool = False) -> ServiceInfo:
        effective_port = get_effective_backend_port(port) if verify_backend else port
        pid = PIDManager.read(name)
        alive = pid is not None and PIDManager.is_alive(pid)
        port_open = PortManager.is_open(effective_port)
        uptime: float | None = None
        started = PIDManager.get_started_at()
        if started:
            uptime = time.time() - started

        if verify_backend:
            serving = _backend_is_serving(effective_port)
            actual_pid = PortManager.get_pid_by_port(effective_port) if serving else None
            return ServiceInfo(
                name=name.capitalize(),
                pid=actual_pid or (pid if serving else None),
                running=serving,
                port_open=port_open,
                port=effective_port,
                uptime=uptime,
            )

        actual_pid = PortManager.get_pid_by_port(effective_port) if port_open else pid
        return ServiceInfo(
            name=name.capitalize(),
            pid=actual_pid or pid,
            running=alive or port_open,
            port_open=port_open,
            port=effective_port,
            uptime=uptime,
        )

    @staticmethod
    def render(be: ServiceInfo, fe: ServiceInfo, resources: SystemResources | None = None) -> None:
        print()
        print(f"  {c('bold', '━━━ MC Server Manager ─ Status ━━━')}")
        print()

        for svc in (be, fe):
            if svc.running and svc.port_open:
                status = c("green", "● Running")
            elif svc.running or svc.pid is not None:
                status = c("yellow", "○ Partial")
            else:
                status = c("red", "○ Stopped")

            pid_txt = c("dim", f"PID {svc.pid}") if svc.pid else c("dim", "—")
            port_txt = c("dim", f":{svc.port}") if svc.port else ""
            print(f"     {c('bold', svc.name):12} {status}   {pid_txt} {port_txt}")

        print()
        started = PIDManager.get_started_at()
        if started:
            uptime = time.time() - started
            print(f"     {c('bold', 'Uptime')}: {c('white', format_duration(uptime))}")

        if resources is not None:
            cpu_str = f"{resources.cpu_percent:.1f}%"
            mem_used = f"{resources.memory_used_mb:.0f}"
            mem_total = f"{resources.memory_total_mb:.0f}"
            mem_str = f"{resources.memory_percent:.1f}% ({mem_used}/{mem_total} MB)"
            print(f"     {c('bold', 'CPU')}:    {c('white', cpu_str)}")
            print(f"     {c('bold', 'Memory')}: {c('white', mem_str)}")

        print(f"     {c('bold', 'Project')}: {c('white', str(PROJECT_ROOT))}")
        print(f"     {c('bold', 'Python')}: {c('white', platform.python_version())}")
        sys_name = c('white', platform.system())
        sys_ver = c('white', platform.release())
        print(f"     {c('bold', 'System')}: {sys_name} {sys_ver}")

        git_branch = get_git_branch()
        git_commit = get_git_commit_short()
        if git_branch:
            bt = c('white', git_branch)
            ct = c('white', git_commit or '?')
            print(f"     {c('bold', 'Git')}: {bt} @ {ct}")
        print()

    @staticmethod
    def show() -> None:
        cfg = ConfigManager.instance().load()
        backend_port = get_effective_backend_port(cfg.backend_port)
        be = StatusDisplay._collect_service("backend", backend_port, verify_backend=True)
        fe = StatusDisplay._collect_service("frontend", cfg.frontend_port)
        resources = SystemMonitor.collect()
        StatusDisplay.render(be, fe, resources)

    @staticmethod
    def watch() -> None:
        """Live monitoring mode — refreshes every WATCH_REFRESH seconds."""
        cfg = ConfigManager.instance().load()
        try:
            while True:
                backend_port = get_effective_backend_port(cfg.backend_port)
                be = StatusDisplay._collect_service("backend", backend_port, verify_backend=True)
                fe = StatusDisplay._collect_service("frontend", cfg.frontend_port)
                resources = SystemMonitor.collect()
                # Clear screen using ANSI codes
                safe_write(sys.stdout, "\033[2J\033[H")
                try:
                    sys.stdout.flush()
                except Exception:
                    pass
                StatusDisplay.render(be, fe, resources)
                print(f"  {c('dim', 'Press Ctrl+C to stop watching')}")
                time.sleep(WATCH_REFRESH)
        except KeyboardInterrupt:
            print()


# ═══════════════════════════════════════════════════════════════════════
# ReadyScreen
# ═══════════════════════════════════════════════════════════════════════


class ReadyScreen:
    @staticmethod
    def show(elapsed: float, be_port: int, fe_port: int) -> None:
        line = render_line()
        print()
        print(f"  {c('dim', line)}")
        print(f"  {c('bold', PROJECT_NAME)}")
        print(f"  {c('dim', 'Development Environment')}")
        print(f"  {c('dim', line)}")
        print()
        print(f"     {c('bold', 'Backend')}     {c('green', '✔ Running')}")
        print(f"     {c('bold', 'Frontend')}    {c('green', '✔ Running')}")
        print(f"     {c('bold', 'API')}         {c('green', '✔ Healthy')}")
        print(f"     {c('bold', 'Browser')}     {c('green', '✔ Open')}")
        print(f"     {c('bold', 'Swagger')}     {c('green', '✔ Open')}")
        print()
        print(f"  {c('dim', line)}")
        print()
        print(f"     {c('bold', 'Backend')}:  {c('cyan', f'http://localhost:{be_port}')}")
        print(f"     {c('bold', 'Frontend')}: {c('cyan', f'http://localhost:{fe_port}')}")
        print(f"     {c('bold', 'Swagger')}:  {c('cyan', f'http://localhost:{be_port}/docs')}")
        print()
        git_branch = get_git_branch()
        git_commit = get_git_commit_short()
        if git_branch:
            bt = c('white', git_branch)
            ct = c('white', git_commit or '?')
            print(f"     {c('dim', 'Branch')}: {bt}  {c('dim', 'Commit')}: {ct}")
        print(f"     {c('dim', 'Ready in')} {c('white', f'{elapsed:.2f} sec')}")
        print()
        print(f"  {c('dim', line)}")
        print()


# ═══════════════════════════════════════════════════════════════════════
# Error display helper
# ═══════════════════════════════════════════════════════════════════════


class ErrorHandler:
    """Displays rich error information with retry option."""

    @staticmethod
    def show(
        message: str,
        fix: str | None = None,
        retry_cb: Callable[[], bool] | None = None,
    ) -> bool:
        print()
        print(f"  {c('bg_red', ' ERROR ')} {c('bold', message)}")
        if fix:
            print(f"  {c('yellow', 'Possible fix')}: {fix}")
        print()
        if retry_cb is not None and ask_yes_no("Retry?", default=True):
            return retry_cb()
        return False


# ═══════════════════════════════════════════════════════════════════════
# Backend/frontend helpers (shared)
# ═══════════════════════════════════════════════════════════════════════


def find_backend_venv() -> Path | None:
    if os.name == "nt":
        candidates = [
            VENV_DIR / "Scripts" / "python.exe",
            VENV_DIR / "Scripts" / "python3.exe",
        ]
    else:
        candidates = [
            VENV_DIR / "bin" / "python",
            VENV_DIR / "bin" / "python3",
        ]
    for c_path in candidates:
        if c_path.is_file() and os.access(c_path, os.X_OK):
            return c_path
    return None


def is_valid_python(py_path: Path | str) -> bool:
    """Check if the given python path exists and is Python 3.12+."""
    try:
        res = subprocess.run(
            [str(py_path), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True, text=True, timeout=5,
        )
        if res.returncode == 0:
            parts = res.stdout.strip().split(".")
            major, minor = int(parts[0]), int(parts[1])
            return major > 3 or (major == 3 and minor >= 12)
    except Exception:
        pass
    return False


def find_system_python() -> Path | None:
    """Find any available Python 3.12+ executable on the host system."""
    candidates: list[Path | str] = []

    # Check PATH commands
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    # Windows-specific search paths
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            candidates.extend([
                Path(local_app) / "Programs" / "Python" / "Python313" / "python.exe",
                Path(local_app) / "Programs" / "Python" / "Python312" / "python.exe",
            ])
        program_files = os.environ.get("ProgramFiles", "C:/Program Files")
        candidates.extend([
            Path(program_files) / "Python313" / "python.exe",
            Path(program_files) / "Python312" / "python.exe",
            Path("C:/Python313/python.exe"),
            Path("C:/Python312/python.exe"),
        ])

    for c in candidates:
        if isinstance(c, str):
            c = Path(c)
        if c.is_file() and is_valid_python(c):
            return c
    return None


def download_file(url: str, dest: Path, description: str = "Downloading") -> bool:
    """Download a file with live progress, SSL verification fallback, and native tool fallback (curl / PowerShell)."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Method 1: Python urllib with chunked download and live progress
    for verify_ssl in (True, False):
        try:
            import ssl
            import urllib.request
            ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
            req = urllib.request.Request(url, headers={"User-Agent": "onx-launcher/1.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp, open(dest, "wb") as f:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 65536
                last_print = 0
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_print > 0.4 or downloaded == total_size:
                        last_print = now
                        if total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            mb_done = downloaded / (1024 * 1024)
                            mb_total = total_size / (1024 * 1024)
                            safe_write(sys.stdout, f"\r  ▸ {description}: {mb_done:.1f} MB / {mb_total:.1f} MB ({pct}%)")
                        else:
                            mb_done = downloaded / (1024 * 1024)
                            safe_write(sys.stdout, f"\r  ▸ {description}: {mb_done:.1f} MB")
                        try:
                            sys.stdout.flush()
                        except Exception:
                            pass
                safe_write(sys.stdout, "\n")
            if dest.is_file() and dest.stat().st_size > 1000000:
                return True
        except Exception:
            continue

    # Method 2: curl (available on Windows 10/11 and Linux)
    curl_cmd = shutil.which("curl.exe") or shutil.which("curl")
    if curl_cmd:
        try:
            safe_print(f"  ▸ {description} via curl...")
            res = subprocess.run([curl_cmd, "-L", "-k", "-#", "-o", str(dest), url], timeout=180)
            if res.returncode == 0 and dest.is_file() and dest.stat().st_size > 1000000:
                return True
        except Exception:
            pass

    # Method 3: PowerShell (Windows)
    if os.name == "nt" and shutil.which("powershell"):
        try:
            safe_print(f"  ▸ {description} via PowerShell...")
            res = subprocess.run([
                "powershell", "-NoProfile", "-Command",
                f"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('{url}', '{dest}')"
            ], capture_output=True, timeout=180)
            if res.returncode == 0 and dest.is_file() and dest.stat().st_size > 1000000:
                return True
        except Exception:
            pass

    return False


def auto_install_python_windows() -> Path | None:
    """Auto-download and install official Python 3.12 on Windows."""
    # 1. Try winget first if available
    if shutil.which("winget"):
        log_step("Python", "Installing Python 3.12 via Windows Package Manager (winget)...")
        try:
            res = subprocess.run(
                [
                    "winget", "install", "--id", "Python.Python.3.12",
                    "-e", "--accept-package-agreements", "--accept-source-agreements",
                    "--silent",
                ],
                capture_output=True, text=True, timeout=300,
            )
            if res.returncode == 0:
                log_ok("Python 3.12 installed via winget")
                time.sleep(2)
                found = find_system_python()
                if found:
                    return found
        except Exception:
            pass

    # 2. Download official installer from python.org
    installer_url = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
    tmp_dir = MCS_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    installer_path = tmp_dir / "python-3.12.8-installer.exe"

    log_step("Python", "Downloading Python 3.12 installer from python.org...")
    try:
        downloaded = download_file(installer_url, installer_path, "Downloading Python 3.12 installer")

        if not downloaded or not installer_path.is_file() or installer_path.stat().st_size < 1000000:
            log_error("Failed to download Python installer (empty or incomplete file)")
            return None

        log_ok(f"Downloaded Python installer ({installer_path.stat().st_size / (1024 * 1024):.1f} MB)")

        log_step("Python", "Running Python installer (passive user install)...")
        install_res = subprocess.run(
            [
                str(installer_path),
                "/passive",
                "InstallAllUsers=0",
                "PrependPath=1",
                "Include_pip=1",
                "Include_test=0",
            ],
            capture_output=True, text=True, timeout=300,
        )
        try:
            installer_path.unlink()
        except OSError:
            pass

        if install_res.returncode == 0:
            log_ok("Python 3.12 installation complete")
            time.sleep(2)
            # Add newly installed Python to current PATH
            local_app = os.environ.get("LOCALAPPDATA", "")
            if local_app:
                py_dir = Path(local_app) / "Programs" / "Python" / "Python312"
                scripts_dir = py_dir / "Scripts"
                if py_dir.is_dir():
                    os.environ["PATH"] = f"{py_dir};{scripts_dir};{os.environ.get('PATH', '')}"
            return find_system_python()
        else:
            log_error(f"Python installer exited with code {install_res.returncode}")
    except Exception as e:
        log_error(f"Failed to auto-download/install Python: {e}")

    return None


def auto_install_cpp_tools_windows() -> bool:
    """Download and install Microsoft Visual C++ Build Tools and Runtime on Windows."""
    if os.name != "nt":
        log_info("Microsoft Visual C++ Tools auto-installer is only applicable on Windows.")
        return True

    # 1. Try winget first if available
    if shutil.which("winget"):
        log_step("C++ Tools", "Installing Visual Studio C++ Build Tools via winget...")
        try:
            res = subprocess.run(
                [
                    "winget", "install", "--id", "Microsoft.VisualStudio.2022.BuildTools",
                    "-e", "--accept-package-agreements", "--accept-source-agreements",
                    "--override", "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended",
                ],
                capture_output=True, text=True, timeout=600,
            )
            if res.returncode == 0:
                log_ok("Visual Studio C++ Build Tools installed via winget")
                return True
        except Exception:
            pass

    tmp_dir = MCS_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 2. Install VC++ Runtime Redistributable first
    vcredist_url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    vcredist_path = tmp_dir / "vc_redist.x64.exe"
    log_step("C++ Tools", "Downloading Microsoft Visual C++ Redistributable...")
    if download_file(vcredist_url, vcredist_path, "Downloading VC++ Redistributable"):
        try:
            log_step("C++ Tools", "Installing VC++ Redistributable...")
            subprocess.run([str(vcredist_path), "/install", "/passive", "/norestart"], timeout=180)
            try:
                vcredist_path.unlink()
            except OSError:
                pass
            log_ok("VC++ Redistributable installed")
        except Exception as e:
            log_warn(f"VC++ Redistributable installation note: {e}")

    # 3. Download official Visual Studio C++ Build Tools bootstrapper from Microsoft
    bt_url = "https://aka.ms/vs/17/release/vs_BuildTools.exe"
    bt_path = tmp_dir / "vs_BuildTools.exe"
    log_step("C++ Tools", "Downloading Visual Studio C++ Build Tools installer from Microsoft...")
    if download_file(bt_url, bt_path, "Downloading VS Build Tools"):
        try:
            log_step("C++ Tools", "Running VS Build Tools installer (quiet mode)...")
            res = subprocess.run(
                [
                    str(bt_path),
                    "--quiet",
                    "--wait",
                    "--norestart",
                    "--nocache",
                    "--add", "Microsoft.VisualStudio.Workload.VCTools",
                    "--includeRecommended",
                ],
                timeout=900,
            )
            try:
                bt_path.unlink()
            except OSError:
                pass
            if res.returncode in (0, 3010):
                log_ok("Visual Studio C++ Build Tools installed successfully")
                return True
            else:
                log_error(f"VS Build Tools installer exited with code {res.returncode}")
        except Exception as e:
            log_error(f"Failed to install VS Build Tools: {e}")

    return False


def _refresh_windows_path() -> None:
    """Refresh process PATH on Windows to detect newly installed software."""
    if os.name != "nt":
        return
    try:
        import winreg
        paths = []
        for hkey, subkey in [
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, r"Environment"),
        ]:
            try:
                with winreg.OpenKey(hkey, subkey) as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                    paths.append(val)
            except Exception:
                pass
        default_node = r"C:\Program Files\nodejs"
        if default_node not in os.environ.get("PATH", ""):
            paths.append(default_node)
        os.environ["PATH"] = ";".join(paths) + ";" + os.environ.get("PATH", "")
    except Exception:
        pass


def auto_install_node_windows() -> bool:
    """Download and install portable Node.js 22 LTS on Windows (zero admin privileges required)."""
    if os.name != "nt":
        log_info("Node.js auto-installer is only applicable on Windows.")
        return True

    node_target_dir = ONX_DIR / "node"
    node_target_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = ONX_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Download official portable Node.js zip archive from nodejs.org
    zip_url = "https://nodejs.org/dist/v22.14.0/node-v22.14.0-win-x64.zip"
    zip_path = tmp_dir / "node-v22.14.0-win-x64.zip"
    log_step("Node.js", "Downloading official portable Node.js 22 LTS...")
    if not download_file(zip_url, zip_path, "Downloading Node.js"):
        log_error("Failed to download Node.js zip archive")
        return False

    # 2. Extract portable archive into .onx/node
    log_step("Node.js", "Extracting Node.js runtime...")
    try:
        import zipfile
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            zf.extractall(str(tmp_dir))

        for extracted_sub in tmp_dir.glob("node-v*"):
            if extracted_sub.is_dir():
                for item in extracted_sub.iterdir():
                    dest = node_target_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(str(dest), ignore_errors=True)
                        else:
                            dest.unlink()
                    shutil.move(str(item), str(node_target_dir))
                shutil.rmtree(str(extracted_sub), ignore_errors=True)

        try:
            zip_path.unlink()
        except OSError:
            pass

        find_or_activate_node()
        log_ok("Node.js portable runtime installed successfully")
        return True
    except Exception as e:
        log_error(f"Failed to extract Node.js archive: {e}")
        return False


def ensure_python_environment() -> Path | None:
    """Ensure a Python 3.12+ environment exists for the backend (auto-downloading and creating venv if needed)."""
    # 1. If backend/.venv already has a valid Python, use it
    venv_py = find_backend_venv()
    if venv_py and is_valid_python(venv_py):
        return venv_py

    # 2. Find system Python
    sys_py = find_system_python()
    if sys_py is None:
        if os.name == "nt":
            log_warn("Python 3.12+ not found. Attempting automatic download & installation...")
            sys_py = auto_install_python_windows()
        else:
            log_error("Python 3.12+ not found on system.")
            return None

    if sys_py is None:
        return None

    # 3. Create backend virtual environment
    log_step("Backend", f"Creating virtual environment at {VENV_DIR}...")
    try:
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
        res = subprocess.run(
            [str(sys_py), "-m", "venv", str(VENV_DIR)],
            cwd=str(BACKEND_DIR),
            capture_output=True, text=True, timeout=90,
        )
        if res.returncode != 0:
            log_error(f"Failed to create virtual environment:\n{res.stderr[:400]}")
            return sys_py
        created_venv = find_backend_venv()
        if created_venv:
            log_ok(f"Created virtual environment at {VENV_DIR}")
            install_backend_deps(created_venv)
            return created_venv
    except Exception as e:
        log_error(f"Error creating virtual environment: {e}")

    return sys_py


def check_backend_health(port: int = BACKEND_PORT, timeout: float = 2.0) -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(
            backend_health_url(port),
            headers={"User-Agent": "onx-launcher/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            return isinstance(data, dict) and data.get("status") == "ok" and "version" in data
    except Exception:
        return False


def _backend_is_serving(port: int, timeout: float = 1.0) -> bool:
    """Return True only if the port has an open listener that returns the panel health signature."""
    try:
        return PortManager.is_open(port) and check_backend_health(port, timeout=timeout)
    except Exception:
        return False


def get_effective_backend_port(preferred: int) -> int:
    """Return the recorded active port only when the panel health signature is valid."""
    active = PIDManager.read_active_port()
    if active is not None and check_backend_health(active, timeout=1.0):
        return active
    return preferred


def check_frontend_ready() -> bool:
    return PortManager.is_open(FRONTEND_PORT)


def install_backend_deps(python: Path) -> bool:
    log_step("Backend", "Installing dependencies from requirements.txt...")
    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.is_file():
        log_error("requirements.txt not found in backend directory")
        return False

    try:
        # On Windows, netifaces lacks Python 3.12 binary wheels and requires MSVC C++ tools.
        # netifaces-plus is the official modern drop-in wheel replacement for Windows Python 3.12+.
        if os.name == "nt":
            subprocess.run(
                [str(python), "-m", "pip", "install", "--no-warn-script-location", "netifaces-plus", "defusedxml"],
                cwd=str(BACKEND_DIR),
                capture_output=True, timeout=60,
            )
            subprocess.run(
                [str(python), "-m", "pip", "install", "--no-warn-script-location", "--no-deps", "aioupnp"],
                cwd=str(BACKEND_DIR),
                capture_output=True, timeout=60,
            )

        proc = subprocess.Popen(
            [str(python), "-m", "pip", "install", "--no-warn-script-location", "-r", str(req_file)],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        error_lines: list[str] = []
        if proc.stdout:
            for line in proc.stdout:
                line_s = line.strip()
                if line_s:
                    if any(k in line_s for k in ("Collecting", "Downloading", "Installing", "Successfully installed", "Requirement already satisfied")):
                        safe_print(f"    {c('dim', '▸')} {line_s[:95]}")
                    elif any(k in line_s for k in ("ERROR:", "error:", "Failed", "Exception", "Traceback")):
                        error_lines.append(line_s)
        proc.wait(timeout=300)
        if proc.returncode != 0:
            log_error(f"pip install exited with code {proc.returncode}")
            if error_lines:
                for el in error_lines[-5:]:
                    safe_print(f"    {c('red', '✖')} {el[:95]}")
            return False
        log_ok("Backend dependencies installed successfully")
        return True
    except subprocess.TimeoutExpired:
        log_error("pip install timed out (300s limit exceeded)")
        return False
    except Exception as e:
        log_error(f"pip install error: {e}")
        return False


def install_npm_deps() -> bool:
    log_step("Frontend", "Installing npm packages...")
    try:
        proc = subprocess.Popen(
            ["npm", "install"] if os.name != "nt" else ["npm.cmd", "install"],
            cwd=str(FRONTEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=(os.name == "nt"),
        )
        if proc.stdout:
            for line in proc.stdout:
                line_s = line.strip()
                if line_s and any(k in line_s for k in ("added", "audited", "packages", "npm", "WARN")):
                    safe_print(f"    {c('dim', '▸')} {line_s[:95]}")
        proc.wait(timeout=300)
        if proc.returncode != 0:
            log_error(f"npm install exited with code {proc.returncode}")
            return False
        log_ok("Frontend dependencies installed successfully")
        return True
    except subprocess.TimeoutExpired:
        log_error("npm install timed out (300s limit exceeded)")
        return False
    except Exception as e:
        log_error(f"npm install error: {e}")
        return False


def get_canonical_db_url() -> str:
    """Resolve database URL to a canonical, unambiguous absolute target."""
    env_url = os.environ.get("ONX_DATABASE_URL") or os.environ.get("MCS_DATABASE_URL")
    if env_url:
        if "sqlite" in env_url.lower() and ":memory:" not in env_url:
            prefix, _, raw_path = env_url.partition(":///")
            if not raw_path:
                prefix, _, raw_path = env_url.partition("://")
            p = Path(raw_path)
            if not p.is_absolute():
                p = (BACKEND_DIR / p).resolve()
            return f"{prefix}:///{p.as_posix()}"
        return env_url

    canonical_sqlite = (BACKEND_DIR / "data" / "onx.db").resolve()
    return f"sqlite+aiosqlite:///{canonical_sqlite.as_posix()}"


def reconcile_database(python: Path) -> bool:
    """Run the pre-backend database readiness and reconciliation layer."""
    log_step("Database", "Checking schema readiness...")
    canonical_db_url = get_canonical_db_url()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    env["ONX_DATABASE_URL"] = canonical_db_url

    try:
        proc = subprocess.run(
            [str(python), "-m", "app.core.persistence.reconciler", "--json", "--db-url", canonical_db_url],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        log_error("Database reconciliation timed out after 60s")
        return False
    except Exception as exc:
        log_error(f"Failed to execute database reconciler: {exc}")
        return False

    try:
        stdout = proc.stdout.strip()
        result = json.loads(stdout) if stdout else {}
    except Exception:
        result = {}

    status = result.get("status", "FAILED")
    msg = result.get("message", proc.stderr.strip() or "Unknown error")
    target_rev = result.get("target_revision", "")

    if status == "READY":
        log_ok(f"Database schema is up to date (revision {target_rev or 'head'})")
        return True
    elif status == "RECONCILED":
        action = result.get("action_taken", "UPGRADE")
        action_verb = "initialized" if action == "INITIALIZE" else "updated"
        log_ok(f"Database schema {action_verb} to revision {target_rev}")
        return True
    elif status == "BLOCKED_UNSAFE":
        log_error(f"Database reconciliation blocked: {msg}")
        log_warn("  Automatic migration blocked to prevent data loss. See .onx/logs/reconciliation.log")
        return False
    elif status == "UNREACHABLE":
        log_error(f"Database unreachable / locked: {msg}")
        log_warn("  Check database connectivity or locks. See .onx/logs/reconciliation.log")
        return False
    else:
        log_error(f"Database reconciliation failed: {msg}")
        log_warn("  Review detailed diagnostics in .onx/logs/reconciliation.log")
        return False


def validate_startup_prerequisites(cfg: LauncherConfig) -> tuple[bool, Path | None]:
    """Validate all runtime prerequisites (Python, Backend venv & deps, Node.js, npm,
    Frontend deps, and Database readiness) UPFRONT before launching any services.

    Returns:
        (success: bool, python_path: Path | None)
    """
    print(f"\n  {c('bold', '▸ Checking Prerequisites')} {c('dim', '──────────────────────────')}")

    # 1. Python environment
    log_step("Python", "Checking interpreter and virtual environment...")
    python = ensure_python_environment()
    if python is None:
        ErrorHandler.show(
            "No Python 3.12+ interpreter found.",
            f"Install Python 3.12+ from https://python.org, then run:\n"
            f"  cd {BACKEND_DIR} && python -m venv .venv\n"
            f"  .venv/bin/pip install -r requirements.txt",
        )
        return False, None

    try:
        ver, _ = Validator.check_python()
        log_ok(f"Python {ver} ({python})")
    except ValidationError as e:
        ErrorHandler.show(str(e), e.fix)
        return False, None

    # 2. Backend pip dependencies
    if python.is_absolute():
        if not Validator.check_backend_deps(python):
            if cfg.auto_install_deps:
                log_step("Backend", "Missing Python dependencies. Auto-installing...")
                if not install_backend_deps(python):
                    ErrorHandler.show(
                        "Failed to install backend dependencies.",
                        f"Try running manually: {python} -m pip install -r requirements.txt",
                    )
                    return False, None
            else:
                log_warn("Backend dependencies may be missing (auto_install_deps=False)")
        else:
            log_ok("Backend dependencies installed")

    # 3. Node.js runtime
    log_step("Node.js", "Checking runtime environment...")
    try:
        node_ver = Validator.check_node()
        log_ok(f"Node.js {node_ver}")
    except ValidationError as e:
        if os.name == "nt" and cfg.auto_install_deps:
            log_step("Node.js", "Node.js missing. Attempting automatic installation...")
            if auto_install_node_windows():
                try:
                    node_ver = Validator.check_node()
                    log_ok(f"Node.js {node_ver}")
                except ValidationError:
                    fix_msg = "Install Node.js 18+ from https://nodejs.org\nOr via PowerShell: winget install OpenJS.NodeJS.LTS"
                    ErrorHandler.show("Node.js installation verification failed.", fix_msg)
                    return False, None
            else:
                fix_msg = "Install Node.js 18+ from https://nodejs.org\nOr via PowerShell: winget install OpenJS.NodeJS.LTS"
                ErrorHandler.show(str(e), fix_msg)
                return False, None
        else:
            fix_msg = "Install Node.js 18+ from https://nodejs.org"
            if os.name == "nt":
                fix_msg += "\nOr via PowerShell: winget install OpenJS.NodeJS.LTS"
            ErrorHandler.show(str(e), fix_msg)
            return False, None

    # 4. npm package manager
    try:
        npm_ver = Validator.check_npm()
        log_ok(f"npm {npm_ver}")
    except ValidationError as e:
        ErrorHandler.show(str(e), e.fix or "npm should come with Node.js — reinstall Node")
        return False, None

    # 5. Frontend node_modules dependencies
    if not Validator.check_frontend_deps():
        if cfg.auto_install_deps:
            log_step("Frontend", "Frontend node_modules missing. Auto-installing...")
            if not install_npm_deps():
                ErrorHandler.show(
                    "Failed to install frontend dependencies.",
                    f"Try running manually: cd {FRONTEND_DIR} && npm install",
                )
                return False, None
        else:
            ErrorHandler.show(
                "Frontend dependencies not installed.",
                f"Run: cd {FRONTEND_DIR} && npm install",
            )
            return False, None
    else:
        log_ok("Frontend dependencies installed")

    # 6. Database schema readiness & reconciliation
    if not reconcile_database(python):
        ErrorHandler.show(
            "Database readiness check failed.",
            "Review .onx/logs/reconciliation.log for detailed diagnostics.\n"
            f"Or inspect manually: cd {BACKEND_DIR} && PYTHONPATH=. {python} -m app.core.persistence.reconciler",
        )
        return False, None

    return True, python


# ═══════════════════════════════════════════════════════════════════════
# Start services
# ═══════════════════════════════════════════════════════════════════════


BIND_ERROR_MARKERS = (
    "address already in use",
    "errno 98",
    "winerror 10048",
    "only one usage of each socket address",
)

_attempt_token_counter = 0


def _generate_attempt_token() -> str:
    global _attempt_token_counter
    _attempt_token_counter += 1
    return f"tok-{os.getpid()}-{time.monotonic_ns()}-{_attempt_token_counter}"


def _stat_file_identity(path: Path) -> tuple[int, int, int]:
    try:
        if not path.is_file():
            return (0, 0, 0)
        st = path.stat()
        return (st.st_dev, st.st_ino, st.st_size)
    except OSError:
        return (0, 0, 0)


# Note on OSError: if writing the attempt marker fails (e.g. permission or disk error),
# the token is still returned. If a subsequent reset to 0 occurs, the reader will not
# find the token and returns no evidence (""), meaning a real bind error may degrade
# to 'timeout' for that attempt (no retry). This degradation is accepted behavior.
def _write_attempt_marker(log_file: Path, attempt: int, token: str | None = None) -> str:
    if token is None:
        token = _generate_attempt_token()
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        marker = f"--- ONX LAUNCH ATTEMPT {attempt} ({ts}) [token:{token}] ---\n"
        with log_file.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(marker)
            fh.flush()
    except OSError as err:
        log_warn(f"Failed to write attempt marker: {err}")
    return token


def _capture_attempt_marker(log_file: Path, token: str) -> bytes | None:
    if not token:
        return None
    try:
        if not log_file.is_file():
            return None
        size = log_file.stat().st_size
        if size == 0:
            return None
        read_len = min(size, 4096)
        with log_file.open("rb") as fh:
            fh.seek(size - read_len)
            chunk = fh.read(read_len)
        if not chunk.endswith(b"\n"):
            return None
        last_nl = chunk[:-1].rfind(b"\n")
        if last_nl == -1:
            if read_len < size:
                with log_file.open("rb") as fh:
                    full = fh.read()
                last_nl = full[:-1].rfind(b"\n")
                line = full if last_nl == -1 else full[last_nl + 1 :]
            else:
                line = chunk
        else:
            line = chunk[last_nl + 1 :]
        token_bytes = token.encode("utf-8")
        if (
            line.startswith(b"--- ONX LAUNCH ATTEMPT ")
            and token_bytes in line
            and line.endswith(b"\n")
        ):
            return line
        return None
    except OSError:
        return None


# Clarification from v3 design review:
# Whenever the reader resets its offset to 0 (file identity changed or file shrank),
# it must NEVER treat text that precedes the CURRENT attempt's marker as evidence.
# A unique per-attempt token is embedded in the marker line; after a reset to 0,
# the reader locates the last occurrence of the current token and only parses text
# after it. If the token is not found, it returns empty string ('no evidence').
# Identity is a 3-tuple of (st_dev, st_ino, st_size); marker_token is a required keyword argument.
# Under F2b, if marker_bytes is provided, bytes immediately before saved_size are verified;
# mismatch or short read triggers a reset to 0.
def _read_backend_log_from(
    identity: tuple[int, int, int],
    *,
    marker_token: str,
    marker_bytes: bytes | None = None,
) -> str:
    saved_dev, saved_ino, saved_size = identity
    try:
        if not BACKEND_LOG.is_file():
            return ""
        st = BACKEND_LOG.stat()
        reset_to_zero = (
            (st.st_dev, st.st_ino) != (saved_dev, saved_ino) or st.st_size < saved_size
        )
        with BACKEND_LOG.open("rb") as fh:
            if not reset_to_zero and marker_bytes:
                if saved_size < len(marker_bytes):
                    reset_to_zero = True
                else:
                    fh.seek(saved_size - len(marker_bytes))
                    if fh.read(len(marker_bytes)) != marker_bytes:
                        reset_to_zero = True

            if reset_to_zero:
                fh.seek(0)
                content = fh.read().decode("utf-8", errors="replace")
                if not marker_token:
                    return ""
                idx = content.rfind(marker_token)
                if idx == -1:
                    return ""
                newline_idx = content.find("\n", idx)
                if newline_idx != -1:
                    return content[newline_idx + 1 :]
                return content[idx + len(marker_token) :]
            fh.seek(saved_size)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _has_bind_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in BIND_ERROR_MARKERS)


def _wait_for_backend_attempt(
    port: int,
    pid: int,
    timeout: float,
    log_identity: tuple[int, int, int],
    *,
    marker_token: str,
    marker_bytes: bytes | None = None,
) -> str:
    """Return healthy | bind | dead | timeout for one launch attempt."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_backend_health(port):
            return "healthy"
        if _has_bind_error(
            _read_backend_log_from(
                log_identity, marker_token=marker_token, marker_bytes=marker_bytes
            )
        ):
            return "bind"
        if not PIDManager.is_alive(pid):
            time.sleep(0.5)
            if check_backend_health(port):
                return "healthy"
            return "dead"
        time.sleep(POLL_INTERVAL)

    if check_backend_health(port):
        return "healthy"
    if _has_bind_error(
        _read_backend_log_from(
            log_identity, marker_token=marker_token, marker_bytes=marker_bytes
        )
    ):
        return "bind"
    return "timeout"


def _backend_supervisor_pid(pid: int | None) -> int | None:
    """Walk up the project-owned uvicorn/terminal chain to the top killable PID."""
    if not pid or pid <= 0:
        return pid
    if not PortManager.belongs_to_project(pid):
        return None
    best = pid
    current = pid
    for _ in range(10):
        try:
            import psutil
            proc = psutil.Process(current)
            parent = proc.parent()
            if parent is None or parent.pid <= 1:
                break
            cmdline = " ".join(parent.cmdline()).lower()
            if not PortManager.belongs_to_project(parent.pid):
                break
            if not any(k in cmdline for k in ("uvicorn", "konsole", "bash -c", " tee ", "cmd.exe")):
                break
            best = parent.pid
            current = parent.pid
        except Exception:
            break
    return best


def _check_backend_provenance(
    port: int,
    wrapper_pid: int | None,
    spawn_time: float | None,
) -> ProvenanceStatus:
    """Determine whether listener on port belongs to the given launcher attempt.

    Returns ProvenanceStatus.VERIFIED only if listener_pid == wrapper_pid (with matching
    create_time) or listener_pid is a project-owned descendant of wrapper_pid via psutil
    with create_time >= spawn_time. Refuses (returns UNKNOWN) when spawn_time is None (O-8).
    """
    if spawn_time is None or wrapper_pid is None or wrapper_pid <= 0:
        return ProvenanceStatus.UNKNOWN

    listener_pid = PortManager.get_pid_by_port(port)
    if listener_pid is None or listener_pid <= 0:
        return ProvenanceStatus.UNKNOWN

    if not PortManager.belongs_to_project(listener_pid):
        return ProvenanceStatus.UNKNOWN

    if listener_pid == wrapper_pid:
        if _verify_process_identity(listener_pid, spawn_time):
            return ProvenanceStatus.VERIFIED
        return ProvenanceStatus.UNKNOWN

    try:
        import psutil

        wrapper_proc = psutil.Process(wrapper_pid)
        descendants = wrapper_proc.children(recursive=True)
        is_descendant = any(child.pid == listener_pid for child in descendants)
    except Exception:
        is_descendant = False

    if not is_descendant:
        return ProvenanceStatus.UNKNOWN

    listener_create_time = _capture_process_create_time(listener_pid)
    if listener_create_time is None or listener_create_time < spawn_time - 0.5:
        return ProvenanceStatus.UNKNOWN

    return ProvenanceStatus.VERIFIED


def _reconcile_backend_attempt(
    port: int,
    wrapper_pid: int | None,
    spawn_time: float | None,
    cfg: LauncherConfig | None = None,
    *,
    allow_adopt: bool = True,
) -> bool:
    """Reconcile startup attempt on timeout or KeyboardInterrupt (D-2, D-10, D-12).

    1. If allow_adopt is True: re-check health; if project-owned and healthy, adopt it.
    2. Else if provenance is VERIFIED: terminate only the proven project-owned attempt tree,
       verify port release, report survivors without SIGKILL escalation (D-10).
    3. Else: terminate wrapper PID only (never signalling foreign or unresolved listeners).
    4. Clean active port and clean backend.pid only if matching wrapper_pid.
    """
    if allow_adopt:
        listener_pid = PortManager.get_pid_by_port(port)
        if (
            listener_pid is not None
            and PortManager.belongs_to_project(listener_pid)
            and check_backend_health(port, timeout=1.0)
        ):
            if cfg is not None:
                cfg.active_backend_port = port
            PIDManager.write_active_port(port)
            supervisor = _backend_supervisor_pid(listener_pid) or listener_pid
            if supervisor:
                PIDManager.write("backend", supervisor)
            log_ok(f"Backend is ready on port {port} (listener PID {supervisor})")
            return True

    prov = _check_backend_provenance(port, wrapper_pid, spawn_time)
    listener_pid = PortManager.get_pid_by_port(port)

    if (
        prov == ProvenanceStatus.VERIFIED
        and listener_pid is not None
        and PortManager.belongs_to_project(listener_pid)
    ):
        listener_create_time = _capture_process_create_time(listener_pid)
        supervisor = _backend_supervisor_pid(listener_pid)
        if supervisor is None or not PortManager.belongs_to_project(supervisor):
            supervisor = listener_pid
        supervisor_create_time = (
            listener_create_time
            if supervisor == listener_pid
            else _capture_process_create_time(supervisor)
        )

        if not _verify_process_identity(listener_pid, listener_create_time):
            log_warn(
                f"Process identity verification failed for listener PID {listener_pid} "
                f"on port {port} — skipping kill"
            )
        elif not _verify_process_identity(supervisor, supervisor_create_time):
            log_warn(
                f"Process identity verification failed for backend PID {supervisor} "
                f"on port {port} — skipping kill"
            )
        else:
            PIDManager.kill_tree(supervisor)

        if wrapper_pid and PIDManager.is_alive(wrapper_pid) and wrapper_pid != supervisor:
            PIDManager.kill_tree(wrapper_pid)

        # Verify port release (D-10)
        if not PortManager.can_bind(port) and PortManager.get_pid_by_port(port) is not None:
            time.sleep(0.5)

        survivor = PortManager.get_pid_by_port(port)
        if survivor is not None:
            log_error(
                f"Failed to free port {port}; untracked process {survivor} still listening"
            )
        else:
            log_ok(f"Backend stopped (PID {supervisor})")
    else:
        # Foreign, unresolved, or unverified listener: DO NOT signal listener (D-2).
        # Terminate only launcher-spawned wrapper PID if alive.
        if wrapper_pid and PIDManager.is_alive(wrapper_pid):
            PIDManager.kill_tree(wrapper_pid)

    PIDManager.clear_active_port()
    _clear_backend_pid_if(wrapper_pid)
    return False


def _resolve_reused_backend_pid(port: int) -> int | None:
    """Resolve verified project-owned PID for a reused backend port.

    Never copies stored backend.pid unless project-owned and consistent with listener.
    Otherwise derives supervisor from listener_pid and verifies ownership.
    """
    listener_pid = PortManager.get_pid_by_port(port)
    supervisor = _backend_supervisor_pid(listener_pid) if listener_pid else None
    if supervisor is None or not PortManager.belongs_to_project(supervisor):
        supervisor = (
            listener_pid
            if (listener_pid and PortManager.belongs_to_project(listener_pid))
            else None
        )

    stored_pid = PIDManager.read("backend")
    if (
        stored_pid
        and PIDManager.is_alive(stored_pid)
        and PortManager.belongs_to_project(stored_pid)
    ):
        if listener_pid and (stored_pid == listener_pid or stored_pid == supervisor):
            return stored_pid
        if listener_pid:
            try:
                import psutil

                proc = psutil.Process(listener_pid)
                parents = [p.pid for p in proc.parents()]
                if stored_pid in parents:
                    return stored_pid
            except Exception:
                pass
    return supervisor


def _handle_own_unhealthy(port: int) -> bool:
    log_warn(
        f"Port {port} is held by a project-owned backend that is not healthy. "
        "Starting a second backend would share the SQLite database."
    )
    expected_pid = PortManager.get_pid_by_port(port)
    expected_create_time = (
        _capture_process_create_time(expected_pid) if expected_pid is not None else None
    )
    if expected_pid is not None and expected_create_time is None:
        log_warn(
            f"Process identity cannot be proven for PID {expected_pid} on port {port} "
            "— refusing to stop"
        )
        return False
    if not ask_yes_no(f"Stop the project-owned process on port {port}?", default=True):
        log_error(f"Port {port} is occupied by a project-owned backend. Aborting.")
        return False
    if PortManager.kill_on_port(
        port, expected_pid=expected_pid, expected_create_time=expected_create_time
    ):
        PIDManager.clear_active_port()
        return True
    return False


def _format_process_info(pid: int) -> str:
    """Format PID with name and cmdline if cheaply available via psutil (D-10)."""
    try:
        import psutil

        p = psutil.Process(pid)
        name = ""
        try:
            name = p.name()
        except Exception:
            pass
        cmdline = ""
        try:
            cmd = p.cmdline()
            if cmd:
                cmdline = " ".join(cmd[:5])
        except Exception:
            pass
        details = []
        if name:
            details.append(f"name: {name}")
        if cmdline:
            details.append(f"cmdline: {cmdline}")
        if details:
            return f"PID {pid} ({', '.join(details)})"
    except Exception:
        pass
    return f"PID {pid}"


def _pid_points_at_survivor(stored_pid: int | None, survivor_pid: int | None) -> bool:
    """Check if stored PID points at or is an ancestor of a surviving process (D-10)."""
    if stored_pid is None or survivor_pid is None:
        return False
    if stored_pid == survivor_pid:
        return True
    try:
        import psutil

        proc = psutil.Process(survivor_pid)
        for parent in proc.parents():
            if parent.pid == stored_pid:
                return True
    except Exception:
        pass
    return False


def _terminate_attempt_wrapper(pid: int | None, spawn_time: float | None) -> None:
    """Terminate the attempt wrapper PID if alive, verified, and project-owned (O-8)."""
    if pid and PIDManager.is_alive(pid):
        if PortManager.belongs_to_project(pid):
            if _verify_process_identity(pid, spawn_time):
                PIDManager.kill_tree(pid)
            else:
                log_warn(
                    f"Wrapper PID {pid} process identity not proven "
                    "— leaving untracked/unproven"
                )
        else:
            log_warn(
                f"Wrapper PID {pid} is foreign or unverified — skipping kill"
            )
    _clear_backend_pid_if(pid)


def _reconcile_failed_attempt(
    port: int,
    attempt_pid: int | None = None,
    *,
    kill_owned: bool = True,
    spawn_time: float | None = None,
) -> bool:
    """Inspect occupant on port after a failed attempt and reconcile state (D-3, D-7, D-10).

    Returns True if safe to proceed to another port candidate (port is free, occupant is
    conclusively foreign, or owned listener was stopped and port freed).
    Returns False if startup must abort immediately (unresolved listener ownership, or owned
    listener could not be stopped).
    """
    if PortManager.can_bind(port):
        _clear_backend_pid_if(attempt_pid)
        return True

    listener_pid = PortManager.get_pid_by_port(port)
    if listener_pid is None:
        log_error(
            f"Port {port} listener ownership is unresolved (cannot attribute PID) — "
            "aborting startup to prevent concurrent database access"
        )
        _terminate_attempt_wrapper(attempt_pid, spawn_time)
        return False

    if not PortManager.belongs_to_project(listener_pid):
        log_warn(
            f"Port {port} is occupied by foreign process (PID {listener_pid}) — "
            "leaving it untouched"
        )
        _clear_backend_pid_if(attempt_pid)
        return True

    if not kill_owned:
        log_error(
            f"Port {port} is occupied by project-owned process (PID {listener_pid}) "
            "and kill_owned is False — aborting startup"
        )
        _terminate_attempt_wrapper(attempt_pid, spawn_time)
        return False

    freed = _handle_own_unhealthy(port)
    survivor_pid = PortManager.get_pid_by_port(port)
    if not freed or not PortManager.can_bind(port) or survivor_pid is not None:
        if survivor_pid is not None:
            survivor_desc = _format_process_info(survivor_pid)
            log_warn(
                f"Port {port} is still occupied after kill; "
                f"surviving untracked process: {survivor_desc}"
            )
            log_error(
                f"Port {port} project-owned listener could not be stopped "
                f"(surviving process {survivor_desc}) — aborting startup"
            )
        else:
            log_error(
                f"Port {port} project-owned listener could not be stopped — "
                "aborting startup"
            )

        if (
            attempt_pid
            and attempt_pid != survivor_pid
            and not _pid_points_at_survivor(attempt_pid, survivor_pid)
        ):
            _terminate_attempt_wrapper(attempt_pid, spawn_time)
        else:
            stored_pid = PIDManager.read("backend")
            points_at_survivor = survivor_pid is not None and _pid_points_at_survivor(
                stored_pid, survivor_pid
            )
            if not points_at_survivor:
                _clear_backend_pid_if(attempt_pid)
        return False

    _clear_backend_pid_if(attempt_pid)
    return True


def start_backend(cfg: LauncherConfig, python: Path | None = None) -> bool:
    decision = PortManager.resolve_startup_port(
        preferred=cfg.backend_port,
        known_active=PIDManager.read_active_port(),
        on_own_unhealthy=_handle_own_unhealthy,
    )
    if decision is None:
        PIDManager.clear_active_port()
        _clear_backend_pid_if(None)
        ErrorHandler.show(
            "No available backend port.",
            f"Ports {cfg.backend_port}-{cfg.backend_port + PORT_SCAN_SPAN - 1} are occupied "
            "by foreign processes or a project backend could not be stopped.",
        )
        return False

    cfg.active_backend_port = decision.port
    if decision.reuse:
        actual_pid = _resolve_reused_backend_pid(decision.port)
        if actual_pid is None:
            log_warn(
                f"Port {decision.port} reuse verification failed (listener vanished "
                "or turned foreign) — aborting startup"
            )
            PIDManager.clear_active_port()
            return False
        PIDManager.write("backend", actual_pid)
        PIDManager.write_active_port(decision.port)
        source = " (from active-port state)" if decision.source == "known-active" else ""
        log_ok(
            f"Backend already running and healthy on port {decision.port} "
            f"(PID {actual_pid}){source}"
        )
        return True

    if python is None:
        python = ensure_python_environment()
        if python is None:
            PIDManager.clear_active_port()
            _clear_backend_pid_if(None)
            ErrorHandler.show(
                "No Python interpreter found.",
                f"Install Python 3.12+ from https://python.org, then run:\n"
                f"  cd {BACKEND_DIR} && python -m venv .venv\n"
                f"  .venv/bin/pip install -r requirements.txt",
            )
            return False

    canonical_db_url = get_canonical_db_url()
    port = decision.port
    tried: set[int] = set()
    last_attempt_pid: int | None = None
    last_attempt_spawn_time: float | None = None

    for attempt in range(1, MAX_PORT_ATTEMPTS + 1):
        tried.add(port)
        timeout = cfg.startup_timeout if attempt == 1 else min(15, cfg.startup_timeout)
        log_step("Backend", f"Starting on port {port} (attempt {attempt}/{MAX_PORT_ATTEMPTS})...")
        token = _write_attempt_marker(BACKEND_LOG, attempt)
        marker_bytes = _capture_attempt_marker(BACKEND_LOG, token)
        log_identity = _stat_file_identity(BACKEND_LOG)
        pid = None
        spawn_time = None
        try:
            pid = TerminalOpener.open_backend(
                python,
                port,
                {
                    "PYTHONPATH": str(BACKEND_DIR),
                    "ONX_DATABASE_URL": canonical_db_url,
                    "ONX_PANEL_BIND_PORT": str(port),
                },
            )
            if pid is None:
                log_error("Failed to launch backend terminal")
                if last_attempt_pid and PIDManager.is_alive(last_attempt_pid):
                    if PortManager.belongs_to_project(last_attempt_pid):
                        if _verify_process_identity(last_attempt_pid, last_attempt_spawn_time):
                            PIDManager.kill_tree(last_attempt_pid)
                        else:
                            log_warn(
                                f"Previous wrapper PID {last_attempt_pid} process identity "
                                "not proven — leaving untracked/unproven"
                            )
                    else:
                        log_warn(
                            f"Previous wrapper PID {last_attempt_pid} is foreign or "
                            "unverified — skipping kill"
                        )
                PIDManager.clear_active_port()
                _clear_backend_pid_if(last_attempt_pid)
                return False
            captured_time = _capture_process_create_time(pid)
            # O-8: no proof, no kill
            spawn_time = captured_time
            PIDManager.write("backend", pid)
            last_attempt_pid = pid
            last_attempt_spawn_time = spawn_time

            spinner = Spinner("Waiting for backend...")
            spinner.start()
            try:
                outcome = _wait_for_backend_attempt(
                    port,
                    pid,
                    timeout,
                    log_identity,
                    marker_token=token,
                    marker_bytes=marker_bytes,
                )
            finally:
                spinner.stop()
        except KeyboardInterrupt:
            _reconcile_backend_attempt(port, pid, spawn_time, cfg=cfg, allow_adopt=False)
            raise

        if outcome == "healthy":
            cfg.active_backend_port = port
            PIDManager.write_active_port(port)
            PIDManager.write("backend", pid)
            actual_pid = PortManager.get_pid_by_port(port) or pid
            log_ok(f"Backend is ready on port {port} (listener PID {actual_pid})")
            return True

        if outcome == "dead" and PortManager.can_bind(port):
            log_error("Backend process died during startup")
            ErrorHandler.show(
                "Backend crashed during startup.",
                "Check the logs with: python launcher.py --logs\n"
                "Or run: cd backend && PYTHONPATH=. python -m uvicorn app.main:app --reload",
            )
            PIDManager.clear_active_port()
            _clear_backend_pid_if(pid)
            return False

        if outcome == "timeout":
            adopted = _reconcile_backend_attempt(
                port, pid, spawn_time, cfg=cfg, allow_adopt=True
            )
            if adopted:
                return True
            log_error(
                f"Backend did not become healthy within {timeout:.0f}s on port {port}. "
                "No bind evidence; not retrying."
            )
            return False

        # D-7: Retry applies ONLY to failures diagnosed as bind races
        is_bind_race = (outcome == "bind") or (
            outcome == "dead" and not PortManager.can_bind(port)
        )
        if not is_bind_race:
            log_error("Backend crashed during startup")
            PIDManager.clear_active_port()
            _clear_backend_pid_if(pid)
            return False

        if attempt >= MAX_PORT_ATTEMPTS:
            break

        # Reconcile failed attempt before selecting next candidate (D-3, D-7)
        if not _reconcile_failed_attempt(
            port, pid, kill_owned=True, spawn_time=spawn_time
        ):
            survivor_pid = PortManager.get_pid_by_port(port)
            if not (survivor_pid is not None and PIDManager.read_active_port() == port):
                PIDManager.clear_active_port()
            stored_pid = PIDManager.read("backend")
            points_at_survivor = survivor_pid is not None and _pid_points_at_survivor(
                stored_pid, survivor_pid
            )
            if not points_at_survivor:
                _clear_backend_pid_if(pid)
            return False

        if outcome == "dead":
            log_warn(f"Port {port} was taken during startup; retrying on the next candidate.")
        else:
            log_warn(f"Port {port} is already in use; retrying on the next candidate.")

        next_decision = PortManager.resolve_startup_port(
            preferred=cfg.backend_port,
            known_active=None,
            on_own_unhealthy=_handle_own_unhealthy,
            exclude_ports=tried,
        )
        if next_decision is None:
            if pid and PIDManager.is_alive(pid):
                if PortManager.belongs_to_project(pid):
                    if _verify_process_identity(pid, spawn_time):
                        PIDManager.kill_tree(pid)
                    else:
                        log_warn(
                            f"Wrapper PID {pid} process identity not proven "
                            "— leaving untracked/unproven"
                        )
                else:
                    log_warn(
                        f"Wrapper PID {pid} is foreign or unverified — skipping kill"
                    )
            PIDManager.clear_active_port()
            _clear_backend_pid_if(pid)
            return False
        if next_decision.reuse:
            cfg.active_backend_port = next_decision.port
            actual_pid = _resolve_reused_backend_pid(next_decision.port)
            if actual_pid is None:
                log_warn(
                    f"Port {next_decision.port} reuse verification failed (listener "
                    "vanished or turned foreign) — aborting startup"
                )
                PIDManager.clear_active_port()
                _clear_backend_pid_if(last_attempt_pid)
                return False
            PIDManager.write("backend", actual_pid)
            PIDManager.write_active_port(next_decision.port)
            log_ok(
                f"Backend already running and healthy on port {next_decision.port} "
                f"(PID {actual_pid})"
            )
            return True
        port = next_decision.port

    if last_attempt_pid and PIDManager.is_alive(last_attempt_pid):
        if PortManager.belongs_to_project(last_attempt_pid):
            if _verify_process_identity(last_attempt_pid, last_attempt_spawn_time):
                PIDManager.kill_tree(last_attempt_pid)
            else:
                log_warn(
                    f"Wrapper PID {last_attempt_pid} process identity not proven "
                    "— leaving untracked/unproven"
                )
        else:
            log_warn(
                f"Wrapper PID {last_attempt_pid} is foreign or unverified — skipping kill"
            )

    survivor = PortManager.get_pid_by_port(port)
    if survivor is not None or not PortManager.can_bind(port):
        if survivor is not None:
            survivor_desc = _format_process_info(survivor)
            log_warn(
                f"Port {port} is still occupied after kill; "
                f"surviving untracked process: {survivor_desc}"
            )
            log_error(
                f"Failed to free port {port}; untracked process {survivor_desc} still listening"
            )
        else:
            log_error(f"Failed to free port {port}")

    log_error(f"Backend failed to start after {MAX_PORT_ATTEMPTS} attempt(s)")
    if not (survivor is not None and PIDManager.read_active_port() == port):
        PIDManager.clear_active_port()
    stored_pid = PIDManager.read("backend")
    points_at_survivor = survivor is not None and _pid_points_at_survivor(
        stored_pid, survivor
    )
    if not points_at_survivor:
        _clear_backend_pid_if(last_attempt_pid)
    return False


def start_frontend(cfg: LauncherConfig) -> bool:
    fe_pid = PIDManager.read("frontend")
    if fe_pid and PIDManager.is_alive(fe_pid) and PortManager.is_open(cfg.frontend_port):
        log_ok(f"Frontend already running (PID {fe_pid})")
        return True

    if PortManager.is_open(cfg.frontend_port):
        if check_frontend_ready():
            actual_pid = PortManager.get_pid_by_port(cfg.frontend_port) or fe_pid
            if actual_pid:
                PIDManager.write("frontend", actual_pid)
            log_ok(f"Frontend already running and ready (PID {actual_pid})")
            return True

        pid = PortManager.get_pid_by_port(cfg.frontend_port)
        if pid and not ask_yes_no(
            f"Port {cfg.frontend_port} is in use by PID {pid} (unresponsive). Kill it?",
            default=True,
        ):
            log_error(f"Port {cfg.frontend_port} is occupied. Aborting.")
            return False
        PortManager.kill_on_port(cfg.frontend_port)

    backend_port = cfg.active_backend_port or cfg.backend_port
    log_step("Frontend", f"Starting in new terminal (proxy -> {backend_port})...")
    pid = TerminalOpener.open_frontend(backend_port)
    if pid is None:
        log_error("Failed to launch frontend terminal")
        return False
    PIDManager.write("frontend", pid)

    spinner = Spinner("Waiting for frontend...")
    spinner.start()
    deadline = time.time() + cfg.startup_timeout
    ready = False
    while time.time() < deadline:
        if check_frontend_ready():
            ready = True
            break
        if not PIDManager.is_alive(pid):
            time.sleep(1)
            if check_frontend_ready():
                ready = True
                break
            log_error("Frontend process died")
            ErrorHandler.show(
                "Frontend crashed during startup.",
                "Check the logs with: python launcher.py --logs\n"
                "Or try: cd frontend && npm run dev",
                lambda: start_frontend(cfg),
            )
            break
        time.sleep(POLL_INTERVAL)
    spinner.stop()

    if ready:
        log_ok("Frontend is ready")
        actual_pid = PortManager.get_pid_by_port(cfg.frontend_port)
        if actual_pid:
            PIDManager.write("frontend", actual_pid)
        return True
    else:
        log_error("Frontend failed to start within timeout")
        return False


# ═══════════════════════════════════════════════════════════════════════
# Command implementations
# ═══════════════════════════════════════════════════════════════════════


def cmd_start() -> int:
    print_banner()
    cfg = ConfigManager.instance().load()
    start_time = time.time()

    MCS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    PIDManager.cleanup_stale()

    # Validate project structure
    try:
        Validator.check_project_structure()
    except ValidationError as e:
        ErrorHandler.show(str(e), e.fix)
        return 1

    # Validate git
    try:
        Validator.check_git()
    except ValidationError:
        log_warn("Not a git repository — some features disabled")

    # Upfront unified prerequisite verification gate
    prereqs_ok, python = validate_startup_prerequisites(cfg)
    if not prereqs_ok or python is None:
        log_error("Startup aborted: missing runtime prerequisites.")
        return 1

    # VS Code
    if cfg.open_vscode:
        cmd_open_vscode()

    # Start backend
    print(f"\n  {c('bold', '▸ Starting Backend')} {c('dim', '───')}")
    if not start_backend(cfg, python):
        log_error("Backend startup failed. Aborting.")
        return 1

    # Start frontend
    print(f"\n  {c('bold', '▸ Starting Frontend')} {c('dim', '──')}")
    if not start_frontend(cfg):
        log_error("Frontend startup failed.")
        return 1

    PIDManager.save_started_at()
    elapsed = time.time() - start_time

    # Open browser
    if cfg.open_browser:
        log_step("Browser", "Opening frontend...")
        try:
            webbrowser.open(FRONTEND_URL)
            log_ok("Browser opened")
        except Exception as e:
            log_warn(f"Could not open browser: {e}")

    # Open Swagger
    if cfg.open_swagger:
        log_step("Swagger", "Opening API docs...")
        try:
            active_port = cfg.active_backend_port or cfg.backend_port
            webbrowser.open(f"http://localhost:{active_port}/docs")
            log_ok("Swagger opened")
        except Exception as e:
            log_warn(f"Could not open Swagger: {e}")

    ReadyScreen.show(elapsed, cfg.active_backend_port or cfg.backend_port, cfg.frontend_port)
    return 0


def cmd_stop() -> int:
    print()
    log_info("Shutting down...")

    # Frontend shutdown
    frontend_pid = PIDManager.read("frontend")
    if frontend_pid and PIDManager.is_alive(frontend_pid):
        PIDManager.kill_tree(frontend_pid)
        log_ok(f"Frontend stopped (PID {frontend_pid})")
    else:
        log(f"  {c('dim', 'Frontend not running')}")
    PIDManager.clear("frontend")

    # Backend shutdown (F1 / D-5 / D-8 / D-9)
    backend_stopped = False
    active_port = PIDManager.read_active_port()

    # 1. Active-port listener branch
    if active_port is not None:
        listener_pid = PortManager.get_pid_by_port(active_port)
        if listener_pid is not None:
            if PortManager.belongs_to_project(listener_pid):
                listener_create_time = _capture_process_create_time(listener_pid)
                supervisor = _backend_supervisor_pid(listener_pid)
                if supervisor is None or not PortManager.belongs_to_project(supervisor):
                    supervisor = listener_pid
                supervisor_create_time = (
                    listener_create_time
                    if supervisor == listener_pid
                    else _capture_process_create_time(supervisor)
                )

                if not _verify_process_identity(listener_pid, listener_create_time):
                    log_warn(
                        f"Process identity verification failed for listener PID {listener_pid} "
                        f"on port {active_port} — skipping kill"
                    )
                elif not _verify_process_identity(supervisor, supervisor_create_time):
                    log_warn(
                        f"Process identity verification failed for backend PID {supervisor} "
                        f"on port {active_port} — skipping kill"
                    )
                else:
                    PIDManager.kill_tree(supervisor)
                    # Verify port is freed
                    if (
                        not PortManager.can_bind(active_port)
                        and PortManager.get_pid_by_port(active_port) is not None
                    ):
                        time.sleep(0.5)

                    survivor = PortManager.get_pid_by_port(active_port)
                    if survivor is not None:
                        log_error(
                            f"Failed to free port {active_port}; "
                            f"untracked process {survivor} still listening"
                        )
                    else:
                        log_ok(f"Backend stopped (PID {supervisor})")
                        PIDManager.clear_active_port()
                        backend_stopped = True
                        _clear_backend_pid_if(supervisor)
                        if listener_pid != supervisor:
                            _clear_backend_pid_if(listener_pid)
            else:
                log_warn(
                    f"Port {active_port} is held by foreign PID {listener_pid} — not stopping"
                )
                PIDManager.clear_active_port()
        else:
            if not PortManager.can_bind(active_port) or PortManager.is_open(active_port):
                log_warn(
                    f"Port {active_port} is in use but ownership cannot be established "
                    "— not stopping"
                )
            PIDManager.clear_active_port()

    # 2. Stored backend.pid evaluation (D-8)
    stored_pid = PIDManager.read("backend")
    if stored_pid is not None:
        stored_create_time = _capture_process_create_time(stored_pid)
        if PIDManager.is_alive(stored_pid):
            if PortManager.belongs_to_project(stored_pid):
                if _verify_process_identity(stored_pid, stored_create_time):
                    PIDManager.kill_tree(stored_pid)
                    log_ok(f"Backend stopped (PID {stored_pid})")
                    backend_stopped = True
                    _clear_backend_pid_if(stored_pid)
                else:
                    log_warn(
                        f"Process identity verification failed for stored backend "
                        f"PID {stored_pid} — skipping kill"
                    )
            else:
                log_warn(
                    f"Stored backend PID {stored_pid} is foreign or unverified — skipping kill"
                )
        else:
            PIDManager.cleanup_stale()
            if not backend_stopped:
                log(f"  {c('dim', 'Backend not running')}")
    else:
        if not backend_stopped:
            log(f"  {c('dim', 'Backend not running')}")

    port_is_free = (
        active_port is None
        or (
            PortManager.can_bind(active_port)
            and not PortManager.is_open(active_port)
            and PortManager.get_pid_by_port(active_port) is None
        )
    )
    if port_is_free:
        PIDManager.clear_active_port()
    PIDManager.clear_started_at()
    log_ok("All processes stopped")
    print()
    return 0


def cmd_restart() -> int:
    cmd_stop()
    time.sleep(1)
    return cmd_start()


def cmd_status() -> int:
    StatusDisplay.show()
    return 0


def cmd_status_watch() -> int:
    StatusDisplay.watch()
    return 0


def cmd_logs() -> int:
    LogViewer.show()
    return 0


def cmd_self_test() -> int:
    results = SelfTester.run()
    SelfTester.print_report(results)
    return 0 if all(r.status for r in results) else 1


def cmd_open_vscode() -> None:
    try:
        log_step("VS Code", "Opening...")
        if os.name == "nt":
            subprocess.Popen(["code", str(PROJECT_ROOT)], shell=True)
        else:
            subprocess.Popen(["code", str(PROJECT_ROOT)])
        log_ok("VS Code opened")
    except FileNotFoundError:
        log_warn("VS Code 'code' command not found in PATH")


def cmd_install_node() -> int:
    print_banner()
    print(f"  {c('bold', '▸ Installing Node.js (20 LTS)')} {c('dim', '───')}\n")
    if os.name != "nt":
        log_info("Node.js auto-installer is only applicable on Windows.")
        return 0
    ok = auto_install_node_windows()
    return 0 if ok else 1


def cmd_install_cpp() -> int:
    print_banner()
    print(f"  {c('bold', '▸ Installing Microsoft C++ Build Tools')} {c('dim', '───')}\n")
    if os.name != "nt":
        log_info("Microsoft Visual C++ Build Tools are only applicable on Windows.")
        return 0
    ok = auto_install_cpp_tools_windows()
    return 0 if ok else 1


# ═══════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════


def main() -> int:
    MCS_DIR.mkdir(parents=True, exist_ok=True)

    raw_args = sys.argv[1:]
    args = [a.lower() for a in raw_args]

    global _unicode_enabled
    if "--ascii" in args or "--no-unicode" in args:
        _unicode_enabled = False
    elif "--unicode" in args or "--force-unicode" in args:
        _unicode_enabled = True

    if "--help" in args or "-h" in args:
        print_banner()
        print_usage()
        return 0

    if "--stop" in args:
        return cmd_stop()

    if "--restart" in args:
        return cmd_restart()

    if "--self-test" in args:
        return cmd_self_test()

    if "--install-node" in args or "--node" in args:
        return cmd_install_node()

    if "--install-cpp" in args or "--cpp-tools" in args:
        return cmd_install_cpp()

    if "--logs" in args:
        return cmd_logs()

    if "--status" in args:
        if "--watch" in args:
            return cmd_status_watch()
        return cmd_status()

    if "--code" in args or "--vscode" in args:
        cfg = ConfigManager.instance().load()
        cfg.open_vscode = True
        ConfigManager.instance().save()

    if "--swagger" in args:
        cfg = ConfigManager.instance().load()
        cfg.open_swagger = True
        ConfigManager.instance().save()

    return cmd_start()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        log_info("Interrupted. Shutting down...")
        cmd_stop()
        sys.exit(130)
    except Exception as exc:
        try:
            log_error(f"Unhandled error: {exc}")
        except Exception:
            try:
                safe_print(f"  [X] Unhandled error: {exc}")
            except Exception:
                pass
        import traceback
        try:
            traceback.print_exc()
        except Exception:
            pass
        sys.exit(1)
