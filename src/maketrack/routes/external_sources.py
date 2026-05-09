from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session, get_sessionmaker
from maketrack.schemas.external_source import (
    ExternalSourceCreate,
    ExternalSourceRead,
    ExternalSourceUpdate,
    HealthCheckResult,
)
from maketrack.services import external_sources as svc
from maketrack.sync import archive_all_for_source, build_source, sync_source

router = APIRouter(prefix="/api/sources", tags=["external_sources"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[ExternalSourceRead])
async def list_sources(session: SessionDep) -> list[ExternalSourceRead]:
    rows = await svc.list_sources(session)
    return [ExternalSourceRead.model_validate(r) for r in rows]


@router.get("/{source_id}", response_model=ExternalSourceRead)
async def get_source(source_id: int, session: SessionDep) -> ExternalSourceRead:
    return ExternalSourceRead.model_validate(await svc.get_source(session, source_id))


@router.post("", response_model=ExternalSourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(payload: ExternalSourceCreate, session: SessionDep) -> ExternalSourceRead:
    row = await svc.create_source(session, payload)
    await session.commit()
    await session.refresh(row)
    return ExternalSourceRead.model_validate(row)


@router.patch("/{source_id}", response_model=ExternalSourceRead)
async def update_source(
    source_id: int, payload: ExternalSourceUpdate, session: SessionDep
) -> ExternalSourceRead:
    existing = await svc.get_source(session, source_id)
    was_enabled = existing.enabled
    row = await svc.update_source(session, source_id, payload)
    # If the user just disabled this source, mark its filaments archived per
    # the spec — a re-enable + sync will un-archive any that come back.
    if was_enabled and row.enabled is False:
        await archive_all_for_source(session, row.type)
    await session.commit()
    await session.refresh(row)
    return ExternalSourceRead.model_validate(row)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, session: SessionDep) -> None:
    await svc.delete_source(session, source_id)
    await session.commit()


@router.post("/{source_id}/sync")
async def manual_sync(source_id: int, session: SessionDep) -> dict:
    # Make sure it exists (404 otherwise) before kicking the worker.
    await svc.get_source(session, source_id)
    result = await sync_source(
        get_sessionmaker(),
        source_id,
        source_factory=build_source,
    )
    return {
        "source_id": result.source_id,
        "outcome": result.outcome.value,
        "rows_upserted": result.rows_upserted,
        "rows_archived": result.rows_archived,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "error": result.error,
    }


@router.post("/{source_id}/health-check", response_model=HealthCheckResult)
async def health_check(source_id: int, session: SessionDep) -> HealthCheckResult:
    source = await svc.get_source(session, source_id)
    adapter = build_source(source)
    healthy = await adapter.health_check()
    return HealthCheckResult(healthy=healthy, detail=None if healthy else "unreachable")
