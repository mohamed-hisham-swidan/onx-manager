from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import sys
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel

logger = logging.getLogger(__name__)

MAX_BUFFER_LINES = 2000
BUFFER_RETAIN_ON_DROP = 500
MAX_BATCH_LINES = 50
BATCH_TIMEOUT_SECONDS = 0.1
DEBOUNCE_SECONDS = 5.0
MAX_FRAME_BYTES = 64 * 1024  # 64 KB per WS frame (well under 256 KB cap)


def partition_lines_by_size(lines: list[str], max_bytes: int = MAX_FRAME_BYTES) -> list[list[str]]:
    """Partition a list of strings into sub-lists whose JSON byte length stays <= max_bytes."""
    if not lines:
        return []
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_bytes = 2  # account for '[]'

    for line in lines:
        line_bytes = len(json.dumps(line, ensure_ascii=False).encode("utf-8")) + 1  # comma
        if current_chunk and (current_bytes + line_bytes > max_bytes):
            chunks.append(current_chunk)
            current_chunk = [line]
            current_bytes = 2 + line_bytes
        else:
            current_chunk.append(line)
            current_bytes += line_bytes

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


class ConsoleStreamManager:
    """Manages demand-driven follower loops for live servers and test containers.

    Active only when channel subscriber count >= 1; shuts down after a 5s debounce
    when subscribers drop to 0. Emits visible backpressure drop markers on queue overflow.
    """

    def __init__(
        self,
        broadcast_fn: Callable[[str, list[str]], Awaitable[int]],
        debounce_seconds: float = DEBOUNCE_SECONDS,
        batch_lines: int = MAX_BATCH_LINES,
        batch_timeout: float = BATCH_TIMEOUT_SECONDS,
        max_buffer_lines: int = MAX_BUFFER_LINES,
    ) -> None:
        self._broadcast_fn = broadcast_fn
        self._debounce_seconds = debounce_seconds
        self._batch_lines = batch_lines
        self._batch_timeout = batch_timeout
        self._max_buffer_lines = max_buffer_lines
        self._streams: dict[str, asyncio.Task[None]] = {}
        self._debounce_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._running = False

    def is_channel_active(self, channel: str) -> bool:
        return channel in self._streams and not self._streams[channel].done()

    async def on_subscription_change(self, channel: str, count: int) -> None:
        """Invoked by ConnectionRegistry when subscriber count for a channel changes."""
        if not self._is_console_channel(channel):
            return

        async with self._lock:
            if count > 0:
                # Cancel pending debounce shutdown if active
                deb = self._debounce_tasks.pop(channel, None)
                if deb and not deb.done():
                    deb.cancel()

                # Start follower task if not already running
                task = self._streams.get(channel)
                if task is None or task.done():
                    self._streams[channel] = asyncio.create_task(
                        self._run_stream_loop(channel),
                        name=f"console-stream-{channel}",
                    )
            else:
                # Subscribers dropped to 0: start debounce stop
                if channel in self._streams and channel not in self._debounce_tasks:
                    self._debounce_tasks[channel] = asyncio.create_task(
                        self._debounce_stop(channel),
                        name=f"console-debounce-{channel}",
                    )

    async def _debounce_stop(self, channel: str) -> None:
        try:
            await asyncio.sleep(self._debounce_seconds)
            async with self._lock:
                self._debounce_tasks.pop(channel, None)
                task = self._streams.pop(channel, None)
                if task and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
        except asyncio.CancelledError:
            pass

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        async with self._lock:
            for deb in self._debounce_tasks.values():
                if not deb.done():
                    deb.cancel()
            self._debounce_tasks.clear()

            for task in self._streams.values():
                if not task.done():
                    task.cancel()
            for task in list(self._streams.values()):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._streams.clear()

    @staticmethod
    def _is_console_channel(channel: str) -> bool:
        parts = channel.split(":")
        return len(parts) == 3 and parts[0] in ("server", "test") and parts[2] == "console"

    async def _resolve_target(self, channel: str) -> tuple[str, str, Path | None]:
        """Resolve channel to (target_name, mode, log_path).

        mode is one of: "docker", "tmux", "file_tail".
        log_path is populated when mode is "file_tail".
        """
        parts = channel.split(":")
        target_type = parts[0]
        target_id = parts[1]

        if target_type == "test":
            return f"onx-test-{target_id}", "docker", None

        # Live server
        async with database.session_factory() as session:
            server = await session.get(ServerModel, target_id)
            if server:
                provider = (server.provider or "docker").lower()
                external_id = server.external_id or ""

                server_dir: Path | None = None
                if server.root_path:
                    server_dir = Path(server.root_path)
                    if server.working_directory and server.working_directory != ".":
                        server_dir = server_dir / server.working_directory
                if not server_dir:
                    from app.core.config import AppSettings

                    server_dir = Path(AppSettings().servers_data_dir).resolve() / target_id

                log_path = server_dir / "logs" / "latest.log"

                is_local = provider in ("local", "local_linux", "local_windows")
                is_windows_local = provider == "local_windows" or (
                    is_local and sys.platform == "win32"
                )

                if is_windows_local:
                    return external_id, "file_tail", log_path

                if is_local:
                    if external_id:
                        return external_id, "tmux", None
                    return "", "file_tail", log_path

                # Docker provider
                if external_id:
                    return external_id, "docker", None

                # Stopped Docker server: use disk log fallback
                return "", "file_tail", log_path

        from app.core.config import AppSettings

        default_dir = Path(AppSettings().servers_data_dir).resolve() / target_id
        return "", "file_tail", default_dir / "logs" / "latest.log"

    async def _run_stream_loop(self, channel: str) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue()
        flusher_task: asyncio.Task[None] | None = None
        producer_task: asyncio.Task[None] | None = None

        try:
            target_name, mode, log_path = await self._resolve_target(channel)

            flusher_task = asyncio.create_task(
                self._flusher(channel, queue),
                name=f"flusher-{channel}",
            )

            if mode == "docker" and target_name:
                producer_task = asyncio.create_task(
                    self._docker_logs_producer(target_name, queue),
                    name=f"docker-producer-{channel}",
                )
            elif mode == "file_tail" and log_path is not None:
                producer_task = asyncio.create_task(
                    self._file_tail_producer(log_path, queue),
                    name=f"file-tail-producer-{channel}",
                )
            elif mode == "tmux" and target_name:
                producer_task = asyncio.create_task(
                    self._tmux_poll_producer(target_name, queue),
                    name=f"tmux-producer-{channel}",
                )
            elif log_path is not None:
                producer_task = asyncio.create_task(
                    self._file_tail_producer(log_path, queue),
                    name=f"file-tail-producer-{channel}",
                )

            if producer_task is None:
                return

            done, pending = await asyncio.wait(
                [producer_task, flusher_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await p
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Console stream loop failed for %s: %s", channel, exc)
        finally:
            if producer_task and not producer_task.done():
                producer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer_task
            if flusher_task and not flusher_task.done():
                flusher_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await flusher_task

    async def _enqueue_line(self, queue: asyncio.Queue[str], line: str) -> None:
        """Enqueue line with backpressure buffer drop & visible marker injection (Task 8)."""
        if queue.qsize() >= self._max_buffer_lines:
            dropped = 0
            retain = min(BUFFER_RETAIN_ON_DROP, max(1, self._max_buffer_lines // 2))
            while queue.qsize() > retain:
                try:
                    queue.get_nowait()
                    dropped += 1
                except asyncio.QueueEmpty:
                    break
            if dropped > 0:
                marker = f"[{dropped} lines dropped — buffer overflow]"
                await queue.put(marker)
        await queue.put(line)

    @staticmethod
    async def _drain_stderr(stream: asyncio.StreamReader, container_name: str) -> None:
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                logger.debug(
                    "docker logs stderr [%s]: %s",
                    container_name,
                    line.decode("utf-8", errors="replace").rstrip(),
                )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("docker logs stderr reader error [%s]: %s", container_name, exc)

    async def _docker_logs_producer(
        self,
        container_name: str,
        queue: asyncio.Queue[str],
    ) -> None:
        backoff = 1.0
        while self._running:
            proc = None
            stderr_task = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "logs",
                    "--follow",
                    "--timestamps",
                    "--tail",
                    "0",
                    container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                backoff = 1.0
                if proc.stdout is None:
                    break

                if proc.stderr is not None:
                    stderr_task = asyncio.create_task(
                        self._drain_stderr(proc.stderr, container_name),
                        name=f"docker-stderr-{container_name}",
                    )

                while self._running:
                    raw_line = await proc.stdout.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    await self._enqueue_line(queue, line)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("docker logs stream for %s encountered: %s", container_name, exc)
            finally:
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stderr_task
                if proc and proc.returncode is None:
                    with contextlib.suppress(Exception):
                        proc.kill()
                    with contextlib.suppress(Exception):
                        await proc.wait()

            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(10.0, backoff * 2)

    async def _tmux_poll_producer(
        self,
        session_name: str,
        queue: asyncio.Queue[str],
    ) -> None:
        seen_hashes: deque[str] = deque(maxlen=300)
        while self._running:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "tmux",
                    "capture-pane",
                    "-t",
                    session_name,
                    "-p",
                    "-S",
                    "-50",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and stdout:
                    for raw in stdout.decode("utf-8", errors="replace").splitlines():
                        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                        if h not in seen_hashes:
                            seen_hashes.append(h)
                            await self._enqueue_line(queue, raw)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("tmux poll producer for %s encountered: %s", session_name, exc)
            await asyncio.sleep(0.25)

    async def _file_tail_producer(
        self,
        log_path: Path,
        queue: asyncio.Queue[str],
    ) -> None:
        log_path = Path(log_path)
        last_offset = 0
        try:
            if log_path.is_file():
                last_offset = log_path.stat().st_size
        except OSError:
            last_offset = 0

        while self._running:
            try:
                if log_path.is_file():
                    current_size = log_path.stat().st_size
                    if current_size < last_offset:
                        # File was truncated or rotated
                        last_offset = 0

                    if current_size > last_offset:
                        with open(log_path, encoding="utf-8", errors="replace") as f:
                            f.seek(last_offset)
                            while self._running:
                                line = f.readline()
                                if not line:
                                    break
                                await self._enqueue_line(queue, line.rstrip("\r\n"))
                                last_offset = f.tell()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("file tail producer for %s encountered: %s", log_path, exc)

            try:
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                break

    async def _flusher(
        self,
        channel: str,
        queue: asyncio.Queue[str],
    ) -> None:
        while self._running:
            batch: list[str] = []
            try:
                first = await asyncio.wait_for(queue.get(), timeout=self._batch_timeout)
                batch.append(first)
                while len(batch) < self._batch_lines and not queue.empty():
                    batch.append(queue.get_nowait())
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                break

            if batch:
                chunks = partition_lines_by_size(batch, max_bytes=MAX_FRAME_BYTES)
                for chunk in chunks:
                    try:
                        await self._broadcast_fn(channel, chunk)
                    except Exception as exc:
                        logger.debug("Broadcast failed on %s: %s", channel, exc)
