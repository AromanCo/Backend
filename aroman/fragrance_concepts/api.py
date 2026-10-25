import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from aroman.authentication.api import current_session
from aroman.core.config import Settings, get_settings
from aroman.core.db import get_db
from aroman.core.pagination import PageParams
from aroman.models import AuthSession, ConceptNote, FragranceConcept, FragranceNote

router = APIRouter(prefix="/fragrance-concepts", tags=["fragrance concepts"])


class NoteSelection(BaseModel):
    note_id: uuid.UUID
    layer: Literal["top", "heart", "base"]
    position: int = Field(ge=0)


class ConceptInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: list[NoteSelection] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("Concept name must contain non-whitespace characters")
        return name

    @model_validator(mode="after")
    def unique_selections(self):
        if len({note.note_id for note in self.notes}) != len(self.notes):
            raise ValueError("Each note may be selected once")
        if len({(note.layer, note.position) for note in self.notes}) != len(self.notes):
            raise ValueError("Duplicate layer position")
        for layer in ("top", "heart", "base"):
            positions = sorted(note.position for note in self.notes if note.layer == layer)
            if positions != list(range(len(positions))):
                raise ValueError("Positions must start at zero and be contiguous within each layer")
        return self


class NoteSelectionOut(NoteSelection):
    pass


class ConceptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    notes: list[NoteSelectionOut]


def owned(
    db: Session, id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> FragranceConcept:
    statement = (
        select(FragranceConcept)
        .options(selectinload(FragranceConcept.notes))
        .where(FragranceConcept.id == id, FragranceConcept.owner_id == user_id)
    )
    if lock:
        statement = statement.with_for_update(of=FragranceConcept)
    concept = db.scalar(statement)
    if concept is None:
        raise HTTPException(404, "Concept not found")
    return concept


def set_notes(
    db: Session, concept: FragranceConcept, body: ConceptInput, settings: Settings
) -> None:
    if len(body.notes) > settings.max_concept_notes:
        raise HTTPException(422, f"Select at most {settings.max_concept_notes} notes")
    ids = {note.note_id for note in body.notes}
    if ids and set(db.scalars(select(FragranceNote.id).where(FragranceNote.id.in_(ids)))) != ids:
        raise HTTPException(422, "Unknown fragrance note")
    concept.name = body.name
    concept.notes = [
        ConceptNote(note_id=n.note_id, layer=n.layer, position=n.position) for n in body.notes
    ]


@router.post("", response_model=ConceptOut, status_code=201)
def create(
    body: ConceptInput,
    db: Session = Depends(get_db),
    session: AuthSession = Depends(current_session),
    settings: Settings = Depends(get_settings),
):
    concept = FragranceConcept(owner_id=session.user_id, name=body.name)
    set_notes(db, concept, body, settings)
    db.add(concept)
    db.commit()
    db.refresh(concept)
    return owned(db, concept.id, session.user_id)


@router.get("", response_model=list[ConceptOut])
def list_concepts(
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    session: AuthSession = Depends(current_session),
):
    return db.scalars(
        select(FragranceConcept)
        .options(selectinload(FragranceConcept.notes))
        .where(FragranceConcept.owner_id == session.user_id)
        .order_by(FragranceConcept.created_at.desc(), FragranceConcept.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    ).all()


@router.get("/{id}", response_model=ConceptOut)
def get_concept(
    id: uuid.UUID, db: Session = Depends(get_db), session: AuthSession = Depends(current_session)
):
    return owned(db, id, session.user_id)


@router.put("/{id}", response_model=ConceptOut)
def update(
    id: uuid.UUID,
    body: ConceptInput,
    db: Session = Depends(get_db),
    session: AuthSession = Depends(current_session),
    settings: Settings = Depends(get_settings),
):
    concept = owned(db, id, session.user_id, lock=True)
    concept.notes.clear()
    db.flush()
    set_notes(db, concept, body, settings)
    db.commit()
    return owned(db, id, session.user_id)


@router.post("/{id}/duplicate", response_model=ConceptOut, status_code=201)
def duplicate(
    id: uuid.UUID, db: Session = Depends(get_db), session: AuthSession = Depends(current_session)
):
    source = owned(db, id, session.user_id, lock=True)
    copy = FragranceConcept(
        owner_id=session.user_id,
        name=source.name[:113] + " (کپی)",
        notes=[
            ConceptNote(note_id=n.note_id, layer=n.layer, position=n.position) for n in source.notes
        ],
    )
    db.add(copy)
    db.commit()
    return owned(db, copy.id, session.user_id)


@router.delete("/{id}", status_code=204)
def delete(
    id: uuid.UUID, db: Session = Depends(get_db), session: AuthSession = Depends(current_session)
):
    db.delete(owned(db, id, session.user_id, lock=True))
    db.commit()
