from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from maketrack.config import get_settings

router = APIRouter(tags=["media"])


@router.get("/media/{subpath:path}")
async def serve_upload(subpath: str) -> FileResponse:
    """Serve a file from the uploads volume.

    Path traversal is blocked by resolving the target and asserting it
    sits inside the uploads root. We also reject anything that isn't a
    regular file, so directories and symlinks pointing outside don't leak.
    """
    root = get_settings().uploads_path.resolve()
    try:
        target = (root / subpath).resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc

    if root not in target.parents and target != root:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(Path(target))
