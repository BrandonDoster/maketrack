from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ExternalFilament:
    """Unified filament shape every source adapter returns."""

    external_id: str
    external_url: str | None = None
    name: str | None = None
    material: str | None = None
    color_hex: str | None = None
    brand: str | None = None
    diameter_mm: float | None = None
    total_weight_g: float | None = None
    remaining_weight_g: float | None = None


class FilamentSource(Protocol):
    async def list_spools(self) -> list[ExternalFilament]: ...

    async def health_check(self) -> bool: ...
