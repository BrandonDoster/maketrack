import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from maketrack.config import get_settings

ALLOWED_PHOTO_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
# Map content-type to extension. Stored filenames include the extension so
# /media/<path> hits Starlette's FileResponse with a guessable mime type.
PHOTO_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


class UploadError(Exception):
    """Raised for any upload failure the user should see."""


def _resolve_inside_uploads(relative_path: str) -> Path:
    """Resolve a stored path against the uploads root with a traversal guard."""
    root = get_settings().uploads_path.resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents and target != root:
        raise UploadError(f"path escapes uploads root: {relative_path!r}")
    return target


async def save_photo(file: UploadFile, *, subdir: str) -> tuple[str, int, str]:
    """Save an uploaded image and return (relative_path, size_bytes, sha256).

    relative_path is a forward-slash path under /uploads so it can be
    embedded in URLs (/media/<relative_path>) and stored verbatim in the DB.
    """
    if file.content_type not in ALLOWED_PHOTO_TYPES:
        raise UploadError(f"unsupported photo type: {file.content_type or 'unknown'}")

    root = get_settings().uploads_path
    target_dir = root / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    extension = PHOTO_EXTENSIONS[file.content_type]
    name = f"{uuid.uuid4().hex}{extension}"
    target = target_dir / name

    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_PHOTO_BYTES:
                    raise UploadError(f"photo too large (>{MAX_PHOTO_BYTES // 1024 // 1024} MB)")
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return f"{subdir}/{name}", size, digest.hexdigest()


def delete_upload(relative_path: str | None) -> None:
    """Best-effort delete. Silent on missing files."""
    if not relative_path:
        return
    target = _resolve_inside_uploads(relative_path)
    target.unlink(missing_ok=True)


# Larger ceiling for general assets (STL/3MF/STEP/gcode can be tens of MB).
MAX_ASSET_BYTES = 200 * 1024 * 1024  # 200 MB


async def save_asset(
    file: UploadFile,
    *,
    subdir: str,
    max_bytes: int = MAX_ASSET_BYTES,
) -> tuple[str, int, str]:
    """Save an arbitrary user-uploaded file under uploads/<subdir>/<uuid><ext>.

    Returns (relative_path, size_bytes, sha256). The original filename is
    NOT preserved on disk; callers store it separately (e.g. in
    model_assets.filename) and use it for Content-Disposition on download.
    """
    if not file.filename:
        raise UploadError("upload has no filename")

    root = get_settings().uploads_path
    target_dir = root / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    extension = Path(file.filename).suffix.lower()
    name = f"{uuid.uuid4().hex}{extension}" if extension else uuid.uuid4().hex
    target = target_dir / name

    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadError(f"file too large (>{max_bytes // 1024 // 1024} MB)")
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return f"{subdir}/{name}", size, digest.hexdigest()


def write_bytes_as_asset(data: bytes, *, subdir: str, extension: str) -> tuple[str, int, str]:
    """Persist raw bytes as a new asset (used for 3MF-extracted thumbnails)."""
    root = get_settings().uploads_path
    target_dir = root / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{extension}"
    target = target_dir / name
    target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return f"{subdir}/{name}", len(data), digest


# ── filesystem-first model storage (models_path) ────────────────────────────
#
# Model assets live under models_path/<folder_name>/{photos,models}/<filename>
# with the ORIGINAL filename preserved on disk so the tree is browsable over a
# network share and the scan can re-derive rows. file_path values returned here
# are forward-slash paths RELATIVE TO models_path (e.g.
# "voron-mount/models/part.stl") and are served via /model-media/<path>.


def _resolve_inside_models(relative_path: str) -> Path:
    """Resolve a stored model path against models_path with a traversal guard."""
    root = get_settings().models_path.resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents and target != root:
        raise UploadError(f"path escapes models root: {relative_path!r}")
    return target


def _dedupe_filename(target_dir: Path, filename: str) -> str:
    """Return a filename that doesn't collide inside target_dir.

    Preserves the original name when free; otherwise appends ' (2)', ' (3)'…
    before the extension so the on-disk name stays human-readable.
    """
    candidate = Path(filename)
    stem, suffix = candidate.stem, candidate.suffix
    name = filename
    n = 2
    while (target_dir / name).exists():
        name = f"{stem} ({n}){suffix}"
        n += 1
    return name


async def save_model_asset(
    file: UploadFile,
    *,
    folder_name: str,
    subdir: str,
    max_bytes: int = MAX_ASSET_BYTES,
) -> tuple[str, int, str, str]:
    """Stream an upload into models_path/<folder_name>/<subdir>/<filename>.

    Returns (relative_path, size_bytes, sha256, filename_on_disk). The
    on-disk filename is the original name, de-duplicated on collision.
    """
    if not file.filename:
        raise UploadError("upload has no filename")

    target_dir = get_settings().models_path / folder_name / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = _dedupe_filename(target_dir, file.filename)
    target = target_dir / name

    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadError(f"file too large (>{max_bytes // 1024 // 1024} MB)")
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return f"{folder_name}/{subdir}/{name}", size, digest.hexdigest(), name


def write_bytes_to_model(
    data: bytes, *, folder_name: str, subdir: str, filename: str
) -> tuple[str, int, str, str]:
    """Persist raw bytes under a model folder (used for 3MF-extracted thumbs).

    Returns (relative_path, size_bytes, sha256, filename_on_disk).
    """
    target_dir = get_settings().models_path / folder_name / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = _dedupe_filename(target_dir, filename)
    target = target_dir / name
    target.write_bytes(data)
    return f"{folder_name}/{subdir}/{name}", len(data), hashlib.sha256(data).hexdigest(), name


def delete_model_file(relative_path: str | None) -> None:
    """Best-effort delete of a single file under models_path."""
    if not relative_path:
        return
    target = _resolve_inside_models(relative_path)
    target.unlink(missing_ok=True)


def delete_model_folder(folder_name: str | None) -> None:
    """Best-effort recursive delete of an entire model folder."""
    if not folder_name:
        return
    target = _resolve_inside_models(folder_name)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
