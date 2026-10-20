import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.core.db import get_db
from aroman.core.pagination import PageParams
from aroman.core.schemas import NamedDemoOut
from aroman.models import Product, ProductVariant

router = APIRouter(tags=["catalog"])


class ProductOut(NamedDemoOut):
    brand_id: uuid.UUID
    family_id: uuid.UUID | None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    label: str
    volume_ml: int | None
    is_demo: bool


@router.get("/products", response_model=list[ProductOut])
def products(
    q: str | None = Query(None, max_length=100),
    brand_id: uuid.UUID | None = None,
    family_id: uuid.UUID | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    stmt = select(Product).order_by(Product.name, Product.id)
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    if brand_id:
        stmt = stmt.where(Product.brand_id == brand_id)
    if family_id:
        stmt = stmt.where(Product.family_id == family_id)
    return db.scalars(stmt.limit(page.limit).offset(page.offset)).all()


@router.get("/products/{product_id}/variants", response_model=list[VariantOut])
def variants(product_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.scalars(
        select(ProductVariant)
        .where(ProductVariant.product_id == product_id)
        .order_by(ProductVariant.label)
    ).all()
