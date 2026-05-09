from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.models.external_source import ExternalSource
from maketrack.models.filament import Filament
from maketrack.models.inventory import InventoryItem
from maketrack.models.printer import Printer
from maketrack.templating import templates

router = APIRouter(tags=["ui"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: SessionDep) -> HTMLResponse:
    filament_count = (
        await session.execute(
            select(func.count()).select_from(Filament).where(Filament.archived_at.is_(None))
        )
    ).scalar_one()
    source_count = (
        await session.execute(select(func.count()).select_from(ExternalSource))
    ).scalar_one()
    inventory_count = (
        await session.execute(select(func.count()).select_from(InventoryItem))
    ).scalar_one()
    inventory_low = (
        await session.execute(
            select(func.count())
            .select_from(InventoryItem)
            .where(InventoryItem.reorder_threshold.is_not(None))
            .where(InventoryItem.quantity <= InventoryItem.reorder_threshold)
        )
    ).scalar_one()
    printer_count = (await session.execute(select(func.count()).select_from(Printer))).scalar_one()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "filament_count": filament_count,
            "source_count": source_count,
            "inventory_count": inventory_count,
            "inventory_low": inventory_low,
            "printer_count": printer_count,
        },
    )
