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
from maketrack.schemas.inventory import InventoryItemCreate, InventoryItemUpdate
from maketrack.services import inventory as svc
from maketrack.services.uploads import UploadError, delete_upload, save_photo
from maketrack.templating import templates

router = APIRouter(tags=["ui-inventory"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _has_uploaded_photo(form_field) -> bool:
    """A blank file input still arrives as an UploadFile with empty filename."""
    return bool(getattr(form_field, "filename", "") or "")


@router.get("/inventory", response_class=HTMLResponse)
async def list_page(
    request: Request,
    session: SessionDep,
    q: str | None = None,
    category: str | None = None,
    below_reorder: bool = False,
) -> HTMLResponse:
    items = await svc.list_items(
        session,
        search=q,
        category=category or None,
        below_reorder=below_reorder,
    )
    return templates.TemplateResponse(
        request,
        "inventory/list.html",
        {
            "items": items,
            "q": q or "",
            "selected_category": category or "",
            "below_reorder": below_reorder,
        },
    )


@router.get("/inventory/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "inventory/form.html", {"item": None, "errors": None}
    )


@router.post("/inventory", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    payload_data = strip_empty_strings({k: v for k, v in form.items() if k != "photo"})
    try:
        payload = InventoryItemCreate(**payload_data)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "inventory/form.html",
            {"item": None, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    photo_field = form.get("photo")
    photo_path: str | None = None
    if _has_uploaded_photo(photo_field):
        try:
            photo_path, _, _ = await save_photo(photo_field, subdir="inventory")
        except UploadError as exc:
            return templates.TemplateResponse(
                request,
                "inventory/form.html",
                {"item": None, "errors": [str(exc)]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    item = await svc.create_item(session, payload)
    if photo_path:
        item.photo_path = photo_path
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
    form = await request.form()
    remove_photo = form.get("remove_photo") in ("true", "on", "1")
    payload_data = null_empty_strings(
        {k: v for k, v in form.items() if k not in ("photo", "remove_photo")}
    )
    try:
        payload = InventoryItemUpdate(**payload_data)
    except ValidationError as exc:
        item = await svc.get_item(session, item_id)
        return templates.TemplateResponse(
            request,
            "inventory/form.html",
            {"item": item, "errors": [format_validation_error(e) for e in exc.errors()]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    item = await svc.update_item(session, item_id, payload)

    photo_field = form.get("photo")
    if _has_uploaded_photo(photo_field):
        try:
            new_path, _, _ = await save_photo(photo_field, subdir="inventory")
        except UploadError as exc:
            return templates.TemplateResponse(
                request,
                "inventory/form.html",
                {"item": item, "errors": [str(exc)]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        old_path = item.photo_path
        item.photo_path = new_path
        delete_upload(old_path)
    elif remove_photo and item.photo_path:
        delete_upload(item.photo_path)
        item.photo_path = None

    await session.commit()
    return RedirectResponse(url="/inventory", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/inventory/{item_id}/delete", response_class=HTMLResponse)
async def delete(item_id: int, session: SessionDep) -> HTMLResponse:
    item = await svc.get_item(session, item_id)
    photo_to_drop = item.photo_path
    await svc.delete_item(session, item_id)
    await session.commit()
    delete_upload(photo_to_drop)
    return RedirectResponse(url="/inventory", status_code=status.HTTP_303_SEE_OTHER)
