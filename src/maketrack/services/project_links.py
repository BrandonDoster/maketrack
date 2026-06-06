from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.models.filament import Filament
from maketrack.models.inventory import InventoryItem
from maketrack.models.model import Model, ModelAsset
from maketrack.models.printer import Printer
from maketrack.models.project import (
    Project,
    ProjectFilament,
    ProjectItem,
    ProjectModel,
)
from maketrack.schemas.project import (
    ProjectFilamentLinkCreate,
    ProjectFilamentLinkUpdate,
    ProjectItemLinkCreate,
    ProjectItemLinkUpdate,
    ProjectModelLinkCreate,
    ProjectModelLinkUpdate,
)
from maketrack.services.models import build_file_tree


@dataclass(slots=True)
class HydratedProjectModel:
    link: ProjectModel
    asset: ModelAsset
    model: Model
    thumbnail_path: str | None


@dataclass(slots=True)
class UnlinkedModelTree:
    """A model collection plus its still-linkable files, arranged as a
    collapsible file tree for the project's 'link a model' browser."""

    model: Model
    tree: dict
    count: int


@dataclass(slots=True)
class HydratedProjectFilament:
    link: ProjectFilament
    filament: Filament


@dataclass(slots=True)
class HydratedProjectItem:
    link: ProjectItem
    # NULL for unlinked custom BOM rows.
    item: InventoryItem | None

    @property
    def display_name(self) -> str:
        if self.item is not None and self.item.name:
            return self.item.name
        return self.link.name or "(unnamed)"

    @property
    def display_unit(self) -> str | None:
        if self.item is not None and self.item.unit:
            return self.item.unit
        return self.link.unit


# ── models ─────────────────────────────────────────────────────────────────


async def list_project_models(session: AsyncSession, project_id: int) -> list[HydratedProjectModel]:
    # Join ProjectModel -> ModelAsset -> Model to get all three entities.
    rows = (
        await session.execute(
            select(ProjectModel, ModelAsset, Model)
            .join(ModelAsset, ModelAsset.id == ProjectModel.model_asset_id)
            .join(Model, Model.id == ModelAsset.model_id)
            .where(ProjectModel.project_id == project_id)
            .order_by(Model.name)
        )
    ).all()
    if not rows:
        return []

    # Resolve thumbnails: thumbnail_filename is a bare name but the image can
    # live anywhere under the model folder (subfolders are allowed), so map it
    # to the matching asset's file_path in one batched query.
    thumb_model_ids = {m.id for _, _, m in rows if m.thumbnail_filename}
    paths_by_model_filename: dict[tuple[int, str], str] = {}
    if thumb_model_ids:
        thumb_rows = (
            await session.execute(
                select(ModelAsset.model_id, ModelAsset.filename, ModelAsset.file_path).where(
                    ModelAsset.model_id.in_(thumb_model_ids)
                )
            )
        ).all()
        paths_by_model_filename = {(mid, fname): fpath for mid, fname, fpath in thumb_rows}

    out: list[HydratedProjectModel] = []
    for link, asset, model in rows:
        thumb_path: str | None = None
        if model.thumbnail_filename:
            thumb_path = paths_by_model_filename.get(
                (model.id, model.thumbnail_filename),
                f"{model.folder_name}/photos/{model.thumbnail_filename}",
            )
        out.append(
            HydratedProjectModel(link=link, asset=asset, model=model, thumbnail_path=thumb_path)
        )
    return out


