from collections.abc import Sequence
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


@dataclass(slots=True)
class HydratedProjectModel:
    link: ProjectModel
    model: Model
    thumbnail_path: str | None


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
    rows = (
        await session.execute(
            select(ProjectModel, Model)
            .join(Model, Model.id == ProjectModel.model_id)
            .where(ProjectModel.project_id == project_id)
            .order_by(Model.name)
        )
    ).all()
    if not rows:
        return []
    # Pull thumbnails for whatever subset has them — single query keyed by
    # the asset id, not per-model lookups.
    thumb_ids = [m.thumbnail_asset_id for _, m in rows if m.thumbnail_asset_id]
    paths_by_id: dict[int, str] = {}
    if thumb_ids:
        asset_rows = (
            await session.execute(
                select(ModelAsset.id, ModelAsset.file_path).where(ModelAsset.id.in_(thumb_ids))
            )
        ).all()
        paths_by_id = {a_id: path for a_id, path in asset_rows}

    out: list[HydratedProjectModel] = []
    for link, model in rows:
        thumb_path = paths_by_id.get(model.thumbnail_asset_id) if model.thumbnail_asset_id else None
        out.append(HydratedProjectModel(link=link, model=model, thumbnail_path=thumb_path))
    return out


async def add_model(
    session: AsyncSession, project_id: int, payload: ProjectModelLinkCreate
) -> ProjectModel:
    if await session.get(Project, project_id) is None:
        raise NotFoundError("project", project_id)
    if await session.get(Model, payload.model_id) is None:
        raise NotFoundError("model", payload.model_id)
    existing = await session.get(ProjectModel, (project_id, payload.model_id))
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
        model_id=payload.model_id,
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
    model_id: int,
    payload: ProjectModelLinkUpdate,
) -> ProjectModel:
    link = await session.get(ProjectModel, (project_id, model_id))
    if link is None:
        raise NotFoundError("project_model", f"({project_id},{model_id})")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(link, k, v)
    await session.flush()
    return link


async def remove_model(session: AsyncSession, project_id: int, model_id: int) -> None:
    link = await session.get(ProjectModel, (project_id, model_id))
    if link is None:
        raise NotFoundError("project_model", f"({project_id},{model_id})")
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


async def list_unlinked_models(session: AsyncSession, project_id: int) -> Sequence[Model]:
    """Models that aren't already attached to this project — for picker UIs."""
    sub = select(ProjectModel.model_id).where(ProjectModel.project_id == project_id)
    stmt = select(Model).where(Model.id.notin_(sub)).order_by(Model.name)
    return (await session.execute(stmt)).scalars().all()
