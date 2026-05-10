from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.errors import NotFoundError
from maketrack.models.filament import Filament
from maketrack.models.inventory import InventoryItem
from maketrack.models.printer import Printer
from maketrack.routes.ui._forms import (
    format_validation_error,
    is_htmx,
    null_empty_strings,
    strip_empty_strings,
)
from maketrack.schemas.model import ModelCreate
from maketrack.schemas.project import (
    PROJECT_STATUSES,
    ProjectCreate,
    ProjectFilamentLinkCreate,
    ProjectItemLinkCreate,
    ProjectItemLinkUpdate,
    ProjectModelLinkCreate,
    ProjectModelLinkUpdate,
    ProjectUpdate,
)
from maketrack.services import assets as asset_svc
from maketrack.services import bom as bom_svc
from maketrack.services import models as model_svc
from maketrack.services import project_links as link_svc
from maketrack.services import projects as svc
from maketrack.services.uploads import (
    UploadError,
    delete_upload,
    save_photo,
)
from maketrack.templating import templates

router = APIRouter(tags=["ui-projects"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


@router.get("/projects", response_class=HTMLResponse)
async def list_page(
    request: Request,
    session: SessionDep,
    status: str | None = None,
    q: str | None = None,
) -> HTMLResponse:
    rows = await svc.list_projects(session, status=status, search=q)
    decorated = [
        {
            "project": p,
            "tags": svc.decode_tags(p.tags),
        }
        for p in rows
    ]
    return templates.TemplateResponse(
        request,
        "projects/list.html",
        {
            "items": decorated,
            "current_status": status,
            "statuses": PROJECT_STATUSES,
            "q": q or "",
        },
    )


@router.get("/projects/new", response_class=HTMLResponse)
async def new_form(request: Request, session: SessionDep) -> HTMLResponse:
    printers = (await session.execute(select(Printer).order_by(Printer.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "projects/form.html",
        {
            "project": None,
            "tags_str": "",
            "printers": printers,
            "errors": None,
            "statuses": PROJECT_STATUSES,
        },
    )


@router.post("/projects", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    tags = _parse_tags(form.pop("tags", None))
    if "printer_id" in form:
        try:
            form["printer_id"] = int(form["printer_id"])
        except (TypeError, ValueError):
            form.pop("printer_id", None)
    try:
        payload = ProjectCreate(**form, tags=tags)
    except ValidationError as exc:
        printers = (await session.execute(select(Printer).order_by(Printer.name))).scalars().all()
        return templates.TemplateResponse(
            request,
            "projects/form.html",
            {
                "project": None,
                "tags_str": ", ".join(tags),
                "printers": printers,
                "errors": [format_validation_error(e) for e in exc.errors()],
                "statuses": PROJECT_STATUSES,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    project = await svc.create_project(session, payload)
    await session.commit()
    return RedirectResponse(url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def detail_page(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    project = await svc.get_project(session, project_id)
    printer = await link_svc.get_printer_for_project(session, project)
    project_models = await link_svc.list_project_models(session, project_id)
    project_filaments = await link_svc.list_project_filaments(session, project_id)
    project_items = await link_svc.list_project_items(session, project_id)
    bom = await bom_svc.project_bom(session, project_id)

    available_models = await link_svc.list_unlinked_models(session, project_id)
    available_filaments = (
        (
            await session.execute(
                select(Filament).where(Filament.archived_at.is_(None)).order_by(Filament.name)
            )
        )
        .scalars()
        .all()
    )
    available_items = (
        (await session.execute(select(InventoryItem).order_by(InventoryItem.name))).scalars().all()
    )

    return templates.TemplateResponse(
        request,
        "projects/detail.html",
        {
            "project": project,
            "tags": svc.decode_tags(project.tags),
            "printer": printer,
            "project_models": project_models,
            "project_filaments": project_filaments,
            "project_items": project_items,
            "bom": bom,
            "available_models": available_models,
            "available_filaments": available_filaments,
            "available_items": available_items,
            "statuses": PROJECT_STATUSES,
        },
    )


@router.get("/projects/{project_id}/edit", response_class=HTMLResponse)
async def edit_form(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    project = await svc.get_project(session, project_id)
    printers = (await session.execute(select(Printer).order_by(Printer.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "projects/form.html",
        {
            "project": project,
            "tags_str": ", ".join(svc.decode_tags(project.tags)),
            "printers": printers,
            "errors": None,
            "statuses": PROJECT_STATUSES,
        },
    )


@router.post("/projects/{project_id}", response_class=HTMLResponse)
async def update(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    # Update path: use null_empty_strings so a cleared description / notes
    # field actually clears the column instead of getting silently dropped.
    form = null_empty_strings(dict(await request.form()))
    tags = _parse_tags(form.pop("tags", None))
    # printer_id arrives as a string from <select>; coerce to int when set.
    if form.get("printer_id") is not None:
        try:
            form["printer_id"] = int(form["printer_id"])
        except (TypeError, ValueError):
            form["printer_id"] = None
    try:
        payload = ProjectUpdate(**form, tags=tags)
    except ValidationError as exc:
        project = await svc.get_project(session, project_id)
        printers = (await session.execute(select(Printer).order_by(Printer.name))).scalars().all()
        return templates.TemplateResponse(
            request,
            "projects/form.html",
            {
                "project": project,
                "tags_str": ", ".join(tags),
                "printers": printers,
                "errors": [format_validation_error(e) for e in exc.errors()],
                "statuses": PROJECT_STATUSES,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.update_project(session, project_id, payload)
    await session.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/status", response_class=HTMLResponse)
async def transition_status(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    new_status = form.get("status")
    if new_status not in PROJECT_STATUSES:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    await svc.update_project(session, project_id, ProjectUpdate(status=new_status))
    await session.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/delete", response_class=HTMLResponse)
async def delete(project_id: int, session: SessionDep) -> HTMLResponse:
    await svc.delete_project(session, project_id)
    await session.commit()
    return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)


# ── inline link actions (HTMX-friendly POST + redirect) ───────────────────


async def _models_partial(request: Request, project_id: int, session: AsyncSession) -> HTMLResponse:
    """HTMX swap target for the project's Models section."""
    project = await svc.get_project(session, project_id)
    project_models = await link_svc.list_project_models(session, project_id)
    available_models = await link_svc.list_unlinked_models(session, project_id)
    return templates.TemplateResponse(
        request,
        "projects/_models_section.html",
        {
            "project": project,
            "project_models": project_models,
            "available_models": available_models,
        },
    )


@router.post("/projects/{project_id}/models", response_class=HTMLResponse)
async def add_model(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    try:
        payload = ProjectModelLinkCreate(
            model_id=int(form.get("model_id", "0")),
            qty_to_print=max(1, int(form.get("qty_to_print", "1"))),
        )
    except (ValueError, ValidationError):
        if is_htmx(request):
            return await _models_partial(request, project_id, session)
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    try:
        await link_svc.add_model(session, project_id, payload)
        await session.commit()
    except NotFoundError:
        pass
    if is_htmx(request):
        return await _models_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


_VALID_MODEL_LINK_STATUSES = frozenset({"pending", "printed", "failed"})


@router.post("/projects/{project_id}/models/{model_id}/qty", response_class=HTMLResponse)
async def update_model_qty(
    project_id: int, model_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    """Inline qty_to_print edit for a project_model link."""
    form = await request.form()
    raw = (form.get("qty_to_print") or "").strip()
    try:
        qty = int(raw)
    except ValueError:
        qty = None
    if qty is not None and qty >= 1:
        try:
            await link_svc.update_model_link(
                session, project_id, model_id, ProjectModelLinkUpdate(qty_to_print=qty)
            )
            await session.commit()
        except NotFoundError:
            pass
    if is_htmx(request):
        return await _models_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/models/{model_id}/status", response_class=HTMLResponse)
async def update_model_status(
    project_id: int, model_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    """Inline status edit for a project_model link.

    The status (pending | printed | failed) belongs to the project link,
    not the underlying Model — the same model can be 'pending' on one
    project and 'printed' on another.
    """
    form = await request.form()
    raw = (form.get("status") or "").strip()
    if raw in _VALID_MODEL_LINK_STATUSES:
        try:
            await link_svc.update_model_link(
                session, project_id, model_id, ProjectModelLinkUpdate(status=raw)
            )
            await session.commit()
        except NotFoundError:
            pass
    if is_htmx(request):
        return await _models_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/models/{model_id}/delete", response_class=HTMLResponse)
async def remove_model(
    project_id: int, model_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    try:
        await link_svc.remove_model(session, project_id, model_id)
        await session.commit()
    except NotFoundError:
        pass
    if is_htmx(request):
        return await _models_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/filaments", response_class=HTMLResponse)
async def add_filament(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    raw_est = form.get("est_weight_g") or None
    try:
        payload = ProjectFilamentLinkCreate(
            filament_id=int(form.get("filament_id", "0")),
            est_weight_g=float(raw_est) if raw_est else None,
            role=(form.get("role") or None),
        )
    except (ValueError, ValidationError):
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    try:
        await link_svc.add_filament(session, project_id, payload)
        await session.commit()
    except NotFoundError:
        pass
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/filaments/{link_id}/delete", response_class=HTMLResponse)
async def remove_filament(project_id: int, link_id: int, session: SessionDep) -> HTMLResponse:
    try:
        await link_svc.remove_filament(session, link_id)
        await session.commit()
    except NotFoundError:
        pass
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


async def _bom_partial(request: Request, project_id: int, session: AsyncSession) -> HTMLResponse:
    """Render the BOM section partial. Used as the HTMX swap response so
    every BOM mutation re-paints the whole section in place — no scroll
    jump, no full page reload.
    """
    project = await svc.get_project(session, project_id)
    project_items = await link_svc.list_project_items(session, project_id)
    bom = await bom_svc.project_bom(session, project_id)
    available_items = (
        (await session.execute(select(InventoryItem).order_by(InventoryItem.name))).scalars().all()
    )
    return templates.TemplateResponse(
        request,
        "projects/_bom_section.html",
        {
            "project": project,
            "project_items": project_items,
            "bom": bom,
            "available_items": available_items,
        },
    )


@router.post("/projects/{project_id}/items", response_class=HTMLResponse)
async def add_item(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    raw_qty = (form.get("qty_required") or "1").strip() or "1"
    raw_consumed = (form.get("qty_consumed") or "0").strip() or "0"
    raw_inv_id = (form.get("inventory_item_id") or "").strip()
    raw_name = (form.get("name") or "").strip()
    raw_unit = (form.get("unit") or "").strip()

    # Empty submission (user tabbed through without typing or picking) is a
    # no-op. Re-render the partial so HTMX gets a valid swap target.
    if not raw_inv_id and not raw_name:
        if is_htmx(request):
            return await _bom_partial(request, project_id, session)
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )

    try:
        payload = ProjectItemLinkCreate(
            inventory_item_id=int(raw_inv_id) if raw_inv_id else None,
            name=raw_name or None,
            unit=raw_unit or None,
            qty_required=float(raw_qty),
            qty_consumed=float(raw_consumed),
        )
    except (ValueError, ValidationError):
        if is_htmx(request):
            return await _bom_partial(request, project_id, session)
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    try:
        await link_svc.add_item(session, project_id, payload)
        await session.commit()
    except (NotFoundError, ValueError):
        pass
    if is_htmx(request):
        return await _bom_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/items/{link_id}/link", response_class=HTMLResponse)
async def link_item_to_inventory(
    project_id: int, link_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    form = await request.form()
    raw = (form.get("inventory_item_id") or "").strip()
    if raw:
        try:
            await link_svc.link_item_to_inventory(session, link_id, int(raw))
            await session.commit()
        except (ValueError, NotFoundError):
            pass
    if is_htmx(request):
        return await _bom_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/items/{link_id}/delete", response_class=HTMLResponse)
async def remove_item(
    project_id: int, link_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    try:
        await link_svc.remove_item(session, link_id)
        await session.commit()
    except NotFoundError:
        pass
    if is_htmx(request):
        return await _bom_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/items/{link_id}/qty", response_class=HTMLResponse)
async def update_item_qty(
    project_id: int, link_id: int, request: Request, session: SessionDep
) -> HTMLResponse:
    """Inline qty edit: tiny per-row form auto-submits on change.

    Accepts qty_required and/or qty_consumed; missing fields are left
    untouched. Bad input is silently ignored — the value snaps back to
    whatever the DB has on the next render.
    """
    form = await request.form()
    payload_data: dict[str, float] = {}
    for field in ("qty_required", "qty_consumed"):
        raw = (form.get(field) or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value < 0:
            continue
        payload_data[field] = value
    if payload_data:
        try:
            await link_svc.update_item_link(session, link_id, ProjectItemLinkUpdate(**payload_data))
            await session.commit()
        except NotFoundError:
            pass
    if is_htmx(request):
        return await _bom_partial(request, project_id, session)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


# ── inline notes edit ─────────────────────────────────────────────────────


@router.post("/projects/{project_id}/notes", response_class=HTMLResponse)
async def update_notes(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    """Quick journal-style notes update from the detail page."""
    form = await request.form()
    notes = form.get("notes")
    # Empty string clears the notes; None should also collapse to NULL.
    cleaned = notes.strip() if isinstance(notes, str) else None
    await svc.update_project(session, project_id, ProjectUpdate(notes=cleaned or None))
    await session.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


# ── project-side file upload (auto-creates Models, links them) ────────────


_MODEL_ASSET_EXTS = frozenset({".stl", ".step", ".stp", ".3mf", ".gcode", ".g", ".gco"})


@router.post("/projects/{project_id}/upload-files", response_class=HTMLResponse)
async def upload_files(
    project_id: int,
    session: SessionDep,
    files: Annotated[list[UploadFile], File()],
) -> HTMLResponse:
    """Drop STL/STEP/3MF/gcode files on a project and have them turn into
    new Models that are auto-linked. Image files are ignored here — they
    belong to the photo upload flow.
    """
    project = await svc.get_project(session, project_id)
    base_name = project.name
    for file in files:
        name = (file.filename or "").strip()
        if not name:
            continue
        ext = Path(name).suffix.lower()
        if ext not in _MODEL_ASSET_EXTS:
            continue
        # New Model named after the filename (without extension); the user
        # can rename later if they want.
        model_name = Path(name).stem or base_name
        model = await model_svc.create_model(
            session, ModelCreate(name=model_name, source_type="local")
        )
        try:
            await asset_svc.upload_asset(session, model.id, file)
        except UploadError:
            # Best-effort: skip the broken file but keep going through the rest.
            await session.rollback()
            continue
        await link_svc.add_model(
            session,
            project_id,
            ProjectModelLinkCreate(model_id=model.id, qty_to_print=1),
        )
        await session.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


# ── project photos ────────────────────────────────────────────────────────


_PHOTO_KIND_FIELDS = {
    "cover": "cover_photo_path",
    "completed": "completed_photo_path",
}


@router.post("/projects/{project_id}/photo/{kind}", response_class=HTMLResponse)
async def upload_photo(
    project_id: int,
    kind: str,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
) -> HTMLResponse:
    field = _PHOTO_KIND_FIELDS.get(kind)
    if field is None:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    project = await svc.get_project(session, project_id)
    if not (file.filename or "").strip():
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    try:
        new_path, _, _ = await save_photo(file, subdir="projects")
    except UploadError:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    old_path = getattr(project, field)
    setattr(project, field, new_path)
    await session.commit()
    delete_upload(old_path)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/photo/{kind}/delete", response_class=HTMLResponse)
async def delete_photo(project_id: int, kind: str, session: SessionDep) -> HTMLResponse:
    field = _PHOTO_KIND_FIELDS.get(kind)
    if field is None:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    project = await svc.get_project(session, project_id)
    old_path = getattr(project, field)
    setattr(project, field, None)
    await session.commit()
    delete_upload(old_path)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)
