"""
FastAPI application setup for Greagent webhook server.

GitHub webhooks drive deep agents: issue workflow (``greagent:code`` / auto mode) and
PR workflow (``greagent:review`` / auto on sync), with Dramatiq workers processing runs.
"""

from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import create_tables, session_scope
from api import (
    health_router,
    auth_router,
    workspaces_router,
    connections_router,
    agents_router,
    billing_router,
    dashboard_router,
)
from api.wh import github_router
from logger import get_logger
from services.github.repository_bootstrap import get_or_create_default_model

load_dotenv()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup."""
    create_tables()
    logger.info("Database tables ensured")
    with session_scope() as session:
        get_or_create_default_model(session)
    logger.info("Default LLM catalog model ensured")
    yield


app = FastAPI(
    title="Greagent Webhook Server",
    description="Receives GitHub webhooks and triggers the agent on new issues",
    version="0.1.0",
    lifespan=lifespan,
    reload=False,
)

# Configure CORS for frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(connections_router)
app.include_router(agents_router)
app.include_router(billing_router)
app.include_router(dashboard_router)
app.include_router(github_router)
