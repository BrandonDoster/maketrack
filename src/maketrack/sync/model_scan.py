import hashlib
import json
import logging
from dataclasses import dataclass

import frontmatter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from maketrack.config import Settings
from maketrack.models.model import Model, ModelAsset
from maketrack.services.three_mf import extract_thumbnail as extract_thumbnail_from_3mf

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    folders_scanned: int
    rows_upserted: int
    rows_deleted: int
    errors: list[str]


async def scan_models(session: AsyncSession, settings: Settings) -> ScanResult:
    """Scan /maketrack-models and sync the database to match the filesystem.

    For each folder in models_path:
    1. Read README.md and parse YAML frontmatter.
    2. Upsert Model row with metadata from frontmatter.
    3. Scan photos/ and models/ subdirs, upsert ModelAsset rows.
    4. Extract 3MF thumbnails if needed.
    5. Rebuild asset_ids JSON.
    6. Archive any models no longer on disk.
    """
    if not settings.models_path.exists():
        logger.warning(f"models_path does not exist: {settings.models_path}")
        return ScanResult(0, 0, 0, [])

    errors: list[str] = []
    scanned_folders: set[str] = set()
    rows_upserted = 0
    rows_deleted = 0

    # Walk top-level folders in models_path.
    for folder in sorted(settings.models_path.iterdir()):
        if not folder.is_dir():
            continue

        folder_name = folder.name
        scanned_folders.add(folder_name)

        readme_path = folder / "README.md"
        if not readme_path.exists():
            logger.warning(f"No README.md found in {folder_name}, skipping")
            errors.append(f"No README.md in {folder_name}")
            continue

        try:
            # Read and hash the README.
            readme_content = readme_path.read_text(encoding="utf-8")
            readme_hash = hashlib.sha256(readme_content.encode()).hexdigest()

            # Parse frontmatter.
            post = frontmatter.loads(readme_content)
            metadata = post.metadata

            # Extract metadata from frontmatter.
            name = metadata.get("name", folder_name)
            thumbnail_filename = metadata.get("thumbnail")
            source_type = metadata.get("source_type")
            source_url = metadata.get("source_url")
            tags_raw = metadata.get("tags")
            notes = metadata.get("notes")

            # Serialize tags back to JSON if present.
            tags_json = None
            if tags_raw:
                if isinstance(tags_raw, list):
                    tags_json = json.dumps(tags_raw)
                elif isinstance(tags_raw, str):
                    tags_json = json.dumps([tags_raw])

            # Upsert Model row.
            model = await session.run_sync(
                _upsert_model,
                folder_name,
                name,
                source_type,
                source_url,
                thumbnail_filename,
                readme_hash,
                notes,
                tags_json,
            )
            rows_upserted += 1

            # Scan and upsert assets.
            photos_dir = folder / "photos"
            models_dir = folder / "models"
            asset_ids = []

            for asset_dir, asset_type_prefix in [
                (photos_dir, "image"),
                (models_dir, None),
            ]:
                if not asset_dir.exists():
                    continue

                for asset_file in sorted(asset_dir.iterdir()):
                    if not asset_file.is_file():
                        continue

                    # Determine asset type.
                    if asset_type_prefix == "image":
                        asset_type = "image"
                    else:
                        ext = asset_file.suffix.lower().lstrip(".")
                        ext_map = {
                            "stl": "stl",
                            "step": "step",
                            "stp": "step",
                            "3mf": "3mf",
                            "gcode": "gcode",
                            "g": "gcode",
                            "gco": "gcode",
                            "png": "image",
                            "jpg": "image",
                            "jpeg": "image",
                            "webp": "image",
                            "gif": "image",
                        }
                        asset_type = ext_map.get(ext, "other")

                    # Construct relative path.
                    file_path = f"{folder_name}/{asset_dir.name}/{asset_file.name}"

                    # Compute file size.
                    file_size = asset_file.stat().st_size

                    # Upsert asset (lazy SHA-256: only compute if not already in DB).
                    asset = await session.run_sync(
                        _upsert_asset,
                        model.id,
                        asset_type,
                        asset_file.name,
                        file_path,
                        file_size,
                    )
                    asset_ids.append(asset.id)

                    # Auto-extract a 3MF thumbnail when the model has none
                    # yet (either from frontmatter or set earlier this scan).
                    if asset_type == "3mf" and not thumbnail_filename:
                        try:
                            thumb_bytes = extract_thumbnail_from_3mf(asset_file)
                        except Exception as e:
                            logger.warning(f"Failed to extract thumbnail from {file_path}: {e}")
                            thumb_bytes = None
                        if thumb_bytes:
                            photos_dir.mkdir(exist_ok=True)
                            thumb_filename = f"{asset_file.stem}_thumbnail.png"
                            (photos_dir / thumb_filename).write_bytes(thumb_bytes)

                            thumb_asset = await session.run_sync(
                                _upsert_asset,
                                model.id,
                                "image",
                                thumb_filename,
                                f"{folder_name}/photos/{thumb_filename}",
                                len(thumb_bytes),
                                generated=True,
                            )
                            asset_ids.append(thumb_asset.id)

                            # Persist the choice: write it back into the
                            # README frontmatter (so a re-scan is stable) and
                            # onto the row, then remember it for this folder.
                            thumbnail_filename = thumb_filename
                            model.thumbnail_filename = thumb_filename
                            model.readme_hash = _set_readme_thumbnail(readme_path, thumb_filename)

            # Update asset_ids on model.
            if asset_ids:
                model.asset_ids = json.dumps(asset_ids)

        except Exception as e:
            logger.error(f"Error scanning {folder_name}: {e!s}")
            errors.append(f"Error in {folder_name}: {e!s}")
            # Mark model as malformed.
            await session.run_sync(_mark_malformed, folder_name)

    # Archive sweep: delete any Model rows not in scanned_folders.
    rows_deleted = await session.run_sync(_archive_orphans, scanned_folders)

    await session.commit()

    return ScanResult(
        folders_scanned=len(scanned_folders),
        rows_upserted=rows_upserted,
        rows_deleted=rows_deleted,
        errors=errors,
    )


