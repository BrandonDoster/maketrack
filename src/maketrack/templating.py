from pathlib import Path

from fastapi.templating import Jinja2Templates

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"
TAILWIND_BUILT_PATH = STATIC_DIR / "tailwind.css"


def tailwind_is_compiled() -> bool:
    return TAILWIND_BUILT_PATH.exists()


templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["tailwind_compiled"] = tailwind_is_compiled
