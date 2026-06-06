import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

import frontmatter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.config import get_settings
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


# ── filesystem-first storage ────────────────────────────────────────────────
#
# Each model is a folder under models_path: README.md (YAML frontmatter +
# markdown body = description) plus photos/ and models/ subdirs. The web app
# writes through to disk AND the DB on every mutation; the scan job
# (sync/model_scan.py) reconciles edits made directly on the share.


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "model"


async def _unique_folder_name(session: AsyncSession, base: str) -> str:
    """A folder_name not already taken in the DB or on disk."""
    root = get_settings().models_path
    existing = set((await session.execute(select(Model.folder_name))).scalars().all())
    candidate = base
    n = 2
    while candidate in existing or (root / candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _readme_path(model: Model):
    return get_settings().models_path / model.folder_name / "README.md"


def write_readme(model: Model, description: str | None) -> str:
    """Render the model's README.md from its row + description body.

    Returns the SHA-256 of the written content so the caller can store it
    as readme_hash for the scan's change detection.
    """
    post = frontmatter.Post(description or "")
    post["name"] = model.name
    if model.thumbnail_filename:
        post["thumbnail"] = model.thumbnail_filename
    if model.source_type:
        post["source_type"] = model.source_type
    if model.source_url:
        post["source_url"] = model.source_url
    tags = decode_tags(model.tags)
    if tags:
        post["tags"] = tags
    if model.notes:
        post["notes"] = model.notes

    content = frontmatter.dumps(post)
    path = _readme_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode()).hexdigest()


def read_description(model: Model) -> str | None:
    """Read the markdown body (description) from the model's README on disk."""
    path = _readme_path(model)
    if not path.exists():
        return None
    try:
        body = frontmatter.load(str(path)).content
    except Exception:
        return None
    return body or None


def thumbnail_path_for(model: Model, assets: list[ModelAsset]) -> str | None:
    """Resolve `model.thumbnail_filename` to an asset's file_path.

    The thumbnail is a bare filename (frontmatter-friendly) but the image can
    live anywhere under the model folder now that subfolders are allowed, so
    match it to a real asset rather than assuming `photos/`. Falls back to the
    photos/ convention if no matching asset row is present yet.
    """
    if not model.thumbnail_filename:
        return None
    for a in assets:
        if a.filename == model.thumbnail_filename:
            return a.file_path
    return f"{model.folder_name}/photos/{model.thumbnail_filename}"


def build_file_tree(assets: list[ModelAsset], folder_name: str) -> dict:
    """Group assets into a nested {dirs, files} tree by their path under the
    model folder, so the detail page can render a collapsible layout that
    mirrors how the user organised models/cad, models/stl, etc. on disk.

    Returns {"dirs": {name: <subtree>}, "files": [ModelAsset, ...]}.
    """
    prefix = f"{folder_name}/"
    root: dict = {"dirs": {}, "files": []}
    for a in sorted(assets, key=lambda x: x.file_path):
        rel = a.file_path[len(prefix) :] if a.file_path.startswith(prefix) else a.file_path
        *dirs, _filename = rel.split("/")
        node = root
        for d in dirs:
            node = node["dirs"].setdefault(d, {"dirs": {}, "files": []})
        node["files"].append(a)
    return root


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

    # Project links now point at a specific ModelAsset, so resolve back to
    # the owning model_id through the asset to know which models are "in a
    # project". A model counts as linked if any of its assets is linked.
    project_link_rows = (
        await session.execute(
            select(ModelAsset.model_id, Project.name)
            .join(ProjectModel, ProjectModel.model_asset_id == ModelAsset.id)
            .join(Project, Project.id == ProjectModel.project_id)
            .where(ModelAsset.model_id.in_(model_ids))
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
        thumb_path = thumbnail_path_for(m, assets)
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
    """Create a model folder (README + photos/ + models/) and its DB row.

    Write-through: the folder and README land on disk immediately so the
    library is browsable over a share without waiting for a scan.
    """
    folder_name = await _unique_folder_name(session, _slugify(payload.name))
    model = Model(
        folder_name=folder_name,
        name=payload.name,
        source_type=payload.source_type,
        source_url=payload.source_url,
        notes=payload.notes,
        tags=_encode_tags(payload.tags),
        thumbnail_filename=None,
    )
    session.add(model)
    await session.flush()

    root = get_settings().models_path / folder_name
    (root / "photos").mkdir(parents=True, exist_ok=True)
    (root / "models").mkdir(parents=True, exist_ok=True)
    model.readme_hash = write_readme(model, payload.description)
    await session.flush()
    return model


async def update_model(session: AsyncSession, model_id: int, payload: ModelUpdate) -> Model:
    """Apply field updates to the row and rewrite README.md to match.

    folder_name is intentionally NOT renamed when the name changes — it
    would invalidate every asset file_path and the on-disk tree. The
    display name lives in README frontmatter; the folder stays stable.
    """
    model = await get_model(session, model_id)
    data = payload.model_dump(exclude_unset=True)
    description_provided = "description" in data
    description = data.pop("description", None)
    if "tags" in data:
        model.tags = _encode_tags(data.pop("tags"))
    for key, value in data.items():
        setattr(model, key, value)
    await session.flush()

    # Preserve the existing README body when the caller didn't send one
    # (e.g. a partial API PATCH that only touches the name).
    if not description_provided:
        description = read_description(model)
    model.readme_hash = write_readme(model, description)
    await session.flush()
    return model


async def delete_model(session: AsyncSession, model_id: int) -> str:
    """Delete a model row (cascading to assets + project links) and return
    the folder_name so the caller can remove the folder after commit.
    """
    model = await get_model(session, model_id)
    folder_name = model.folder_name
    await session.delete(model)
    await session.flush()
    return folder_name
