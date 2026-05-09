from typing import Literal

from fastapi import Request

ThemeChoice = Literal["auto", "light", "dark"]
THEME_COOKIE = "maketrack_theme"
ALLOWED_THEMES: tuple[ThemeChoice, ...] = ("auto", "light", "dark")
DEFAULT_THEME: ThemeChoice = "auto"


def get_theme(request: Request) -> ThemeChoice:
    """Read the theme cookie, defaulting to 'auto' if missing or invalid."""
    raw = request.cookies.get(THEME_COOKIE, DEFAULT_THEME)
    if raw not in ALLOWED_THEMES:
        return DEFAULT_THEME
    return raw  # type: ignore[return-value]


def is_valid(value: str) -> bool:
    return value in ALLOWED_THEMES
