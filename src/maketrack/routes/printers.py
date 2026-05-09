from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.schemas.printer import PrinterCreate, PrinterRead, PrinterUpdate
from maketrack.services import printers as svc

router = APIRouter(prefix="/api/printers", tags=["printers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[PrinterRead])
async def list_printers(session: SessionDep) -> list[PrinterRead]:
    rows = await svc.list_printers(session)
    return [PrinterRead.model_validate(r) for r in rows]


@router.get("/{printer_id}", response_model=PrinterRead)
async def get_printer(printer_id: int, session: SessionDep) -> PrinterRead:
    return PrinterRead.model_validate(await svc.get_printer(session, printer_id))


@router.post("", response_model=PrinterRead, status_code=status.HTTP_201_CREATED)
async def create_printer(payload: PrinterCreate, session: SessionDep) -> PrinterRead:
    row = await svc.create_printer(session, payload)
    await session.commit()
    await session.refresh(row)
    return PrinterRead.model_validate(row)


@router.patch("/{printer_id}", response_model=PrinterRead)
async def update_printer(
    printer_id: int, payload: PrinterUpdate, session: SessionDep
) -> PrinterRead:
    row = await svc.update_printer(session, printer_id, payload)
    await session.commit()
    await session.refresh(row)
    return PrinterRead.model_validate(row)


@router.delete("/{printer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_printer(printer_id: int, session: SessionDep) -> None:
    await svc.delete_printer(session, printer_id)
    await session.commit()