def _set_readme_thumbnail(readme_path, thumbnail_filename: str) -> str:
    """Write `thumbnail:` into the README frontmatter and return the new hash.

    Uses python-frontmatter so we round-trip YAML correctly instead of
    string-poking the raw text. Keeps the body intact.
    """
    post = frontmatter.load(str(readme_path))
    post["thumbnail"] = thumbnail_filename
    new_content = frontmatter.dumps(post)
    readme_path.write_text(new_content, encoding="utf-8")
    return hashlib.sha256(new_content.encode()).hexdigest()


def _upsert_model(
    session: Session,
    folder_name: str,
    name: str,
    source_type: str | None,
    source_url: str | None,
    thumbnail_filename: str | None,
    readme_hash: str,
    notes: str | None,
    tags: str | None,
) -> Model:
    """Upsert a Model by folder_name."""
    model = session.query(Model).filter_by(folder_name=folder_name).first()
    if not model:
        model = Model(folder_name=folder_name)
        session.add(model)
    model.name = name
    model.source_type = source_type
    model.source_url = source_url
    model.thumbnail_filename = thumbnail_filename
    model.readme_hash = readme_hash
    model.notes = notes
    model.tags = tags
    model.readme_malformed = False
    session.flush()
    return model


def _upsert_asset(
    session: Session,
    model_id: int,
    asset_type: str,
    filename: str,
    file_path: str,
    file_size: int,
    generated: bool = False,
) -> ModelAsset:
    """Upsert a ModelAsset by model_id + filename."""
    asset = session.query(ModelAsset).filter_by(model_id=model_id, filename=filename).first()
    if not asset:
        asset = ModelAsset(
            model_id=model_id,
            asset_type=asset_type,
            filename=filename,
            file_path=file_path,
            file_size=file_size,
            generated=generated,
        )
        session.add(asset)
    else:
        asset.asset_type = asset_type
        asset.file_path = file_path
        asset.file_size = file_size
        asset.generated = generated
    session.flush()
    return asset


def _mark_malformed(session: Session, folder_name: str) -> None:
    """Mark a model as having a malformed README."""
    model = session.query(Model).filter_by(folder_name=folder_name).first()
    if model:
        model.readme_malformed = True


def _archive_orphans(session: Session, scanned_folders: set[str]) -> int:
    """Delete Model rows whose folder_name is not in scanned_folders."""
    orphans = session.query(Model).filter(~Model.folder_name.in_(scanned_folders)).all()
    count = len(orphans)
    for orphan in orphans:
        session.delete(orphan)
    return count
