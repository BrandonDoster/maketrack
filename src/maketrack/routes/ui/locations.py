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
from maketrack.schemas.location import LocationCreate, LocationUpdate
from maketrack.services import locations as svc
from maketrack.services.locations import DuplicateLocationError
from maketrack.templating import templates

router = APIRouter(tags=["ui-locations"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _render_index(
    request: Request,
    session: AsyncSession,
    *,
    errors: list[str] | None = None,
    form_values: dict | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    locations = await svc.list_locations(session)
    item_counts = {loc.id: await svc.count_items_in(session, loc.id) for loc in locations}
    return templates.TemplateResponse(
        request,
        "locations/index.html",
        {
            "locations": locations,
            "item_counts": item_counts,
            "errors": errors,
            "form_values": form_values or {},
        },
        status_code=status_code,
    )


@router.get("/settings/locations", response_class=HTMLResponse)
async def index(request: Request, session: SessionDep) -> HTMLResponse:
    return await _render_index(request, session)


@router.post("/settings/locations", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    try:
        payload = LocationCreate(**form)
    except ValidationError as exc:
        return await _render_index(
            request,
            session,
            errors=[format_validation_error(e) for e in exc.errors()],
            form_values=form,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        await svc.create_location(session, payload)
    except DuplicateLocationError as exc:
        return await _render_index(
            request,
            session,
            errors=[f"A location named '{exc}' already exists."],
            form_values=form,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await session.commit()
    return RedirectResponse(url="/settings/locations", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/settings/locations/{location_id}/edit", response_class=HTMLResponse)
async def edit_form(location_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    loc = await svc.get_location(session, location_id)
    return templates.TemplateResponse(
        request, "locations/edit.html", {"location": loc, "errors": None}
    )


@router.post("/settings/locations/{location_id}", response_class=HTMLResponse)
async def update(location_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = null_empty_strings(dict(await request.form()))
    try:
        payload = LocationUpdate(**form)
    except ValidationError as exc:
        loc = await svc.get_location(session, location_id)
        return templates.TemplateResponse(
            request,
            "locations/edit.html",
            {"location": loc, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        await svc.update_location(session, location_id, payload)
    except DuplicateLocationError as exc:
        loc = await svc.get_location(session, location_id)
        return templates.TemplateResponse(
            request,
            "locations/edit.html",
            {"location": loc, "errors": [f"A location named '{exc}' already exists."]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await session.commit()
    return RedirectResponse(url="/settings/locations", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/locations/{location_id}/delete", response_class=HTMLResponse)
async def delete(location_id: int, session: SessionDep) -> HTMLResponse:
    await svc.delete_location(session, location_id)
    await session.commit()
    return RedirectResponse(url="/settings/locations", status_code=status.HTTP_303_SEE_OTHER)
