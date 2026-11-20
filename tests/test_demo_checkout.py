from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aroman.core.config import Settings
from aroman.demo_checkout import router
from aroman.exploration_api import app as showcase_app

PATH = "/api/v1/demo-checkout/quote"


@pytest.fixture
def quote_client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client


def seeded_cart(client):
    products = client.get("/api/v1/products").json()
    lines = []
    for slug, quantity in (("nava-wood-demo", 2), ("aroman-garden-demo", 1)):
        product = next(item for item in products if item["slug"] == slug)
        variants = client.get(f"/api/v1/products/{product['id']}/variants").json()
        lines.append({"variant_id": variants[0]["id"], "quantity": quantity})
    return lines


def test_quotes_seeded_variants_in_request_order(client, quote_client):
    lines = seeded_cart(client)
    response = quote_client.post(PATH, json={"items": lines})
    assert response.status_code == 200, response.text
    quote = response.json()
    assert quote["mode"] == "demo"
    assert quote["currency"] == "IRR"
    assert [item["variant_id"] for item in quote["items"]] == [
        line["variant_id"] for line in lines
    ]
    assert [item["unit_price"] for item in quote["items"]] == [1_350_000, 1_200_000]
    assert [item["line_total"] for item in quote["items"]] == [2_700_000, 1_200_000]
    assert quote["subtotal"] == 3_900_000


def test_unknown_variant_rejects_the_entire_quote(client, quote_client):
    lines = seeded_cart(client)
    lines[1]["variant_id"] = str(uuid4())
    assert quote_client.post(PATH, json={"items": lines}).status_code == 404


@pytest.mark.parametrize(
    "changes", [{"quantity": 0}, {"quantity": 11}, {"quantity": "2"}, {"unit_price": 1}]
)
def test_rejects_invalid_quantities_and_client_prices(client, quote_client, changes):
    line = {**seeded_cart(client)[0], **changes}
    assert quote_client.post(PATH, json={"items": [line]}).status_code == 422


def test_does_not_accept_duplicate_items(client, quote_client):
    line = seeded_cart(client)[0]
    assert quote_client.post(PATH, json={"items": [line, line]}).status_code == 422


def test_default_api_and_showcase_omit_the_route(client):
    assert PATH not in client.get("/openapi.json").json()["paths"]
    assert PATH not in showcase_app.openapi()["paths"]


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_rejects_non_test_opt_in(environment):
    with pytest.raises(ValidationError, match="Demo checkout is available only in the test"):
        Settings(environment=environment, demo_checkout_enabled=True)
