import hashlib
import json
import logging
from dataclasses import dataclass

import frontmatter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from maketrack.config import Settings
from maketrack.models.model import Model, ModelAsset
from maketrack.services.assets import asset_type_from_filename
from maketrack.services.three_mf import extract_thumbnail as extract_thumbnail_from_3mf

logger = logging.getLogger(__name__)

# Subtrees of a model folder that hold assets. The folder root only holds
# README.md (metadata); files live under these, and either may nest
# (e.g. models/cad/, models/stl/, a root models/print.3mf).
ASSET_SUBDIRS = ("photos", "models")


@dataclass
class ScanResult:
    folders_scanned: int
    rows_upserted: int
    rows_deleted: int
    errors: list[str]


async def scan_models(
    session: AsyncSession, settings: Settings, *, only_folder: str | None = None
) -> ScanResult:
    """Sync the database to match the model library on disk.

    For each folder in models_path: read README.md frontmatter, upsert the
    Model, then recursively index every file under photos/ and models/ as a
    ModelAsset (nesting preserved in file_path), extracting 3MF thumbnails.
    Per-model orphan assets (rows whose file vanished) are swept.

    `only_folder` rescans just that one folder and skips the cross-folder
    archive sweep — used for the cheap per-model rescan when a detail page
    is opened.
    """
    if not settings.models_path.exists():
        logger.warning(f"models_path does not exist: {settings.models_path}")
        return ScanResult(0, 0, 0, [])

    errors: list[str] = []
    scanned_folders: set[str] = set()
    rows_upserted = 0
    rows_deleted = 0

    for folder in sorted(settings.models_path.iterdir()):
        if not folder.is_dir():
            continue
        folder_name = folder.name
        if only_folder is not None and folder_name != only_folder:
            continue
        scanned_folders.add(folder_name)

        readme_path = folder / "README.md"
        if not readme_path.exists():
            logger.warning(f"No README.md found in {folder_name}, skipping")
            errors.append(f"No README.md in {folder_name}")
            continue

        try:
            readme_content = readme_path.read_text(encoding="utf-8")
            readme_hash = hashlib.sha256(readme_content.encode()).hexdigest()
            metadata = frontmatter.loads(readme_content).metadata

            name = metadata.get("name", folder_name)
            thumbnail_filename = metadata.get("thumbnail")
            source_type = metadata.get("source_type")
            source_url = metadata.get("source_url")
            tags_raw = metadata.get("tags")
            notes = metadata.get("notes")

            tags_json = None
            if tags_raw:
                tags_json = json.dumps(tags_raw if isinstance(tags_raw, list) else [tags_raw])

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

            # Recursively index photos/ and models/ (and their subfolders).
            photos_dir = folder / "photos"
            asset_ids: list[int] = []
            seen_paths: list[str] = []
            for subdir in ASSET_SUBDIRS:
                sub = folder / subdir
                if not sub.is_dir():
                    continue
                for asset_file in sorted(sub.rglob("*")):
                    if not asset_file.is_file():
                        continue
                    # Skip dotfiles and anything under a dot-directory.
                    if any(part.startswith(".") for part in asset_file.relative_to(folder).parts):
                        continue

                    rel = asset_file.relative_to(settings.models_path).as_posix()
                    asset_type = asset_type_from_filename(asset_file.name)
                    asset = await session.run_sync(
                        _upsert_asset,
                        model.id,
                        asset_type,
                        asset_file.name,
                        rel,
                        asset_file.stat().st_size,
                    )
                    asset_ids.append(asset.id)
                    seen_paths.append(rel)

                    # Auto-extract a 3MF thumbnail when the model has none yet.
                    if asset_type == "3mf" and not thumbnail_filename:
                        try:
                            thumb_bytes = extract_thumbnail_from_3mf(asset_file)
                        except Exception as e:
                            logger.warning(f"Failed to extract thumbnail from {rel}: {e}")
                            thumb_bytes = None
                        if thumb_bytes:
                            photos_dir.mkdir(exist_ok=True)
                            thumb_filename = f"{asset_file.stem}_thumbnail.png"
                            (photos_dir / thumb_filename).write_bytes(thumb_bytes)
                            thumb_rel = f"{folder_name}/photos/{thumb_filename}"
                            thumb_asset = await session.run_sync(
                                _upsert_asset,
                                model.id,
                                "image",
                                thumb_filename,
                                thumb_rel,
                                len(thumb_bytes),
                                generated=True,
                            )
                            asset_ids.append(thumb_asset.id)
                            seen_paths.append(thumb_rel)
                            thumbnail_filename = thumb_filename
                            model.thumbnail_filename = thumb_filename
                            model.readme_hash = _set_readme_thumbnail(readme_path, thumb_filename)

            # Drop rows for files that no longer exist (moved/renamed/deleted).
            rows_deleted += await session.run_sync(_sweep_model_assets, model.id, set(seen_paths))
            model.asset_ids = json.dumps(asset_ids) if asset_ids else None

        except Exception as e:
            logger.error(f"Error scanning {folder_name}: {e!s}")
            errors.append(f"Error in {folder_name}: {e!s}")
            await session.run_sync(_mark_malformed, folder_name)

    # Cross-folder archive sweep: drop models whose folder is gone. Skipped
    # for a scoped (single-folder) rescan so it can't delete other models.
    if only_folder is None:
        rows_deleted += await session.run_sync(_archive_orphans, scanned_folders)

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
    """Upsert a ModelAsset by (model_id, file_path).

    Keyed on file_path, not filename: with subfolders, two files can share a
    name (models/cad/x.stl vs models/stl/x.stl). The path is the file's
    identity on disk.
    """
    asset = session.query(ModelAsset).filter_by(model_id=model_id, file_path=file_path).first()
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


def _sweep_model_assets(session: Session, model_id: int, seen_paths: set[str]) -> int:
    """Delete a model's asset rows whose file_path was not seen this scan.

    Fixes stale paths after a file is moved, renamed, or deleted on disk.
    Cascades to any project_models link (filesystem is the source of truth).
    """
    rows = session.query(ModelAsset).filter_by(model_id=model_id).all()
    count = 0
    for asset in rows:
        if asset.file_path not in seen_paths:
            session.delete(asset)
            count += 1
    return count


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
