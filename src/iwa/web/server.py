"""FastAPI Server Entrypoint."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from iwa.core.wallet import init_db

# Import dependencies to ensure initialization
# Import routers
from iwa.web.routers import accounts, olas, state, swap, transactions

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events."""
    logger.info("Starting up check operations...")
    init_db()
    yield
    logger.info("Shutting down...")


app = FastAPI(title="IWA Web UI", version="0.1.0", lifespan=lifespan)

# CORS
origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
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

# Mount Static Files (Frontend)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server using uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
