"""ORM → dict serializers for MCP tool responses.

The MCP protocol expects JSON-serializable payloads. Each helper takes an
ORM row and returns a flat dict the same shape an LLM caller would expect
to see when asking "what's in my project". Datetimes are serialized as
ISO-8601 strings so they round-trip cleanly through JSON.
"""

from datetime import datetime

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
from maketrack.services.models import decode_tags as decode_model_tags
from maketrack.services.projects import decode_tags as decode_project_tags


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def project_to_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "printer_id": p.printer_id,
        "notes": p.notes,
        "tags": decode_project_tags(p.tags),
        "completed_at": _iso(p.completed_at),
        "created_at": _iso(p.created_at),
        "updated_at": _iso(p.updated_at),
    }


def model_to_dict(m: Model) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description,
        "source_type": m.source_type,
        "source_url": m.source_url,
        "notes": m.notes,
        "tags": decode_model_tags(m.tags),
        "thumbnail_asset_id": m.thumbnail_asset_id,
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
    }


def asset_to_dict(a: ModelAsset) -> dict:
    return {
        "id": a.id,
        "model_id": a.model_id,
        "asset_type": a.asset_type,
        "filename": a.filename,
        "file_path": a.file_path,
        "file_size": a.file_size,
        "sha256": a.sha256,
        "generated": a.generated,
        "uploaded_at": _iso(a.uploaded_at),
    }


def filament_to_dict(f: Filament) -> dict:
    return {
        "id": f.id,
        "source": f.source,
        "external_id": f.external_id,
        "external_url": f.external_url,
        "name": f.name,
        "material": f.material,
        "color_hex": f.color_hex,
        "brand": f.brand,
        "diameter_mm": f.diameter_mm,
        "total_weight_g": f.total_weight_g,
        "remaining_weight_g": f.remaining_weight_g,
        "notes": f.notes,
        "archived_at": _iso(f.archived_at),
    }


def printer_to_dict(p: Printer) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "model": p.model,
        "access_url": p.access_url,
        "notes": p.notes,
    }


def inventory_item_to_dict(i: InventoryItem) -> dict:
    return {
        "id": i.id,
        "name": i.name,
        "category": i.category,
        "quantity": i.quantity,
        "unit": i.unit,
        "location": i.location.name if i.location else None,
        "reorder_threshold": i.reorder_threshold,
    }


def project_model_link_to_dict(link: ProjectModel) -> dict:
    return {
        "model_id": link.model_id,
        "qty_to_print": link.qty_to_print,
        "status": link.status,
        "notes": link.notes,
    }


def project_filament_link_to_dict(link: ProjectFilament) -> dict:
    return {
        "id": link.id,
        "filament_id": link.filament_id,
        "est_weight_g": link.est_weight_g,
        "actual_weight_g": link.actual_weight_g,
        "role": link.role,
    }


def project_item_link_to_dict(link: ProjectItem) -> dict:
    return {
        "id": link.id,
        "inventory_item_id": link.inventory_item_id,
        "name": link.name,
        "unit": link.unit,
        "qty_required": link.qty_required,
        "qty_consumed": link.qty_consumed,
        "notes": link.notes,
    }
