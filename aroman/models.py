import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aroman.core.db import AuditMixin, Base


def uuid_column():
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(AuditMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_column()
    mobile_e164: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="customer", server_default="customer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    __table_args__ = (CheckConstraint("role IN ('customer', 'admin')", name="ck_users_role"),)


class AuthChallenge(AuditMixin, Base):
    __tablename__ = "auth_challenges"
    id: Mapped[uuid.UUID] = uuid_column()
    mobile_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    delivery_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_challenge_attempts"),
        CheckConstraint(
            "delivery_status IN ('pending', 'accepted', 'rejected')",
            name="ck_challenge_delivery_status",
        ),
        Index(
            "uq_challenge_open_pending_mobile",
            "mobile_digest",
            unique=True,
            postgresql_where=text("delivery_status = 'pending' AND consumed_at IS NULL"),
            sqlite_where=text("delivery_status = 'pending' AND consumed_at IS NULL"),
        ),
    )


class AuthSession(AuditMixin, Base):
    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = uuid_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class AuthVerifyAttempt(Base):
    __tablename__ = "auth_verify_attempts"
    id: Mapped[uuid.UUID] = uuid_column()
    mobile_digest: Mapped[str] = mapped_column(String(64), index=True)
    requester_digest: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Brand(AuditMixin, Base):
    __tablename__ = "brands"
    id: Mapped[uuid.UUID] = uuid_column()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class FragranceFamily(AuditMixin, Base):
    __tablename__ = "fragrance_families"
    id: Mapped[uuid.UUID] = uuid_column()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class FragranceNote(AuditMixin, Base):
    __tablename__ = "fragrance_notes"
    id: Mapped[uuid.UUID] = uuid_column()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fragrance_families.id"), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    family: Mapped[FragranceFamily] = relationship()


class Product(AuditMixin, Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = uuid_column()
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id"), index=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fragrance_families.id"), index=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    brand: Mapped[Brand] = relationship()
    family: Mapped[FragranceFamily | None] = relationship()
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product")


class ProductVariant(AuditMixin, Base):
    __tablename__ = "product_variants"
    id: Mapped[uuid.UUID] = uuid_column()
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String(100), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    volume_ml: Mapped[int | None]
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    product: Mapped[Product] = relationship(back_populates="variants")
    __table_args__ = (CheckConstraint("volume_ml > 0", name="ck_variant_volume"),)


class FragranceConcept(AuditMixin, Base):
    __tablename__ = "fragrance_concepts"
    id: Mapped[uuid.UUID] = uuid_column()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    owner: Mapped[User] = relationship()
    notes: Mapped[list["ConceptNote"]] = relationship(
        back_populates="concept", cascade="all, delete-orphan"
    )


class ConceptNote(Base):
    __tablename__ = "concept_notes"
    id: Mapped[uuid.UUID] = uuid_column()
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fragrance_concepts.id", ondelete="CASCADE"), index=True
    )
    note_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fragrance_notes.id"), index=True)
    layer: Mapped[str] = mapped_column(String(8))
    position: Mapped[int] = mapped_column(Integer)
    concept: Mapped[FragranceConcept] = relationship(back_populates="notes")
    note: Mapped[FragranceNote] = relationship()
    __table_args__ = (
        CheckConstraint("layer IN ('top', 'heart', 'base')", name="ck_concept_note_layer"),
        CheckConstraint("position >= 0", name="ck_concept_note_position"),
        UniqueConstraint("concept_id", "note_id", name="uq_concept_note"),
        UniqueConstraint("concept_id", "layer", "position", name="uq_concept_position"),
    )


Index("ix_products_name", Product.name)
Index("ix_notes_name", FragranceNote.name)
