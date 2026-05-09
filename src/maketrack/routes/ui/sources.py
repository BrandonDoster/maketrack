from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session, get_sessionmaker
from maketrack.routes.ui._forms import format_validation_error, strip_empty_strings
from maketrack.schemas.external_source import (
    ExternalSourceCreate,
    ExternalSourceUpdate,
)
from maketrack.services import external_sources as svc
from maketrack.sync import archive_all_for_source, build_source, sync_source
from maketrack.templating import templates

router = APIRouter(tags=["ui-sources"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _form_payload(form: dict) -> dict:
    out = strip_empty_strings(form)
    # Checkboxes only appear in the form data when checked.
    out["enabled"] = form.get("enabled") in ("true", "on", "1")
    return out


@router.get("/sources", response_class=HTMLResponse)
async def list_page(request: Request, session: SessionDep) -> HTMLResponse:
    sources = await svc.list_sources(session)
    return templates.TemplateResponse(
        request,
        "sources/list.html",
        {"sources": sources, "last_sync_result": None},
    )


@router.get("/sources/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "sources/form.html",
        {"source": None, "errors": None},
    )


@router.post("/sources", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = dict(await request.form())
    try:
        payload = ExternalSourceCreate(**_form_payload(form))
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "sources/form.html",
            {"source": None, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.create_source(session, payload)
    await session.commit()
    return RedirectResponse(url="/sources", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/sources/{source_id}/edit", response_class=HTMLResponse)
async def edit_form(source_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    source = await svc.get_source(session, source_id)
    return templates.TemplateResponse(
        request,
        "sources/form.html",
        {"source": source, "errors": None},
    )


@router.post("/sources/{source_id}", response_class=HTMLResponse)
async def update(source_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = dict(await request.form())
    payload_data = _form_payload(form)
    # Type isn't editable post-creation; drop it so the partial schema validates.
    payload_data.pop("type", None)
    try:
        payload = ExternalSourceUpdate(**payload_data)
    except ValidationError as exc:
        source = await svc.get_source(session, source_id)
        return templates.TemplateResponse(
            request,
            "sources/form.html",
            {"source": source, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    existing = await svc.get_source(session, source_id)
    was_enabled = existing.enabled
    row = await svc.update_source(session, source_id, payload)
    if was_enabled and row.enabled is False:
        await archive_all_for_source(session, row.type)
    await session.commit()
    return RedirectResponse(url="/sources", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sources/{source_id}/delete", response_class=HTMLResponse)
async def delete(source_id: int, session: SessionDep) -> HTMLResponse:
    await svc.delete_source(session, source_id)
    await session.commit()
    return RedirectResponse(url="/sources", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sources/{source_id}/sync", response_class=HTMLResponse)
async def manual_sync(source_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    await svc.get_source(session, source_id)
    result = await sync_source(
        get_sessionmaker(),
        source_id,
        source_factory=build_source,
    )
    sources = await svc.list_sources(session)
    return templates.TemplateResponse(
        request,
        "sources/list.html",
        {
            "sources": sources,
            "last_sync_result": {
                "outcome": result.outcome.value,
                "rows_upserted": result.rows_upserted,
                "rows_archived": result.rows_archived,
                "error": result.error,
            },
        },
    )
