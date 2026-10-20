import logging

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from aroman.authentication.api import router as auth_router
from aroman.brands.api import router as brands_router
from aroman.catalog.api import router as catalog_router
from aroman.core.config import get_settings
from aroman.core.db import get_db
from aroman.fragrance_concepts.api import router as concepts_router
from aroman.fragrance_notes.api import router as notes_router
from aroman.users.api import router as users_router

settings = get_settings()
logger = logging.getLogger(__name__)
schema_head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
app = FastAPI(
    title="AROMAN API",
    version="1.0.0",
    description=(
        "Persian-first fragrance catalog and private scent concepts. "
        "Concepts are not manufacturing formulas."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, error: SQLAlchemyError):
    logger.error("Database operation failed: %s", type(error).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.middleware("http")
async def private_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/v1/auth", "/api/v1/users", "/api/v1/fragrance-concepts")):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(brands_router, prefix="/api/v1")
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")
app.include_router(concepts_router, prefix="/api/v1")


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(db: Session = Depends(get_db)):
    try:
        migrated = inspect(db.get_bind()).has_table("alembic_version")
    except Exception:
        raise HTTPException(503, "Database unavailable") from None
    if not migrated:
        raise HTTPException(503, "Database migration required")
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        raise HTTPException(503, "Database unavailable") from None
    if revision != schema_head:
        raise HTTPException(503, "Database migration required")
    return {"status": "ok"}
