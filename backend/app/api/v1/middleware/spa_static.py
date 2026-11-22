"""Pure ASGI middleware for single-process production SPA static serving.

Serves built Vite assets (e.g. ``frontend/dist``) and client-side SPA routes on
the same port as FastAPI without registering catch-all routes in ``app.routes``
(preserving route/permission contract verification).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import ConfigFactory

_RESERVED_EXACT_PATHS: frozenset[str] = frozenset(
    {"/api", "/ws", "/health", "/metrics", "/docs", "/redoc", "/openapi.json"}
)
_RESERVED_PREFIXES: tuple[str, ...] = (
    "/api/",
    "/ws/",
    "/docs/",
    "/redoc/",
    "/.well-known/",
)
_ASSET_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".js",
        ".mjs",
        ".css",
        ".map",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".json",
        ".txt",
        ".xml",
        ".wasm",
    }
)
_DISABLE_TOKENS: frozenset[str] = frozenset({"none", "off", "disabled", "false", "0"})


def resolve_static_dir(explicit: str | Path | None = None) -> Path | None:
    """Resolve a built SPA directory containing ``index.html``, or ``None``."""
    if isinstance(explicit, str) and explicit.strip().lower() in _DISABLE_TOKENS:
        return None

    env_val = (
        os.environ.get("ONX_STATIC_DIR") or os.environ.get("MCS_STATIC_DIR") or ""
    ).strip()
    if explicit is None and env_val.lower() in _DISABLE_TOKENS:
        return None

    candidates: list[Path] = []
    if explicit is not None and str(explicit).strip():
        candidates.append(Path(explicit))
    else:
        configured = env_val or ConfigFactory.global_settings().static_dir.strip()
        if configured:
            candidates.append(Path(configured))
        else:
            repo_dist = Path(__file__).resolve().parents[5] / "frontend" / "dist"
            cwd_static = Path.cwd() / "static"
            cwd_parent_dist = Path.cwd().parent / "frontend" / "dist"
            candidates.extend([repo_dist, cwd_static, cwd_parent_dist])

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and (resolved / "index.html").is_file():
            return resolved
    return None


def _is_reserved_backend_path(path: str) -> bool:
    return path in _RESERVED_EXACT_PATHS or any(path.startswith(p) for p in _RESERVED_PREFIXES)


class SpaStaticMiddleware:
    """Serve static SPA files and HTML fallback when a built bundle is present."""

    def __init__(self, app: ASGIApp, static_dir: Path | str | None = None) -> None:
        self.app = app
        self._root = resolve_static_dir(static_dir)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._root is None or scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return

        raw_path = str(scope.get("path", "/"))
        if _is_reserved_backend_path(raw_path):
            await self.app(scope, receive, send)
            return

        if "\x00" in raw_path or ".." in raw_path.split("/"):
            resp = JSONResponse({"detail": "Not found"}, status_code=404)
            await resp(scope, receive, send)
            return

        rel = raw_path.lstrip("/")
        if rel:
            candidate = (self._root / rel).resolve()
            if candidate != self._root and self._root not in candidate.parents:
                resp = JSONResponse({"detail": "Not found"}, status_code=404)
                await resp(scope, receive, send)
                return

            if candidate.is_file():
                cache = (
                    "public, max-age=31536000, immutable"
                    if rel.startswith("assets/")
                    else "no-cache"
                )
                resp = FileResponse(candidate, headers={"Cache-Control": cache})
                await resp(scope, receive, send)
                return

            if rel.startswith("assets/") or Path(rel).suffix.lower() in _ASSET_EXTENSIONS:
                resp = JSONResponse({"detail": "Static asset not found"}, status_code=404)
                await resp(scope, receive, send)
                return

        index_file = self._root / "index.html"
        resp = FileResponse(
            index_file,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )
        await resp(scope, receive, send)
