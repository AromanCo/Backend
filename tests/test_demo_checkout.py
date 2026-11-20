from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aroman.core.config import Settings
from aroman.demo_checkout import DemoOrders, OrderReceipt, router
from aroman.exploration_api import app as showcase_app
from tests.conftest import login

PATH = "/api/v1/demo-checkout/quote"
ORDERS = "/api/v1/demo-checkout/orders"


@pytest.fixture
def quote_client(tmp_path):
    app = FastAPI()
    app.state.demo_orders = DemoOrders(tmp_path / "demo.orders")
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def order_customer(client):
    with TestClient(client.app, client=("198.51.100.28", 47000)) as customer:
        yield customer


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
    assert ORDERS not in client.get("/openapi.json").json()["paths"]
    assert ORDERS not in showcase_app.openapi()["paths"]


def test_order_requires_session_and_csrf_and_replays_same_receipt(
    order_customer, quote_client, sms
):
    lines = seeded_cart(order_customer)
    body = {"items": lines, "attempt_id": str(uuid4()), "expected_subtotal": 3_900_000}
    origin = {"Origin": "http://localhost:3000"}
    assert quote_client.post(ORDERS, json=body, headers=origin).status_code == 401
    assert quote_client.get(ORDERS).status_code == 401

    token = login(order_customer, sms, "09990000081")
    quote_client.cookies.update(order_customer.cookies)
    assert quote_client.get(ORDERS).json() == []
    assert quote_client.post(ORDERS, json=body, headers=origin).status_code == 403
    headers = {**origin, "X-CSRF-Token": token}
    stale = {**body, "expected_subtotal": 1}
    assert quote_client.post(ORDERS, json=stale, headers=headers).status_code == 409

    created = quote_client.post(ORDERS, json=body, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "placed"
    assert created.json()["subtotal"] == 3_900_000
    assert created.json()["events"] == [
        {"status": "placed", "occurred_at": created.json()["created_at"]}
    ]
    assert quote_client.post(ORDERS, json=body, headers=headers).json() == created.json()
    assert quote_client.post(ORDERS, json=stale, headers=headers).status_code == 409
    assert quote_client.get(ORDERS).json() == [created.json()]
    second = quote_client.post(
        ORDERS, json={**body, "attempt_id": str(uuid4())}, headers=headers
    )
    assert second.status_code == 201
    assert quote_client.get(ORDERS).json() == [second.json(), created.json()]
    paid_url = f"{ORDERS}/{created.json()['id']}/actions/simulate-payment"
    cancel_url = f"{ORDERS}/{created.json()['id']}/actions/cancel"
    assert quote_client.post(paid_url, headers=origin).status_code == 403
    paid = quote_client.post(paid_url, headers=headers)
    assert paid.status_code == 200
    paid_event = paid.json()["events"][-1]
    assert paid_event["status"] == "paid" and paid_event["occurred_at"]
    assert paid.json() == {
        **created.json(), "status": "paid", "events": [*created.json()["events"], paid_event]
    }
    assert quote_client.post(paid_url, headers=headers).json() == paid.json()
    assert quote_client.post(cancel_url, headers=headers).status_code == 409
    assert quote_client.post(ORDERS, json=body, headers=headers).json() == paid.json()

    second_path = f"{ORDERS}/{second.json()['id']}/actions"
    cancelled = quote_client.post(f"{second_path}/cancel", headers=headers)
    assert cancelled.status_code == 200
    cancel_event = cancelled.json()["events"][-1]
    assert cancel_event["status"] == "cancelled" and cancel_event["occurred_at"]
    assert cancelled.json() == {
        **second.json(), "status": "cancelled", "events": [*second.json()["events"], cancel_event]
    }
    assert quote_client.post(f"{second_path}/cancel", headers=headers).json() == cancelled.json()
    assert quote_client.post(f"{second_path}/simulate-payment", headers=headers).status_code == 409
    assert quote_client.get(ORDERS).json() == [cancelled.json(), paid.json()]
    for final in [cancelled.json(), paid.json()]:
        previous_format = {key: value for key, value in final.items() if key != "events"}
        events = OrderReceipt.model_validate(previous_format).model_dump(mode="json")["events"]
        assert events == [
            {"status": "placed", "occurred_at": final["created_at"]},
            {"status": final["status"], "occurred_at": None},
        ]
    reopened = FastAPI()
    reopened.state.demo_orders = DemoOrders(quote_client.app.state.demo_orders.path)
    reopened.include_router(router, prefix="/api/v1")
    with TestClient(reopened, cookies=quote_client.cookies) as restarted:
        assert restarted.get(ORDERS).json() == [cancelled.json(), paid.json()]
        assert restarted.post(ORDERS, json=body, headers=headers).json() == paid.json()

    token = login(order_customer, sms, "09990000082")
    quote_client.cookies.update(order_customer.cookies)
    assert quote_client.get(ORDERS).json() == []
    assert quote_client.post(paid_url, headers={**origin, "X-CSRF-Token": token}).status_code == 404
    other = quote_client.post(ORDERS, json=body, headers={**origin, "X-CSRF-Token": token})
    assert other.status_code == 201, other.text
    assert other.json()["id"] != created.json()["id"]
    assert quote_client.get(ORDERS).json() == [other.json()]


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_rejects_non_test_opt_in(environment):
    with pytest.raises(ValidationError, match="Demo checkout is available only in the test"):
        Settings(environment=environment, demo_checkout_enabled=True)
