"""
Service 1: API Backend
Main FastAPI application for user-facing APIs and webhook handling.
- User authentication, onboarding, connections, agents
- GitHub webhook receiver (publishes to RabbitMQ via Dramatiq)
- Does NOT execute the agent (that's done by workers)
"""

import uvicorn
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import create_tables
from api import (
    health_router,
    auth_router,
    onboarding_router,
    connections_router,
    agents_router,
    billing_router,
)
from api.wh import github_router
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup."""
    create_tables()
    logger.info("Database tables ensured")
    yield


app = FastAPI(
    title="Greagent API Backend",
    description="Main API for user authentication, onboarding, agent management, and webhook handling",
    version="0.1.0",
    lifespan=lifespan,
    reload=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(connections_router)
app.include_router(agents_router)
app.include_router(billing_router)
app.include_router(github_router)


def main() -> None:
    """Start the API Backend service."""
    logger.info("Starting Greagent API Backend service...")

    uvicorn.run(
        "services_entrypoints.api_backend:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
