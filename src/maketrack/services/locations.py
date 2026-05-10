from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.models.location import Location
from maketrack.schemas.location import LocationCreate, LocationUpdate


class DuplicateLocationError(Exception):
    """Raised when a location name collides with an existing row."""


async def list_locations(session: AsyncSession) -> Sequence[Location]:
    stmt = select(Location).order_by(Location.name)
    return (await session.execute(stmt)).scalars().all()


async def get_location(session: AsyncSession, location_id: int) -> Location:
    loc = await session.get(Location, location_id)
    if loc is None:
        raise NotFoundError("location", location_id)
    return loc


async def create_location(session: AsyncSession, payload: LocationCreate) -> Location:
    loc = Location(**payload.model_dump())
    session.add(loc)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateLocationError(payload.name) from exc
    return loc


async def update_location(
    session: AsyncSession, location_id: int, payload: LocationUpdate
) -> Location:
    loc = await get_location(session, location_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(loc, key, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateLocationError(payload.name or loc.name) from exc
    return loc


async def delete_location(session: AsyncSession, location_id: int) -> None:
    loc = await get_location(session, location_id)
    await session.delete(loc)
    await session.flush()


async def count_items_in(session: AsyncSession, location_id: int) -> int:
    """How many inventory items reference this location — shown next to delete."""
    from maketrack.models.inventory import InventoryItem

    stmt = (
        select(func.count())
        .select_from(InventoryItem)
        .where(InventoryItem.location_id == location_id)
    )
    return (await session.execute(stmt)).scalar_one()
