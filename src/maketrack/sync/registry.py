from collections.abc import Callable

import httpx

from maketrack.models.external_source import ExternalSource
from maketrack.sources.base import FilamentSource
from maketrack.sources.spoolman import build_spoolman_source

SourceBuilder = Callable[[ExternalSource, httpx.AsyncClient | None], FilamentSource]


def _spoolman(source: ExternalSource, client: httpx.AsyncClient | None) -> FilamentSource:
    return build_spoolman_source(source, client=client)


SOURCE_BUILDERS: dict[str, SourceBuilder] = {
    "spoolman": _spoolman,
}


def build_source(
    source: ExternalSource,
    client: httpx.AsyncClient | None = None,
) -> FilamentSource:
    builder = SOURCE_BUILDERS.get(source.type)
    if builder is None:
        raise ValueError(f"unknown external source type: {source.type!r}")
    return builder(source, client)
