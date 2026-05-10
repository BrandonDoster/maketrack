"""MCP server for MakeTrack.

Read-only tools first, then a small write surface scoped to model
creation per CLAUDE.md M7. Reuses the existing async services so the
LLM client and the web UI stay consistent.

The server binds to 127.0.0.1 only (see __main__.py) — there is no
auth, the caller is assumed to be the same user that runs the web app.
"""

import base64
from io import BytesIO
from typing import Any

import structlog
from fastapi import UploadFile

# Late import: the mcp library prints a banner on first import on some
# versions, but FastMCP itself is fine. Keep the import scoped so test
# harnesses that don't need it can skip the cost.
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from maketrack.db import get_sessionmaker
from maketrack.errors import NotFoundError
from maketrack.mcp.serializers import (
    asset_to_dict,
    filament_to_dict,
    inventory_item_to_dict,
    model_to_dict,
    printer_to_dict,
    project_filament_link_to_dict,
    project_item_link_to_dict,
    project_model_link_to_dict,
    project_to_dict,
)
from maketrack.models.filament import Filament
from maketrack.models.inventory import InventoryItem
from maketrack.models.printer import Printer
from maketrack.schemas.model import ModelCreate
from maketrack.services import assets as asset_svc
from maketrack.services import bom as bom_svc
from maketrack.services import filaments as filament_svc
from maketrack.services import models as model_svc
from maketrack.services import printers as printer_svc
from maketrack.services import project_links as link_svc
from maketrack.services import projects as project_svc

mcp = FastMCP("maketrack")
log = structlog.get_logger()


# ────────────────────────────────────────────────────────────────────────
# Read tools
# ────────────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_projects(status: str | None = None) -> list[dict]:
    """List MakeTrack projects, optionally filtered by status.

    status: one of 'planning', 'printing', 'done', 'archived',
    'abandoned'. Omit for all projects.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await project_svc.list_projects(session, status=status)
        return [project_to_dict(r) for r in rows]


@mcp.tool()
async def get_project(project_id: int) -> dict:
    """Full detail of one project: linked models, filaments, BOM items,
    and printer.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        project = await project_svc.get_project(session, project_id)
        models = await link_svc.list_project_models(session, project_id)
        filaments = await link_svc.list_project_filaments(session, project_id)
        items = await link_svc.list_project_items(session, project_id)
        printer = await link_svc.get_printer_for_project(session, project)
        return {
            **project_to_dict(project),
            "printer": printer_to_dict(printer) if printer else None,
            "models": [
                {
                    **project_model_link_to_dict(h.link),
                    "model_name": h.model.name,
                }
                for h in models
            ],
            "filaments": [
                {
                    **project_filament_link_to_dict(h.link),
                    "filament_name": h.filament.name,
                    "filament_material": h.filament.material,
                    "filament_remaining_g": h.filament.remaining_weight_g,
                }
                for h in filaments
            ],
            "items": [
                {
                    **project_item_link_to_dict(h.link),
                    "inventory_name": h.item.name if h.item else None,
                    "inventory_on_hand": h.item.quantity if h.item else None,
                }
                for h in items
            ],
        }


@mcp.tool()
async def list_models(tag: str | None = None, source_type: str | None = None) -> list[dict]:
    """List all models, optionally filtered by tag or source_type
    ('local' | 'printables' | 'thingiverse' | 'github' | 'other').
    """
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await model_svc.list_models(session, tag=tag, source_type=source_type)
        return [model_to_dict(r) for r in rows]


@mcp.tool()
async def get_model(model_id: int) -> dict:
    """Full detail of one model, including all of its assets."""
    sm = get_sessionmaker()
    async with sm() as session:
        model = await model_svc.get_model(session, model_id)
        assets = await model_svc.list_assets(session, model_id)
        return {
            **model_to_dict(model),
            "assets": [asset_to_dict(a) for a in assets],
        }


@mcp.tool()
async def list_filaments(material: str | None = None, source: str | None = None) -> list[dict]:
    """List filaments, optionally filtered by material (e.g. 'PLA',
    'PETG') or source ('local' | 'spoolman').
    """
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await filament_svc.list_filaments(session, material=material, source=source)
        return [filament_to_dict(r) for r in rows]


