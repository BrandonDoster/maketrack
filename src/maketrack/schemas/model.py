from pydantic import BaseModel, Field

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
