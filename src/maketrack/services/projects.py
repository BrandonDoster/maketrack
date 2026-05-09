import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import utcnow
from maketrack.errors import NotFoundError
from maketrack.models.project import Project
from maketrack.schemas.project import ProjectCreate, ProjectUpdate


def _encode_tags(tags: list[str] | None) -> str | None:
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
    return [str(t) for t in decoded] if isinstance(decoded, list) else []


async def list_projects(
    session: AsyncSession,
    *,
    status: str | None = None,
) -> Sequence[Project]:
    stmt = select(Project).order_by(Project.created_at.desc())
    if status is not None:
        stmt = stmt.where(Project.status == status)
    return (await session.execute(stmt)).scalars().all()


async def get_project(session: AsyncSession, project_id: int) -> Project:
    p = await session.get(Project, project_id)
    if p is None:
        raise NotFoundError("project", project_id)
    return p


async def create_project(session: AsyncSession, payload: ProjectCreate) -> Project:
    data = payload.model_dump()
    tags = data.pop("tags", [])
    project = Project(**data, tags=_encode_tags(tags))
    session.add(project)
    await session.flush()
    return project


async def update_project(session: AsyncSession, project_id: int, payload: ProjectUpdate) -> Project:
    project = await get_project(session, project_id)
    data = payload.model_dump(exclude_unset=True)
    if "tags" in data:
        project.tags = _encode_tags(data.pop("tags"))
    new_status = data.get("status")
    # Auto-stamp completed_at when transitioning into 'done', clear it on
    # transitions back out. Caller can override by passing completed_at
    # explicitly.
    if new_status is not None and new_status != project.status:
        if new_status == "done" and "completed_at" not in data:
            data["completed_at"] = utcnow()
        elif new_status != "done" and "completed_at" not in data:
            data["completed_at"] = None
    for key, value in data.items():
        setattr(project, key, value)
    await session.flush()
    return project


async def delete_project(session: AsyncSession, project_id: int) -> None:
    project = await get_project(session, project_id)
    await session.delete(project)
    await session.flush()
