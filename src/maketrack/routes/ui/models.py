import contextlib
from typing import Annotated

import mistune
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.errors import NotFoundError
from maketrack.routes.ui._forms import (
    format_validation_error,
    null_empty_strings,
    query_string,
)
from maketrack.schemas.model import ModelCreate, ModelUpdate
from maketrack.services import assets as asset_svc
from maketrack.services import models as svc
from maketrack.services._pagination import DEFAULT_PAGE_SIZE
from maketrack.services.uploads import UploadError, delete_model_file, delete_model_folder
from maketrack.templating import templates

router = APIRouter(tags=["ui-models"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


# escape=True renders raw HTML in the README body as text rather than
# injecting it — the README is user-owned but we still don't trust it as
# markup in the page.
_markdown = mistune.create_markdown(escape=True)


def render_markdown(text: str | None) -> str | None:
    if not text:
        return None
    return _markdown(text)


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


async def _render_detail(
    request: Request,
    session: AsyncSession,
    model_id: int | None,
    *,
    edit_mode: bool,
    errors: list[str] | None = None,
    tags_override: list[str] | None = None,
    description_override: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    """Render the model detail page. `model_id=None` renders the create
    form (a blank draft that persists nothing until the user hits Save)."""
    is_new = model_id is None
    if is_new:
        model = None
        assets: list = []
        tags = tags_override or []
        description = description_override
        thumb_path = None
        stl_assets: list = []
    else:
        model = await svc.get_model(session, model_id)
        assets = list(await svc.list_assets(session, model_id))
        thumb_path = None
        if model.thumbnail_filename:
            thumb_path = f"{model.folder_name}/photos/{model.thumbnail_filename}"
        stl_assets = [a for a in assets if a.asset_type == "stl"]
        tags = tags_override if tags_override is not None else svc.decode_tags(model.tags)
        description = (
            description_override
            if description_override is not None
            else svc.read_description(model)
        )
    return templates.TemplateResponse(
        request,
        "models/detail.html",
        {
            "model": model,
            "is_new": is_new,
            "tags": tags,
            "tags_str": ", ".join(tags),
            "description": description,
            "description_html": render_markdown(description),
            "assets": assets,
            "thumbnail_path": thumb_path,
            "stl_assets": stl_assets,
            "first_stl": stl_assets[0] if stl_assets else None,
            "edit_mode": edit_mode,
            "errors": errors,
        },
        status_code=status_code,
    )


@router.get("/models/new", response_class=HTMLResponse)
async def new_page(request: Request, session: SessionDep) -> HTMLResponse:
    """Blank create form. Nothing is written to disk or the DB until Save —
    so abandoning the form leaves no orphan folder behind."""
    return await _render_detail(request, session, None, edit_mode=True)


@router.get("/models/{model_id}", response_class=HTMLResponse)
async def detail_page(
    model_id: int,
    request: Request,
    session: SessionDep,
    edit: bool = False,
) -> HTMLResponse:
    return await _render_detail(request, session, model_id, edit_mode=edit)


def _read_save_form(form) -> dict:
    """Pull the fields/files/marks out of a multipart Save submission."""
    new_files = [
        f for f in form.getlist("files") if getattr(f, "filename", None) and f.filename.strip()
    ]
    delete_ids = [
        int(x) for x in form.getlist("delete_asset_ids") if str(x).strip().lstrip("-").isdigit()
    ]
    thumbnail = (form.get("thumbnail") or "").strip() or None
    return {"new_files": new_files, "delete_ids": delete_ids, "thumbnail": thumbnail}


async def _apply_assets(
    session: AsyncSession,
    model_id: int,
    *,
    new_files: list,
    delete_ids: list[int],
    thumbnail: str | None,
) -> tuple[list[str], list[str]]:
    """Apply staged asset changes for one Save. Returns (upload_errors,
    removed_disk_paths). Disk deletes are returned for the caller to run
    after commit."""
    upload_errors: list[str] = []
    removed_paths: list[str] = []
    for aid in delete_ids:
        with contextlib.suppress(NotFoundError):
            removed_paths.append(await asset_svc.delete_asset(session, aid))
    for file in new_files:
        try:
            await asset_svc.upload_asset(session, model_id, file, set_as_thumbnail=False)
        except UploadError as exc:
            upload_errors.append(f"{file.filename}: {exc}")
    if thumbnail:
        assets = await asset_svc.list_for_model(session, model_id)
        match = next(
            (a for a in assets if a.filename == thumbnail and a.asset_type == "image"), None
        )
        if match is not None:
            await asset_svc.set_thumbnail(session, model_id, match.id)
    return upload_errors, removed_paths


@router.post("/models", response_class=HTMLResponse)
async def create(request: Request, session: SessionDep) -> HTMLResponse:
    """Commit a brand-new model from the create form: write the folder +
    README, upload the staged files, set the chosen thumbnail — all at once."""
    form = await request.form()
    raw = null_empty_strings(
        {k: form.get(k) for k in ("name", "source_type", "source_url", "notes", "description")}
    )
    tags = _parse_tags(form.get("tags"))
    if not (raw.get("name") or "").strip():
        return await _render_detail(
            request,
            session,
            None,
            edit_mode=True,
            errors=["Name is required."],
            tags_override=tags,
            description_override=raw.get("description"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        payload = ModelCreate(**raw, tags=tags)
    except ValidationError as exc:
        return await _render_detail(
            request,
            session,
            None,
            edit_mode=True,
            errors=[format_validation_error(e) for e in exc.errors()],
            tags_override=tags,
            description_override=raw.get("description"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    staged = _read_save_form(form)
    model = await svc.create_model(session, payload)
    await _apply_assets(
        session,
        model.id,
        new_files=staged["new_files"],
        delete_ids=[],
        thumbnail=staged["thumbnail"],
    )
    await session.commit()
    return RedirectResponse(url=f"/models/{model.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/models/{model_id}", response_class=HTMLResponse)
async def update(model_id: int, request: Request, session: SessionDep) -> HTMLResponse:
    """Commit a full-draft edit: field changes, new uploads, asset deletions,
    and the thumbnail choice are applied atomically when the user hits Save."""
    await svc.get_model(session, model_id)  # 404 if missing
    form = await request.form()
    raw = null_empty_strings(
        {k: form.get(k) for k in ("name", "source_type", "source_url", "notes", "description")}
    )
    tags = _parse_tags(form.get("tags"))
    if not (raw.get("name") or "").strip():
        return await _render_detail(
            request,
            session,
            model_id,
            edit_mode=True,
            errors=["Name is required."],
            tags_override=tags,
            description_override=raw.get("description"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        payload = ModelUpdate(**raw, tags=tags)
    except ValidationError as exc:
        return await _render_detail(
            request,
            session,
            model_id,
            edit_mode=True,
            errors=[format_validation_error(e) for e in exc.errors()],
            tags_override=tags,
            description_override=raw.get("description"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    staged = _read_save_form(form)
    _, removed_paths = await _apply_assets(
        session,
        model_id,
        new_files=staged["new_files"],
        delete_ids=staged["delete_ids"],
        thumbnail=staged["thumbnail"],
    )
    # update_model runs last so the README reflects the final thumbnail + fields.
    await svc.update_model(session, model_id, payload)
    await session.commit()
    for path in removed_paths:
        delete_model_file(path)
    # Save exits edit mode.
    return RedirectResponse(url=f"/models/{model_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/models/{model_id}/delete", response_class=HTMLResponse)
async def delete(model_id: int, session: SessionDep) -> HTMLResponse:
    folder_name = await svc.delete_model(session, model_id)
    await session.commit()
    delete_model_folder(folder_name)
    return RedirectResponse(url="/models", status_code=status.HTTP_303_SEE_OTHER)
