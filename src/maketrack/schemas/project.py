from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

PROJECT_STATUSES = ("planning", "printing", "done", "archived", "abandoned")
ACTIVE_STATUSES = frozenset({"planning", "printing"})

PROJECT_MODEL_STATUSES = ("pending", "printed", "failed")


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: str = Field(
        default="planning",
        pattern=r"^(planning|printing|done|archived|abandoned)$",
    )
    printer_id: int | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(planning|printing|done|archived|abandoned)$",
    )
    printer_id: int | None = None
    notes: str | None = None
    tags: list[str] | None = None
    completed_at: datetime | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    status: str
    printer_id: int | None
    notes: str | None
    tags: list[str]
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── link payloads ──────────────────────────────────────────────────────────


class ProjectModelLinkCreate(BaseModel):
    model_id: int
    qty_to_print: int = Field(default=1, ge=1)
    status: str = Field(default="pending", pattern=r"^(pending|printed|failed)$")
    notes: str | None = None


class ProjectModelLinkUpdate(BaseModel):
    qty_to_print: int | None = Field(default=None, ge=1)
    status: str | None = Field(default=None, pattern=r"^(pending|printed|failed)$")
    notes: str | None = None


class ProjectModelLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    model_id: int
    qty_to_print: int
    status: str | None
    notes: str | None
    # Hydrated by the route from joined ORM data so the UI doesn't N+1.
    model_name: str | None = None
    model_thumbnail_path: str | None = None


class ProjectFilamentLinkCreate(BaseModel):
    filament_id: int
    est_weight_g: float | None = Field(default=None, ge=0)
    actual_weight_g: float | None = Field(default=None, ge=0)
    role: str | None = None


class ProjectFilamentLinkUpdate(BaseModel):
    est_weight_g: float | None = Field(default=None, ge=0)
    actual_weight_g: float | None = Field(default=None, ge=0)
    role: str | None = None


class ProjectFilamentLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    filament_id: int
    est_weight_g: float | None
    actual_weight_g: float | None
    role: str | None
    filament_name: str | None = None
    filament_color_hex: str | None = None
    filament_remaining_g: float | None = None
    filament_source: str | None = None


class ProjectItemLinkCreate(BaseModel):
    inventory_item_id: int
    qty_required: float = Field(ge=0)
    qty_consumed: float = Field(default=0.0, ge=0)
    notes: str | None = None


class ProjectItemLinkUpdate(BaseModel):
    qty_required: float | None = Field(default=None, ge=0)
    qty_consumed: float | None = Field(default=None, ge=0)
    notes: str | None = None


class ProjectItemLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    inventory_item_id: int
    qty_required: float
    qty_consumed: float
    notes: str | None
    item_name: str | None = None
    item_unit: str | None = None
    item_on_hand: float | None = None


# ── BOM / shopping list ────────────────────────────────────────────────────


class BOMRow(BaseModel):
    inventory_item_id: int
    name: str
    unit: str | None
    still_needed_for_project: float
    on_hand: float
    still_to_buy: float


class ShoppingListRow(BaseModel):
    inventory_item_id: int
    name: str
    unit: str | None
    on_hand: float
    still_to_buy: float
    project_ids: list[int]
