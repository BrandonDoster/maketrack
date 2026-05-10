from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.schemas.printer import (
    PrinterBuildCreate,
    PrinterBuildModelCreate,
    PrinterBuildRead,
    PrinterBuildUpdate,
)
from maketrack.services import printer_builds as svc
from maketrack.services import printers as printer_svc

router = APIRouter(tags=["printer-builds"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _read(session: AsyncSession, build_id: int) -> PrinterBuildRead:
    build = await svc.get_build(session, build_id)
    return PrinterBuildRead.model_validate(build)


@router.get("/api/printers/{printer_id}/builds", response_model=list[PrinterBuildRead])
async def list_for_printer(printer_id: int, session: SessionDep) -> list[PrinterBuildRead]:
    # 404 cleanly if the printer doesn't exist.
    await printer_svc.get_printer(session, printer_id)
    builds = await svc.list_for_printer(session, printer_id)
    return [PrinterBuildRead.model_validate(b) for b in builds]


@router.post(
    "/api/printers/{printer_id}/builds",
    response_model=PrinterBuildRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_for_printer(
    printer_id: int, payload: PrinterBuildCreate, session: SessionDep
) -> PrinterBuildRead:
    await printer_svc.get_printer(session, printer_id)
    build = await svc.create_build(session, printer_id=printer_id, payload=payload)
    await session.commit()
    return await _read(session, build.id)


@router.get("/api/printer-builds/{build_id}", response_model=PrinterBuildRead)
async def get_build(build_id: int, session: SessionDep) -> PrinterBuildRead:
    return await _read(session, build_id)


@router.patch("/api/printer-builds/{build_id}", response_model=PrinterBuildRead)
async def update_build(
    build_id: int, payload: PrinterBuildUpdate, session: SessionDep
) -> PrinterBuildRead:
    await svc.update_build(session, build_id, payload)
    await session.commit()
    return await _read(session, build_id)


@router.delete("/api/printer-builds/{build_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_build(build_id: int, session: SessionDep) -> None:
    await svc.delete_build(session, build_id)
    await session.commit()


@router.post(
    "/api/printer-builds/{build_id}/models",
    response_model=PrinterBuildRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_model(
    build_id: int, payload: PrinterBuildModelCreate, session: SessionDep
) -> PrinterBuildRead:
    await svc.add_model(session, build_id=build_id, payload=payload)
    await session.commit()
    return await _read(session, build_id)


@router.delete(
    "/api/printer-builds/{build_id}/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_model(build_id: int, model_id: int, session: SessionDep) -> None:
    await svc.remove_model(session, build_id=build_id, model_id=model_id)
    await session.commit()
