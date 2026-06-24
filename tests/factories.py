import io

import factory
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.models.external_source import ExternalSource
from maketrack.models.filament import LOCAL_SOURCE, Filament
from maketrack.models.inventory import InventoryItem
from maketrack.models.model import Model
from maketrack.models.printer import Printer
from maketrack.models.project import Project
from maketrack.schemas.inventory import InventoryItemCreate
from maketrack.schemas.model import ModelCreate
from maketrack.schemas.project import (
    ProjectCreate,
    ProjectFilamentLinkCreate,
    ProjectItemLinkCreate,
    ProjectModelLinkCreate,
    ProjectUpdate,
)
from maketrack.services import assets as asset_svc
from maketrack.services import inventory as inventory_svc
from maketrack.services import models as model_svc
from maketrack.services import project_links as link_svc
from maketrack.services import projects as project_svc


class LocalFilamentFactory(factory.Factory):
    class Meta:
        model = Filament

    source = LOCAL_SOURCE
    name = factory.Sequence(lambda n: f"Filament {n}")
    material = "PLA"
    color_hex = "#FF0000"
    brand = "Generic"
    diameter_mm = 1.75
    total_weight_g = 1000.0
    remaining_weight_g = 1000.0


class SpoolmanSourceFactory(factory.Factory):
    class Meta:
        model = ExternalSource

    type = "spoolman"
    name = factory.Sequence(lambda n: f"spoolman-{n}")
    base_url = "http://localhost:7912"


class RemoteFilamentFactory(factory.Factory):
    class Meta:
        model = Filament

    source = "spoolman"
    external_id = factory.Sequence(lambda n: str(100 + n))
    external_url = factory.LazyAttribute(lambda o: f"http://localhost:7912/spool/{o.external_id}")
    name = factory.Sequence(lambda n: f"Spoolman Spool {n}")
    material = "PETG"
    diameter_mm = 1.75


class InventoryItemFactory(factory.Factory):
    class Meta:
        model = InventoryItem

    name = factory.Sequence(lambda n: f"M3 Bolt {n}")
    category = "hardware"
    quantity = 100
    unit = "each"


class PrinterFactory(factory.Factory):
    class Meta:
        model = Printer

    name = factory.Sequence(lambda n: f"Printer {n}")
    model = "Voron 2.4"
    access_url = "http://mainsail.local"


async def persist(session: AsyncSession, instance):
    session.add(instance)
    await session.flush()
    return instance


def stl_bytes() -> bytes:
    """Smallest valid binary STL: 80-byte header + uint32 0 triangles."""
    return b"\x00" * 80 + (0).to_bytes(4, "little")


# ── service-backed builders ────────────────────────────────────────────────
# These replace the (now removed) JSON API as the way tests set up state:
# they call the same service the API route used and commit, so a later
# `client` request (which opens its own session) sees the rows.


async def make_project(session: AsyncSession, **kw) -> Project:
    row = await project_svc.create_project(session, ProjectCreate(**{"name": "P", **kw}))
    await session.commit()
    return row


async def update_project(session: AsyncSession, project_id: int, **kw) -> Project:
    row = await project_svc.update_project(session, project_id, ProjectUpdate(**kw))
    await session.commit()
    return row


async def make_model(session: AsyncSession, **kw) -> Model:
    row = await model_svc.create_model(session, ModelCreate(**{"name": "M", **kw}))
    await session.commit()
    return row


async def make_inventory_item(session: AsyncSession, **kw) -> InventoryItem:
    row = await inventory_svc.create_item(session, InventoryItemCreate(**{"name": "Item", **kw}))
    await session.commit()
    return row


async def link_model(session: AsyncSession, project_id: int, model_asset_id: int, **kw):
    link = await link_svc.add_model(
        session, project_id, ProjectModelLinkCreate(model_asset_id=model_asset_id, **kw)
    )
    await session.commit()
    return link


async def link_filament(session: AsyncSession, project_id: int, filament_id: int, **kw):
    link = await link_svc.add_filament(
        session, project_id, ProjectFilamentLinkCreate(filament_id=filament_id, **kw)
    )
    await session.commit()
    return link


async def link_item(session: AsyncSession, project_id: int, **kw):
    link = await link_svc.add_item(session, project_id, ProjectItemLinkCreate(**kw))
    await session.commit()
    return link


async def upload_model_asset(
    session: AsyncSession,
    model_id: int,
    filename: str = "part.stl",
    *,
    data: bytes | None = None,
    set_as_thumbnail: bool = False,
):
    """Upload a small STL (or given bytes) and return the ModelAsset row."""
    upload = UploadFile(file=io.BytesIO(data if data is not None else stl_bytes()), filename=filename)
    asset = await asset_svc.upload_asset(
        session, model_id, upload, set_as_thumbnail=set_as_thumbnail
    )
    await session.commit()
    return asset


async def add_model_asset(
    session: AsyncSession,
    model_id: int,
    filename: str = "part.stl",
    *,
    data: bytes | None = None,
    set_as_thumbnail: bool = False,
) -> int:
    """Upload a file and return just the asset id.

    Project links now target a specific ModelAsset, so a test that wants a
    model "in a project" must first give the model a file to link against.
    """
    asset = await upload_model_asset(
        session, model_id, filename, data=data, set_as_thumbnail=set_as_thumbnail
    )
    return asset.id
