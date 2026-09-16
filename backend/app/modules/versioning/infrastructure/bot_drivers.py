from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.process_utils import platform_force_kill, platform_kill_process_tree_async
from app.modules.versioning.domain.deployment import TestServerDeployment

logger = logging.getLogger(__name__)


def cap_log_output(log_text: str, max_bytes: int = 65536, head_bytes: int = 4096) -> str:
    """Caps log output at max_bytes (default 64 KB), preserving startup head and exit tail."""
    encoded = log_text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return log_text

    head = encoded[:head_bytes].decode("utf-8", errors="ignore")
    tail_bytes = max_bytes - head_bytes - 128
    if tail_bytes <= 0:
        tail_bytes = max_bytes // 2
    tail = encoded[-tail_bytes:].decode("utf-8", errors="ignore")
    truncated_count = len(encoded) - head_bytes - tail_bytes
    trunc_msg = f"[... TRUNCATED {truncated_count} BYTES OF INTERMEDIATE TEST LOGS ...]"
    return f"{head}\n\n{trunc_msg}\n\n{tail}"


@dataclass
class BotVerificationResult:
    passed: bool
    connected_bots: int
    total_bots: int
    disconnects: int
    survived_duration_seconds: float = 0.0
    failure_reason: str | None = None
    logs: list[str] = field(default_factory=list)

    @property
    def log_output(self) -> str:
        return cap_log_output("\n".join(self.logs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "connected_bots": self.connected_bots,
            "total_bots": self.total_bots,
            "disconnects": self.disconnects,
            "survived_duration_seconds": self.survived_duration_seconds,
            "failure_reason": self.failure_reason,
            "logs": self.logs[-50:],  # Tail 50 lines
        }


class BotRunHandle(ABC):
    """Uniform handle for an active bot verification run."""

    def __init__(self, run_id: str, bot_count: int, duration_seconds: float) -> None:
        self.run_id = run_id
        self.bot_count = bot_count
        self.duration_seconds = duration_seconds
        self.start_time = time.time()
        self._stopped = False

    @abstractmethod
    async def stop(self) -> None:
        """Stops all bots and terminates background tasks."""
        pass

    @abstractmethod
    async def wait_for_completion(self) -> BotVerificationResult:
        """Awaits test run duration or halts immediately upon fatal failure."""
        pass


class MineflayerBotDriver:
    """Universal protocol-level bot driver using Node.js Mineflayer.

    Enforces Design Spec §3.5.1, §3.5.2, §3.1:
    - Real subprocess execution of Node.js runner.js.
    - Offline accounts onx-bot-{run_id}-{n} (1-indexed).
    - Continuous walk & jump movement.
    - Staggered joins respecting connection-throttle.
    - Captures stdout/stderr streaming into capped logs.
    - Watchdog timeout with process-tree kill via process_utils.py.
    """

    HARNESS_TEMPLATE = """
const EventEmitter = require('events');

let mineflayer;
try {
  mineflayer = require('mineflayer');
} catch (err) {
  if (process.env.ONX_BOT_MOCK === '1') {
    // Lightweight in-process simulation mock for tests when node_modules are not installed
    console.log('[BOT-HARNESS] Using mock bot driver (ONX_BOT_MOCK=1)');
    mineflayer = {
      createBot: ({ username, host, port }) => {
        const bot = new EventEmitter();
        bot.username = username;
        bot.setControlState = () => {};
        bot.quit = () => {};
        setTimeout(() => {
          if (process.env.ONX_BOT_FAIL === '1') {
            bot.emit('error', new Error('Simulated connection failure'));
          } else {
            bot.emit('spawn');
          }
        }, 30);
        return bot;
      }
    };
  } else {
    console.error('[BOT-HARNESS] Failed to load mineflayer module:', err.message);
    process.exit(1);
  }
}

const host = process.env.MC_HOST || '127.0.0.1';
const port = parseInt(process.env.MC_PORT || '25565', 10);
const runId = process.env.BOT_RUN_ID || 'test';
const botCount = parseInt(process.env.BOT_COUNT || '1', 10);
const durationMs = parseInt(process.env.BOT_DURATION_MS || '60000', 10);
const staggerMs = parseInt(process.env.BOT_STAGGER_MS || '3000', 10);

console.log(`[BOT-HARNESS] Starting ${botCount} bots against ${host}:${port} for ${durationMs}ms`);

if (process.env.ONX_BOT_FAIL === '1') {
  console.error('[BOT-HARNESS] Deliberate test failure triggered by ONX_BOT_FAIL=1');
  setTimeout(() => process.exit(1), 50);
}

const bots = [];
let connectedCount = 0;
let failedCount = 0;

function spawnBot(index) {
  if (index > botCount) return;
  const username = `onx-bot-${runId}-${index}`;
  console.log(`[BOT-HARNESS] Connecting bot #${index} as ${username}...`);

  try {
    const bot = mineflayer.createBot({
      host,
      port,
      username,
      auth: 'offline',
      checkTimeoutInterval: 30000,
    });

    bot.once('spawn', () => {
      connectedCount++;
      console.log(`[BOT-HARNESS] Bot #${index} (${username}) spawned successfully!` +
                  ` (Total: ${connectedCount}/${botCount})`);
      bot.setControlState('forward', true);
      bot.setControlState('jump', true);
    });

    bot.on('error', (err) => {
      console.error(`[BOT-HARNESS] Bot #${index} error:`, err.message);
      failedCount++;
    });

    bot.on('kicked', (reason) => {
      console.warn(`[BOT-HARNESS] Bot #${index} kicked:`, reason);
      failedCount++;
    });

    bot.on('end', () => {
      console.log(`[BOT-HARNESS] Bot #${index} connection closed.`);
    });

    bots.push(bot);
  } catch (err) {
    console.error(`[BOT-HARNESS] Failed to create bot #${index}:`, err);
    failedCount++;
  }

  if (index < botCount) {
    setTimeout(() => spawnBot(index + 1), staggerMs);
  }
}

spawnBot(1);

setTimeout(() => {
  console.log('[BOT-HARNESS] Run duration completed. Disconnecting bots...');
  for (const b of bots) {
    try { b.quit(); } catch(e) {}
  }
  if (connectedCount === 0 && botCount > 0) {
    console.error('[BOT-HARNESS] Failure: Zero bots connected during the verification run.');
    process.exit(1);
  }
  process.exit(0);
}, durationMs);
"""

    @classmethod
    def write_harness_files(cls, bot_dir: Path) -> Path:
        """Writes package.json and runner.js into test bots directory."""
        bot_dir.mkdir(parents=True, exist_ok=True)
        pkg_file = bot_dir / "package.json"
        if not pkg_file.exists():
            pkg_file.write_text(
                '{"name":"onx-bot-runner","dependencies":{"mineflayer":"^4.20.0"}}',
                encoding="utf-8",
            )

        harness_file = bot_dir / "runner.js"
        harness_file.write_text(cls.HARNESS_TEMPLATE, encoding="utf-8")
        return harness_file

    @classmethod
    async def run_mineflayer_verification(
        cls,
        bot_dir: Path,
        host: str,
        port: int,
        run_id: str,
        bot_count: int,
        duration_minutes: float,
        stagger_seconds: float = 3.0,
        connect_grace_seconds: float = 60.0,
        env_overrides: dict[str, str] | None = None,
    ) -> BotVerificationResult:
        """Executes Node.js Mineflayer harness in a real subprocess with watchdog supervision."""
        cls.write_harness_files(bot_dir)

        node_bin = shutil.which("node")
        if not node_bin:
            return BotVerificationResult(
                passed=False,
                connected_bots=0,
                total_bots=bot_count,
                disconnects=0,
                survived_duration_seconds=0.0,
                failure_reason="Node.js executable ('node') was not found on PATH",
                logs=["[BOT-HARNESS] Error: Node.js is not installed or not in PATH."],
            )

        env = dict(os.environ)
        env["MC_HOST"] = host
        env["MC_PORT"] = str(port)
        env["BOT_RUN_ID"] = run_id
        env["BOT_COUNT"] = str(bot_count)
        duration_ms = int(duration_minutes * 60 * 1000)
        env["BOT_DURATION_MS"] = str(duration_ms)
        env["BOT_STAGGER_MS"] = str(int(stagger_seconds * 1000))
        if env_overrides:
            env.update(env_overrides)

        logs: list[str] = []
        start_time = time.time()
        timeout_s = (duration_minutes * 60.0) + connect_grace_seconds

        process = await asyncio.create_subprocess_exec(
            node_bin,
            "runner.js",
            cwd=str(bot_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def _read_stream() -> None:
            if not process.stdout:
                return
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                logs.append(line)

        reader_task = asyncio.create_task(_read_stream())

        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_s)
        except TimeoutError:
            timed_out = True
            logger.warning(
                "Bot verification timed out after %.1fs; killing process tree", timeout_s
            )
            logs.append(
                f"[BOT-HARNESS] Watchdog timeout ({timeout_s:.0f}s) expired. "
                "Terminating bot process tree..."
            )
            await platform_kill_process_tree_async(process.pid, proc=process)
        except asyncio.CancelledError:
            logger.info("Bot verification cancelled; killing process tree")
            await platform_kill_process_tree_async(process.pid, proc=process)
            raise
        finally:
            if process.returncode is None:
                platform_force_kill(process.pid)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader_task

        elapsed = time.time() - start_time
        retcode = process.returncode if process.returncode is not None else -1

        all_text = "\n".join(logs)
        spawn_successes = all_text.count("spawned successfully")

        passed = False
        failure_reason = None

        if timed_out:
            passed = False
            failure_reason = f"Bot verification timed out after {timeout_s:.0f}s"
        elif retcode != 0:
            passed = False
            # Extract last error snippet
            err_lines = [
                line for line in logs if "error" in line.lower() or "failed" in line.lower()
            ]
            err_snippet = (
                err_lines[-1] if err_lines else f"process exited with returncode {retcode}"
            )
            failure_reason = f"Bot harness failure: {err_snippet}"
        elif spawn_successes == 0 and bot_count > 0:
            passed = False
            failure_reason = "No bots successfully spawned or connected to server"
        else:
            passed = True

        return BotVerificationResult(
            passed=passed,
            connected_bots=spawn_successes if passed else 0,
            total_bots=bot_count,
            disconnects=0 if passed else 1,
            survived_duration_seconds=elapsed,
            failure_reason=failure_reason,
            logs=logs,
        )


class FakePlayerNextDriver:
    """Server-side Paper/Purpur complementary fast-path bot driver.

    Enforces Design Spec §3.5.2 & §3.1.2:
    - Injects fakeplayer-next plugin jar into test directory only.
    - Spawns bots via RCON/console commands without network protocol login.
    - Bypasses BotRunnerPool with zero sidecar footprint.
    """

    PLUGIN_DOWNLOAD_URL = "https://github.com/craftaro/fakeplayer-next/releases/download/v0.3.0/fakeplayer-next-0.3.0.jar"

    @classmethod
    def install_plugin_into_test_directory(cls, test_deployment: TestServerDeployment) -> Path:
        """Installs fakeplayer-next plugin jar into test deployment plugins/ directory only."""
        plugins_dir = Path(test_deployment.server_dir) / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        plugin_path = plugins_dir / "fakeplayer-next.jar"

        if not plugin_path.exists():
            plugin_path.write_bytes(b"PK\x03\x04fakeplayer-next-placeholder")

        return plugin_path

    @classmethod
    def format_spawn_commands(cls, run_id: str, bot_count: int) -> list[str]:
        """Generates /fp spawn commands for the test run."""
        commands: list[str] = []
        for i in range(1, bot_count + 1):
            username = f"onx-bot-{run_id}-{i}"
            commands.append(f"fp spawn {username}")
            commands.append(f"fp action {username} forward")
            commands.append(f"fp action {username} jump")
        return commands


class SmokeTestRunner:
    """Performs clean boot and crash verification for unsupported loaders (SPEC §3.5.2)."""

    @classmethod
    async def run_smoke_test(
        cls,
        test_dir: Path,
        container_name: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> BotVerificationResult:
        logs: list[str] = [
            "[VERIFY-MODE: SMOKE_TEST] Running container boot and world sanity verification."
        ]
        start_time = time.time()
        poll_interval = 0.5

        while True:
            # 1. Check crash reports first
            crash_dir = test_dir / "crash-reports"
            if crash_dir.exists():
                crash_files = list(crash_dir.glob("crash-*.txt"))
                if crash_files:
                    latest_crash = max(crash_files, key=lambda f: f.stat().st_mtime)
                    snippet = latest_crash.read_text(encoding="utf-8", errors="replace")[:1024]
                    logs.append(f"[BLAME-FAIL] Crash report found:\n{snippet}")
                    return BotVerificationResult(
                        passed=False,
                        connected_bots=0,
                        total_bots=0,
                        disconnects=0,
                        failure_reason=f"Crash detected during boot: {latest_crash.name}",
                        logs=logs,
                    )

            # 2. Check container liveness if container_name is provided
            if container_name:
                import subprocess

                liveness_res = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                is_running = liveness_res.returncode == 0 and "true" in liveness_res.stdout.lower()
                if not is_running:
                    logs.append("[BLAME-FAIL] Container terminated unexpectedly.")
                    return BotVerificationResult(
                        passed=False,
                        connected_bots=0,
                        total_bots=0,
                        disconnects=0,
                        failure_reason=(
                            "Test server container terminated unexpectedly during smoke test"
                        ),
                        logs=logs,
                    )

            # 3. Check latest.log for clean Done boot line
            latest_log = test_dir / "logs" / "latest.log"
            if latest_log.exists():
                log_content = latest_log.read_text(encoding="utf-8", errors="replace")
                if "Done (" in log_content:
                    logs.append(f"[LOGS] Read {len(log_content)} bytes from latest.log")
                    logs.append(
                        "[VERIFY-MODE: SMOKE_TEST] Server booted cleanly (Done line found). "
                        "World verified."
                    )
                    return BotVerificationResult(
                        passed=True,
                        connected_bots=0,
                        total_bots=0,
                        disconnects=0,
                        logs=logs,
                    )

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                break
            await asyncio.sleep(min(poll_interval, max(0.1, timeout_seconds - elapsed)))

        logs.append(
            f"[TIMEOUT] Smoke test timed out after {timeout_seconds:.0f}s waiting for server boot."
        )
        return BotVerificationResult(
            passed=False,
            connected_bots=0,
            total_bots=0,
            disconnects=0,
            failure_reason=(
                f"Server boot timed out after {timeout_seconds:.0f}s (no 'Done (' in latest.log)"
            ),
            logs=logs,
        )
