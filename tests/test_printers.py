from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import PrinterFactory, persist


async def test_create_printer(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/printers",
        json={
            "name": "Voron 2.4 350",
            "model": "Voron 2.4 350mm",
            "access_url": "http://voron.local",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Voron 2.4 350"


async def test_list_printers(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, PrinterFactory(name="A"))
    await persist(session, PrinterFactory(name="B"))
    await session.commit()

    resp = await client.get("/api/printers")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_update_and_delete_printer(client: AsyncClient, session: AsyncSession) -> None:
    p = await persist(session, PrinterFactory())
    await session.commit()

    patch = await client.patch(f"/api/printers/{p.id}", json={"notes": "updated"})
    assert patch.status_code == 200
    assert patch.json()["notes"] == "updated"

    delete = await client.delete(f"/api/printers/{p.id}")
    assert delete.status_code == 204


async def test_empty_name_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/printers", json={"name": ""})
    assert resp.status_code == 422


async def test_printers_list_renders(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, PrinterFactory(name="Voron Bench"))
    await session.commit()

    resp = await client.get("/printers")
    assert resp.status_code == 200
    assert "Voron Bench" in resp.text


async def test_create_printer_via_form(client: AsyncClient) -> None:
    resp = await client.post(
        "/printers",
        data={"name": "Form Printer", "model": "Bambu X1C"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    listing = await client.get("/printers")
    assert "Form Printer" in listing.text
