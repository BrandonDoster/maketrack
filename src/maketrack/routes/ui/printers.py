from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.routes.ui._forms import (
    format_validation_error,
    null_empty_strings,
)
from maketrack.schemas.printer import PrinterCreate, PrinterUpdate
from maketrack.services import printer_builds as build_svc
from maketrack.services import printers as svc
from maketrack.services.uploads import delete_upload
from maketrack.templating import templates

router = APIRouter(tags=["ui-printers"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Placeholder used when a draft printer is created with no fields filled
# in. The user is dropped immediately on the detail page in edit mode and
# is expected to rename it.
DRAFT_PRINTER_NAME = "New printer"


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


@router.post("/printers/new", response_class=HTMLResponse)
async def create_draft(session: SessionDep) -> HTMLResponse:
    """Create a stub printer and drop the user on its detail page in
    edit mode. Replaces the standalone create-printer form."""
    p = await svc.create_printer(session, PrinterCreate(name=DRAFT_PRINTER_NAME))
    await session.commit()
    return RedirectResponse(
        url=f"/printers/{p.id}?edit=true", status_code=status.HTTP_303_SEE_OTHER
    )


async def _render_edit_with_errors(
    request: Request,
    session: AsyncSession,
    printer_id: int,
    errors: list[str],
) -> HTMLResponse:
    p = await svc.get_printer(session, printer_id)
    builds = await build_svc.list_for_printer(session, printer_id)
    return templates.TemplateResponse(
        request,
        "printers/detail.html",
        {
            "printer": p,
            "builds": builds,
            "available_projects": [],
            "available_models": [],
            "edit_mode": True,
            "errors": errors,
        },
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.post("/printers/{printer_id}", response_class=HTMLResponse)
async def update(printer_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    raw_form = dict(await request.form())
    # The detail-page form always includes `name`. Don't let null_empty_strings
    # collapse a cleared name into None — PrinterUpdate would accept that and
    # then the DB would reject it with a NOT NULL violation. Catch it here.
    if not (raw_form.get("name") or "").strip():
        return await _render_edit_with_errors(request, session, printer_id, ["Name is required."])

    form = null_empty_strings(raw_form)
    try:
        payload = PrinterUpdate(**form)
    except ValidationError as exc:
        return await _render_edit_with_errors(
            request,
            session,
            printer_id,
            [format_validation_error(e) for e in exc.errors()],
        )
    await svc.update_printer(session, printer_id, payload)
    await session.commit()
    # "Done editing" submits this form, so saving exits edit mode.
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
