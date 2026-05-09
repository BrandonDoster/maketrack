from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.routes.ui._forms import format_validation_error, strip_empty_strings
from maketrack.schemas.inventory import InventoryItemCreate, InventoryItemUpdate
from maketrack.services import inventory as svc
from maketrack.templating import templates

router = APIRouter(tags=["ui-inventory"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/inventory", response_class=HTMLResponse)
async def list_page(request: Request, session: SessionDep) -> HTMLResponse:
    items = await svc.list_items(session)
    return templates.TemplateResponse(request, "inventory/list.html", {"items": items})


@router.get("/inventory/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "inventory/form.html", {"item": None, "errors": None}
    )


@router.post("/inventory", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    try:
        payload = InventoryItemCreate(**form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "inventory/form.html",
            {"item": None, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.create_item(session, payload)
    await session.commit()
    return RedirectResponse(url="/inventory", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/inventory/{item_id}/edit", response_class=HTMLResponse)
async def edit_form(item_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    item = await svc.get_item(session, item_id)
    return templates.TemplateResponse(
        request, "inventory/form.html", {"item": item, "errors": None}
    )


@router.post("/inventory/{item_id}", response_class=HTMLResponse)
async def update(item_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    try:
        payload = InventoryItemUpdate(**form)
    except ValidationError as exc:
        item = await svc.get_item(session, item_id)
        return templates.TemplateResponse(
            request,
            "inventory/form.html",
            {"item": item, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.update_item(session, item_id, payload)
    await session.commit()
    return RedirectResponse(url="/inventory", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/inventory/{item_id}/delete", response_class=HTMLResponse)
async def delete(item_id: int, session: SessionDep) -> HTMLResponse:
    await svc.delete_item(session, item_id)
    await session.commit()
    return RedirectResponse(url="/inventory", status_code=status.HTTP_303_SEE_OTHER)
