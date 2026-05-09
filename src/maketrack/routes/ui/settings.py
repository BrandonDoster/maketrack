from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.models.external_source import ExternalSource
from maketrack.services.theme import (
    ALLOWED_THEMES,
    DEFAULT_THEME,
    THEME_COOKIE,
    get_theme,
    is_valid,
)
from maketrack.templating import templates

router = APIRouter(tags=["ui-settings"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, session: SessionDep) -> HTMLResponse:
    source_count = (
        await session.execute(select(func.count()).select_from(ExternalSource))
    ).scalar_one()
    return templates.TemplateResponse(
        request,
        "settings/index.html",
        {
            "source_count": source_count,
            "current_theme": get_theme(request),
            "themes": ALLOWED_THEMES,
        },
    )


@router.post("/settings/theme", response_class=HTMLResponse)
async def set_theme(request: Request) -> HTMLResponse:
    form = await request.form()
    choice = form.get("theme", DEFAULT_THEME)
    if not is_valid(choice):
        choice = DEFAULT_THEME
    response = RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)
    # 1 year, scoped to the host. Single-user LAN: no need for HttpOnly
    # since the browser-side script reads this to apply the theme without
    # FOUC; if we made it HttpOnly the script would have to call back.
    response.set_cookie(
        THEME_COOKIE,
        choice,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
    )
    return response
