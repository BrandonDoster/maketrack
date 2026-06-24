from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.config import get_settings
from maketrack.db import get_session
from maketrack.services import assets as svc

router = APIRouter(tags=["assets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/assets/{asset_id}/download")
async def download_asset(asset_id: int, session: SessionDep) -> FileResponse:
    """Serve the asset bytes with the original filename via Content-Disposition.

    /media/<path> serves the same bytes for inline display (e.g. <img>),
    but downloads need the user's original filename so they end up with
    something sensible in their Downloads folder, not a UUID.
    """
    asset = await svc.get_asset(session, asset_id)
    target = (get_settings().models_path / asset.file_path).resolve()
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(
        target,
        filename=asset.filename,
        media_type="application/octet-stream",
    )
