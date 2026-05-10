"""Hardware-preset autocomplete wiring."""

import json
from pathlib import Path

from httpx import AsyncClient

PRESETS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "maketrack"
    / "static"
    / "hardware-presets.json"
)


def test_presets_json_parses_with_expected_shape() -> None:
    data = json.loads(PRESETS_PATH.read_text())
    assert "presets" in data
    assert isinstance(data["presets"], list)
    assert len(data["presets"]) >= 50  # starter list is meaningful
    for entry in data["presets"]:
        assert isinstance(entry["name"], str) and entry["name"].strip()
        assert entry["unit"] in {"each", "m"}
        assert entry["category"] in {"hardware", "electronic", "tool", "other"}


def test_presets_have_expected_starter_entries() -> None:
    """Spot-check a handful of common parts so a future edit doesn't
    accidentally drop the obvious ones."""
    data = json.loads(PRESETS_PATH.read_text())
    names = {p["name"] for p in data["presets"]}
    for required in ["M3x12 SHCS", "M3 Heatset", "GT2 Belt 6mm", "PTFE Tube 2x4mm"]:
        assert required in names, f"missing starter preset: {required}"


async def test_presets_json_served_by_static_mount(client: AsyncClient) -> None:
    resp = await client.get("/static/hardware-presets.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "presets" in body and len(body["presets"]) > 0


async def test_autocomplete_js_served_by_static_mount(client: AsyncClient) -> None:
    resp = await client.get("/static/hardware-presets.js")
    assert resp.status_code == 200
    assert "data-hardware-preset" in resp.text  # references the wiring attribute
    assert "/static/hardware-presets.json" in resp.text  # fetches the JSON


async def test_inventory_form_marks_name_input(client: AsyncClient) -> None:
    resp = await client.get("/inventory/new")
    assert resp.status_code == 200
    # Name input is wired to the unit field via the data attribute.
    assert 'data-hardware-preset="unit"' in resp.text


async def test_bom_entry_row_has_autocomplete_and_hidden_unit(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    resp = await client.get(f"/projects/{pid}")
    assert resp.status_code == 200
    # The entry-row name input is wired.
    assert 'data-hardware-preset="unit"' in resp.text
    # Hidden unit input is present so the JS fill survives form submission.
    assert 'type="hidden" name="unit"' in resp.text


async def test_autocomplete_script_loaded_on_every_page(client: AsyncClient) -> None:
    """The script is in base.html so it's available on any page that has
    a wired input — the script self-skips when no inputs match."""
    for path in ["/", "/inventory", "/inventory/new", "/projects"]:
        resp = await client.get(path)
        assert "/static/hardware-presets.js" in resp.text, f"{path} missing autocomplete script"
