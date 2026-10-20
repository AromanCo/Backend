"""Clearly fictional catalog records for local demonstrations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.core.db import get_engine
from aroman.models import Brand, FragranceFamily, FragranceNote, Product, ProductVariant

FAMILIES = [
    ("floral", "گلی", "برداشت مفهومی از رایحه گل‌ها"),
    ("citrus", "مرکباتی", "برداشت مفهومی از مرکبات"),
    ("woody", "چوبی", "برداشت مفهومی از چوب‌ها"),
    ("amber", "کهربایی", "برداشت مفهومی گرم"),
    ("fresh", "تازه", "برداشت مفهومی تازه"),
    ("gourmand", "خوراکی", "برداشت مفهومی شیرین"),
]
NOTES = [
    ("rose", "رز", "floral"),
    ("jasmine", "یاس", "floral"),
    ("orange-blossom", "شکوفه پرتقال", "floral"),
    ("violet", "بنفشه", "floral"),
    ("iris", "زنبق", "floral"),
    ("lavender", "اسطوخودوس", "floral"),
    ("bergamot", "ترنج", "citrus"),
    ("lemon", "لیمو", "citrus"),
    ("mandarin", "نارنگی", "citrus"),
    ("grapefruit", "گریپ‌فروت", "citrus"),
    ("cedar", "سدر", "woody"),
    ("sandalwood", "چوب صندل", "woody"),
    ("vetiver", "وتیور", "woody"),
    ("pine", "کاج", "woody"),
    ("amber", "کهربا", "amber"),
    ("vanilla", "وانیل", "amber"),
    ("incense", "بخور", "amber"),
    ("saffron", "زعفران", "amber"),
    ("mint", "نعناع", "fresh"),
    ("green-tea", "چای سبز", "fresh"),
    ("sea-breeze", "نسیم دریا", "fresh"),
    ("rain", "باران", "fresh"),
    ("cocoa", "کاکائو", "gourmand"),
    ("coffee", "قهوه", "gourmand"),
]
BRANDS = [
    ("aroman-demo", "آرومان — نمونه"),
    ("mehr-demo", "مهر — برند خیالی"),
    ("nava-demo", "نوا — برند خیالی"),
]
PRODUCTS = [
    ("aroman-garden-demo", "باغ آرومان — نمونه", "aroman-demo", "floral"),
    ("mehr-citrus-demo", "صبح مهر — نمونه", "mehr-demo", "citrus"),
    ("nava-wood-demo", "چوب نوا — نمونه", "nava-demo", "woody"),
]


def seed(db: Session) -> None:
    for slug, name, description in FAMILIES:
        if not db.scalar(select(FragranceFamily.id).where(FragranceFamily.slug == slug)):
            db.add(FragranceFamily(slug=slug, name=name, description=description, is_demo=True))
    db.flush()
    families = {f.slug: f for f in db.scalars(select(FragranceFamily))}
    for slug, name, family in NOTES:
        if not db.scalar(select(FragranceNote.id).where(FragranceNote.slug == slug)):
            db.add(FragranceNote(slug=slug, name=name, family_id=families[family].id, is_demo=True))
    for slug, name in BRANDS:
        if not db.scalar(select(Brand.id).where(Brand.slug == slug)):
            db.add(
                Brand(
                    slug=slug, name=name, is_demo=True, description="رکورد نمایشی؛ برند واقعی نیست."
                )
            )
    db.flush()
    brands = {b.slug: b for b in db.scalars(select(Brand))}
    for slug, name, brand, family in PRODUCTS:
        if not db.scalar(select(Product.id).where(Product.slug == slug)):
            product = Product(
                slug=slug,
                name=name,
                description="محصول نمایشی؛ موجودی و ادعای عملکرد ندارد.",
                brand_id=brands[brand].id,
                family_id=families[family].id,
                is_demo=True,
            )
            db.add(product)
            db.flush()
            db.add(
                ProductVariant(
                    product_id=product.id, sku=slug + "-sample", label="نمونه مفهومی", is_demo=True
                )
            )
    db.commit()


def main() -> None:
    with Session(get_engine()) as db:
        seed(db)


if __name__ == "__main__":
    main()
