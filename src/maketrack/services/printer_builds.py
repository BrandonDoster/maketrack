from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from maketrack.errors import NotFoundError
from maketrack.models.printer import PrinterBuild, PrinterBuildModel
from maketrack.schemas.printer import (
    PrinterBuildCreate,
    PrinterBuildModelCreate,
    PrinterBuildModelUpdate,
    PrinterBuildUpdate,
)


async def list_for_printer(session: AsyncSession, printer_id: int) -> Sequence[PrinterBuild]:
    stmt = (
        select(PrinterBuild)
        .where(PrinterBuild.printer_id == printer_id)
        .order_by(PrinterBuild.created_at)
        .options(selectinload(PrinterBuild.model_links))
    )
    return (await session.execute(stmt)).scalars().all()


async def get_build(session: AsyncSession, build_id: int) -> PrinterBuild:
    stmt = (
        select(PrinterBuild)
        .where(PrinterBuild.id == build_id)
        .options(selectinload(PrinterBuild.model_links))
    )
    build = (await session.execute(stmt)).scalar_one_or_none()
    if build is None:
        raise NotFoundError("printer_build", build_id)
    return build


async def create_build(
    session: AsyncSession,
    *,
    printer_id: int,
    payload: PrinterBuildCreate,
) -> PrinterBuild:
    build = PrinterBuild(printer_id=printer_id, **payload.model_dump())
    session.add(build)
    await session.flush()
    return build


async def update_build(
    session: AsyncSession, build_id: int, payload: PrinterBuildUpdate
) -> PrinterBuild:
    build = await get_build(session, build_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(build, key, value)
    await session.flush()
    return build


async def delete_build(session: AsyncSession, build_id: int) -> PrinterBuild:
    """Returns the row so the caller can clean up the photo file after commit."""
    build = await get_build(session, build_id)
    await session.delete(build)
    await session.flush()
    return build


async def add_model(
    session: AsyncSession,
    *,
    build_id: int,
    payload: PrinterBuildModelCreate,
) -> PrinterBuildModel:
    # Make sure the build exists so the FK error path is a clean 404.
    await get_build(session, build_id)
    link = PrinterBuildModel(
        printer_build_id=build_id,
        model_id=payload.model_id,
        qty=payload.qty,
        notes=payload.notes,
    )
    session.add(link)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise NotFoundError("model", payload.model_id) from None
    return link


async def update_model_link(
    session: AsyncSession,
    *,
    build_id: int,
    model_id: int,
    payload: PrinterBuildModelUpdate,
) -> PrinterBuildModel:
    link = await session.get(PrinterBuildModel, (build_id, model_id))
    if link is None:
        raise NotFoundError("printer_build_model", f"{build_id}/{model_id}")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(link, key, value)
    await session.flush()
    return link


async def remove_model(session: AsyncSession, *, build_id: int, model_id: int) -> None:
    link = await session.get(PrinterBuildModel, (build_id, model_id))
    if link is None:
        raise NotFoundError("printer_build_model", f"{build_id}/{model_id}")
    await session.delete(link)
    await session.flush()
