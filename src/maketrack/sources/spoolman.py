from typing import Any

import httpx

from maketrack.models.external_source import ExternalSource
from maketrack.sources.base import ExternalFilament

# Spoolman's frontend SPA route for an individual spool. Override via
# field_map["url_template"] using {base_url} and {id} placeholders.
DEFAULT_URL_TEMPLATE = "{base_url}/spool/show/{id}"

DEFAULT_TIMEOUT_SECONDS = 10.0


class SpoolmanFilamentSource:
    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str | None = None,
        field_map: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.field_map = field_map or {}
        self._client = client

    @property
    def url_template(self) -> str:
        return self.field_map.get("url_template", DEFAULT_URL_TEMPLATE)

    def _headers(self) -> dict[str, str]:
        if self.auth_token:
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if self._client is not None:
            resp = await self._client.get(url, params=params, headers=self._headers())
        else:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def list_spools(self) -> list[ExternalFilament]:
        # Spoolman returns the full collection in one shot. Pass
        # allow_archived=true so a spool the user archived in Spoolman still
        # gets surfaced (and we mirror that state through the archive sweep
        # rather than letting it silently disappear from MakeTrack).
        data = await self._get_json("/api/v1/spool", params={"allow_archived": "true"})
        return [self._to_external(spool) for spool in data]

    def _to_external(self, spool: dict[str, Any]) -> ExternalFilament:
        filament = spool.get("filament") or {}
        vendor = filament.get("vendor") or {}
        external_id = str(spool["id"])
        external_url = self.url_template.format(base_url=self.base_url, id=external_id)
        color = filament.get("color_hex")
        return ExternalFilament(
            external_id=external_id,
            external_url=external_url,
            name=filament.get("name"),
            material=filament.get("material"),
            color_hex=f"#{color}" if color and not color.startswith("#") else color,
            brand=(vendor.get("name") if isinstance(vendor, dict) else None),
            diameter_mm=filament.get("diameter"),
            total_weight_g=filament.get("weight"),
            remaining_weight_g=spool.get("remaining_weight"),
        )

    async def health_check(self) -> bool:
        try:
            data = await self._get_json("/api/v1/health")
        except Exception:
            return False
        return isinstance(data, dict) and data.get("status") == "healthy"


def build_spoolman_source(
    source: ExternalSource,
    *,
    client: httpx.AsyncClient | None = None,
) -> SpoolmanFilamentSource:
    if not source.base_url:
        raise ValueError(f"external source {source.id} has no base_url configured")
    return SpoolmanFilamentSource(
        base_url=source.base_url,
        auth_token=source.auth_token,
        field_map=source.field_map,
        client=client,
    )
