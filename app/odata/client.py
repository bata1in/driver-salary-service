from __future__ import annotations

from typing import Any, Dict, Iterator, Optional
from urllib.parse import urljoin

import httpx


class ODataError(RuntimeError):
    pass


class ODataClient:
    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_tls: bool = True,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        auth = (username, password) if username and password else None
        self._client = httpx.Client(auth=auth, verify=verify_tls, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ODataClient":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = urljoin(self.base_url, path.lstrip("/"))
        response = self._client.get(url, params=params, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise ODataError(f"OData GET {url} failed: {response.status_code} {response.text[:500]}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ODataError(f"OData GET {url} returned non-object JSON")
        return payload

    def iter_entities(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
        page_size: int = 100,
    ) -> Iterator[Dict[str, Any]]:
        base_query = dict(params or {})
        base_query.setdefault("$top", page_size)
        skip = int(base_query.get("$skip", 0) or 0)
        query = dict(base_query)
        query.setdefault("$skip", skip)
        next_path: Optional[str] = entity

        while next_path:
            payload = self.get(next_path, query if next_path == entity else None)
            values = payload.get("value")
            if values is None and "d" in payload:
                values = payload["d"].get("results", payload["d"])
            if isinstance(values, dict):
                values = [values]
            if not isinstance(values, list):
                raise ODataError(f"OData entity {entity} has no value list")
            for item in values:
                if isinstance(item, dict):
                    yield item
            next_link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
            if next_link and next_link.startswith(self.base_url):
                next_path = next_link[len(self.base_url) :]
                query = {}
            elif next_link:
                next_path = next_link
                query = {}
            elif next_path == entity and len(values) >= int(base_query["$top"]):
                skip += int(base_query["$top"])
                query = dict(base_query)
                query["$skip"] = skip
            else:
                next_path = None
