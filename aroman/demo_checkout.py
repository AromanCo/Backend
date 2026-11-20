"""Cart quotes and temporary orders for the fictional test catalog."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection, connect
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.authentication.api import current_session
from aroman.core.db import get_db, utcnow
from aroman.models import AuthSession, Product, ProductVariant

router = APIRouter(prefix="/demo-checkout", tags=["demo checkout"])

# Price fixtures in integer rials, keyed by the fictional product's seeded slug.
DEMO_UNIT_PRICES_IRR = {
    "aroman-garden-demo": 1_200_000,
    "mehr-citrus-demo": 1_100_000,
    "nava-wood-demo": 1_350_000,
    "nava-amber-demo": 1_450_000,
    "mehr-fresh-demo": 1_050_000,
    "nava-gourmand-demo": 1_300_000,
}


class CartLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: UUID
    quantity: Annotated[int, Field(strict=True, ge=1, le=10)]


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: Annotated[list[CartLine], Field(min_length=1, max_length=len(DEMO_UNIT_PRICES_IRR))]

    @model_validator(mode="after")
    def distinct_variants(self) -> Self:
        if len({item.variant_id for item in self.items}) != len(self.items):
            raise ValueError("Each variant may occur only once")
        return self


class QuoteLine(CartLine):
    product_id: UUID
    product_name: str
    variant_label: str
    unit_price: int
    line_total: int


class Quote(BaseModel):
    mode: Literal["demo"] = "demo"
    currency: Literal["IRR"] = "IRR"
    items: list[QuoteLine]
    subtotal: int


class OrderRequest(QuoteRequest):
    attempt_id: UUID
    expected_subtotal: Annotated[int, Field(strict=True, ge=1)]


OrderStatus = Literal["placed", "paid", "cancelled"]


class OrderEvent(BaseModel):
    status: OrderStatus
    occurred_at: datetime | None


class OrderReceipt(Quote):
    id: UUID
    created_at: datetime
    status: OrderStatus = "placed"
    events: list[OrderEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_legacy_events(self) -> Self:
        if not self.events:
            self.events = [OrderEvent(status="placed", occurred_at=self.created_at)]
            if self.status != "placed":
                self.events.append(OrderEvent(status=self.status, occurred_at=None))
        return self


class DemoOrders:
    """A SQLite sidecar for the isolated demo, separate from the catalog schema."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS demo_orders (
                    sequence INTEGER PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    order_id TEXT NOT NULL UNIQUE,
                    original TEXT NOT NULL,
                    receipt TEXT NOT NULL,
                    UNIQUE (owner_id, attempt_id)
                )
            """)

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[Connection]:
        with closing(connect(self.path)) as db, db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db


@router.post("/quote", response_model=Quote)
def quote(body: QuoteRequest, db: Session = Depends(get_db)) -> Quote:
    rows = db.execute(
        select(ProductVariant, Product)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            ProductVariant.id.in_([item.variant_id for item in body.items]),
            ProductVariant.is_demo.is_(True),
            Product.is_demo.is_(True),
        )
    )
    catalog = {
        variant.id: (variant, product)
        for variant, product in rows
        if product.slug in DEMO_UNIT_PRICES_IRR and variant.sku == f"{product.slug}-sample"
    }
    if len(catalog) != len(body.items):
        raise HTTPException(status_code=404, detail="Demo variant unavailable")

    items = []
    for item in body.items:
        variant, product = catalog[item.variant_id]
        unit_price = DEMO_UNIT_PRICES_IRR[product.slug]
        items.append(
            QuoteLine(
                variant_id=variant.id,
                quantity=item.quantity,
                product_id=product.id,
                product_name=product.name,
                variant_label=variant.label,
                unit_price=unit_price,
                line_total=unit_price * item.quantity,
            )
        )
    return Quote(items=items, subtotal=sum(item.line_total for item in items))


@router.post("/orders", response_model=OrderReceipt, status_code=201)
def submit_order(
    body: OrderRequest,
    request: Request,
    db: Session = Depends(get_db),
    session: AuthSession = Depends(current_session),
) -> OrderReceipt:
    store: DemoOrders = request.app.state.demo_orders
    key = (str(session.user_id), str(body.attempt_id))
    with store.transaction() as orders:
        previous = orders.execute(
            "SELECT original, receipt FROM demo_orders WHERE owner_id = ? AND attempt_id = ?", key
        ).fetchone()
        if previous is not None:
            original, receipt = previous
            if OrderRequest.model_validate_json(original) != body:
                raise HTTPException(409, "Order attempt already used for another cart")
            return OrderReceipt.model_validate_json(receipt)

        priced_cart = quote(body, db)
        if priced_cart.subtotal != body.expected_subtotal:
            raise HTTPException(409, "Demo quote changed")
        if orders.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0] >= 256:
            raise HTTPException(503, "Demo order capacity reached")
        receipt = OrderReceipt(id=uuid4(), created_at=utcnow(), **priced_cart.model_dump())
        orders.execute(
            "INSERT INTO demo_orders (owner_id, attempt_id, order_id, original, receipt) "
            "VALUES (?, ?, ?, ?, ?)",
            (*key, str(receipt.id), body.model_dump_json(), receipt.model_dump_json()),
        )
        return receipt


@router.get("/orders", response_model=list[OrderReceipt])
def list_orders(
    request: Request, session: AuthSession = Depends(current_session)
) -> list[OrderReceipt]:
    store: DemoOrders = request.app.state.demo_orders
    with store.transaction(write=False) as orders:
        rows = orders.execute(
            "SELECT receipt FROM demo_orders WHERE owner_id = ? ORDER BY sequence DESC",
            (str(session.user_id),),
        )
        return [OrderReceipt.model_validate_json(receipt) for (receipt,) in rows]


@router.post("/orders/{order_id}/actions/{action}", response_model=OrderReceipt)
def change_order_status(
    order_id: UUID,
    action: Literal["simulate-payment", "cancel"],
    request: Request,
    session: AuthSession = Depends(current_session),
) -> OrderReceipt:
    store: DemoOrders = request.app.state.demo_orders
    target = "paid" if action == "simulate-payment" else "cancelled"
    key = (str(session.user_id), str(order_id))
    with store.transaction() as orders:
        row = orders.execute(
            "SELECT receipt FROM demo_orders WHERE owner_id = ? AND order_id = ?", key
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Demo order not found")
        receipt = OrderReceipt.model_validate_json(row[0])
        if receipt.status == target:
            return receipt
        if receipt.status != "placed":
            raise HTTPException(409, "Demo order is no longer awaiting payment")
        changed = receipt.model_copy(update={
            "status": target,
            "events": [*receipt.events, OrderEvent(status=target, occurred_at=utcnow())],
        })
        orders.execute(
            "UPDATE demo_orders SET receipt = ? WHERE owner_id = ? AND order_id = ?",
            (changed.model_dump_json(), *key),
        )
        return changed
