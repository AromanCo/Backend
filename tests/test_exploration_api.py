import uuid

import pytest
from fastapi import APIRouter, WebSocket
from fastapi import routing as fastapi_routing
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from aroman import exploration_api
from aroman.core.db import get_engine
from aroman.exploration_api import app as exploration_app
from aroman.exploration_api import create_exploration_app, validate_public_routes
from aroman.main import app as internal_app
from aroman.models import AuthChallenge, AuthSession, ConceptNote, FragranceConcept


@pytest.fixture
def public_client():
    with TestClient(exploration_app) as value:
        yield value


def test_public_catalog_routes_and_existing_filters(public_client):
    brands = public_client.get("/api/v1/brands?q=آرومان&limit=1&offset=0")
    assert brands.status_code == 200
    assert len(brands.json()) == 1 and brands.json()[0]["is_demo"]

    products = public_client.get(
        "/api/v1/products", params={"brand_id": brands.json()[0]["id"]}
    )
    assert products.status_code == 200 and len(products.json()) == 1
    product = products.json()[0]
    assert public_client.get("/api/v1/products", params={"q": product["name"]}).json()
    variants = public_client.get(f"/api/v1/products/{product['id']}/variants")
    assert variants.status_code == 200 and variants.json()[0]["is_demo"]
    assert public_client.get("/api/v1/products/not-a-uuid/variants").status_code == 422

    families = public_client.get("/api/v1/fragrance-families?q=")
    notes = public_client.get("/api/v1/fragrance-notes", params={"limit": 2})
    assert families.status_code == 200 and families.json()
    assert notes.status_code == 200 and len(notes.json()) == 2
    family_id = notes.json()[0]["family_id"]
    assert all(
        note["family_id"] == family_id
        for note in public_client.get(
            "/api/v1/fragrance-notes", params={"family_id": family_id}
        ).json()
    )


def test_route_registry_compatibility_without_context_helper(monkeypatch):
    monkeypatch.setattr(exploration_api.fastapi.routing, "iter_route_contexts", None)
    isolated_app = create_exploration_app()
    with TestClient(isolated_app) as client:
        assert client.get("/api/v1/brands").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/challenges"),
        ("POST", "/api/v1/auth/verify"),
        ("GET", "/api/v1/auth/session"),
        ("GET", "/api/v1/auth/csrf"),
        ("GET", "/api/v1/users/me"),
        ("GET", "/api/v1/fragrance-concepts"),
        ("POST", "/api/v1/fragrance-concepts"),
        ("PUT", "/api/v1/fragrance-concepts/00000000-0000-0000-0000-000000000001"),
        ("DELETE", "/api/v1/fragrance-concepts/00000000-0000-0000-0000-000000000001"),
        ("POST", "/api/v1/fragrance-concepts/00000000-0000-0000-0000-000000000001/duplicate"),
        ("GET", "/docs"),
        ("GET", "/redoc"),
        ("GET", "/openapi.json"),
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/api/v1/admin/users"),
        ("GET", "/api/v1/unknown"),
    ],
)
def test_private_and_unknown_routes_are_denied_without_side_effects(
    public_client, method, path, sms
):
    before = _private_state()
    response = public_client.request(method, path, json={"mobile": "09121234567"})
    assert response.status_code in {404, 405}
    assert _private_state() == before
    assert sms.messages == []


def _private_state():
    with Session(get_engine()) as db:
        return (
            db.scalar(select(func.count()).select_from(AuthChallenge)),
            db.scalar(select(func.count()).select_from(AuthSession)),
            db.scalar(select(func.count()).select_from(FragranceConcept)),
            db.scalar(select(func.count()).select_from(ConceptNote)),
        )


