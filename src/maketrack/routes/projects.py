from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.models.project import Project
from maketrack.schemas.project import (
    BOMRow,
    ProjectCreate,
    ProjectFilamentLinkCreate,
    ProjectFilamentLinkRead,
    ProjectFilamentLinkUpdate,
    ProjectItemLinkCreate,
    ProjectItemLinkRead,
    ProjectItemLinkUpdate,
    ProjectModelLinkCreate,
    ProjectModelLinkRead,
    ProjectModelLinkUpdate,
    ProjectRead,
    ProjectUpdate,
)
from maketrack.services import bom as bom_svc
from maketrack.services import project_links as link_svc
from maketrack.services import projects as svc

router = APIRouter(prefix="/api/projects", tags=["projects"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _to_read(row: Project) -> ProjectRead:
    return ProjectRead(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        printer_id=row.printer_id,
        notes=row.notes,
        tags=svc.decode_tags(row.tags),
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ── project CRUD ──────────────────────────────────────────────────────────


@router.get("", response_model=list[ProjectRead])
async def list_projects(session: SessionDep, status: str | None = None) -> list[ProjectRead]:
    rows = await svc.list_projects(session, status=status)
    return [_to_read(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: int, session: SessionDep) -> ProjectRead:
    return _to_read(await svc.get_project(session, project_id))


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: SessionDep) -> ProjectRead:
    row = await svc.create_project(session, payload)
    await session.commit()
    await session.refresh(row)
    return _to_read(row)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int, payload: ProjectUpdate, session: SessionDep
) -> ProjectRead:
    row = await svc.update_project(session, project_id, payload)
    await session.commit()
    await session.refresh(row)
    return _to_read(row)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, session: SessionDep) -> None:
    await svc.delete_project(session, project_id)
    await session.commit()


# ── project_models links ──────────────────────────────────────────────────


@router.get("/{project_id}/models", response_model=list[ProjectModelLinkRead])
async def list_models(project_id: int, session: SessionDep) -> list[ProjectModelLinkRead]:
    rows = await link_svc.list_project_models(session, project_id)
    return [
        ProjectModelLinkRead(
            project_id=h.link.project_id,
            model_id=h.link.model_id,
            qty_to_print=h.link.qty_to_print,
            status=h.link.status,
            notes=h.link.notes,
            model_name=h.model.name,
            model_thumbnail_path=h.thumbnail_path,
        )
        for h in rows
    ]


@router.post(
    "/{project_id}/models",
    response_model=ProjectModelLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_model(
    project_id: int, payload: ProjectModelLinkCreate, session: SessionDep
) -> ProjectModelLinkRead:
    link = await link_svc.add_model(session, project_id, payload)
    await session.commit()
    return ProjectModelLinkRead.model_validate(link)


@router.patch("/{project_id}/models/{model_id}", response_model=ProjectModelLinkRead)
async def update_model_link(
    project_id: int,
    model_id: int,
    payload: ProjectModelLinkUpdate,
    session: SessionDep,
) -> ProjectModelLinkRead:
    link = await link_svc.update_model_link(session, project_id, model_id, payload)
    await session.commit()
    return ProjectModelLinkRead.model_validate(link)


@router.delete("/{project_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model_link(project_id: int, model_id: int, session: SessionDep) -> None:
    await link_svc.remove_model(session, project_id, model_id)
    await session.commit()


# ── project_filaments links ───────────────────────────────────────────────


@router.get("/{project_id}/filaments", response_model=list[ProjectFilamentLinkRead])
async def list_filaments(project_id: int, session: SessionDep) -> list[ProjectFilamentLinkRead]:
    rows = await link_svc.list_project_filaments(session, project_id)
    return [
        ProjectFilamentLinkRead(
            id=h.link.id,
            project_id=h.link.project_id,
            filament_id=h.link.filament_id,
            est_weight_g=h.link.est_weight_g,
            actual_weight_g=h.link.actual_weight_g,
            role=h.link.role,
            filament_name=h.filament.name,
            filament_color_hex=h.filament.color_hex,
            filament_remaining_g=h.filament.remaining_weight_g,
            filament_source=h.filament.source,
        )
        for h in rows
    ]


@router.post(
    "/{project_id}/filaments",
    response_model=ProjectFilamentLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_filament(
    project_id: int, payload: ProjectFilamentLinkCreate, session: SessionDep
) -> ProjectFilamentLinkRead:
    link = await link_svc.add_filament(session, project_id, payload)
    await session.commit()
    return ProjectFilamentLinkRead.model_validate(link)


@router.patch("/{project_id}/filaments/{link_id}", response_model=ProjectFilamentLinkRead)
async def update_filament_link(
    project_id: int,
    link_id: int,
    payload: ProjectFilamentLinkUpdate,
    session: SessionDep,
) -> ProjectFilamentLinkRead:
    link = await link_svc.update_filament_link(session, link_id, payload)
    await session.commit()
    return ProjectFilamentLinkRead.model_validate(link)


@router.delete("/{project_id}/filaments/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_filament_link(project_id: int, link_id: int, session: SessionDep) -> None:
    await link_svc.remove_filament(session, link_id)
    await session.commit()


# ── project_items / BOM ───────────────────────────────────────────────────


@router.get("/{project_id}/items", response_model=list[ProjectItemLinkRead])
async def list_items(project_id: int, session: SessionDep) -> list[ProjectItemLinkRead]:
    rows = await link_svc.list_project_items(session, project_id)
    return [
        ProjectItemLinkRead(
            id=h.link.id,
            project_id=h.link.project_id,
            inventory_item_id=h.link.inventory_item_id,
            qty_required=h.link.qty_required,
            qty_consumed=h.link.qty_consumed,
            notes=h.link.notes,
            name=h.link.name,
            unit=h.link.unit,
            item_name=h.item.name if h.item else None,
            item_unit=h.item.unit if h.item else None,
            item_on_hand=h.item.quantity if h.item else None,
            display_name=h.display_name,
        )
        for h in rows
    ]


@router.post(
    "/{project_id}/items",
    response_model=ProjectItemLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    project_id: int, payload: ProjectItemLinkCreate, session: SessionDep
) -> ProjectItemLinkRead:
    from fastapi import HTTPException

    try:
        link = await link_svc.add_item(session, project_id, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return ProjectItemLinkRead.model_validate(link)


@router.patch("/{project_id}/items/{link_id}", response_model=ProjectItemLinkRead)
async def update_item_link(
    project_id: int,
    link_id: int,
    payload: ProjectItemLinkUpdate,
    session: SessionDep,
) -> ProjectItemLinkRead:
    link = await link_svc.update_item_link(session, link_id, payload)
    await session.commit()
    return ProjectItemLinkRead.model_validate(link)


@router.post(
    "/{project_id}/items/{link_id}/link/{inventory_item_id}",
    response_model=ProjectItemLinkRead,
)
async def link_item_to_inventory(
    project_id: int,
    link_id: int,
    inventory_item_id: int,
    session: SessionDep,
) -> ProjectItemLinkRead:
    """Attach an existing inventory_items row to an unlinked custom BOM row."""
    link = await link_svc.link_item_to_inventory(session, link_id, inventory_item_id)
    await session.commit()
    return ProjectItemLinkRead.model_validate(link)


@router.delete("/{project_id}/items/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item_link(project_id: int, link_id: int, session: SessionDep) -> None:
    await link_svc.remove_item(session, link_id)
    await session.commit()


@router.get("/{project_id}/bom", response_model=list[BOMRow])
async def project_bom(project_id: int, session: SessionDep) -> list[BOMRow]:
    return await bom_svc.project_bom(session, project_id)
