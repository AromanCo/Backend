"""Cart quotes and temporary orders for the fictional test catalog."""

from threading import Lock
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.authentication.api import current_session
from aroman.core.db import get_db
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


class OrderReceipt(Quote):
    id: UUID
    status: Literal["placed"] = "placed"


class DemoOrders:
    """One bounded order store for the lifetime of a test API process."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.orders: dict[tuple[UUID, UUID], tuple[OrderRequest, OrderReceipt]] = {}


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
    key = (session.user_id, body.attempt_id)
    with store.lock:
        previous = store.orders.get(key)
        if previous is not None:
            original, receipt = previous
            if original != body:
                raise HTTPException(409, "Order attempt already used for another cart")
            return receipt

        priced_cart = quote(body, db)
        if priced_cart.subtotal != body.expected_subtotal:
            raise HTTPException(409, "Demo quote changed")
        if len(store.orders) >= 256:
            raise HTTPException(503, "Demo order capacity reached")
        receipt = OrderReceipt(id=uuid4(), **priced_cart.model_dump())
        store.orders[key] = (body, receipt)
        return receipt
