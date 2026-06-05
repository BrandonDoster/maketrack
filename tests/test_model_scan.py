"""Coverage for the filesystem → DB scan engine (sync/model_scan.py).

The scan reconciles the DB to whatever is on disk under models_path: it
upserts a Model per folder (reading README.md frontmatter), upserts a
ModelAsset per file in photos/ and models/, extracts 3MF thumbnails, and
hard-deletes Models whose folders have vanished — cascading through their
assets and any project links.
"""

import io
import shutil
import zipfile
from pathlib import Path

import frontmatter
import pytest
from sqlalchemy import select

from maketrack.config import get_settings
from maketrack.models.model import Model, ModelAsset
from maketrack.models.project import Project, ProjectModel
from maketrack.sync.model_scan import scan_models

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_folder(name: str, *, frontmatter_extra: dict | None = None, body: str = "") -> Path:
    """Create a model folder on disk with README + empty subdirs."""
    root = get_settings().models_path / name
    (root / "photos").mkdir(parents=True, exist_ok=True)
    (root / "models").mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, name=name, **(frontmatter_extra or {}))
    (root / "README.md").write_text(frontmatter.dumps(post), encoding="utf-8")
    return root


def _stl_bytes() -> bytes:
    return b"\x00" * 80 + (0).to_bytes(4, "little")


def _3mf_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("Metadata/plate_1.png", _PNG)
    return buf.getvalue()


@pytest.mark.usefixtures("db_engine")
async def test_scan_upserts_model_and_assets(session) -> None:
    folder = _make_folder("voron-mount", frontmatter_extra={"tags": ["voron"]}, body="A mount.")
    (folder / "models" / "part.stl").write_bytes(_stl_bytes())

    result = await scan_models(session, get_settings())
    assert result.folders_scanned == 1
    assert not result.errors

    model = (await session.execute(select(Model))).scalars().one()
    assert model.folder_name == "voron-mount"
    assert model.name == "voron-mount"
    assert model.readme_hash is not None

    asset = (await session.execute(select(ModelAsset))).scalars().one()
    assert asset.asset_type == "stl"
    assert asset.file_path == "voron-mount/models/part.stl"


@pytest.mark.usefixtures("db_engine")
async def test_scan_is_idempotent(session) -> None:
    folder = _make_folder("thing")
    (folder / "models" / "a.stl").write_bytes(_stl_bytes())

    await scan_models(session, get_settings())
    await scan_models(session, get_settings())

    models = (await session.execute(select(Model))).scalars().all()
    assets = (await session.execute(select(ModelAsset))).scalars().all()
    assert len(models) == 1
    assert len(assets) == 1


@pytest.mark.usefixtures("db_engine")
async def test_scan_extracts_3mf_thumbnail(session) -> None:
    folder = _make_folder("printed")
    (folder / "models" / "plate.3mf").write_bytes(_3mf_bytes())

    await scan_models(session, get_settings())

    model = (await session.execute(select(Model))).scalars().one()
    assert model.thumbnail_filename == "plate_thumbnail.png"
    # The extracted PNG landed in photos/ and the README was updated to match.
    assert (folder / "photos" / "plate_thumbnail.png").is_file()
    assert frontmatter.load(str(folder / "README.md"))["thumbnail"] == "plate_thumbnail.png"
    types = {a.asset_type for a in (await session.execute(select(ModelAsset))).scalars().all()}
    assert types == {"3mf", "image"}


@pytest.mark.usefixtures("db_engine")
async def test_scan_deletes_orphan_and_cascades_project_link(session) -> None:
    folder = _make_folder("doomed")
    (folder / "models" / "p.stl").write_bytes(_stl_bytes())
    await scan_models(session, get_settings())

    asset = (await session.execute(select(ModelAsset))).scalars().one()
    project = Project(name="P")
    session.add(project)
    await session.flush()
    session.add(ProjectModel(project_id=project.id, model_asset_id=asset.id))
    await session.commit()

    # Folder vanishes (e.g. deleted over the network share).
    shutil.rmtree(folder)
    result = await scan_models(session, get_settings())
    assert result.rows_deleted == 1

    # Model, its asset, and the project link are all gone — no IntegrityError.
    assert (await session.execute(select(Model))).scalars().all() == []
    assert (await session.execute(select(ModelAsset))).scalars().all() == []
    assert (await session.execute(select(ProjectModel))).scalars().all() == []


@pytest.mark.usefixtures("db_engine")
async def test_scan_flags_folder_without_readme(session) -> None:
    root = get_settings().models_path / "no-readme"
    (root / "models").mkdir(parents=True, exist_ok=True)

    result = await scan_models(session, get_settings())
    assert any("no-readme" in e for e in result.errors)
    assert (await session.execute(select(Model))).scalars().all() == []
