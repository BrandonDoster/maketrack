from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.config import get_settings
from maketrack.errors import NotFoundError
from maketrack.models.model import Model, ModelAsset
from maketrack.services import three_mf
from maketrack.services.uploads import (
    UploadError,
    delete_upload,
    save_asset,
    write_bytes_as_asset,
)

ASSET_TYPE_BY_EXT: dict[str, str] = {
    ".stl": "stl",
    ".step": "step",
    ".stp": "step",
    ".3mf": "3mf",
    ".gcode": "gcode",
    ".g": "gcode",
    ".gco": "gcode",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
}


def asset_type_from_filename(filename: str) -> str:
    return ASSET_TYPE_BY_EXT.get(Path(filename).suffix.lower(), "other")


async def upload_asset(
    session: AsyncSession,
    model_id: int,
    file: UploadFile,
    *,
    set_as_thumbnail: bool = False,
) -> ModelAsset:
    """Save an uploaded file and create a model_asset row for it.

    For 3MF uploads we also try to extract the embedded thumbnail PNG and
    save it as a second asset (asset_type='image', generated=True). If
    the model has no thumbnail set yet, point its thumbnail_asset_id at
    that extracted image.
    """
    model = await session.get(Model, model_id)
    if model is None:
        raise NotFoundError("model", model_id)

    if not file.filename:
        raise UploadError("upload has no filename")

    asset_type = asset_type_from_filename(file.filename)
    relative_path, size, sha = await save_asset(file, subdir="models")

    asset = ModelAsset(
        model_id=model_id,
        asset_type=asset_type,
        filename=file.filename,
        file_path=relative_path,
        file_size=size,
        sha256=sha,
        generated=False,
    )
    session.add(asset)
    await session.flush()

    image_for_thumb: ModelAsset | None = None
    if asset_type == "image":
        image_for_thumb = asset
    elif asset_type == "3mf":
        full_path = get_settings().uploads_path / relative_path
        thumb_bytes = three_mf.extract_thumbnail(full_path)
        if thumb_bytes is not None:
            t_path, t_size, t_sha = write_bytes_as_asset(
                thumb_bytes, subdir="models", extension=".png"
            )
            image_for_thumb = ModelAsset(
                model_id=model_id,
                asset_type="image",
                filename=f"{Path(file.filename).stem}-thumbnail.png",
                file_path=t_path,
                file_size=t_size,
                sha256=t_sha,
                generated=True,
            )
            session.add(image_for_thumb)
            await session.flush()

    # Auto-set thumbnail on first eligible image, or honor explicit request.
    if image_for_thumb is not None and (set_as_thumbnail or model.thumbnail_asset_id is None):
        model.thumbnail_asset_id = image_for_thumb.id

    await session.flush()
    return asset


async def get_asset(session: AsyncSession, asset_id: int) -> ModelAsset:
    asset = await session.get(ModelAsset, asset_id)
    if asset is None:
        raise NotFoundError("model_asset", asset_id)
    return asset


async def delete_asset(session: AsyncSession, asset_id: int) -> str:
    """Delete an asset row. Returns the file path for disk cleanup.

    The model's thumbnail_asset_id FK has ON DELETE SET NULL so an
    in-flight thumbnail vanishes cleanly. No need to clear it manually.
    """
    asset = await get_asset(session, asset_id)
    file_path = asset.file_path
    await session.delete(asset)
    await session.flush()
    return file_path


async def set_thumbnail(session: AsyncSession, model_id: int, asset_id: int) -> Model:
    model = await session.get(Model, model_id)
    if model is None:
        raise NotFoundError("model", model_id)
    asset = await get_asset(session, asset_id)
    if asset.model_id != model_id:
        raise NotFoundError("model_asset", asset_id)
    if asset.asset_type != "image":
        raise UploadError(f"can't use {asset.asset_type} asset as a thumbnail")
    model.thumbnail_asset_id = asset_id
    await session.flush()
    return model


async def list_for_model(session: AsyncSession, model_id: int) -> list[ModelAsset]:
    stmt = (
        select(ModelAsset)
        .where(ModelAsset.model_id == model_id)
        .order_by(ModelAsset.uploaded_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


def cleanup_files(paths: list[str]) -> None:
    for p in paths:
        delete_upload(p)
