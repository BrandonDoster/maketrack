from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.models.printer import Printer
from maketrack.schemas.printer import PrinterCreate, PrinterUpdate


async def list_printers(
    session: AsyncSession,
    *,
    search: str | None = None,
) -> Sequence[Printer]:
    stmt = select(Printer).order_by(Printer.name)
    if search:
        stmt = stmt.where(Printer.name.icontains(search))
    return (await session.execute(stmt)).scalars().all()


async def get_printer(session: AsyncSession, printer_id: int) -> Printer:
    p = await session.get(Printer, printer_id)
    if p is None:
        raise NotFoundError("printer", printer_id)
    return p


async def create_printer(session: AsyncSession, payload: PrinterCreate) -> Printer:
    p = Printer(**payload.model_dump())
    session.add(p)
    await session.flush()
    return p


async def update_printer(session: AsyncSession, printer_id: int, payload: PrinterUpdate) -> Printer:
    p = await get_printer(session, printer_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(p, key, value)
    await session.flush()
    return p


async def delete_printer(session: AsyncSession, printer_id: int) -> None:
    p = await get_printer(session, printer_id)
    await session.delete(p)
    await session.flush()
