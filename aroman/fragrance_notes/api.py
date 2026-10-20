import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.core.db import get_db
from aroman.core.pagination import PageParams
from aroman.core.schemas import NamedDemoOut
from aroman.models import FragranceFamily, FragranceNote

router = APIRouter(tags=["fragrance notes"])


class NoteOut(NamedDemoOut):
    family_id: uuid.UUID


@router.get("/fragrance-families", response_model=list[NamedDemoOut])
def families(
    q: str | None = Query(None, max_length=100),
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    stmt = select(FragranceFamily).order_by(FragranceFamily.name, FragranceFamily.id)
    if q:
        stmt = stmt.where(FragranceFamily.name.ilike(f"%{q}%"))
    return db.scalars(stmt.limit(page.limit).offset(page.offset)).all()


@router.get("/fragrance-notes", response_model=list[NoteOut])
def notes(
    q: str | None = Query(None, max_length=100),
    family_id: uuid.UUID | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    stmt = select(FragranceNote).order_by(FragranceNote.name, FragranceNote.id)
    if q:
        stmt = stmt.where(FragranceNote.name.ilike(f"%{q}%"))
    if family_id:
        stmt = stmt.where(FragranceNote.family_id == family_id)
    return db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
