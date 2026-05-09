import httpx
import pytest

from maketrack.sources.spoolman import SpoolmanFilamentSource

# Sample shape mirrors what the live Spoolman v0.23 API returns.
SAMPLE_SPOOL = {
    "id": 1,
    "registered": "2026-05-09T21:07:00Z",
    "filament": {
        "id": 1,
        "name": "PolyTerra Charcoal Black",
        "vendor": {"id": 1, "name": "Polymaker"},
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "weight": 1000.0,
        "color_hex": "212121",
    },
    "remaining_weight": 750.0,
    "initial_weight": 1000.0,
    "used_weight": 250.0,
    "location": "Dry box A",
    "archived": False,
}


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_list_spools_maps_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/spool"
        assert request.url.params.get("allow_archived") == "true"
        return httpx.Response(200, json=[SAMPLE_SPOOL])

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        src = SpoolmanFilamentSource(base_url="http://example", client=client)
        result = await src.list_spools()

    assert len(result) == 1
    ext = result[0]
    assert ext.external_id == "1"
    assert ext.external_url == "http://example/spool/show/1"
    assert ext.name == "PolyTerra Charcoal Black"
    assert ext.material == "PLA"
    assert ext.color_hex == "#212121"  # adapter prepends '#'
    assert ext.brand == "Polymaker"
    assert ext.diameter_mm == 1.75
    assert ext.total_weight_g == 1000.0
    assert ext.remaining_weight_g == 750.0


async def test_list_spools_handles_missing_vendor_and_color() -> None:
    spool = {
        **SAMPLE_SPOOL,
        "filament": {**SAMPLE_SPOOL["filament"], "vendor": None, "color_hex": None},
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[spool])

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        src = SpoolmanFilamentSource(base_url="http://example", client=client)
        result = await src.list_spools()

    assert result[0].brand is None
    assert result[0].color_hex is None


async def test_list_spools_passes_auth_token() -> None:
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        src = SpoolmanFilamentSource(base_url="http://example", auth_token="secret", client=client)
        await src.list_spools()

    assert seen_headers.get("authorization") == "Bearer secret"


async def test_health_check_truthy_on_healthy_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "healthy"})

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        src = SpoolmanFilamentSource(base_url="http://example", client=client)
        assert await src.health_check() is True


async def test_health_check_false_on_unreachable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        src = SpoolmanFilamentSource(base_url="http://example", client=client)
        assert await src.health_check() is False


def test_url_template_override_via_field_map() -> None:
    src = SpoolmanFilamentSource(
        base_url="http://example",
        field_map={"url_template": "{base_url}/spools/{id}"},
    )
    ext = src._to_external(SAMPLE_SPOOL)
    assert ext.external_url == "http://example/spools/1"


@pytest.mark.parametrize(
    "given,expected",
    [
        ("212121", "#212121"),
        ("#212121", "#212121"),
        (None, None),
    ],
)
def test_color_hex_normalization(given, expected) -> None:
    src = SpoolmanFilamentSource(base_url="http://example")
    spool = {**SAMPLE_SPOOL, "filament": {**SAMPLE_SPOOL["filament"], "color_hex": given}}
    assert src._to_external(spool).color_hex == expected
