from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.core.db import get_db
from aroman.core.pagination import PageParams
from aroman.core.schemas import NamedDemoOut
from aroman.models import Brand

router = APIRouter(tags=["brands"])


@router.get("/brands", response_model=list[NamedDemoOut])
def brands(
    q: str | None = Query(None, max_length=100),
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    stmt = select(Brand).order_by(Brand.name, Brand.id)
    if q:
        stmt = stmt.where(Brand.name.ilike(f"%{q}%"))
    return db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
