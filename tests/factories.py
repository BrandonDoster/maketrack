import factory
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.models.external_source import ExternalSource
from maketrack.models.filament import LOCAL_SOURCE, Filament
from maketrack.models.inventory import InventoryItem
from maketrack.models.printer import Printer


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
