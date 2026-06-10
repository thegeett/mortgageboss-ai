"""mortgageboss-ai backend application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup/shutdown logic."""
    # Startup: connections, etc. will be added in later tickets
    yield
    # Shutdown: cleanup will be added in later tickets


app = FastAPI(
    title="mortgageboss-ai",
    description="AI-powered loan processing assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration - restrictive by default, will be configured properly in LP-6
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    """Welcome endpoint."""
    return {
        "service": "mortgageboss-ai",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for monitoring and load balancers."""
    return {"status": "healthy"}
