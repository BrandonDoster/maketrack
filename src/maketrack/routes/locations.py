from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.schemas.location import LocationCreate, LocationRead, LocationUpdate
from maketrack.services import locations as svc
from maketrack.services.locations import DuplicateLocationError

router = APIRouter(prefix="/api/locations", tags=["locations"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[LocationRead])
async def list_locations(session: SessionDep) -> list[LocationRead]:
    rows = await svc.list_locations(session)
    return [LocationRead.model_validate(r) for r in rows]


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(location_id: int, session: SessionDep) -> LocationRead:
    return LocationRead.model_validate(await svc.get_location(session, location_id))


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
async def create_location(payload: LocationCreate, session: SessionDep) -> LocationRead:
    try:
        row = await svc.create_location(session, payload)
    except DuplicateLocationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(row)
    return LocationRead.model_validate(row)


@router.patch("/{location_id}", response_model=LocationRead)
async def update_location(
    location_id: int, payload: LocationUpdate, session: SessionDep
) -> LocationRead:
    try:
        row = await svc.update_location(session, location_id, payload)
    except DuplicateLocationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(row)
    return LocationRead.model_validate(row)


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(location_id: int, session: SessionDep) -> None:
    await svc.delete_location(session, location_id)
    await session.commit()
