from httpx import AsyncClient


async def _make_models(client: AsyncClient) -> tuple[int, int, int]:
    """Create three models, two of which get linked to a project. Returns
    (standalone_id, in_project_a_id, in_project_b_id)."""
    standalone = (await client.post("/api/models", json={"name": "Standalone"})).json()["id"]
    in_proj_a = (await client.post("/api/models", json={"name": "ProjPart A"})).json()["id"]
    in_proj_b = (await client.post("/api/models", json={"name": "ProjPart B"})).json()["id"]

    proj = (await client.post("/api/projects", json={"name": "Voron"})).json()["id"]
    await client.post(f"/api/projects/{proj}/models", json={"model_id": in_proj_a})
    await client.post(f"/api/projects/{proj}/models", json={"model_id": in_proj_b})
    return standalone, in_proj_a, in_proj_b


async def test_models_list_default_view_is_cards(client: AsyncClient) -> None:
    await _make_models(client)
    resp = await client.get("/models")
    assert resp.status_code == 200
    # Cards view uses a grid; details/list each use a <table>/<ul>.
    assert "grid grid-cols-1" in resp.text


async def test_models_details_view_renders_table(client: AsyncClient) -> None:
    await _make_models(client)
    resp = await client.get("/models?view=details")
    assert resp.status_code == 200
    # Table heading specific to details view.
    assert '<th class="px-3 py-2">In projects</th>' in resp.text
    assert '<th class="px-3 py-2">Updated</th>' in resp.text


async def test_details_view_rows_are_clickable(client: AsyncClient) -> None:
    """Each <tr> in the details view navigates to the model on click —
    matches the behavior of the cards and list views where the whole
    entry is clickable, not just the name."""
    await _make_models(client)
    resp = await client.get("/models?view=details")
    # The onclick handler wires the whole row to the model URL.
    assert "onclick=\"window.location='/models/" in resp.text
    assert "cursor-pointer" in resp.text


async def test_models_list_view_renders_compact_rows(client: AsyncClient) -> None:
    await _make_models(client)
    resp = await client.get("/models?view=list")
    assert resp.status_code == 200
    # The list view renders <ul>+<li> with no headings; details renders a table head.
    assert "<th " not in resp.text
    assert "<ul" in resp.text


async def test_invalid_view_falls_back_to_cards(client: AsyncClient) -> None:
    await _make_models(client)
    resp = await client.get("/models?view=spreadsheet")
    assert resp.status_code == 200
    # The cards view's grid container is the tell.
    assert "grid grid-cols-1" in resp.text


async def test_in_project_chip_appears_for_linked_models(client: AsyncClient) -> None:
    await _make_models(client)
    resp = await client.get("/models?view=cards")
    assert "in 1 project" in resp.text  # both ProjPart A and B are in 1 project


async def test_hide_project_models_filter(client: AsyncClient) -> None:
    await _make_models(client)

    resp = await client.get("/models?hide_project_models=true")
    assert resp.status_code == 200
    # Standalone is the only one that should still render.
    assert "Standalone" in resp.text
    assert "ProjPart A" not in resp.text
    assert "ProjPart B" not in resp.text


async def test_hide_filter_preserves_view(client: AsyncClient) -> None:
    """The toolbar should keep the filter on when switching views, and
    keep the view when toggling the filter."""
    await _make_models(client)
    resp = await client.get("/models?view=details&hide_project_models=true")
    assert resp.status_code == 200
    # Details view artifact is the table head.
    assert '<th class="px-3 py-2">In projects</th>' in resp.text
    # The view-switch links should preserve hide_project_models=true.
    assert (
        "view=cards&amp;hide_project_models=true" in resp.text
        or "view=cards&hide_project_models=true" in resp.text
    )
    # The filter toggle should drop hide_project_models (turn it off).
    assert "view=details&amp;tag" not in resp.text  # tag not present at all
    # And the active filter chip should show with the check.
    assert "✓" in resp.text


async def test_in_projects_column_shows_names(client: AsyncClient) -> None:
    await _make_models(client)
    resp = await client.get("/models?view=details")
    assert "Voron" in resp.text


async def test_details_view_renders_actual_tag_text(client: AsyncClient) -> None:
    """Regression: tags should appear in the details view's Tags column."""
    await client.post("/api/models", json={"name": "Tagged", "tags": ["voron", "filter"]})
    resp = await client.get("/models?view=details")
    assert resp.status_code == 200
    assert "voron" in resp.text
    assert "filter" in resp.text


async def test_details_view_shows_project_chip_on_name(client: AsyncClient) -> None:
    """Each row in details should clearly show whether the model is in
    a project, regardless of whether it has user-added tags."""
    proj = (await client.post("/api/projects", json={"name": "Voron Build"})).json()["id"]
    m = (await client.post("/api/models", json={"name": "BedFoot"})).json()["id"]
    await client.post(f"/api/projects/{proj}/models", json={"model_id": m})

    resp = await client.get("/models?view=details")
    assert "in 1 project" in resp.text


async def test_save_preferences_sets_cookies(client: AsyncClient) -> None:
    resp = await client.post(
        "/models/preferences",
        data={"view": "details", "hide_project_models": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    set_cookie = resp.headers.get("set-cookie", "")
    assert "maketrack_models_view=details" in set_cookie
    assert "maketrack_models_hide_project_models=true" in set_cookie


async def test_cookies_become_default_for_models_list(client: AsyncClient) -> None:
    """After saving prefs, an unparam'd /models GET picks up the cookie
    defaults (so the user lands on details + filtered automatically)."""
    await client.post("/api/models", json={"name": "Library"})
    proj = (await client.post("/api/projects", json={"name": "Voron"})).json()["id"]
    in_proj = (await client.post("/api/models", json={"name": "Bracket"})).json()["id"]
    await client.post(f"/api/projects/{proj}/models", json={"model_id": in_proj})

    # Initial visit — defaults to cards + no filter, both models visible.
    initial = await client.get("/models")
    assert "grid grid-cols-1" in initial.text  # cards layout
    assert "Library" in initial.text
    assert "Bracket" in initial.text

    # Save details + hide_project_models as defaults.
    await client.post(
        "/models/preferences",
        data={"view": "details", "hide_project_models": "true"},
        follow_redirects=False,
    )

    # Subsequent unparam'd visit picks up the saved defaults.
    after = await client.get("/models")
    assert '<th class="px-3 py-2">In projects</th>' in after.text  # details layout
    assert "Library" in after.text  # standalone visible
    assert "Bracket" not in after.text  # project-scoped hidden by saved filter

    # Explicit ?view= still wins over the cookie (so the user can poke
    # other views without losing their saved default).
    override = await client.get("/models?view=cards")
    assert "grid grid-cols-1" in override.text


async def test_save_preferences_handles_invalid_view(client: AsyncClient) -> None:
    resp = await client.post(
        "/models/preferences",
        data={"view": "spreadsheet", "hide_project_models": "false"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    set_cookie = resp.headers.get("set-cookie", "")
    # Falls back to 'cards' rather than persisting nonsense.
    assert "maketrack_models_view=cards" in set_cookie


async def test_empty_after_filter_shows_useful_message(client: AsyncClient) -> None:
    # All models linked to a project; filtering them out leaves nothing.
    proj = (await client.post("/api/projects", json={"name": "P"})).json()["id"]
    m = (await client.post("/api/models", json={"name": "OnlyOne"})).json()["id"]
    await client.post(f"/api/projects/{proj}/models", json={"model_id": m})

    resp = await client.get("/models?hide_project_models=true")
    assert resp.status_code == 200
    assert "All your models are scoped to projects" in resp.text
