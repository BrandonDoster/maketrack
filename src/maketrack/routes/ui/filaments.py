from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session, get_sessionmaker
from maketrack.errors import RemoteFilamentError
from maketrack.routes.ui._forms import (
    format_validation_error,
    null_empty_strings,
    query_string,
    strip_empty_strings,
)
from maketrack.schemas.filament import FilamentCreate, FilamentUpdate
from maketrack.services import external_sources as sources_svc
from maketrack.services import filaments as svc
from maketrack.services._pagination import DEFAULT_PAGE_SIZE, Page, normalize_page
from maketrack.sync import build_source, ensure_fresh_sources
from maketrack.templating import templates

router = APIRouter(tags=["ui-filaments"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/filaments", response_class=HTMLResponse)
async def list_page(
    request: Request,
    session: SessionDep,
    q: str | None = None,
    material: str | None = None,
    source: str | None = None,
    page: int | None = None,
) -> HTMLResponse:
    await ensure_fresh_sources(get_sessionmaker(), source_factory=build_source)
    filter_kwargs = {
        "search": q,
        "material": material or None,
        "source": source or None,
    }
    total = await svc.count_filaments(session, **filter_kwargs)
    current_page = normalize_page(page, total, DEFAULT_PAGE_SIZE)
    filaments = await svc.list_filaments(
        session, **filter_kwargs, page=current_page, page_size=DEFAULT_PAGE_SIZE
    )
    enabled_sources = await sources_svc.list_sources(session, enabled_only=True)
    materials = await svc.distinct_materials(session)
    page_obj: Page = Page(
        items=list(filaments),
        total=total,
        page=current_page,
        page_size=DEFAULT_PAGE_SIZE,
    )
    query_base = query_string({"q": q, "material": material, "source": source})
    return templates.TemplateResponse(
        request,
        "filaments/list.html",
        {
            "filaments": filaments,
            "enabled_sources": enabled_sources,
            "q": q or "",
            "selected_material": material or "",
            "selected_source": source or "",
            "materials": materials,
            "page": page_obj,
            "query_base": query_base,
        },
    )


@router.get("/filaments/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "filaments/form.html",
        {"filament": None, "errors": None, "banner": None},
    )


@router.post("/filaments", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = dict(await request.form())
    try:
        payload = FilamentCreate(**strip_empty_strings(form))
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "filaments/form.html",
            {
                "filament": None,
                "errors": [format_validation_error(e) for e in exc.errors()],
                "banner": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.create_local_filament(session, payload)
    await session.commit()
    return RedirectResponse(url="/filaments", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/filaments/{filament_id}/edit", response_class=HTMLResponse)
async def edit_form(filament_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    filament = await svc.get_filament(session, filament_id)
    banner = None
    if filament.source != "local":
        banner = {"source": filament.source, "external_url": filament.external_url}
    return templates.TemplateResponse(
        request,
        "filaments/form.html",
        {"filament": filament, "errors": None, "banner": banner},
    )


@router.post("/filaments/{filament_id}", response_class=HTMLResponse)
async def update(filament_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = dict(await request.form())
    try:
        payload = FilamentUpdate(**null_empty_strings(form))
    except ValidationError as exc:
        filament = await svc.get_filament(session, filament_id)
        return templates.TemplateResponse(
            request,
            "filaments/form.html",
            {
                "filament": filament,
                "errors": [format_validation_error(e) for e in exc.errors()],
                "banner": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        await svc.update_filament(session, filament_id, payload)
    except RemoteFilamentError as exc:
        filament = await svc.get_filament(session, filament_id)
        return templates.TemplateResponse(
            request,
            "filaments/form.html",
            {
                "filament": filament,
                "errors": None,
                "banner": {"source": exc.source, "external_url": exc.external_url},
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    await session.commit()
    return RedirectResponse(url="/filaments", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/filaments/{filament_id}/archive", response_class=HTMLResponse)
async def archive(filament_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    try:
        await svc.archive_filament(session, filament_id)
    except RemoteFilamentError as exc:
        filament = await svc.get_filament(session, filament_id)
        return templates.TemplateResponse(
            request,
            "filaments/form.html",
            {
                "filament": filament,
                "errors": None,
                "banner": {"source": exc.source, "external_url": exc.external_url},
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    await session.commit()
    return RedirectResponse(url="/filaments", status_code=status.HTTP_303_SEE_OTHER)
