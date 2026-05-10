from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.models.model import Model
from maketrack.models.project import Project
from maketrack.routes.ui._forms import (
    format_validation_error,
    null_empty_strings,
    strip_empty_strings,
)
from maketrack.schemas.printer import (
    PrinterBuildCreate,
    PrinterBuildModelCreate,
    PrinterBuildModelUpdate,
    PrinterBuildUpdate,
)
from maketrack.services import printer_builds as svc
from maketrack.services import printers as printer_svc
from maketrack.services.uploads import UploadError, delete_upload, save_photo
from maketrack.templating import templates

router = APIRouter(tags=["ui-printer-builds"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]

_PHOTO_SUBDIR_PRINTER = "printers"
_PHOTO_SUBDIR_BUILD = "printers/builds"


def _has_uploaded_photo(form_field) -> bool:
    return bool(getattr(form_field, "filename", "") or "")


def _coerce_optional_int(form: dict, key: str) -> None:
    """Best-effort coerce a form field to int-or-None in place."""
    value = form.get(key)
    if value in (None, ""):
        form[key] = None
        return
    try:
        form[key] = int(value)
    except (TypeError, ValueError):
        form[key] = None


@router.get("/printers/{printer_id}", response_class=HTMLResponse)
async def detail_page(printer_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    printer = await printer_svc.get_printer(session, printer_id)
    builds = await svc.list_for_printer(session, printer_id)
    available_projects = (
        (await session.execute(select(Project).order_by(Project.name))).scalars().all()
    )
    return templates.TemplateResponse(
        request,
        "printers/detail.html",
        {
            "printer": printer,
            "builds": builds,
            "available_projects": available_projects,
        },
    )


@router.post("/printers/{printer_id}/photo", response_class=HTMLResponse)
async def upload_photo(printer_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    printer = await printer_svc.get_printer(session, printer_id)
    form = await request.form()
    photo_field = form.get("photo")
    if _has_uploaded_photo(photo_field):
        try:
            new_path, _, _ = await save_photo(photo_field, subdir=_PHOTO_SUBDIR_PRINTER)
        except UploadError:
            return RedirectResponse(
                url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER
            )
        old = printer.photo_path
        printer.photo_path = new_path
        await session.commit()
        delete_upload(old)
    return RedirectResponse(url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/printers/{printer_id}/photo/delete", response_class=HTMLResponse)
async def delete_photo(printer_id: int, session: SessionDep) -> HTMLResponse:
    printer = await printer_svc.get_printer(session, printer_id)
    old = printer.photo_path
    printer.photo_path = None
    await session.commit()
    delete_upload(old)
    return RedirectResponse(url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/printers/{printer_id}/builds", response_class=HTMLResponse)
async def create_build(printer_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    await printer_svc.get_printer(session, printer_id)
    form = strip_empty_strings(dict(await request.form()))
    _coerce_optional_int(form, "source_project_id")
    try:
        payload = PrinterBuildCreate(**form)
    except ValidationError:
        # Inline form with only name+description+project — easiest fallback
        # is just to redirect; the user will see their input cleared, which
        # is rare since the only required field is name.
        return RedirectResponse(
            url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    await svc.create_build(session, printer_id=printer_id, payload=payload)
    await session.commit()
    return RedirectResponse(url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER)


async def _render_build_edit(
    request: Request,
    session: AsyncSession,
    *,
    printer_id: int,
    build_id: int,
    errors: list[str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    printer = await printer_svc.get_printer(session, printer_id)
    build = await svc.get_build(session, build_id)
    available_projects = (
        (await session.execute(select(Project).order_by(Project.name))).scalars().all()
    )
    available_models = (await session.execute(select(Model).order_by(Model.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "printers/build_form.html",
        {
            "printer": printer,
            "build": build,
            "available_projects": available_projects,
            "available_models": available_models,
            "errors": errors,
        },
        status_code=status_code,
    )


@router.get("/printers/{printer_id}/builds/{build_id}/edit", response_class=HTMLResponse)
async def edit_build_form(
    printer_id: int, build_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    return await _render_build_edit(request, session, printer_id=printer_id, build_id=build_id)


@router.post("/printers/{printer_id}/builds/{build_id}", response_class=HTMLResponse)
async def update_build(
    printer_id: int, build_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    form = await request.form()
    remove_photo = form.get("remove_photo") in ("true", "on", "1")
    payload_data = null_empty_strings(
        {k: v for k, v in form.items() if k not in ("photo", "remove_photo")}
    )
    _coerce_optional_int(payload_data, "source_project_id")
    try:
        payload = PrinterBuildUpdate(**payload_data)
    except ValidationError as exc:
        return await _render_build_edit(
            request,
            session,
            printer_id=printer_id,
            build_id=build_id,
            errors=[format_validation_error(e) for e in exc.errors()],
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    build = await svc.update_build(session, build_id, payload)

    photo_field = form.get("photo")
    if _has_uploaded_photo(photo_field):
        try:
            new_path, _, _ = await save_photo(photo_field, subdir=_PHOTO_SUBDIR_BUILD)
        except UploadError as exc:
            return await _render_build_edit(
                request,
                session,
                printer_id=printer_id,
                build_id=build_id,
                errors=[str(exc)],
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        old = build.photo_path
        build.photo_path = new_path
        delete_upload(old)
    elif remove_photo and build.photo_path:
        delete_upload(build.photo_path)
        build.photo_path = None

    await session.commit()
    return RedirectResponse(url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/printers/{printer_id}/builds/{build_id}/delete", response_class=HTMLResponse)
async def delete_build(printer_id: int, build_id: int, session: SessionDep) -> HTMLResponse:
    build = await svc.delete_build(session, build_id)
    await session.commit()
    delete_upload(build.photo_path)
    return RedirectResponse(url=f"/printers/{printer_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/printers/{printer_id}/builds/{build_id}/models", response_class=HTMLResponse)
async def link_model(
    printer_id: int, build_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    _coerce_optional_int(form, "model_id")
    _coerce_optional_int(form, "qty")
    if form.get("model_id") is None:
        return RedirectResponse(
            url=f"/printers/{printer_id}/builds/{build_id}/edit",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if form.get("qty") in (None, 0):
        form["qty"] = 1
    try:
        payload = PrinterBuildModelCreate(**form)
    except ValidationError as exc:
        return await _render_build_edit(
            request,
            session,
            printer_id=printer_id,
            build_id=build_id,
            errors=[format_validation_error(e) for e in exc.errors()],
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.add_model(session, build_id=build_id, payload=payload)
    await session.commit()
    return RedirectResponse(
        url=f"/printers/{printer_id}/builds/{build_id}/edit",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/printers/{printer_id}/builds/{build_id}/models/{model_id}",
    response_class=HTMLResponse,
)
async def update_link(
    printer_id: int,
    build_id: int,
    model_id: int,
    request: Request,
    session: SessionDep,
) -> HTMLResponse:
    form = null_empty_strings(dict(await request.form()))
    _coerce_optional_int(form, "qty")
    try:
        payload = PrinterBuildModelUpdate(**form)
    except ValidationError as exc:
        return await _render_build_edit(
            request,
            session,
            printer_id=printer_id,
            build_id=build_id,
            errors=[format_validation_error(e) for e in exc.errors()],
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.update_model_link(session, build_id=build_id, model_id=model_id, payload=payload)
    await session.commit()
    return RedirectResponse(
        url=f"/printers/{printer_id}/builds/{build_id}/edit",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/printers/{printer_id}/builds/{build_id}/models/{model_id}/delete",
    response_class=HTMLResponse,
)
async def unlink_model(
    printer_id: int, build_id: int, model_id: int, session: SessionDep
) -> HTMLResponse:
    await svc.remove_model(session, build_id=build_id, model_id=model_id)
    await session.commit()
    return RedirectResponse(
        url=f"/printers/{printer_id}/builds/{build_id}/edit",
        status_code=status.HTTP_303_SEE_OTHER,
    )
