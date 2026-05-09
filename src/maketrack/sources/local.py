from maketrack.sources.base import ExternalFilament


class LocalFilamentSource:
    """Degenerate adapter for source='local'.

    Local filaments are managed directly through the service layer; the sync
    engine never invokes a local adapter. This class exists so the protocol
    has a complete set of implementations and so callers that iterate
    sources by type don't have to special-case 'local'.
    """

    async def list_spools(self) -> list[ExternalFilament]:
        return []

    async def health_check(self) -> bool:
        return True
