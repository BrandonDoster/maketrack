from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.routes.ui._forms import (
    format_validation_error,
    null_empty_strings,
    strip_empty_strings,
)
from maketrack.schemas.printer import PrinterCreate, PrinterUpdate
from maketrack.services import printer_builds as build_svc
from maketrack.services import printers as svc
from maketrack.services.uploads import delete_upload
from maketrack.templating import templates

router = APIRouter(tags=["ui-printers"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/printers", response_class=HTMLResponse)
async def list_page(
    request: Request,
    session: SessionDep,
    q: str | None = None,
) -> HTMLResponse:
    printers = await svc.list_printers(session, search=q)
    return templates.TemplateResponse(
        request,
        "printers/list.html",
        {"printers": printers, "q": q or ""},
    )


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
    form = null_empty_strings(dict(await request.form()))
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
    return RedirectResponse(url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/printers/{printer_id}/delete", response_class=HTMLResponse)
async def delete(printer_id: int, session: SessionDep) -> HTMLResponse:
    # Walk the build photos before delete: CASCADE removes the rows but
    # not the files on disk.
    p = await svc.get_printer(session, printer_id)
    photo_paths_to_drop = [p.photo_path]
    builds = await build_svc.list_for_printer(session, printer_id)
    photo_paths_to_drop.extend(b.photo_path for b in builds)

    await svc.delete_printer(session, printer_id)
    await session.commit()

    for path in photo_paths_to_drop:
        delete_upload(path)

    return RedirectResponse(url="/printers", status_code=status.HTTP_303_SEE_OTHER)
