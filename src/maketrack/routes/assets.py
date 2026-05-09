from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.config import get_settings
from maketrack.db import get_session
from maketrack.schemas.model import ModelAssetRead
from maketrack.services import assets as svc
from maketrack.services.uploads import UploadError, delete_upload

router = APIRouter(tags=["assets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class SetThumbnailPayload(BaseModel):
    asset_id: int


@router.get("/api/models/{model_id}/assets", response_model=list[ModelAssetRead])
async def list_assets(model_id: int, session: SessionDep) -> list[ModelAssetRead]:
    rows = await svc.list_for_model(session, model_id)
    return [ModelAssetRead.model_validate(r) for r in rows]


@router.post(
    "/api/models/{model_id}/assets",
    response_model=ModelAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    model_id: int,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    set_as_thumbnail: bool = False,
) -> ModelAssetRead:
    try:
        asset = await svc.upload_asset(session, model_id, file, set_as_thumbnail=set_as_thumbnail)
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(asset)
    return ModelAssetRead.model_validate(asset)


@router.delete("/api/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(asset_id: int, session: SessionDep) -> None:
    file_path = await svc.delete_asset(session, asset_id)
    await session.commit()
    delete_upload(file_path)


@router.post("/api/models/{model_id}/thumbnail")
async def set_thumbnail(model_id: int, payload: SetThumbnailPayload, session: SessionDep) -> dict:
    try:
        model = await svc.set_thumbnail(session, model_id, payload.asset_id)
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return {"id": model.id, "thumbnail_asset_id": model.thumbnail_asset_id}


@router.get("/assets/{asset_id}/download")
async def download_asset(asset_id: int, session: SessionDep) -> FileResponse:
    """Serve the asset bytes with the original filename via Content-Disposition.

    /media/<path> serves the same bytes for inline display (e.g. <img>),
    but downloads need the user's original filename so they end up with
    something sensible in their Downloads folder, not a UUID.
    """
    asset = await svc.get_asset(session, asset_id)
    target = (get_settings().uploads_path / asset.file_path).resolve()
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(
        target,
        filename=asset.filename,
        media_type="application/octet-stream",
    )
