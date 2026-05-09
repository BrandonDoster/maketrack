import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_sessionmaker
from maketrack.models.external_source import ExternalSource
from maketrack.services.external_sources import try_acquire_lock
from maketrack.sources.base import ExternalFilament, FilamentSource
from maketrack.sources.spoolman import SpoolmanFilamentSource
from maketrack.sync.engine import SyncOutcome, sync_source
from tests.factories import SpoolmanSourceFactory, persist


class FakeSpoolmanSource:
    def __init__(self, spools: list[ExternalFilament]) -> None:
        self.spools = spools
        self.calls = 0

    async def list_spools(self) -> list[ExternalFilament]:
        self.calls += 1
        return list(self.spools)

    async def health_check(self) -> bool:
        return True


def _make_factory(spools: list[ExternalFilament]):
    fake = FakeSpoolmanSource(spools)

    def factory(_source: ExternalSource, _client: httpx.AsyncClient | None) -> FilamentSource:
        return fake

    return factory, fake


async def _seed_source(session: AsyncSession, **overrides) -> ExternalSource:
    src = await persist(session, SpoolmanSourceFactory(**overrides))
    await session.commit()
    return src


async def test_sync_upserts_new_spools(session: AsyncSession) -> None:
    src = await _seed_source(session)
    factory, _ = _make_factory(
        [
            ExternalFilament(external_id="1", name="A", material="PLA"),
            ExternalFilament(external_id="2", name="B", material="PETG"),
        ]
    )

    result = await sync_source(get_sessionmaker(), src.id, source_factory=factory)

    assert result.outcome == SyncOutcome.OK
    assert result.rows_upserted == 2
    assert result.rows_archived == 0


async def test_sync_archive_sweep_removes_missing(session: AsyncSession) -> None:
    src = await _seed_source(session)

    factory_a, _ = _make_factory(
        [
            ExternalFilament(external_id="1", name="A"),
            ExternalFilament(external_id="2", name="B"),
        ]
    )
    await sync_source(get_sessionmaker(), src.id, source_factory=factory_a)

    # Second sync only returns spool 1; spool 2 should be archived.
    factory_b, _ = _make_factory([ExternalFilament(external_id="1", name="A")])
    result = await sync_source(get_sessionmaker(), src.id, source_factory=factory_b)

    assert result.outcome == SyncOutcome.OK
    assert result.rows_upserted == 1
    assert result.rows_archived == 1


async def test_sync_clears_archived_at_on_reappearance(session: AsyncSession) -> None:
    src = await _seed_source(session)

    # Sync once with two spools.
    f1, _ = _make_factory(
        [
            ExternalFilament(external_id="1", name="A"),
            ExternalFilament(external_id="2", name="B"),
        ]
    )
    await sync_source(get_sessionmaker(), src.id, source_factory=f1)

    # Sync again with only one — second is archived.
    f2, _ = _make_factory([ExternalFilament(external_id="1", name="A")])
    await sync_source(get_sessionmaker(), src.id, source_factory=f2)

    # Sync a third time with both back — archived_at should clear on spool 2.
    f3, _ = _make_factory(
        [
            ExternalFilament(external_id="1", name="A"),
            ExternalFilament(external_id="2", name="B"),
        ]
    )
    result = await sync_source(get_sessionmaker(), src.id, source_factory=f3)

    assert result.outcome == SyncOutcome.OK
    # Both rows still present and active after the third sync.
    from sqlalchemy import select

    from maketrack.models.filament import Filament

    rows = (
        (await session.execute(select(Filament).where(Filament.source == "spoolman")))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.archived_at is None for r in rows)


async def test_sync_skipped_when_lock_held(session: AsyncSession) -> None:
    src = await _seed_source(session)

    # Manually grab the lock to simulate a concurrent run.
    acquired = await try_acquire_lock(session, src.id)
    assert acquired is True

    factory, fake = _make_factory([ExternalFilament(external_id="1")])
    result = await sync_source(get_sessionmaker(), src.id, source_factory=factory)

    assert result.outcome == SyncOutcome.SKIPPED_LOCKED
    assert fake.calls == 0  # adapter never invoked


async def test_sync_skipped_when_disabled(session: AsyncSession) -> None:
    src = await _seed_source(session, enabled=False)
    factory, fake = _make_factory([ExternalFilament(external_id="1")])
    result = await sync_source(get_sessionmaker(), src.id, source_factory=factory)
    assert result.outcome == SyncOutcome.SKIPPED_DISABLED
    assert fake.calls == 0


async def test_sync_failed_releases_lock_and_skips_archive_sweep(session: AsyncSession) -> None:
    src = await _seed_source(session)

    # First sync seeds two rows.
    factory_ok, _ = _make_factory(
        [
            ExternalFilament(external_id="1", name="A"),
            ExternalFilament(external_id="2", name="B"),
        ]
    )
    await sync_source(get_sessionmaker(), src.id, source_factory=factory_ok)

    class BrokenSource:
        async def list_spools(self) -> list[ExternalFilament]:
            raise httpx.ConnectError("boom")

        async def health_check(self) -> bool:
            return False

    def broken_factory(_s, _c):
        return BrokenSource()

    result = await sync_source(get_sessionmaker(), src.id, source_factory=broken_factory)
    assert result.outcome == SyncOutcome.FAILED
    assert "boom" in (result.error or "")

    # Lock released so a follow-up sync can run.
    await session.refresh(src)
    assert src.sync_in_progress is False

    # Existing rows untouched (no archive sweep on failure).
    from sqlalchemy import select

    from maketrack.models.filament import Filament

    rows = (
        (await session.execute(select(Filament).where(Filament.source == "spoolman")))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.archived_at is None for r in rows)


def test_spoolman_source_requires_base_url(session: AsyncSession) -> None:
    import pytest

    from maketrack.sources.spoolman import build_spoolman_source

    src = ExternalSource(type="spoolman", name="missing", base_url=None)
    with pytest.raises(ValueError, match="no base_url"):
        build_spoolman_source(src)


# Touch SpoolmanFilamentSource here so the import isn't unused.
_ = SpoolmanFilamentSource
