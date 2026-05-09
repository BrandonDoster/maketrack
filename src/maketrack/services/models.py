import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.models.model import Model, ModelAsset
from maketrack.schemas.model import ModelCreate, ModelUpdate


def _encode_tags(tags: list[str] | None) -> str | None:
    if tags is None:
        return None
    if not tags:
        return None
    return json.dumps(list(tags))


def decode_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    try:
        decoded = json.loads(tags)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(t) for t in decoded]


async def list_models(
    session: AsyncSession,
    *,
    tag: str | None = None,
    source_type: str | None = None,
) -> Sequence[Model]:
    stmt = select(Model).order_by(Model.name)
    if source_type is not None:
        stmt = stmt.where(Model.source_type == source_type)
    rows = (await session.execute(stmt)).scalars().all()
    if tag is None:
        return rows
    # Tags are JSON-as-text; filter in Python rather than tying us to a
    # JSON1-on-by-default SQLite build.
    return [r for r in rows if tag in decode_tags(r.tags)]


async def get_model(session: AsyncSession, model_id: int) -> Model:
    model = await session.get(Model, model_id)
    if model is None:
        raise NotFoundError("model", model_id)
    return model


async def list_assets(session: AsyncSession, model_id: int) -> Sequence[ModelAsset]:
    stmt = (
        select(ModelAsset)
        .where(ModelAsset.model_id == model_id)
        .order_by(ModelAsset.uploaded_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def create_model(session: AsyncSession, payload: ModelCreate) -> Model:
    data = payload.model_dump()
    tags = data.pop("tags", [])
    model = Model(**data, tags=_encode_tags(tags))
    session.add(model)
    await session.flush()
    return model


async def update_model(session: AsyncSession, model_id: int, payload: ModelUpdate) -> Model:
    model = await get_model(session, model_id)
    data = payload.model_dump(exclude_unset=True)
    if "tags" in data:
        model.tags = _encode_tags(data.pop("tags"))
    for key, value in data.items():
        setattr(model, key, value)
    await session.flush()
    return model


async def delete_model(session: AsyncSession, model_id: int) -> Sequence[str]:
    """Delete a model. Returns the list of asset paths to clean up on disk.

    The DB cascade drops the model_assets rows; the caller is responsible
    for unlinking the underlying files (callers usually run inside a
    transaction so we hand back the paths instead of touching disk here).
    """
    assets = await list_assets(session, model_id)
    paths = [a.file_path for a in assets]
    model = await get_model(session, model_id)
    await session.delete(model)
    await session.flush()
    return paths
