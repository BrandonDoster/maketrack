from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.routes.ui._forms import (
    format_validation_error,
    null_empty_strings,
    query_string,
    strip_empty_strings,
)
from maketrack.schemas.model import ModelCreate, ModelUpdate
from maketrack.services import assets as asset_svc
from maketrack.services import models as svc
from maketrack.services._pagination import DEFAULT_PAGE_SIZE
from maketrack.services.uploads import UploadError, delete_upload
from maketrack.templating import templates

router = APIRouter(tags=["ui-models"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


_VALID_MODEL_VIEWS = ("cards", "details", "list")
_VIEW_COOKIE = "maketrack_models_view"
_HIDE_COOKIE = "maketrack_models_hide_project_models"


def _resolve_view(query_view: str | None, request: Request) -> str:
    """Pick the view: explicit ?view= wins, then cookie, then 'cards'."""
    if query_view in _VALID_MODEL_VIEWS:
        return query_view
    cookie = request.cookies.get(_VIEW_COOKIE)
    if cookie in _VALID_MODEL_VIEWS:
        return cookie
    return "cards"


def _resolve_hide(query_hide: bool | None, request: Request) -> bool:
    """Same precedence as _resolve_view, default off."""
    if query_hide is not None:
        return query_hide
    return request.cookies.get(_HIDE_COOKIE) == "true"


@router.get("/models", response_class=HTMLResponse)
async def list_page(
    request: Request,
    session: SessionDep,
    view: str | None = None,
    hide_project_models: bool | None = None,
    tag: str | None = None,
    q: str | None = None,
    page: int | None = None,
) -> HTMLResponse:
    view = _resolve_view(view, request)
    hide_resolved = _resolve_hide(hide_project_models, request)
    page_obj = await svc.list_models_with_context(
        session,
        tag=tag,
        hide_project_models=hide_resolved,
        search=q,
        page=page,
        page_size=DEFAULT_PAGE_SIZE,
    )
    query_base = query_string(
        {
            "view": view,
            "hide_project_models": hide_resolved,
            "tag": tag,
            "q": q,
        }
    )
    return templates.TemplateResponse(
        request,
        "models/list.html",
        {
            "items": page_obj.items,
            "view": view,
            "hide_project_models": hide_resolved,
            "tag": tag,
            "q": q or "",
            "page": page_obj,
            "query_base": query_base,
        },
    )


@router.post("/models/preferences", response_class=HTMLResponse)
async def save_preferences(request: Request) -> HTMLResponse:
    """Persist the current view + filter as cookies so /models with no
    query params uses these as the default. The user controls when to
    save (explicit button) so experimenting with views doesn't clobber
    their default.
    """
    form = await request.form()
    view = form.get("view", "cards")
    if view not in _VALID_MODEL_VIEWS:
        view = "cards"
    hide = form.get("hide_project_models") in ("true", "on", "1")
    response = RedirectResponse(url="/models", status_code=status.HTTP_303_SEE_OTHER)
    one_year = 60 * 60 * 24 * 365
    response.set_cookie(_VIEW_COOKIE, view, max_age=one_year, samesite="lax")
    response.set_cookie(_HIDE_COOKIE, "true" if hide else "false", max_age=one_year, samesite="lax")
    return response


@router.get("/models/new", response_class=HTMLResponse)
async def new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "models/form.html", {"model": None, "tags_str": "", "errors": None}
    )


@router.post("/models", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    form = strip_empty_strings(dict(await request.form()))
    tags = _parse_tags(form.pop("tags", None))
    try:
        payload = ModelCreate(**form, tags=tags)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "models/form.html",
            {
                "model": None,
                "tags_str": ", ".join(tags),
                "errors": [format_validation_error(e) for e in exc.errors()],
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    model = await svc.create_model(session, payload)
    await session.commit()
    return RedirectResponse(url=f"/models/{model.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/models/{model_id}", response_class=HTMLResponse)
async def detail_page(model_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    model = await svc.get_model(session, model_id)
    assets = await svc.list_assets(session, model_id)
    thumb_path = None
    if model.thumbnail_asset_id:
        for a in assets:
            if a.id == model.thumbnail_asset_id:
                thumb_path = a.file_path
                break
    stl_assets = [a for a in assets if a.asset_type == "stl"]
    return templates.TemplateResponse(
        request,
        "models/detail.html",
        {
            "model": model,
            "tags": svc.decode_tags(model.tags),
            "assets": assets,
            "thumbnail_path": thumb_path,
            "stl_assets": stl_assets,
            "first_stl": stl_assets[0] if stl_assets else None,
        },
    )


@router.get("/models/{model_id}/edit", response_class=HTMLResponse)
async def edit_form(model_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    model = await svc.get_model(session, model_id)
    return templates.TemplateResponse(
        request,
        "models/form.html",
        {
            "model": model,
            "tags_str": ", ".join(svc.decode_tags(model.tags)),
            "errors": None,
        },
    )


@router.post("/models/{model_id}", response_class=HTMLResponse)
async def update(model_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    form = null_empty_strings(dict(await request.form()))
    tags = _parse_tags(form.pop("tags", None))
    try:
        payload = ModelUpdate(**form, tags=tags)
    except ValidationError as exc:
        model = await svc.get_model(session, model_id)
        return templates.TemplateResponse(
            request,
            "models/form.html",
            {
                "model": model,
                "tags_str": ", ".join(tags),
                "errors": [format_validation_error(e) for e in exc.errors()],
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    await svc.update_model(session, model_id, payload)
    await session.commit()
    return RedirectResponse(url=f"/models/{model_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/models/{model_id}/delete", response_class=HTMLResponse)
async def delete(model_id: int, session: SessionDep) -> HTMLResponse:
    paths = await svc.delete_model(session, model_id)
    await session.commit()
    asset_svc.cleanup_files(paths)
    return RedirectResponse(url="/models", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/models/{model_id}/assets", response_class=HTMLResponse)
async def upload(
    model_id: int,
    request: Request,
    session: SessionDep,
    files: Annotated[list[UploadFile], File()],
) -> HTMLResponse:
    errors: list[str] = []
    saved = 0
    for file in files:
        if not (file.filename or "").strip():
            continue
        try:
            await asset_svc.upload_asset(session, model_id, file)
            saved += 1
        except UploadError as exc:
            errors.append(f"{file.filename}: {exc}")
    if saved:
        await session.commit()
    if errors:
        # Re-render detail with errors so the user sees what failed.
        model = await svc.get_model(session, model_id)
        assets = await svc.list_assets(session, model_id)
        thumb_path = None
        if model.thumbnail_asset_id:
            for a in assets:
                if a.id == model.thumbnail_asset_id:
                    thumb_path = a.file_path
                    break
        stl_assets = [a for a in assets if a.asset_type == "stl"]
        return templates.TemplateResponse(
            request,
            "models/detail.html",
            {
                "model": model,
                "tags": svc.decode_tags(model.tags),
                "assets": assets,
                "thumbnail_path": thumb_path,
                "stl_assets": stl_assets,
                "first_stl": stl_assets[0] if stl_assets else None,
                "upload_errors": errors,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(url=f"/models/{model_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/models/{model_id}/thumbnail/{asset_id}", response_class=HTMLResponse)
async def set_thumbnail(model_id: int, asset_id: int, session: SessionDep) -> HTMLResponse:
    try:
        await asset_svc.set_thumbnail(session, model_id, asset_id)
    except UploadError:
        return RedirectResponse(url=f"/models/{model_id}", status_code=status.HTTP_303_SEE_OTHER)
    await session.commit()
    return RedirectResponse(url=f"/models/{model_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/assets/{asset_id}/delete", response_class=HTMLResponse)
async def delete_asset(asset_id: int, session: SessionDep) -> HTMLResponse:
    asset = await asset_svc.get_asset(session, asset_id)
    model_id = asset.model_id
    file_path = await asset_svc.delete_asset(session, asset_id)
    await session.commit()
    delete_upload(file_path)
    return RedirectResponse(url=f"/models/{model_id}", status_code=status.HTTP_303_SEE_OTHER)
