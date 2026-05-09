from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.routes.ui._forms import format_validation_error, strip_empty_strings
from maketrack.schemas.printer import PrinterCreate, PrinterUpdate
from maketrack.services import printers as svc
from maketrack.templating import templates

router = APIRouter(tags=["ui-printers"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/printers", response_class=HTMLResponse)
async def list_page(request: Request, session: SessionDep) -> HTMLResponse:
    printers = await svc.list_printers(session)
    return templates.TemplateResponse(request, "printers/list.html", {"printers": printers})


@router.get("/printers/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "printers/form.html", {"printer": None, "errors": None}
    )


@router.post("/printers", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    try:
        payload = PrinterCreate(**form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "printers/form.html",
            {"printer": None, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.create_printer(session, payload)
    await session.commit()
    return RedirectResponse(url="/printers", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/printers/{printer_id}/edit", response_class=HTMLResponse)
async def edit_form(printer_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    p = await svc.get_printer(session, printer_id)
    return templates.TemplateResponse(request, "printers/form.html", {"printer": p, "errors": None})


@router.post("/printers/{printer_id}", response_class=HTMLResponse)
async def update(printer_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    try:
        payload = PrinterUpdate(**form)
    except ValidationError as exc:
        p = await svc.get_printer(session, printer_id)
        return templates.TemplateResponse(
            request,
            "printers/form.html",
            {"printer": p, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.update_printer(session, printer_id, payload)
    await session.commit()
    return RedirectResponse(url="/printers", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/printers/{printer_id}/delete", response_class=HTMLResponse)
async def delete(printer_id: int, session: SessionDep) -> HTMLResponse:
    await svc.delete_printer(session, printer_id)
    await session.commit()
    return RedirectResponse(url="/printers", status_code=status.HTTP_303_SEE_OTHER)
