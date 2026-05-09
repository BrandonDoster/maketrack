class MakeTrackError(Exception):
    pass


class NotFoundError(MakeTrackError):
    def __init__(self, entity: str, entity_id: int | str) -> None:
        super().__init__(f"{entity} not found: {entity_id}")
        self.entity = entity
        self.entity_id = entity_id


class RemoteFilamentError(MakeTrackError):
    """Raised when a write is attempted against a non-local filament.

    The UI catches this and renders a banner with an "Open in [source]" link
    pointing at ``external_url``. The JSON API surfaces it as 409 + structured
    body.
    """

    def __init__(self, source: str, external_url: str | None) -> None:
        super().__init__(
            f"filament is read-only (source={source}); edit it in the source system instead"
        )
        self.source = source
        self.external_url = external_url
