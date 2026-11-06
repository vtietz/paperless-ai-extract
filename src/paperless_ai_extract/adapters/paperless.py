"""Paperless-ngx REST adapter (documented endpoints only, API version 10)."""
from __future__ import annotations

import httpx

from ..config import PaperlessConfig
from ..domain.errors import StoreError
from ..domain.models import DocumentSnapshot, Item, Taxonomy

API_VERSION = "10"


def snapshot_from_api(data: dict) -> DocumentSnapshot:
    return DocumentSnapshot(
        id=data["id"], title=data.get("title") or "",
        original_file_name=data.get("original_file_name"),
        correspondent=data.get("correspondent"),
        document_type=data.get("document_type"),
        storage_path=data.get("storage_path"),
        created=data.get("created"),
        tags=list(data.get("tags") or []),
        content=data.get("content") or "",
        custom_fields={cf["field"]: cf.get("value") for cf in data.get("custom_fields") or []},
    )


class PaperlessClient:
    def __init__(self, config: PaperlessConfig, transport: httpx.BaseTransport | None = None):
        headers = {"Authorization": f"Token {config.resolved_token()}",
                   "Accept": f"application/json; version={API_VERSION}",
                   **config.headers}
        self.http = httpx.Client(base_url=config.url.rstrip("/"), headers=headers,
                                 timeout=config.timeout, verify=config.verify_tls,
                                 transport=transport)

    # -- transport helpers -------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise StoreError(f"{method} {path} failed: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise StoreError(f"{method} {path} HTTP {response.status_code}: {response.text[:300]}")
        return response

    def _json(self, method: str, path: str, **kwargs):
        response = self._request(method, path, **kwargs)
        return response.json() if response.content else None

    def _all(self, path: str) -> list[dict]:
        results, page = [], 1
        while True:
            data = self._json("GET", path, params={"page": page, "page_size": 100})
            results.extend(data.get("results", []))
            if not data.get("next"):
                return results
            page += 1

    # -- reads -------------------------------------------------------------
    def ping(self) -> None:
        self._json("GET", "/api/documents/", params={"page_size": 1, "fields": "id"})

    def taxonomy(self) -> Taxonomy:
        def items(path: str) -> list[Item]:
            return [Item(o["id"], o["name"], o.get("owner"), bool(o.get("is_inbox_tag")))
                    for o in self._all(path)]
        return Taxonomy(
            correspondents=items("/api/correspondents/"),
            document_types=items("/api/document_types/"),
            storage_paths=items("/api/storage_paths/"),
            tags=items("/api/tags/"),
            custom_fields=self._all("/api/custom_fields/"),
        )

    def document_ids_with_tag(self, tag_id: int) -> list[int]:
        """All documents carrying the tag, oldest first (IDs only, paginated)."""
        ids, page = [], 1
        while True:
            data = self._json("GET", "/api/documents/", params={
                "tags__id__all": tag_id, "ordering": "added", "fields": "id",
                "page": page, "page_size": 100})
            ids += [d["id"] for d in data.get("results", [])]
            if not data.get("next"):
                return ids
            page += 1

    def document(self, doc_id: int) -> DocumentSnapshot:
        return snapshot_from_api(self._json("GET", f"/api/documents/{doc_id}/"))

    def checksum(self, doc_id: int, original: bool) -> str:
        meta = self._json("GET", f"/api/documents/{doc_id}/metadata/") or {}
        archive = None if original else meta.get("archive_checksum")
        return archive or meta.get("original_checksum") or ""

    def download(self, doc_id: int, original: bool) -> tuple[bytes, str]:
        params = {"original": "true"} if original else {}
        response = self._request("GET", f"/api/documents/{doc_id}/download/", params=params)
        return response.content, response.headers.get("content-type", "")

    # -- writes ------------------------------------------------------------
    def create_object(self, endpoint: str, name: str) -> Item:
        # Explicit owner null: shared taxonomy, as Paperless's AI workflow creates it.
        data = self._json("POST", f"/api/{endpoint}/", json={"name": name[:128], "owner": None})
        return Item(data["id"], data["name"], data.get("owner"))

    def update_document(self, doc_id: int, fields: dict) -> None:
        if fields:
            self._json("PATCH", f"/api/documents/{doc_id}/", json=fields)

    def set_custom_fields(self, doc_id: int, values: dict[int, object]) -> None:
        """Additive: other custom field instances are left untouched."""
        if values:
            self._bulk(doc_id, "modify_custom_fields", {
                "add_custom_fields": {str(k): v for k, v in values.items()},
                "remove_custom_fields": []})

    def modify_tags(self, doc_id: int, add: list[int], remove: list[int]) -> None:
        if add or remove:
            self._bulk(doc_id, "modify_tags", {"add_tags": add, "remove_tags": remove})

    def add_note(self, doc_id: int, text: str) -> None:
        self._json("POST", f"/api/documents/{doc_id}/notes/", json={"note": text})

    def _bulk(self, doc_id: int, method: str, parameters: dict) -> None:
        self._json("POST", "/api/documents/bulk_edit/",
                   json={"documents": [doc_id], "method": method, "parameters": parameters})
