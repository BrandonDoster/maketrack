from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.errors import NotFoundError
from maketrack.models.filament import Filament
from maketrack.models.inventory import InventoryItem
from maketrack.models.printer import Printer
from maketrack.routes.ui._forms import format_validation_error, strip_empty_strings
from maketrack.schemas.project import (
    PROJECT_STATUSES,
    ProjectCreate,
    ProjectFilamentLinkCreate,
    ProjectItemLinkCreate,
    ProjectModelLinkCreate,
    ProjectUpdate,
)
from maketrack.services import bom as bom_svc
from maketrack.services import project_links as link_svc
from maketrack.services import projects as svc
from maketrack.templating import templates

router = APIRouter(tags=["ui-projects"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


@router.get("/projects", response_class=HTMLResponse)
async def list_page(
    request: Request, session: SessionDep, status: str | None = None
) -> HTMLResponse:
    rows = await svc.list_projects(session, status=status)
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
    form = strip_empty_strings(dict(await request.form()))
    tags = _parse_tags(form.pop("tags", None))
    if "printer_id" in form:
        try:
            form["printer_id"] = int(form["printer_id"])
        except (TypeError, ValueError):
            form.pop("printer_id", None)
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


@router.post("/projects/{project_id}/models", response_class=HTMLResponse)
async def add_model(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    try:
        payload = ProjectModelLinkCreate(
            model_id=int(form.get("model_id", "0")),
            qty_to_print=max(1, int(form.get("qty_to_print", "1"))),
        )
    except (ValueError, ValidationError):
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    try:
        await link_svc.add_model(session, project_id, payload)
        await session.commit()
    except NotFoundError:
        pass
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/models/{model_id}/delete", response_class=HTMLResponse)
async def remove_model(project_id: int, model_id: int, session: SessionDep) -> HTMLResponse:
    try:
        await link_svc.remove_model(session, project_id, model_id)
        await session.commit()
    except NotFoundError:
        pass
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


@router.post("/projects/{project_id}/items", response_class=HTMLResponse)
async def add_item(project_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    raw_qty = form.get("qty_required") or "0"
    try:
        payload = ProjectItemLinkCreate(
            inventory_item_id=int(form.get("inventory_item_id", "0")),
            qty_required=float(raw_qty),
            qty_consumed=0.0,
        )
    except (ValueError, ValidationError):
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER
        )
    try:
        await link_svc.add_item(session, project_id, payload)
        await session.commit()
    except NotFoundError:
        pass
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{project_id}/items/{link_id}/delete", response_class=HTMLResponse)
async def remove_item(project_id: int, link_id: int, session: SessionDep) -> HTMLResponse:
    try:
        await link_svc.remove_item(session, link_id)
        await session.commit()
    except NotFoundError:
        pass
    return RedirectResponse(url=f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)
