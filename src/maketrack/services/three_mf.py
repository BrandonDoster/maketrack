import zipfile
from pathlib import Path

# Different slicers stash the thumbnail PNG at different paths inside the
# 3MF zip. CLAUDE.md flags this — try the well-known names first, then
# fall back to anything PNG that lives under Metadata/.
KNOWN_THUMBNAIL_PATHS: tuple[str, ...] = (
    "Metadata/plate_1.png",
    "Metadata/thumbnail.png",
    "Metadata/_rels/thumbnail.png",
    "Metadata/plate.png",
)


def extract_thumbnail(threemf_path: Path) -> bytes | None:
    """Return the embedded thumbnail PNG bytes, or None if there isn't one.

    Doesn't raise on a malformed zip — the caller has already saved the
    file and we'd rather skip the thumbnail than fail the upload.
    """
    try:
        with zipfile.ZipFile(threemf_path) as zf:
            names = set(zf.namelist())
            for candidate in KNOWN_THUMBNAIL_PATHS:
                if candidate in names:
                    data = zf.read(candidate)
                    if _looks_like_png(data):
                        return data
            for name in sorted(names):
                if name.lower().startswith("metadata/") and name.lower().endswith(".png"):
                    data = zf.read(name)
                    if _looks_like_png(data):
                        return data
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    return None


def _looks_like_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")
