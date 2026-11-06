import json

import httpx
import pytest

from paperless_ai_extract.adapters.paperless import PaperlessClient
from paperless_ai_extract.config import PaperlessConfig
from paperless_ai_extract.domain.errors import StoreError


class Api:
    def __init__(self, routes):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        key = (request.method, request.url.path)
        route = self.routes.get(key)
        if route is None:
            return httpx.Response(404, json={"detail": "not found"})
        return route(request) if callable(route) else httpx.Response(200, json=route)


def client(routes):
    api = Api(routes)
    return PaperlessClient(PaperlessConfig(url="http://p/", token="t"), httpx.MockTransport(api)), api


def test_headers_and_document_mapping():
    paperless, api = client({("GET", "/api/documents/7/"): {
        "id": 7, "title": "T", "original_file_name": "a.pdf", "correspondent": None,
        "document_type": 3, "storage_path": None, "created": "2026-01-02", "tags": [1],
        "content": "text", "custom_fields": [{"field": 1, "value": "opt"}], "notes": []}})
    doc = paperless.document(7)
    assert doc.custom_fields == {1: "opt"} and doc.document_type == 3 and doc.created == "2026-01-02"
    headers = api.requests[0].headers
    assert headers["authorization"] == "Token t" and headers["accept"] == "application/json; version=10"


def test_taxonomy_follows_pagination():
    def correspondents(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={
            "results": [{"id": page, "name": f"C{page}", "owner": None}],
            "next": "http://p/next" if page == 1 else None})
    empty = {"results": [], "next": None}
    paperless, _ = client({("GET", "/api/correspondents/"): correspondents,
                           ("GET", "/api/document_types/"): empty,
                           ("GET", "/api/storage_paths/"): empty,
                           ("GET", "/api/tags/"): empty,
                           ("GET", "/api/custom_fields/"): empty})
    assert [c.name for c in paperless.taxonomy().correspondents] == ["C1", "C2"]


def test_writes_use_partial_and_additive_endpoints():
    ok = httpx.Response(200, json="OK")
    paperless, api = client({("PATCH", "/api/documents/7/"): {"id": 7},
                             ("POST", "/api/documents/bulk_edit/"): lambda r: ok,
                             ("POST", "/api/documents/7/notes/"): [],
                             ("POST", "/api/correspondents/"): {"id": 9, "name": "N", "owner": None}})
    paperless.update_document(7, {"title": "x"})
    paperless.set_custom_fields(7, {1: "opt"})
    paperless.modify_tags(7, [1], [2])
    paperless.add_note(7, "hello")
    item = paperless.create_object("correspondents", "N")
    bodies = [json.loads(r.content) for r in api.requests]
    assert bodies[0] == {"title": "x"}
    assert bodies[1]["method"] == "modify_custom_fields"
    assert bodies[1]["parameters"] == {"add_custom_fields": {"1": "opt"}, "remove_custom_fields": []}
    assert bodies[2]["parameters"] == {"add_tags": [1], "remove_tags": [2]}
    assert bodies[3] == {"note": "hello"}
    assert bodies[4] == {"name": "N", "owner": None} and item.id == 9


def test_empty_writes_are_skipped():
    paperless, api = client({})
    paperless.update_document(7, {})
    paperless.set_custom_fields(7, {})
    paperless.modify_tags(7, [], [])
    assert api.requests == []


def test_checksum_prefers_archive_unless_original():
    meta = {"original_checksum": "o", "archive_checksum": "a"}
    paperless, _ = client({("GET", "/api/documents/7/metadata/"): meta})
    assert paperless.checksum(7, original=False) == "a"
    assert paperless.checksum(7, original=True) == "o"


def test_http_errors_become_store_errors():
    paperless, _ = client({})
    with pytest.raises(StoreError, match="404"):
        paperless.document(1)
