from __future__ import annotations

import asyncio
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass, field

from app.core.container_hardening import (
    hardening_args,
    validate_data_only_mounts,
)
from app.core.exceptions import BotRunnerUnavailableError
from app.core.settings_store import get_live_settings

logger = logging.getLogger(__name__)


@dataclass
class PooledRunner:
    runner_id: str
    container_name: str
    image: str
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    is_busy: bool = False

    def is_alive(self) -> bool:
        """Inspects Docker container status directly via Docker CLI."""
        try:
            res = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0 and res.stdout.strip().lower() == "true"
        except Exception:
            return False

    def execute_reset(self) -> bool:
        """Executes reset entrypoint inside runner container to purge all bot state."""
        try:
            # Kill any running node or bot processes
            res = subprocess.run(
                ["docker", "exec", self.container_name, "sh", "-c", "pkill -f node || true"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return res.returncode == 0 and self.is_alive()
        except Exception as e:
            logger.warning("Reset failed on runner %s: %s", self.container_name, e)
            return False

    def destroy(self) -> None:
        """Forcibly stops and removes the runner container."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as e:
            logger.debug("Failed to remove container %s: %s", self.container_name, e)


class BotRunnerPool:
    """In-memory pool managing reusable warm sidecar bot runner containers.

    Enforces Design Spec §3.5.5:
    - Default 2 warm idle sidecars, up to 4 concurrent runners (LiveSettings configurable).
    - Compute-only shells with strict state-reset between runs.
    - Health check on acquire with automatic retry and eviction.
    - fakeplayer_next and in_container runs bypass this pool entirely.
    """

    DEFAULT_SIDECAR_IMAGE = "node:20-alpine"

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._idle: list[PooledRunner] = []
        self._active: dict[str, PooledRunner] = {}

    @property
    def idle_count(self) -> int:
        return len(self._idle)

    @property
    def active_count(self) -> int:
        return len(self._active)

    async def acquire(
        self,
        image: str | None = None,
        bridge_network: str = "bridge",
        timeout: float | None = None,
    ) -> PooledRunner:
        """Acquires an idle healthy runner, spinning up a new one if below max pool capacity."""
        target_image = image or self.DEFAULT_SIDECAR_IMAGE
        try:
            live = get_live_settings()
            pool_max = getattr(live, "bot_pool_max", 4)
            retries = getattr(live, "bot_pool_acquire_retries", 2)
        except Exception:
            pool_max = 4
            retries = 2

        attempts = 0
        last_error = ""
        deadline = (time.time() + timeout) if timeout is not None else None

        while attempts <= retries:
            if deadline is not None and time.time() > deadline:
                raise TimeoutError(f"Timed out acquiring bot runner after {timeout}s")

            attempts += 1
            # 1. Look for existing idle runner
            while True:
                candidate = None
                async with self._lock:
                    if self._idle:
                        candidate = self._idle.pop(0)
                if candidate is None:
                    break

                is_alive = await asyncio.to_thread(candidate.is_alive)
                if candidate.image == target_image and is_alive:
                    async with self._lock:
                        candidate.is_busy = True
                        candidate.last_used_at = time.time()
                        self._active[candidate.runner_id] = candidate
                    logger.info("Acquired warm runner from pool: %s", candidate.container_name)
                    return candidate
                else:
                    logger.info(
                        "Evicting dead/mismatched idle runner: %s", candidate.container_name
                    )
                    await asyncio.to_thread(candidate.destroy)

            async with self._lock:
                # 2. If below max concurrent capacity, spin up a new container
                if len(self._active) < pool_max:
                    runner_id = uuid.uuid4().hex[:8]
                    container_name = f"onx-bot-runner-{runner_id}"
                    cmd = [
                        "docker",
                        "run",
                        "-d",
                        "--name",
                        container_name,
                        "--network",
                        bridge_network,
                        "--restart",
                        "no",
                        *hardening_args(),
                        target_image,
                        "sleep",
                        "infinity",
                    ]
                    validate_data_only_mounts(cmd, image=target_image)
                    try:
                        res = await asyncio.to_thread(
                            subprocess.run, cmd, capture_output=True, text=True, timeout=30
                        )
                        if res.returncode == 0:
                            runner = PooledRunner(
                                runner_id=runner_id,
                                container_name=container_name,
                                image=target_image,
                                is_busy=True,
                            )
                            self._active[runner_id] = runner
                            logger.info("Created new runner in pool: %s", container_name)
                            return runner
                        else:
                            last_error = res.stderr.strip()
                    except Exception as e:
                        last_error = str(e)

            # If we reach here, retry after brief delay
            sleep_time = 0.5
            if deadline is not None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out acquiring bot runner after {timeout}s")
                sleep_time = min(sleep_time, remaining)
            await asyncio.sleep(sleep_time)

        raise BotRunnerUnavailableError(
            message=(
                f"No healthy bot runner could be acquired from pool after {retries} retries: "
                f"{last_error}"
            ),
            details={"attempts": attempts, "last_error": last_error},
        )

    async def release(self, runner: PooledRunner, outcome: str = "clean") -> None:
        """Releases a runner back to the pool, resetting state or destroying on failure."""
        async with self._lock:
            self._active.pop(runner.runner_id, None)

            try:
                live = get_live_settings()
                pool_idle = getattr(live, "bot_pool_idle", 2)
            except Exception:
                pool_idle = 2

            eligible = outcome == "clean" and len(self._idle) < pool_idle

        if eligible:
            is_alive = await asyncio.to_thread(runner.is_alive)
            if is_alive:
                reset_ok = await asyncio.to_thread(runner.execute_reset)
                if reset_ok:
                    async with self._lock:
                        if len(self._idle) < pool_idle:
                            runner.is_busy = False
                            self._idle.append(runner)
                            logger.info(
                                "Runner %s reset cleanly and returned to idle pool.",
                                runner.container_name,
                            )
                            return

        logger.info(
            "Destroying released runner %s (outcome=%s)", runner.container_name, outcome
        )
        await asyncio.to_thread(runner.destroy)

    async def destroy_all(self) -> None:
        """Destroys all active and idle containers in the pool."""
        async with self._lock:
            all_runners = list(self._idle) + list(self._active.values())
            self._idle.clear()
            self._active.clear()

        for r in all_runners:
            await asyncio.to_thread(r.destroy)


# Global in-memory pool singleton for versioning subsystem
_runner_pool: BotRunnerPool | None = None


def get_bot_runner_pool() -> BotRunnerPool:
    global _runner_pool
    if _runner_pool is None:
        _runner_pool = BotRunnerPool()
    return _runner_pool
