from __future__ import annotations

import json
from datetime import UTC
from typing import Any

from app.tasks.base import TaskQueue, TaskStatus


class ArqQueue(TaskQueue):
    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = redis_url
        self._pool: Any = None
        self._arq_redis: Any = None

    async def _get_redis(self) -> Any:
        if self._arq_redis is None:
            import aredis

            self._pool = aredis.ConnectionPool.from_url(self._redis_url)
            self._arq_redis = aredis.Redis(connection_pool=self._pool)
        return self._arq_redis

    async def enqueue(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        delay: int = 0,
    ) -> str:
        import uuid
        from datetime import datetime

        task_id = uuid.uuid4().hex
        job_data = json.dumps(
            {
                "task_id": task_id,
                "name": name,
                "params": params or {},
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        r = await self._get_redis()

        if delay > 0:
            import time

            await r.zadd("arq:delayed", {job_data: time.time() + delay})
        else:
            await r.lpush(f"arq:queue:{name}", job_data)

        return task_id

    async def cancel(self, task_id: str) -> bool:
        r = await self._get_redis()
        keys = await r.keys("arq:queue:*")
        for key in keys:
            items = await r.lrange(key, 0, -1)
            for item in items:
                data = json.loads(item)
                if data.get("task_id") == task_id:
                    await r.lrem(key, 1, item)
                    return True
        return False

    async def get_status(self, task_id: str) -> TaskStatus:
        return TaskStatus.PENDING

    async def get_result(self, task_id: str) -> Any:
        return None

    async def close(self) -> None:
        if self._arq_redis:
            await self._arq_redis.close()
        if self._pool:
            await self._pool.disconnect()