@pytest.mark.parametrize("path", [
    "/api/v1/brands",
    "/api/v1/products",
    "/api/v1/products/00000000-0000-0000-0000-000000000001/variants",
    "/api/v1/fragrance-families",
    "/api/v1/fragrance-notes",
])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_catalog_paths_reject_all_non_get_methods(public_client, path, method):
    before = _private_state()
    response = public_client.request(method, path, json={"name": "must-not-write"})
    assert response.status_code in {404, 405}
    assert _private_state() == before


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/brands/",
        "/api//v1/brands",
        "/api/v1/products/00000000-0000-0000-0000-000000000001/variants/extra",
        "/api/v1/products/00000000-0000-0000-0000-000000000001/variants/nested",
        "/api/v1/products/%2F/variants",
        "/api/v1/products/%252F/variants",
        "/api/v1/products/%2e%2e/variants",
        "/api/v1/products/%5c/variants",
    ],
)
def test_path_normalization_and_suffixes_do_not_bypass_boundary(public_client, path):
    before = _private_state()
    response = public_client.get(path)
    assert response.status_code in {404, 405, 422}
    assert _private_state() == before


def test_exact_origin_credentialed_cors_and_options_policy(public_client):
    allowed = public_client.get(
        "/api/v1/brands", headers={"Origin": "http://localhost:3000"}
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    denied = public_client.get(
        "/api/v1/brands", headers={"Origin": "https://untrusted.example"}
    )
    assert "access-control-allow-origin" not in denied.headers
    preflight = public_client.options(
        "/api/v1/brands",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code in {404, 405}


def test_registry_drift_fails_construction_and_runtime_attachment_is_denied():
    extra_router = APIRouter()
    handler_calls = 0

    @extra_router.get("/unexpected")
    def unexpected():
        nonlocal handler_calls
        handler_calls += 1
        return {"private": True}

    with pytest.raises(RuntimeError, match="route registry drift"):
        create_exploration_app([extra_router])

    # Simulate a later accidental include on an isolated instance. Drift blocks
    # both the unexpected handler and previously approved catalog routes.
    isolated_app = create_exploration_app()
    isolated_app.include_router(extra_router, prefix="/api/v1")
    with TestClient(isolated_app) as client:
        unexpected_response = client.get("/api/v1/unexpected")
        approved_response = client.get("/api/v1/brands")
    assert unexpected_response.status_code == 404
    assert approved_response.status_code == 404
    assert handler_calls == 0


def test_duplicate_route_registration_is_rejected():
    duplicate_router = APIRouter()

    @duplicate_router.get("/brands")
    def duplicate_brands():
        return []

    isolated_app = create_exploration_app()
    isolated_app.include_router(duplicate_router, prefix="/api/v1")
    with pytest.raises(RuntimeError, match="route registry drift"):
        validate_public_routes(isolated_app)


def test_unexpected_websocket_registration_is_rejected_without_handler_call():
    websocket_router = APIRouter()
    handler_calls = 0

    @websocket_router.websocket("/private-socket")
    async def private_socket(websocket: WebSocket):
        nonlocal handler_calls
        handler_calls += 1
        await websocket.accept()

    isolated_app = create_exploration_app()
    isolated_app.include_router(websocket_router, prefix="/api/v1")
    with TestClient(isolated_app) as client:
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with client.websocket_connect("/api/v1/private-socket"):
                pass
        approved_response = client.get("/api/v1/brands")
    assert disconnected.value.code == 1008
    assert approved_response.status_code == 404
    assert handler_calls == 0


def test_internal_app_still_registers_private_development_routes():
    context_iterator = getattr(fastapi_routing, "iter_route_contexts", None)
    contexts = context_iterator(internal_app.routes) if context_iterator else internal_app.routes
    paths = {getattr(route, "path", "") for route in contexts}
    assert "/api/v1/auth/challenges" in paths
    assert "/api/v1/auth/verify" in paths
    assert "/api/v1/auth/session" in paths
    assert "/api/v1/auth/csrf" in paths
    assert "/api/v1/users/me" in paths
    assert "/api/v1/fragrance-concepts" in paths
    assert "/api/v1/fragrance-concepts/{id}/duplicate" in paths
    assert "/api/v1/fragrance-concepts/{id}" in paths


def test_valid_variant_id_remains_uuid_validated(public_client):
    response = public_client.get(f"/api/v1/products/{uuid.uuid4()}/variants")
    assert response.status_code == 200
