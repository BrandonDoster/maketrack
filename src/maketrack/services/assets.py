from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.config import get_settings
from maketrack.errors import NotFoundError
from maketrack.models.model import Model, ModelAsset
from maketrack.services import models as models_svc
from maketrack.services import three_mf
from maketrack.services.uploads import (
    UploadError,
    delete_model_file,
    save_model_asset,
    write_bytes_to_model,
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


def _subdir_for(asset_type: str) -> str:
    """Images live in photos/, everything printable in models/."""
    return "photos" if asset_type == "image" else "models"


def _rewrite_readme(model: Model) -> None:
    """Persist a frontmatter change (e.g. thumbnail) back to README.md."""
    model.readme_hash = models_svc.write_readme(model, models_svc.read_description(model))


async def upload_asset(
    session: AsyncSession,
    model_id: int,
    file: UploadFile,
    *,
    set_as_thumbnail: bool = False,
) -> ModelAsset:
    """Save an uploaded file into the model's folder and create its row.

    Images land in <folder>/photos/, printable files in <folder>/models/,
    with the original filename preserved on disk. For 3MF uploads we also
    extract the embedded thumbnail PNG into photos/ as a generated image.
    If the model has no thumbnail yet (or the caller asks), point
    models.thumbnail_filename at the image and rewrite README.md.
    """
    model = await session.get(Model, model_id)
    if model is None:
        raise NotFoundError("model", model_id)

    if not file.filename:
        raise UploadError("upload has no filename")

    asset_type = asset_type_from_filename(file.filename)
    rel_path, size, sha, name = await save_model_asset(
        file, folder_name=model.folder_name, subdir=_subdir_for(asset_type)
    )

    asset = ModelAsset(
        model_id=model_id,
        asset_type=asset_type,
        filename=name,
        file_path=rel_path,
        file_size=size,
        sha256=sha,
        generated=False,
    )
    session.add(asset)
    await session.flush()

    thumb_filename: str | None = None
    if asset_type == "image":
        thumb_filename = name
    elif asset_type == "3mf":
        full_path = get_settings().models_path / rel_path
        thumb_bytes = three_mf.extract_thumbnail(full_path)
        if thumb_bytes is not None:
            t_path, t_size, t_sha, t_name = write_bytes_to_model(
                thumb_bytes,
                folder_name=model.folder_name,
                subdir="photos",
                filename=f"{Path(name).stem}-thumbnail.png",
            )
            thumb_asset = ModelAsset(
                model_id=model_id,
                asset_type="image",
                filename=t_name,
                file_path=t_path,
                file_size=t_size,
                sha256=t_sha,
                generated=True,
            )
            session.add(thumb_asset)
            await session.flush()
            thumb_filename = t_name

    # Auto-set thumbnail on first eligible image, or honor explicit request.
    if thumb_filename is not None and (set_as_thumbnail or model.thumbnail_filename is None):
        model.thumbnail_filename = thumb_filename
        _rewrite_readme(model)

    await session.flush()
    return asset


async def get_asset(session: AsyncSession, asset_id: int) -> ModelAsset:
    asset = await session.get(ModelAsset, asset_id)
    if asset is None:
        raise NotFoundError("model_asset", asset_id)
    return asset


async def delete_asset(session: AsyncSession, asset_id: int) -> str:
    """Delete an asset row and return its file path for disk cleanup.

    If the asset was the model's thumbnail, clear thumbnail_filename and
    rewrite README.md so the frontmatter stays consistent.
    """
    asset = await get_asset(session, asset_id)
    file_path = asset.file_path
    model = await session.get(Model, asset.model_id)
    was_thumbnail = model is not None and model.thumbnail_filename == asset.filename
    await session.delete(asset)
    await session.flush()
    if was_thumbnail:
        model.thumbnail_filename = None
        _rewrite_readme(model)
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
    model.thumbnail_filename = asset.filename
    _rewrite_readme(model)
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
        delete_model_file(p)