@mcp.tool()
async def find_filament_for_project(project_id: int) -> list[dict]:
    """For each filament linked to the project, report whether the spool's
    remaining weight covers the estimated weight on this project_filament.

    Returns a list of rows, one per project_filament link, with a
    `coverage` field that is `'covered'`, `'short'`, or `'unknown'` (when
    estimates / remaining weight are missing).
    """
    sm = get_sessionmaker()
    async with sm() as session:
        await project_svc.get_project(session, project_id)  # 404 if missing
        rows = await link_svc.list_project_filaments(session, project_id)
        out: list[dict] = []
        for h in rows:
            est = h.link.est_weight_g
            remaining = h.filament.remaining_weight_g
            if est is None or remaining is None:
                coverage = "unknown"
            elif remaining >= est:
                coverage = "covered"
            else:
                coverage = "short"
            out.append(
                {
                    **project_filament_link_to_dict(h.link),
                    "filament_name": h.filament.name,
                    "filament_material": h.filament.material,
                    "filament_color_hex": h.filament.color_hex,
                    "filament_source": h.filament.source,
                    "filament_external_url": h.filament.external_url,
                    "filament_remaining_g": remaining,
                    "coverage": coverage,
                }
            )
        return out


@mcp.tool()
async def project_shopping_list(project_id: int | None = None) -> list[dict]:
    """BOM-derived shopping list. Without a project_id, aggregates "still
    to buy" across all active projects (status in planning/printing).
    With a project_id, returns the per-project BOM.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        if project_id is None:
            rows = await bom_svc.shopping_list(session)
            return [r.model_dump() for r in rows]
        # Verify the project exists, then return its BOM rollup.
        await project_svc.get_project(session, project_id)
        rows = await bom_svc.project_bom(session, project_id)
        return [r.model_dump() for r in rows]


@mcp.tool()
async def list_printers() -> list[dict]:
    """List all configured printers."""
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await printer_svc.list_printers(session)
        return [printer_to_dict(r) for r in rows]


@mcp.tool()
async def list_inventory(category: str | None = None) -> list[dict]:
    """List inventory items, optionally filtered by category
    ('hardware' | 'electronic' | 'tool' | 'other'). Useful when an LLM
    is helping plan a project and wants to know what's already on hand.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = select(InventoryItem).order_by(InventoryItem.name)
        if category is not None:
            stmt = stmt.where(InventoryItem.category == category)
        rows = (await session.execute(stmt)).scalars().all()
        return [inventory_item_to_dict(r) for r in rows]


# Manual references so ruff doesn't flag the imported names as unused
# (some ORM imports are reachable only through serializers).
_ = (Filament, Printer)


# ────────────────────────────────────────────────────────────────────────
# Write tools (scoped to model creation per CLAUDE.md)
# ────────────────────────────────────────────────────────────────────────


@mcp.tool()
async def create_model(
    name: str,
    description: str | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
) -> dict:
    """Create a new model entry (no assets attached yet).

    source_type if provided must be one of 'local', 'printables',
    'thingiverse', 'github', 'other'.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        payload = ModelCreate(
            name=name,
            description=description,
            source_type=source_type,
            source_url=source_url,
        )
        model = await model_svc.create_model(session, payload)
        await session.commit()
        await session.refresh(model)
        return model_to_dict(model)


@mcp.tool()
async def upload_model_asset(
    model_id: int,
    filename: str,
    content_base64: str,
    set_as_thumbnail: bool = False,
) -> dict:
    """Upload an asset (STL/STEP/3MF/gcode/image/...) to an existing model.

    The file's bytes must be base64-encoded; the original filename is
    preserved for downloads. asset_type is inferred from the extension
    of `filename`. If the file is a 3MF, the embedded thumbnail is
    extracted and saved as a sibling asset (and auto-set as the model's
    thumbnail if none is configured yet).

    Pass set_as_thumbnail=True to force this asset to become the model
    thumbnail (only meaningful for image asset types).
    """
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise ValueError(f"content_base64 is not valid base64: {exc}") from exc

    upload = UploadFile(filename=filename, file=BytesIO(raw))
    sm = get_sessionmaker()
    async with sm() as session:
        asset = await asset_svc.upload_asset(
            session, model_id, upload, set_as_thumbnail=set_as_thumbnail
        )
        await session.commit()
        await session.refresh(asset)
        return asset_to_dict(asset)


@mcp.tool()
async def set_model_thumbnail(model_id: int, asset_id: int) -> dict:
    """Set models.thumbnail_asset_id. The asset must be an image asset
    that belongs to the same model.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            model = await asset_svc.set_thumbnail(session, model_id, asset_id)
        except NotFoundError:
            raise
        await session.commit()
        return {"id": model.id, "thumbnail_asset_id": model.thumbnail_asset_id}


def _http_app() -> Any:
    """Return the streamable-http ASGI app. Wrapped here so callers can
    mount it into uvicorn without importing FastMCP-specific types."""
    return mcp.streamable_http_app()
