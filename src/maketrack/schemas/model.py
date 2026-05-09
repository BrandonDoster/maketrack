from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MODEL_SOURCE_TYPES = ("local", "printables", "thingiverse", "github", "other")


class ModelBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    source_type: str | None = Field(
        default=None,
        pattern=r"^(local|printables|thingiverse|github|other)$",
    )
    source_url: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class ModelCreate(ModelBase):
    pass


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    source_type: str | None = Field(
        default=None,
        pattern=r"^(local|printables|thingiverse|github|other)$",
    )
    source_url: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class ModelAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model_id: int
    asset_type: str
    filename: str
    file_path: str
    file_size: int | None
    sha256: str | None
    generated: bool
    uploaded_at: datetime


class ModelRead(BaseModel):
    """Read shape. Tags are decoded from the stored JSON-as-text via the
    service layer; the route is responsible for calling decode_tags()
    when constructing this from an ORM row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    source_type: str | None
    source_url: str | None
    notes: str | None
    tags: list[str]
    thumbnail_asset_id: int | None
    created_at: datetime
    updated_at: datetime
