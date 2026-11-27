import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_schedule_permission
from app.core.authorization import authorize_server_action, is_admin_or_owner_context
from app.core.identity import IDENTITY
from app.core.timeutil import format_datetime_utc
from app.tasks.scheduler import (
    ALLOWED_GLOBAL_TASKS,
    ALLOWED_SERVER_TASKS,
    MIN_USER_SCHEDULE_INTERVAL_SECONDS,
    CronJobModel,
    Scheduler,
    get_scheduler,
    validate_cleanup_params,
)

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.schedules")

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

__all__ = ["router"]


def _normalize_task_name(task_name: str | None) -> str:
    cleaned = (task_name or "").strip()
    if not cleaned or cleaned == "backup":
        return "run_backup_task"
    return cleaned


class CreateScheduleRequest(BaseModel):
    name: str | None = None
    cron_expression: str = "0 0 * * *"
    task_name: str = "run_backup_task"
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


@router.get("", response_model=list[dict[str, Any]])
async def list_schedules(
    server_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    is_admin = is_admin_or_owner_context(current_user)
    if (
        server_id
        and not is_admin
        and not authorize_server_action(current_user, server_id, "backups.view")
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
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
        job_sid = params.get("server_id") if isinstance(params, dict) else None
        if server_id and job_sid != server_id:
            continue
        if not is_admin and (
            not job_sid
            or not authorize_server_action(current_user, str(job_sid), "backups.view")
        ):
            continue
        out.append({
            "id": j.id,
            "name": j.name,
            "cron_expression": j.cron_expression,
            "task_name": _normalize_task_name(j.task_name),
            "params": params,
            "enabled": bool(j.enabled),
            "last_run_at": format_datetime_utc(j.last_run_at) if j.last_run_at else None,
            "created_at": format_datetime_utc(j.created_at) if j.created_at else None,
        })
    return out


@router.post("", response_model=dict[str, Any], status_code=201)
async def create_schedule(
    body: CreateScheduleRequest = Body(default_factory=CreateScheduleRequest),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_schedule_permission("settings:write")),
) -> dict[str, Any]:
    normalized_task_name = _normalize_task_name(body.task_name)
    is_admin = is_admin_or_owner_context(current_user)
    params = dict(body.params or {})

    if is_admin:
        if normalized_task_name not in ALLOWED_GLOBAL_TASKS:
            raise HTTPException(
                status_code=400,
                detail=f"Task '{normalized_task_name}' is not an allowed schedulable task",
            )
    else:
        if normalized_task_name not in ALLOWED_SERVER_TASKS:
            raise HTTPException(
                status_code=403,
                detail=f"Only owner or admin may schedule task '{normalized_task_name}'",
            )
        target_sid = params.get("server_id")
        if not target_sid or not authorize_server_action(current_user, str(target_sid), "backups"):
            raise HTTPException(
                status_code=403,
                detail="Server-scoped schedules must target an authorized server_id",
            )

    if normalized_task_name == "run_cleanup_task":
        try:
            validate_cleanup_params(params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        Scheduler._validate_expression(
            body.cron_expression,
            min_interval_seconds=MIN_USER_SCHEDULE_INTERVAL_SECONDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        task_name=normalized_task_name,
        params_json=json.dumps(body.params or {}),
        enabled=1 if body.enabled else 0,
        created_at=now,
    )
    db.add(model)
    await db.commit()

    scheduler = get_scheduler()
    if body.enabled and scheduler and getattr(scheduler, "_aps", None):
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
        "task_name": normalized_task_name,
        "params": body.params,
        "enabled": body.enabled,
        "created_at": format_datetime_utc(now),
    }


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: dict = Depends(require_schedule_permission("settings:write")),
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
