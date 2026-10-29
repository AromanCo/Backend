"""Restricted ASGI entry point for the exploration release catalog."""

import re
from collections.abc import Callable, Iterable

import fastapi.routing
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Receive, Scope, Send

from aroman.brands.api import router as brands_router
from aroman.catalog.api import router as catalog_router
from aroman.core.config import get_settings
from aroman.fragrance_notes.api import router as notes_router

PUBLIC_ROUTES = {
    ("GET", "/api/v1/brands"),
    ("GET", "/api/v1/products"),
    ("GET", "/api/v1/products/{product_id}/variants"),
    ("GET", "/api/v1/fragrance-families"),
    ("GET", "/api/v1/fragrance-notes"),
}
_VARIANT_PATH = re.compile(rb"/api/v1/products/[^/%\\]+/variants\Z")
_FIXED_PATHS = {
    b"/api/v1/brands",
    b"/api/v1/products",
    b"/api/v1/fragrance-families",
    b"/api/v1/fragrance-notes",
}


def validate_public_routes(
    app: FastAPI,
    router_sources: Iterable[tuple[APIRouter, str]] | None = None,
    app_route_ids: tuple[int, ...] | None = None,
) -> None:
    """Fail closed if included routers register anything beyond the reviewed API."""
    context_iterator = getattr(fastapi.routing, "iter_route_contexts", None)
    # FastAPI 0.137.2+ exposes effective route contexts for lazy router
    # inclusion. The declared lower bound predates that helper, when included
    # routes were public, flat entries in app.routes. FastAPI 0.137.0/.1 used
    # lazy inclusion without the helper, so validate the public source-router
    # entries and ensure the application's include registry has not changed.
    if context_iterator:
        route_contexts = context_iterator(app.routes)
    elif all(
        isinstance(getattr(route, "path", None), str)
        and isinstance(getattr(route, "methods", None), set)
        for route in app.routes
    ):
        route_contexts = app.routes
    elif router_sources is not None and app_route_ids is not None:
        if tuple(id(route) for route in app.routes) != app_route_ids:
            raise RuntimeError(
                "Exploration API route registry drift (application includes changed)"
            )
        route_contexts = []
        for router, prefix in router_sources:
            for route in router.routes:
                path = getattr(route, "path", None)
                methods = getattr(route, "methods", None)
                if isinstance(path, str) and isinstance(methods, set):
                    route_contexts.extend(
                        (method, f"{prefix.rstrip('/')}/{path.lstrip('/')}")
                        for method in methods
                    )
                else:
                    route_contexts.append(route)
    else:
        route_contexts = app.routes

    route_entries: list[tuple[str, str]] = []
    unsupported: list[str] = []
    for route_context in route_contexts:
        if (
            isinstance(route_context, tuple)
            and len(route_context) == 2
            and isinstance(route_context[0], str)
            and isinstance(route_context[1], str)
        ):
            route_entries.append(route_context)
            continue
        path = getattr(route_context, "path", None)
        methods = getattr(route_context, "methods", None)
        if not isinstance(path, str) or not isinstance(methods, set) or not methods:
            unsupported.append(type(route_context).__name__)
            continue
        route_entries.extend((method, path) for method in methods)
    registered = set(route_entries)
    if (
        registered != PUBLIC_ROUTES
        or len(route_entries) != len(registered)
        or unsupported
    ):
        unexpected = sorted(registered - PUBLIC_ROUTES)
        missing = sorted(PUBLIC_ROUTES - registered)
        raise RuntimeError(
            "Exploration API route registry drift "
            f"(unexpected={unexpected}, missing={missing}, unsupported={unsupported})"
        )


class PublicBoundary:
    """Reject all paths and methods outside exact catalog GET requests."""

    def __init__(
        self,
        app: ASGIApp,
        origins: Iterable[str],
        validate_registry: Callable[[], None],
    ):
        self.app = app
        self.origins = frozenset(origins)
        self.validate_registry = validate_registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            try:
                self.validate_registry()
            except RuntimeError:
                await send({"type": "websocket.close", "code": 1008})
                return
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            self.validate_registry()
        except RuntimeError:
            response = JSONResponse({"detail": "Not found"}, status_code=404)
            await response(scope, receive, send)
            return

        raw_path = scope.get("raw_path", b"")
        path_allowed = (
            b"%" not in raw_path
            and raw_path not in {b"/api/v1/products/./variants", b"/api/v1/products/../variants"}
            and (raw_path in _FIXED_PATHS or _VARIANT_PATH.fullmatch(raw_path) is not None)
        )
        if not path_allowed or scope["method"] != "GET":
            status = 405 if path_allowed else 404
            response = JSONResponse({"detail": "Not found"}, status_code=status)
            await response(scope, receive, send)
            return

        origin = dict(scope.get("headers", [])).get(b"origin", b"").decode("latin-1")

        async def send_with_cors(message):
            if message["type"] == "http.response.start" and origin in self.origins:
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"access-control-allow-origin", origin.encode("latin-1")),
                        (b"access-control-allow-credentials", b"true"),
                        (b"vary", b"Origin"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_cors)


def create_exploration_app(routers: Iterable[APIRouter] | None = None) -> FastAPI:
    app = FastAPI(
        title="AROMAN Exploration Catalog API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        debug=False,
    )
    included_routers = tuple(routers) if routers is not None else (
        brands_router,
        catalog_router,
        notes_router,
    )
    for router in included_routers:
        app.include_router(router, prefix="/api/v1")

    # Validate at construction and again per request; the latter also protects
    # against routes attached to the app after construction.
    app_route_ids = tuple(id(route) for route in app.routes)
    router_sources = tuple((router, "/api/v1") for router in included_routers)

    def check_registry() -> None:
        validate_public_routes(app, router_sources, app_route_ids)

    check_registry()
    settings = get_settings()
    app.add_middleware(
        PublicBoundary,
        origins=settings.origins,
        validate_registry=check_registry,
    )

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request: Request, error: RequestValidationError):
        detail = [
            {key: item[key] for key in ("type", "loc", "msg")}
            for item in error.errors()
        ]
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def safe_database_error(request: Request, error: SQLAlchemyError):
        return JSONResponse({"detail": "Catalog unavailable"}, status_code=503)

    return app


app = create_exploration_app()
