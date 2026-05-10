import json
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.models.model import Model, ModelAsset
from maketrack.models.project import Project, ProjectModel
from maketrack.schemas.model import ModelCreate, ModelUpdate
from maketrack.services._pagination import DEFAULT_PAGE_SIZE, Page, normalize_page


@dataclass(slots=True)
class ModelListEntry:
    """Hydrated row for the models list — bundles the model itself with the
    cheap aggregates the UI wants (thumbnail, formats, asset count, project
    links). One round trip per axis instead of N+1 per model."""

    model: Model
    tags: list[str]
    thumbnail_path: str | None
    formats: list[str]
    asset_count: int
    project_names: list[str]


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
    search: str | None = None,
) -> Sequence[Model]:
    stmt = select(Model).order_by(Model.name)
    if source_type is not None:
        stmt = stmt.where(Model.source_type == source_type)
    if search:
        stmt = stmt.where(Model.name.icontains(search))
    rows = (await session.execute(stmt)).scalars().all()
    if tag is None:
        return rows
    # Tags are JSON-as-text; filter in Python rather than tying us to a
    # JSON1-on-by-default SQLite build.
    return [r for r in rows if tag in decode_tags(r.tags)]


async def list_models_with_context(
    session: AsyncSession,
    *,
    tag: str | None = None,
    source_type: str | None = None,
    search: str | None = None,
    hide_project_models: bool = False,
    page: int | None = None,
    page_size: int | None = None,
) -> Page[ModelListEntry]:
    """Like list_models but pulls in the data the list page needs in three
    flat queries rather than one-per-model.

    Returns a Page so the caller has both the slice and the post-filter
    total in one call. tag + hide_project_models are Python-side filters
    (because tags are JSON-as-text and the project-link gate compares
    against a join), so the page slice happens after that filter pass.
    """
    stmt = select(Model).order_by(Model.name)
    if source_type is not None:
        stmt = stmt.where(Model.source_type == source_type)
    if search:
        stmt = stmt.where(Model.name.icontains(search))
    models = list((await session.execute(stmt)).scalars().all())
    if not models:
        effective_size = page_size if page_size is not None else DEFAULT_PAGE_SIZE
        return Page(items=[], total=0, page=1, page_size=effective_size)

    model_ids = [m.id for m in models]

    asset_rows = (
        (await session.execute(select(ModelAsset).where(ModelAsset.model_id.in_(model_ids))))
        .scalars()
        .all()
    )
    assets_by_model: dict[int, list[ModelAsset]] = {}
    for a in asset_rows:
        assets_by_model.setdefault(a.model_id, []).append(a)

    project_link_rows = (
        await session.execute(
            select(ProjectModel.model_id, Project.name)
            .join(Project, Project.id == ProjectModel.project_id)
            .where(ProjectModel.model_id.in_(model_ids))
        )
    ).all()
    projects_by_model: dict[int, list[str]] = {}
    for model_id, project_name in project_link_rows:
        projects_by_model.setdefault(model_id, []).append(project_name)

    out: list[ModelListEntry] = []
    for m in models:
        project_names = projects_by_model.get(m.id, [])
        if hide_project_models and project_names:
            continue
        decoded_tags = decode_tags(m.tags)
        if tag is not None and tag not in decoded_tags:
            continue
        assets = assets_by_model.get(m.id, [])
        thumb_path: str | None = None
        if m.thumbnail_asset_id is not None:
            for a in assets:
                if a.id == m.thumbnail_asset_id:
                    thumb_path = a.file_path
                    break
        formats = sorted({a.asset_type for a in assets})
        out.append(
            ModelListEntry(
                model=m,
                tags=decoded_tags,
                thumbnail_path=thumb_path,
                formats=formats,
                asset_count=len(assets),
                project_names=sorted(project_names),
            )
        )

    total = len(out)
    effective_size = page_size if page_size is not None else max(total, DEFAULT_PAGE_SIZE)
    if page is None:
        # No pagination requested — single "page" with everything on it.
        return Page(items=out, total=total, page=1, page_size=effective_size)

    current_page = normalize_page(page, total, effective_size)
    start = (current_page - 1) * effective_size
    return Page(
        items=out[start : start + effective_size],
        total=total,
        page=current_page,
        page_size=effective_size,
    )


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
