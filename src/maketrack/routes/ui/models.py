from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.routes.ui._forms import format_validation_error, strip_empty_strings
from maketrack.schemas.model import ModelCreate, ModelUpdate
from maketrack.services import assets as asset_svc
from maketrack.services import models as svc
from maketrack.services.uploads import UploadError, delete_upload
from maketrack.templating import templates

router = APIRouter(tags=["ui-models"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


@router.get("/models", response_class=HTMLResponse)
async def list_page(request: Request, session: SessionDep) -> HTMLResponse:
    rows = await svc.list_models(session)
    # Build a lightweight rollup the template can rely on without N more
    # queries: per-model thumbnail file_path and the set of asset_types.
    decorated = []
    for m in rows:
        assets = await svc.list_assets(session, m.id)
        thumb_path = None
        if m.thumbnail_asset_id is not None:
            for a in assets:
                if a.id == m.thumbnail_asset_id:
                    thumb_path = a.file_path
                    break
        formats = sorted({a.asset_type for a in assets})
        decorated.append(
            {
                "model": m,
                "tags": svc.decode_tags(m.tags),
                "thumbnail_path": thumb_path,
                "formats": formats,
                "asset_count": len(assets),
            }
        )
    return templates.TemplateResponse(request, "models/list.html", {"items": decorated})


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
    form = strip_empty_strings(dict(await request.form()))
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