async def add_model(
    session: AsyncSession, project_id: int, payload: ProjectModelLinkCreate
) -> ProjectModel:
    if await session.get(Project, project_id) is None:
        raise NotFoundError("project", project_id)
    if await session.get(ModelAsset, payload.model_asset_id) is None:
        raise NotFoundError("model_asset", payload.model_asset_id)
    existing = await session.get(ProjectModel, (project_id, payload.model_asset_id))
    if existing is not None:
        # Idempotent re-link: bump qty/status/notes from the new payload
        # rather than failing on the composite PK.
        existing.qty_to_print = payload.qty_to_print
        existing.status = payload.status
        existing.notes = payload.notes
        await session.flush()
        return existing
    link = ProjectModel(
        project_id=project_id,
        model_asset_id=payload.model_asset_id,
        qty_to_print=payload.qty_to_print,
        status=payload.status,
        notes=payload.notes,
    )
    session.add(link)
    await session.flush()
    return link


async def update_model_link(
    session: AsyncSession,
    project_id: int,
    model_asset_id: int,
    payload: ProjectModelLinkUpdate,
) -> ProjectModel:
    link = await session.get(ProjectModel, (project_id, model_asset_id))
    if link is None:
        raise NotFoundError("project_model", f"({project_id},{model_asset_id})")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(link, k, v)
    await session.flush()
    return link


async def remove_model(session: AsyncSession, project_id: int, model_asset_id: int) -> None:
    link = await session.get(ProjectModel, (project_id, model_asset_id))
    if link is None:
        raise NotFoundError("project_model", f"({project_id},{model_asset_id})")
    await session.delete(link)
    await session.flush()


# ── filaments ──────────────────────────────────────────────────────────────


async def list_project_filaments(
    session: AsyncSession, project_id: int
) -> list[HydratedProjectFilament]:
    rows = (
        await session.execute(
            select(ProjectFilament, Filament)
            .join(Filament, Filament.id == ProjectFilament.filament_id)
            .where(ProjectFilament.project_id == project_id)
            .order_by(ProjectFilament.id)
        )
    ).all()
    return [HydratedProjectFilament(link=link, filament=f) for link, f in rows]


async def add_filament(
    session: AsyncSession, project_id: int, payload: ProjectFilamentLinkCreate
) -> ProjectFilament:
    if await session.get(Project, project_id) is None:
        raise NotFoundError("project", project_id)
    if await session.get(Filament, payload.filament_id) is None:
        raise NotFoundError("filament", payload.filament_id)
    link = ProjectFilament(
        project_id=project_id,
        filament_id=payload.filament_id,
        est_weight_g=payload.est_weight_g,
        actual_weight_g=payload.actual_weight_g,
        role=payload.role,
    )
    session.add(link)
    await session.flush()
    return link


