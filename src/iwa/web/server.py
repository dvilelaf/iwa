"""FastAPI Server Entrypoint."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from iwa.core.wallet import init_db

# Pre-load cowdao_cowpy modules BEFORE async loop starts
# This is required because cowdao_cowpy uses asyncio.run() at import time
# which fails if called from an already running event loop
from iwa.plugins.gnosis.cow_utils import get_cowpy_module

get_cowpy_module("DEFAULT_APP_DATA_HASH")  # Forces import now, not during async

# Import dependencies to ensure initialization
# Import routers
from iwa.web.routers import accounts, olas, state, swap, transactions  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Rate limiter (in-memory storage, resets on restart)
limiter = Limiter(key_func=get_remote_address)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        """Add security headers to response."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Content Security Policy for XSS protection
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'"
        )
        # HSTS for production HTTPS deployments (enable via environment variable)
        if os.getenv("ENABLE_HSTS", "").lower() in ("true", "1", "yes"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events."""
    logger.info("Starting up check operations...")
    init_db()

    # Initialize block tracking for Tenderly monitoring
    from iwa.core.chain import ChainInterfaces

    ChainInterfaces().gnosis.init_block_tracking()
    # Check block limit immediately at startup with visual progress bar
    ChainInterfaces().gnosis.check_block_limit(show_progress_bar=True)

    yield
    logger.info("Shutting down...")


app = FastAPI(title="IWA Web UI", version="0.1.0", lifespan=lifespan)

# Attach rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security Headers Middleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS - configurable via environment variable for production
default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
allowed_origins_env = os.getenv("ALLOWED_ORIGINS")
if allowed_origins_env:
    origins = [origin.strip() for origin in allowed_origins_env.split(",")]
else:
    origins = default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for the API."""
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error. Check logs for details."},
    )


# Include Routers
app.include_router(state.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(swap.router)
app.include_router(olas.router)

# Mount Static Files at /static/ path
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Serve index.html for root path
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return index_path.read_text()
    return HTMLResponse(content="<h1>IWA Web UI</h1><p>index.html not found</p>", status_code=200)


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server using uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
