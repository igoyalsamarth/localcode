"""
FastAPI application setup for LocalCode webhook server.

When someone adds the ``greagent:code`` label to an issue, the webhook runs the
coder agent: in-progress / done / error labels, PR, and issue comment.
"""

from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from agents.checkpoint import init_checkpointer, shutdown_checkpointer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import create_tables
from api import health_router, auth_router, onboarding_router, connections_router, agents_router
from api.wh import github_router
from logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables and LangGraph checkpoint tables on startup."""
    create_tables()
    logger.info("Database tables ensured")
    init_checkpointer()
    yield
    shutdown_checkpointer()


app = FastAPI(
    title="LocalCode Webhook Server",
    description="Receives GitHub webhooks and triggers the agent on new issues",
    version="0.1.0",
    lifespan=lifespan,
    reload=True,  # Enable auto-reload in development
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
app.include_router(onboarding_router)
app.include_router(connections_router)
app.include_router(agents_router)
app.include_router(github_router)
