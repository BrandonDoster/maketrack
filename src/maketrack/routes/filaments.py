from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.schemas.filament import FilamentCreate, FilamentRead, FilamentUpdate
from maketrack.services import filaments as svc

router = APIRouter(prefix="/api/filaments", tags=["filaments"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[FilamentRead])
async def list_filaments(
    session: SessionDep,
    material: str | None = None,
    source: str | None = None,
    include_archived: bool = False,
) -> list[FilamentRead]:
    rows = await svc.list_filaments(
        session,
        material=material,
        source=source,
        include_archived=include_archived,
    )
    return [FilamentRead.model_validate(r) for r in rows]


@router.get("/{filament_id}", response_model=FilamentRead)
async def get_filament(filament_id: int, session: SessionDep) -> FilamentRead:
    row = await svc.get_filament(session, filament_id)
    return FilamentRead.model_validate(row)


@router.post("", response_model=FilamentRead, status_code=status.HTTP_201_CREATED)
async def create_filament(payload: FilamentCreate, session: SessionDep) -> FilamentRead:
    row = await svc.create_local_filament(session, payload)
    await session.commit()
    await session.refresh(row)
    return FilamentRead.model_validate(row)


@router.patch("/{filament_id}", response_model=FilamentRead)
async def update_filament(
    filament_id: int,
    payload: FilamentUpdate,
    session: SessionDep,
) -> FilamentRead:
    row = await svc.update_filament(session, filament_id, payload)
    await session.commit()
    await session.refresh(row)
    return FilamentRead.model_validate(row)


@router.delete("/{filament_id}", response_model=FilamentRead)
async def archive_filament(filament_id: int, session: SessionDep) -> FilamentRead:
    row = await svc.archive_filament(session, filament_id)
    await session.commit()
    await session.refresh(row)
    return FilamentRead.model_validate(row)
