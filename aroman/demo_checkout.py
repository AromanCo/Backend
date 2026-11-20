"""Price quotes for the fictional catalog in the test environment."""

from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.core.db import get_db
from aroman.models import Product, ProductVariant

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