async def update_filament_link(
    session: AsyncSession, link_id: int, payload: ProjectFilamentLinkUpdate
) -> ProjectFilament:
    link = await session.get(ProjectFilament, link_id)
    if link is None:
        raise NotFoundError("project_filament", link_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(link, k, v)
    await session.flush()
    return link


async def remove_filament(session: AsyncSession, link_id: int) -> None:
    link = await session.get(ProjectFilament, link_id)
    if link is None:
        raise NotFoundError("project_filament", link_id)
    await session.delete(link)
    await session.flush()


# ── inventory items / BOM ──────────────────────────────────────────────────


async def list_project_items(session: AsyncSession, project_id: int) -> list[HydratedProjectItem]:
    # Outer join so unlinked BOM rows still come back; sort first by linked
    # item name, then by typed name, then by id for stability.
    rows = (
        await session.execute(
            select(ProjectItem, InventoryItem)
            .outerjoin(InventoryItem, InventoryItem.id == ProjectItem.inventory_item_id)
            .where(ProjectItem.project_id == project_id)
            .order_by(InventoryItem.name.asc().nulls_last(), ProjectItem.name, ProjectItem.id)
        )
    ).all()
    return [HydratedProjectItem(link=link, item=it) for link, it in rows]


async def add_item(
    session: AsyncSession, project_id: int, payload: ProjectItemLinkCreate
) -> ProjectItem:
    if await session.get(Project, project_id) is None:
        raise NotFoundError("project", project_id)
    if payload.inventory_item_id is None and not (payload.name and payload.name.strip()):
        raise ValueError("BOM row needs either an inventory_item_id or a typed name")
    if (
        payload.inventory_item_id is not None
        and await session.get(InventoryItem, payload.inventory_item_id) is None
    ):
        raise NotFoundError("inventory_item", payload.inventory_item_id)
    link = ProjectItem(
        project_id=project_id,
        inventory_item_id=payload.inventory_item_id,
        name=payload.name,
        unit=payload.unit,
        qty_required=payload.qty_required,
        qty_consumed=payload.qty_consumed,
        notes=payload.notes,
    )
    session.add(link)
    await session.flush()
    return link


async def update_item_link(
    session: AsyncSession, link_id: int, payload: ProjectItemLinkUpdate
) -> ProjectItem:
    link = await session.get(ProjectItem, link_id)
    if link is None:
        raise NotFoundError("project_item", link_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(link, k, v)
    await session.flush()
    return link


async def link_item_to_inventory(
    session: AsyncSession, link_id: int, inventory_item_id: int
) -> ProjectItem:
    """Attach an existing inventory_items row to a previously-unlinked BOM
    row. Keeps the typed name/unit on the link as a record of what the user
    originally wrote.
    """
    link = await session.get(ProjectItem, link_id)
    if link is None:
        raise NotFoundError("project_item", link_id)
    if await session.get(InventoryItem, inventory_item_id) is None:
        raise NotFoundError("inventory_item", inventory_item_id)
    link.inventory_item_id = inventory_item_id
    await session.flush()
    return link


async def remove_item(session: AsyncSession, link_id: int) -> None:
    link = await session.get(ProjectItem, link_id)
    if link is None:
        raise NotFoundError("project_item", link_id)
    await session.delete(link)
    await session.flush()


# ── printer ────────────────────────────────────────────────────────────────


async def get_printer_for_project(session: AsyncSession, project: Project) -> Printer | None:
    if project.printer_id is None:
        return None
    return await session.get(Printer, project.printer_id)


async def list_unlinked_assets(
    session: AsyncSession, project_id: int
) -> list[tuple[Model, list[ModelAsset]]]:
    """Models with their unlinked assets, for picker UIs.

    Returns a list of (model, [assets]) tuples where assets are not yet
    linked to the project.
    """
    # Get all asset IDs linked to this project.
    linked_sub = select(ProjectModel.model_asset_id).where(ProjectModel.project_id == project_id)
    linked_asset_ids = set((await session.execute(linked_sub)).scalars().all())

    # Get all models ordered by name.
    models = (await session.execute(select(Model).order_by(Model.name))).scalars().all()

    # For each model, get its assets and filter out linked ones.
    result: list[tuple[Model, list[ModelAsset]]] = []
    for model in models:
        assets = (
            (
                await session.execute(
                    select(ModelAsset)
                    .where(ModelAsset.model_id == model.id)
                    .order_by(ModelAsset.asset_type, ModelAsset.filename)
                )
            )
            .scalars()
            .all()
        )

        unlinked = [a for a in assets if a.id not in linked_asset_ids]
        if unlinked:
            result.append((model, unlinked))

    return result


async def list_unlinked_asset_trees(
    session: AsyncSession, project_id: int
) -> list[UnlinkedModelTree]:
    """Models with their unlinked, printable files arranged as a collapsible
    tree — feeds the project's in-page 'link a model' browser instead of a
    flat dropdown that lists every file across every collection.

    Images (thumbnails / photos) are dropped: a project links a printable
    file, not a picture. Collections left with no linkable file are omitted.
    Models are returned in name order (from list_unlinked_assets).
    """
    out: list[UnlinkedModelTree] = []
    for model, assets in await list_unlinked_assets(session, project_id):
        printable = [a for a in assets if a.asset_type != "image"]
        if not printable:
            continue
        tree = build_file_tree(printable, model.folder_name)
        out.append(UnlinkedModelTree(model=model, tree=tree, count=len(printable)))
    return out
