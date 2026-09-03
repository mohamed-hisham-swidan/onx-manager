import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_permission
from app.core.identity import IDENTITY
from app.tasks.scheduler import CronJobModel, get_scheduler

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.schedules")

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

__all__ = ["router"]


class CreateScheduleRequest(BaseModel):
    name: str | None = None
    cron_expression: str = "0 0 * * *"
    task_name: str = "backup"
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


@router.get("", response_model=list[dict[str, Any]])
async def list_schedules(
    db: AsyncSession = Depends(get_db),
    _current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    stmt = select(CronJobModel).order_by(CronJobModel.created_at.desc())
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    out: list[dict[str, Any]] = []
    for j in jobs:
        params: dict[str, Any] = {}
        if j.params_json:
            try:
                params = json.loads(j.params_json)
            except Exception:
                params = {}
        out.append({
            "id": j.id,
            "name": j.name,
            "cron_expression": j.cron_expression,
            "task_name": j.task_name,
            "params": params,
            "enabled": bool(j.enabled),
            "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        })
    return out


@router.post("", response_model=dict[str, Any], status_code=201)
async def create_schedule(
    body: CreateScheduleRequest = CreateScheduleRequest(),
    db: AsyncSession = Depends(get_db),
    _current_user: dict = Depends(require_permission("global.settings")),
) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    sched_name = body.name or f"schedule-{job_id[:8]}"

    stmt = select(CronJobModel).where(CronJobModel.name == sched_name)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Schedule '{sched_name}' already exists")

    now = datetime.now(UTC)
    model = CronJobModel(
        id=job_id,
        name=sched_name,
        cron_expression=body.cron_expression,
        task_name=body.task_name,
        params_json=json.dumps(body.params or {}),
        enabled=1 if body.enabled else 0,
        created_at=now,
    )
    db.add(model)
    await db.commit()

    scheduler = get_scheduler()
    if scheduler and getattr(scheduler, "_aps", None):
        try:
            scheduler._schedule_job(model)
        except Exception as e:
            logger.warning("Failed to schedule job in running APScheduler: %s", e)

    return {
        "success": True,
        "schedule_id": job_id,
        "id": job_id,
        "name": sched_name,
        "cron_expression": body.cron_expression,
        "task_name": body.task_name,
        "params": body.params,
        "enabled": body.enabled,
        "created_at": now.isoformat(),
    }


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: dict = Depends(require_permission("global.settings")),
) -> None:
    model = await db.get(CronJobModel, schedule_id)
    if model is not None:
        await db.delete(model)
        await db.commit()

    scheduler = get_scheduler()
    if scheduler and getattr(scheduler, "_aps", None) and scheduler._aps.get_job(schedule_id):
        try:
            scheduler._aps.remove_job(schedule_id)
        except Exception as e:
            logger.warning("Failed to remove job from running APScheduler: %s", e)
